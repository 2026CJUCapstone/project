from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import String, cast, desc, literal, or_
from sqlalchemy.orm import Session
from typing import List, Optional
from app.core.database import get_db
from app.core.config import settings
from app.models import database as db_models
from app.models import schemas
from app.models.contest_schemas import AuthoringValidationWrite
from app.api.routes.auth import get_current_user, get_optional_current_user, require_admin
from app.core.bootstrap import SYSTEM_BOARD_IDS
from app.services.rating import RatingStats, calculate_rating_stats, invalidate_rating_cache, rating_stats_for_users
from app.services.redis_client import cache_get_json, cache_set_json, redis_key
from app.services.contest_access import private_problem_ids, require_public_problem, resolve_problem_identifier, now_utc
from app.services.public_identity import public_display_name, public_problem_id, public_receipt_id
from app.services.judge_policy import UNREVIEWED, stored_policy, public_policy_fields_for_problem, validate_stored_publication
from app.models.judge_test_manifest import is_reference_case,canonical_case
from app.services.judge_test_manifest import validate_stored_cases

router = APIRouter()


from app.models.problem_authoring import MetadataUpdate, ReviewWrite
from app.services import problem_authoring as authoring_service


@router.get('/{id}/authoring')
def read_authoring(id:str,response:Response,db:Session=Depends(get_db),user=Depends(require_admin)):
    response.headers['Cache-Control']='no-store'
    return authoring_service.review_read(db,id)


@router.put('/{id}/authoring')
def edit_authoring(id:str,data:MetadataUpdate,response:Response,db:Session=Depends(get_db),user=Depends(require_admin)):
    response.headers['Cache-Control']='no-store'
    return authoring_service.update_metadata(db,id,data,user)


@router.post('/{id}/authoring/reviews')
def review_authoring(id:str,data:ReviewWrite,response:Response,db:Session=Depends(get_db),user=Depends(require_admin)):
    response.headers['Cache-Control']='no-store'
    return authoring_service.append_review(db,id,data,user)


@router.post('/{id}/authoring-validations', status_code=202)
def create_problem_authoring_validation(
    id: str,
    data: AuthoringValidationWrite,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    user=Depends(require_admin),
):
    from app.services import authoring_validation
    from app.services.execution_admission import admit_execution
    from app.services.execution_runtime import execution_queue
    response.headers['Cache-Control'] = 'no-store'
    admit_execution(request, user_id=user.id)
    return authoring_validation.create_problem(
        db, problem_id=id, data=data, user=user, queue=execution_queue()
    )


@router.get('/{id}/authoring-validations/{job_id}')
def read_problem_authoring_validation(
    id: str,
    job_id: str,
    response: Response,
    db: Session = Depends(get_db),
    user=Depends(require_admin),
):
    from app.services import authoring_validation
    response.headers['Cache-Control'] = 'no-store'
    return authoring_validation.read_problem(db, problem_id=id, job_id=job_id, user=user)

PROBLEM_DIFFICULTIES = [
    f"{tier}{level}"
    for tier in ("iron", "bronze", "silver", "gold", "platinum", "diamond", "ruby")
    for level in range(5, 0, -1)
]


def _validate_problem_tests(problem: schemas.ProblemCreate) -> None:
    # Contest drafts may still be empty; only public practice writes require tests.
    count = len(problem.test_cases) + len(problem.hidden_test_cases)
    if not 1 <= count <= 200:
        raise HTTPException(422, "문제에는 테스트를 1개 이상 200개 이하로 등록하세요.")


def _validate_submission_code_size(code: str) -> None:
    if len(code.encode("utf-8")) > settings.SUBMISSION_CODE_MAX_BYTES:
        raise HTTPException(status_code=413, detail="제출 코드가 너무 큽니다.")


def _prune_old_submissions(db: Session, user_id: str) -> None:
    # SessionLocal disables autoflush. Include the just-finished submission in
    # the retention window, but never remove a queued/running submission.
    db.flush()
    stale_ids = [
        submission_id
        for (submission_id,) in (
            db.query(db_models.Submission.id)
            .filter(db_models.Submission.user_id == user_id)
            .filter(~db_models.Submission.status.in_(["queued", "running"]))
            .order_by(db_models.Submission.created_at.desc(), db_models.Submission.id.desc())
            .offset(settings.SUBMISSION_RETENTION_PER_USER)
            .all()
        )
    ]
    if stale_ids:
        db.query(db_models.Submission).filter(db_models.Submission.id.in_(stale_ids)).delete(
            synchronize_session=False
        )


def _normalize_problem_test_cases(raw_test_cases: object) -> tuple[list[dict], list[dict]]:
    def normalize_case(raw_case: object) -> dict:
        if not isinstance(raw_case, dict):
            return {"input": "", "expected_output": ""}
        if is_reference_case(raw_case):
            return canonical_case(raw_case,allow_reference=True)
        return {
            "input": raw_case.get("input", ""),
            "expected_output": raw_case.get("expected_output", raw_case.get("expectedOutput", "")),
        }

    if isinstance(raw_test_cases, dict):
        sample_cases = raw_test_cases.get("sample") or raw_test_cases.get("test_cases") or []
        hidden_cases = raw_test_cases.get("hidden") or []
    elif isinstance(raw_test_cases, list):
        sample_cases = raw_test_cases
        hidden_cases = []
    else:
        sample_cases = []
        hidden_cases = []

    return [normalize_case(test_case) for test_case in sample_cases], [normalize_case(test_case) for test_case in hidden_cases]


def _submission_verdict_from_status(status: str) -> schemas.CompileQueueVerdict:
    if status == "Accepted":
        return "accepted"
    if status in {"SampleFailed", "Rejected"}:
        return "wrong_answer"
    return "system_error"


def _submission_message(verdict: schemas.CompileQueueVerdict) -> str:
    return {
        "accepted": "정답입니다.",
        "wrong_answer": "틀렸습니다.",
        "compile_error": "컴파일 실패입니다.",
        "runtime_error": "런타임 오류입니다.",
        "time_limit_exceeded": "시간 초과입니다.",
        "memory_limit_exceeded": "메모리 초과입니다.",
        "output_limit_exceeded": "출력 제한을 초과했습니다.",
        "process_limit_exceeded": "프로세스 수 제한을 초과했습니다.",
        "compile_resource_error": "컴파일 중 자원 제한을 초과했습니다. 대회 오답 패널티에는 포함되지 않습니다.",
        "system_error": "시스템 오류입니다.",
        "canceled": "취소되었습니다.",
        "pending": "대기 중입니다.",
        "running": "실행 중입니다.",
        "compile_success": "컴파일 성공입니다.",
        "finished": "정상 종료되었습니다.",
    }[verdict]


def _problem_progress_map(db: Session, user_id: str | None, problem_ids: list[str]) -> dict[str, dict]:
    if not user_id or not problem_ids:
        return {}

    scores = (
        db.query(db_models.UserProblemScore)
        .filter(
            db_models.UserProblemScore.user_id == user_id,
            db_models.UserProblemScore.challenge_id.in_(problem_ids),
        )
        .all()
    )
    score_by_problem = {score.challenge_id: score for score in scores}

    submissions = (
        db.query(db_models.Submission)
        .filter(
            db_models.Submission.user_id == user_id,
            db_models.Submission.problem_id.in_(problem_ids),
        )
        .order_by(db_models.Submission.problem_id.asc(), db_models.Submission.created_at.desc())
        .all()
    )
    latest_by_problem: dict[str, db_models.Submission] = {}
    for submission in submissions:
        latest_by_problem.setdefault(submission.problem_id, submission)

    progress: dict[str, dict] = {}
    for problem_id in problem_ids:
        score = score_by_problem.get(problem_id)
        latest = latest_by_problem.get(problem_id)
        verdict = latest.verdict if latest and latest.verdict else (
            _submission_verdict_from_status(latest.status) if latest else None
        )
        progress[problem_id] = {
            "solved": score is not None,
            "attempted": latest is not None,
            "last_submission_status": latest.status if latest else None,
            "last_submission_verdict": verdict,
            "last_submitted_at": latest.created_at if latest else None,
            "best_awarded_points": score.points_awarded if score else 0,
        }
    return progress


def _serialize_problem(problem: db_models.Problem, include_hidden: bool = False, progress: dict | None = None,
                       include_policy: bool = False) -> dict:
    sample_cases, hidden_cases = _normalize_problem_test_cases(problem.test_cases)
    progress = progress or {}
    limits = public_policy_fields_for_problem(
        problem.judge_policy, len(sample_cases) + len(hidden_cases), settings=settings
    )
    return {
        "judge_limits": limits['judgeLimits'],
        "judge_policy_legacy": limits['judgePolicyLegacy'],
        "judge_policy_compatibility": limits.get('judgePolicyCompatibility', False),
        "judge_policy": problem.judge_policy if include_policy and problem.judge_policy != UNREVIEWED else None,
        "publication_status": (
            "draft"
            if problem.publication_review_required is True and problem.publication_approved_at is None
            else "published"
            if problem.publication_review_required is True
            else "legacy"
        ),
        "id": problem.id if include_hidden or include_policy else public_problem_id(problem),
        "creator_id": problem.creator_id if include_hidden or include_policy else None,
        "title": problem.title,
        "difficulty": problem.difficulty,
        "tags": problem.tags,
        "description": problem.description,
        "points": problem.points,
        "test_cases": sample_cases,
        "hidden_test_cases": hidden_cases if include_hidden else [],
        "created_at": problem.created_at,
        "solved": bool(progress.get("solved", False)),
        "attempted": bool(progress.get("attempted", False)),
        "last_submission_status": progress.get("last_submission_status"),
        "last_submission_verdict": progress.get("last_submission_verdict"),
        "last_submitted_at": progress.get("last_submitted_at"),
        "best_awarded_points": progress.get("best_awarded_points", 0),
    }


def _leaderboard_entry(user: db_models.User, rank: int, rating_stats: RatingStats | None = None) -> dict:
    stats = rating_stats or calculate_rating_stats([])
    return {
        "rank": rank,
        "username": public_display_name(user),
        "total_score": user.total_score,
        "rating": stats.rating,
        "tier": stats.tier,
        "solved_count": stats.solved_count,
        "avatar_url": user.avatar_url,
    }


def _leaderboard_rows(db: Session) -> list[tuple[db_models.User, RatingStats]]:
    users = (
        db.query(db_models.User)
        .filter(db_models.User.role != "admin", db_models.User.public_profile_enabled.is_(True))
        .order_by(db_models.User.username.asc())
        .all()
    )
    stats_by_user = rating_stats_for_users(db, [user.id for user in users])
    rows = [(user, stats_by_user.get(user.id, calculate_rating_stats([]))) for user in users]
    return sorted(
        rows,
        key=lambda row: (
            -row[1].rating,
            -row[1].solved_count,
            -row[0].total_score,
            row[0].username,
        ),
    )


def _leaderboard_rank(db: Session, user_id: str) -> int:
    return next(
        (
            index
            for index, (current, _stats) in enumerate(_leaderboard_rows(db), start=1)
            if current.id == user_id
        ),
        0,
    )

@router.post("/", response_model=schemas.ProblemRead)
def create_problem(
    problem: schemas.ProblemCreate,
    response: Response,
    db: Session = Depends(get_db),
    current_user: db_models.User = Depends(require_admin)
):
    response.headers['Cache-Control'] = 'no-store'
    _validate_problem_tests(problem)
    policy = stored_policy(problem.judge_policy, creating=True)
    try:
        validate_stored_cases(db,[c.model_dump() for c in problem.test_cases],
                              [c.model_dump() for c in problem.hidden_test_cases],integrity=True)
        validate_stored_publication(policy, [c.model_dump() for c in problem.test_cases],
                                   [c.model_dump() for c in problem.hidden_test_cases], settings=settings)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    db_problem = db_models.Problem(
        judge_policy=policy,
        publication_review_required=True,
        publication_approved_at=None,
        creator_id=current_user.id,
        title=problem.title,
        difficulty=problem.difficulty,
        tags=problem.tags,
        description=problem.description,
        points=problem.points,
        test_cases={
            "sample": [tc.model_dump() for tc in problem.test_cases],
            "hidden": [tc.model_dump() for tc in problem.hidden_test_cases],
        }
    )
    db.add(db_problem)
    db.commit()
    db.refresh(db_problem)
    invalidate_rating_cache()
    return _serialize_problem(db_problem, include_hidden=True, include_policy=True)

@router.get("/", response_model=List[schemas.ProblemRead])
def list_problems(
    response: Response,
    difficulty: Optional[str] = Query(None),
    tag: List[str] = Query(default=[]),
    difficulty_min: Optional[str] = Query(None, alias="difficultyMin"),
    difficulty_max: Optional[str] = Query(None, alias="difficultyMax"),
    search: Optional[str] = Query(None, max_length=100),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: db_models.User | None = Depends(get_optional_current_user),
):
    query = db.query(db_models.Problem).filter(~db_models.Problem.id.in_(SYSTEM_BOARD_IDS), db_models.Problem.deleted_at.is_(None))
    if current_user is None or current_user.role != "admin":
        query = query.filter(~db_models.Problem.id.in_(private_problem_ids()))
    if difficulty:
        query = query.filter(db_models.Problem.difficulty == difficulty)
    if difficulty_min or difficulty_max:
        low = PROBLEM_DIFFICULTIES.index(difficulty_min) if difficulty_min in PROBLEM_DIFFICULTIES else 0
        high = PROBLEM_DIFFICULTIES.index(difficulty_max) if difficulty_max in PROBLEM_DIFFICULTIES else len(PROBLEM_DIFFICULTIES) - 1
        if low > high:
            low, high = high, low
        query = query.filter(db_models.Problem.difficulty.in_(PROBLEM_DIFFICULTIES[low:high + 1]))
    if search and search.strip():
        keyword = search.strip()
        query = query.filter(or_(db_models.Problem.title.contains(keyword, autoescape=True), db_models.Problem.description.contains(keyword, autoescape=True)))
    if tag:
        tag_filters = []
        for value in tag:
            escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_").replace('"', '\\"')
            tag_filters.append(cast(db_models.Problem.tags, String).like(f'%"{escaped}"%', escape="\\"))
        query = query.filter(or_(*tag_filters))

    response.headers["X-Total-Count"] = str(query.count())
    problems = query.order_by(db_models.Problem.created_at.asc()).offset(offset).limit(limit).all()
    include_sensitive = current_user is not None and (
        current_user.role == "admin" or any(problem.creator_id == current_user.id for problem in problems)
    )
    if include_sensitive:
        response.headers['Cache-Control'] = 'no-store'
    progress_by_problem = _problem_progress_map(
        db,
        current_user.id if current_user else None,
        [problem.id for problem in problems],
    )
    return [
        _serialize_problem(
            problem,
            include_hidden=current_user is not None and (
                current_user.role == "admin" or problem.creator_id == current_user.id
            ),
            progress=progress_by_problem.get(problem.id),
            include_policy=current_user is not None and current_user.role == "admin",
        )
        for problem in problems
    ]

@router.put("/{id}", response_model=schemas.ProblemRead)
def update_problem(id: str, problem: schemas.ProblemCreate, response: Response,
                   db: Session = Depends(get_db), current_user: db_models.User = Depends(require_admin)):
    response.headers['Cache-Control'] = 'no-store'
    from app.services.runtime_registry import execution_lock
    execution_lock(db)
    require_public_problem(db, id, current_user)
    _validate_problem_tests(problem)
    if db.query(db_models.ContestProblem.id).join(db_models.Contest).filter(
        db_models.ContestProblem.problem_id == id, db_models.ContestProblem.is_new.is_(True),
        or_(db_models.Contest.published.is_(False), db_models.Contest.ends_at > now_utc()),
    ).first():
        raise HTTPException(409, "비공개 대회 문제는 시작 전 대회 관리 화면에서 수정하세요.")
    db_problem = db.query(db_models.Problem).filter(db_models.Problem.id == id).with_for_update().first()
    if not db_problem:
        raise HTTPException(status_code=404, detail="Problem not found")    
    
    try:
        policy = stored_policy(problem.judge_policy, previous=db_problem.judge_policy)
        validate_stored_cases(db,[c.model_dump() for c in problem.test_cases],
                              [c.model_dump() for c in problem.hidden_test_cases],integrity=True)
        validate_stored_publication(policy, [c.model_dump() for c in problem.test_cases],
                                   [c.model_dump() for c in problem.hidden_test_cases], settings=settings)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    db_problem.judge_policy = policy
    db_problem.title = problem.title
    db_problem.difficulty = problem.difficulty
    db_problem.tags = problem.tags
    db_problem.description = problem.description
    db_problem.points = problem.points
    db_problem.test_cases = {
        "sample": [tc.model_dump() for tc in problem.test_cases],
        "hidden": [tc.model_dump() for tc in problem.hidden_test_cases],
    }
    # The exact content fingerprint changed. Keep it visible to administrators,
    # but remove it from every public surface until new evidence is approved.
    db_problem.publication_review_required = True
    db_problem.publication_approved_at = None
    
    db.commit()
    db.refresh(db_problem)
    invalidate_rating_cache()
    return _serialize_problem(db_problem, include_hidden=True, include_policy=True)


@router.post('/{id}/publish', response_model=schemas.ProblemRead)
def publish_problem(
    id: str,
    response: Response,
    db: Session = Depends(get_db),
    current_user: db_models.User = Depends(require_admin),
):
    from app.services.runtime_registry import execution_lock
    execution_lock(db)
    response.headers['Cache-Control'] = 'no-store'
    problem = (
        db.query(db_models.Problem)
        .filter(db_models.Problem.id == id, db_models.Problem.deleted_at.is_(None))
        .with_for_update()
        .first()
    )
    if problem is None or problem.id in SYSTEM_BOARD_IDS:
        raise HTTPException(404, 'Problem not found')
    if problem.publication_review_required is not True:
        raise HTTPException(409, '기존 공개 문제는 별도의 공개 승인이 필요하지 않습니다.')
    sample, hidden = _normalize_problem_test_cases(problem.test_cases)
    try:
        validate_stored_cases(db, sample, hidden, integrity=True)
        validate_stored_publication(problem.judge_policy, sample, hidden, settings=settings)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    authoring_service.assert_reviewed(
        db,
        problem.id,
        authoring_service.current_snapshot(db, problem),
        contest_id='__problem__',
        contest_problem_id=problem.id,
        require_tracked=True,
    )
    problem.publication_approved_at = now_utc()
    db.commit()
    db.refresh(problem)
    invalidate_rating_cache()
    return _serialize_problem(problem, include_hidden=True, include_policy=True)

@router.delete("/{id}")
def delete_problem(id: str, db: Session = Depends(get_db), current_user: db_models.User = Depends(require_admin)):
    # Contest composition changes use the execution lock before inspecting or
    # attaching problems. Take it first here as well, then recheck relations
    # inside the same transaction so an archive and a new contest link have
    # one serial order.
    from app.services.runtime_registry import execution_lock
    execution_lock(db)
    if db.query(db_models.ContestProblem.id).filter_by(problem_id=id).first():
        raise HTTPException(409, "대회에서 사용하는 문제는 삭제할 수 없습니다.")
    # Practice acceptance freezes the same row under FOR UPDATE. Deletion must
    # participate in that serialization so an acknowledged receipt is either
    # committed before archival or rejected after archival, never interleaved.
    db_problem = (
        db.query(db_models.Problem)
        .filter(db_models.Problem.id == id)
        .with_for_update()
        .first()
    )
    if not db_problem:
        raise HTTPException(status_code=404, detail="Problem not found")
    if id in SYSTEM_BOARD_IDS:
        raise HTTPException(status_code=400, detail="System board cannot be deleted")
    if db.query(db_models.ContestProblem.id).filter_by(problem_id=id).first():
        raise HTTPException(409, "대회에서 사용하는 문제는 삭제할 수 없습니다.")
    
    # Preserve solved history, its difficulty and score ledger. Deletion must
    # not leave total_score without the ledger rows that explain it.
    if db_problem.deleted_at is None:
        db_problem.deleted_at = now_utc()
    db.commit()
    invalidate_rating_cache()
    return {"message": "Successfully deleted"}

@router.get("/leaderboard", response_model=List[schemas.LeaderboardRead])
def get_leaderboard(
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    cache_key = redis_key("leaderboard-public-v2", str(limit))
    cached = cache_get_json(cache_key)
    if isinstance(cached, list):
        return cached

    rows = _leaderboard_rows(db)[:limit]
    payload = [
        _leaderboard_entry(user, rank, stats)
        for rank, (user, stats) in enumerate(rows, start=1)
    ]
    cache_set_json(cache_key, payload)
    return payload


@router.post("/leaderboard/score", response_model=schemas.LeaderboardScoreRead)
def submit_leaderboard_score(
    score: schemas.LeaderboardScoreCreate,
    db: Session = Depends(get_db),
    current_user: db_models.User = Depends(require_admin),
):
    username = score.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="Username is required")

    user = db.query(db_models.User).filter(db_models.User.username == username).first()
    if user is None:
        user = db_models.User(
            username=username,
            total_score=0,
            avatar_url=score.avatar_url,
            hashed_password="",
            role="user",
        )
        db.add(user)
        db.flush()
    else:
        if score.avatar_url:
            user.avatar_url = score.avatar_url

    db.query(db_models.User).filter_by(id=user.id).update({'id':user.id}, synchronize_session=False)
    from app.services.solve_evidence import preserve_legacy, record as record_solve
    preserve_legacy(db, user.id, score.challenge_id)
    existing_score = (
        db.query(db_models.UserProblemScore)
        .filter(
            db_models.UserProblemScore.user_id == user.id,
            db_models.UserProblemScore.challenge_id == score.challenge_id,
        )
        .first()
    )

    awarded_points = 0
    already_solved = existing_score is not None
    if existing_score is None:
        awarded_points = score.points
        db.query(db_models.User).filter_by(id=user.id).update(
            {db_models.User.total_score:db_models.User.total_score + awarded_points}, synchronize_session=False)
        db.add(
            db_models.UserProblemScore(
                user_id=user.id,
                challenge_id=score.challenge_id,
                points_awarded=awarded_points,
            )
        )

    db.flush()
    credited = db.query(db_models.UserProblemScore).filter_by(user_id=user.id, challenge_id=score.challenge_id).one()
    record_solve(db, user_id=user.id, problem_id=score.challenge_id, source_kind='manual',
        source_id=credited.id, points=credited.points_awarded, solved_at=credited.solved_at)
    db.commit()
    db.refresh(user)
    invalidate_rating_cache(user.id)

    stats = rating_stats_for_users(db, [user.id]).get(user.id, calculate_rating_stats([]))

    return {
        **_leaderboard_entry(user, _leaderboard_rank(db, user.id), stats),
        "challenge_id": score.challenge_id,
        "awarded_points": awarded_points,
        "already_solved": already_solved,
    }


def _serialize_submission(
    submission: db_models.Submission,
    problem: db_models.Problem | None,
    user: db_models.User | None,
) -> schemas.SubmissionRead:
    from app.services.judge_metrics import public_usage
    return schemas.SubmissionRead(
        id=public_receipt_id(submission.id),
        problem_id=public_problem_id(problem) if problem else "unavailable",
        problem_title=problem.title if problem else None,
        user_id=None,
        username=public_display_name(user) if user else None,
        language=submission.language,
        status=submission.status,
        verdict=submission.verdict or _submission_verdict_from_status(submission.status),
        sample_total_cases=submission.sample_total_cases,
        sample_passed_cases=submission.sample_passed_cases,
        grading_completed=submission.grading_completed,
        grading_passed=submission.grading_passed,
        awarded_points=submission.awarded_points,
        resource_usage=public_usage(submission.resource_report),
        created_at=submission.created_at,
    )


@router.get("/submissions", response_model=schemas.SubmissionListResponse)
def list_submissions(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    problem_id: Optional[str] = Query(None, alias="problemId"),
    username: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None, alias="userId"),
    status: Optional[str] = Query(None),
    verdict: Optional[str] = Query(None),
    mine: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: db_models.User | None = Depends(get_optional_current_user),
):
    query = db.query(db_models.Submission).filter(~db_models.Submission.problem_id.in_(private_problem_ids()))
    if (current_user is None or current_user.role != "admin") and not mine:
        query = query.join(db_models.User, db_models.User.id == db_models.Submission.user_id).filter(
            db_models.User.public_profile_enabled.is_(True)
        )
    if problem_id:
        resolved_problem = resolve_problem_identifier(db, problem_id)
        query = query.filter(
            db_models.Submission.problem_id == resolved_problem.id if resolved_problem is not None else literal(False)
        )
    if status:
        query = query.filter(db_models.Submission.status == status)
    if verdict:
        query = query.filter(db_models.Submission.verdict == verdict)
    if mine:
        if current_user is None:
            raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
        query = query.filter(db_models.Submission.user_id == current_user.id)
    elif user_id and current_user is not None and current_user.role == "admin":
        query = query.filter(db_models.Submission.user_id == user_id)
    elif username and current_user is not None and current_user.role == "admin":
        matched_user = (
            db.query(db_models.User)
            .filter(db_models.User.username == username.strip())
            .first()
        )
        if matched_user is None:
            return {"submissions": [], "total": db.query(db_models.Submission).filter(
                ~db_models.Submission.problem_id.in_(private_problem_ids())).count(), "filtered_total": 0}
        query = query.filter(db_models.Submission.user_id == matched_user.id)

    total_query = db.query(db_models.Submission).filter(~db_models.Submission.problem_id.in_(private_problem_ids()))
    if current_user is None or current_user.role != "admin":
        total_query = total_query.join(db_models.User, db_models.User.id == db_models.Submission.user_id).filter(
            db_models.User.public_profile_enabled.is_(True)
        )
    total = total_query.count()
    filtered_total = query.count()
    submissions = (
        query.order_by(desc(db_models.Submission.created_at))
        .offset(offset)
        .limit(limit)
        .all()
    )
    problem_ids = {submission.problem_id for submission in submissions}
    user_ids = {submission.user_id for submission in submissions if submission.user_id}
    problems = (
        db.query(db_models.Problem).filter(db_models.Problem.id.in_(problem_ids)).all()
        if problem_ids else []
    )
    users = db.query(db_models.User).filter(db_models.User.id.in_(user_ids)).all() if user_ids else []
    problems_by_id = {problem.id: problem for problem in problems}
    users_by_id = {user.id: user for user in users}

    return {
        "submissions": [
            _serialize_submission(
                submission,
                problems_by_id.get(submission.problem_id),
                users_by_id.get(submission.user_id),
            )
            for submission in submissions
        ],
        "total": total,
        "filtered_total": filtered_total,
    }


@router.get('/submissions/{submission_id}/resources')
def submission_resources(submission_id:str,response:Response,db:Session=Depends(get_db),user=Depends(require_admin)):
    response.headers['Cache-Control']='no-store'
    row=db.get(db_models.Submission,submission_id)
    if row is None: raise HTTPException(404,'제출을 찾을 수 없습니다.')
    return {'submissionId':row.id,'report':row.resource_report}


@router.get("/{id}", response_model=schemas.ProblemRead)
def get_problem(
    id: str,
    response: Response,
    db: Session = Depends(get_db),
    current_user: db_models.User | None = Depends(get_optional_current_user),
):
    problem = require_public_problem(db, id, current_user)
    if not problem or problem.id in SYSTEM_BOARD_IDS:
        raise HTTPException(status_code=404, detail="Problem not found")

    progress_by_problem = _problem_progress_map(
        db,
        current_user.id if current_user else None,
        [problem.id],
    )
    include_sensitive = current_user is not None and (
        current_user.role == "admin" or problem.creator_id == current_user.id
    )
    if include_sensitive:
        response.headers['Cache-Control'] = 'no-store'
    return _serialize_problem(
        problem,
        include_hidden=include_sensitive,
        progress=progress_by_problem.get(problem.id),
        include_policy=current_user is not None and current_user.role == "admin",
    )

@router.post("/{id}/submit", status_code=202, tags=["Grading"])
def submit_problem(
    id: str, 
    request: schemas.SubmissionRequest, 
    http_request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: db_models.User | None = Depends(get_optional_current_user)
):
    from app.services.submission_acceptance import accept_practice
    problem = require_public_problem(db, id, current_user)
    return accept_practice(problem.id, request, http_request, response, db, current_user)
