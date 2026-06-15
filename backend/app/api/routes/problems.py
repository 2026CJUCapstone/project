from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc
from sqlalchemy.orm import Session
from typing import List, Optional
from app.core.database import get_db
from app.core.config import settings
from app.models import database as db_models
from app.models import schemas
from app.api.routes.auth import get_current_user, get_optional_current_user, require_admin
from app.core.bootstrap import SYSTEM_BOARD_IDS
from app.services.compiler import compiler_instance
from app.services.compile_queue import classify_grading_result, compile_queue
from app.services.rating import RatingStats, calculate_rating_stats, invalidate_rating_cache, rating_stats_for_users
from app.services.redis_client import cache_get_json, cache_set_json, redis_key

router = APIRouter()


def _validate_submission_code_size(code: str) -> None:
    if len(code.encode("utf-8")) > settings.SUBMISSION_CODE_MAX_BYTES:
        raise HTTPException(status_code=413, detail="제출 코드가 너무 큽니다.")


def _prune_old_submissions(db: Session, user_id: str) -> None:
    stale_ids = [
        submission_id
        for (submission_id,) in (
            db.query(db_models.Submission.id)
            .filter(db_models.Submission.user_id == user_id)
            .order_by(db_models.Submission.created_at.desc())
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


def _serialize_problem(problem: db_models.Problem, include_hidden: bool = False, progress: dict | None = None) -> dict:
    sample_cases, hidden_cases = _normalize_problem_test_cases(problem.test_cases)
    progress = progress or {}
    return {
        "id": problem.id,
        "creator_id": problem.creator_id,
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
        "username": user.username,
        "total_score": user.total_score,
        "rating": stats.rating,
        "tier": stats.tier,
        "solved_count": stats.solved_count,
        "avatar_url": user.avatar_url,
    }


def _leaderboard_rows(db: Session) -> list[tuple[db_models.User, RatingStats]]:
    users = (
        db.query(db_models.User)
        .filter(db_models.User.role != "admin")
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
    db: Session = Depends(get_db),
    current_user: db_models.User = Depends(require_admin)
):
    db_problem = db_models.Problem(
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
    return _serialize_problem(db_problem, include_hidden=True)

@router.get("/", response_model=List[schemas.ProblemRead])
def list_problems(
    difficulty: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: db_models.User | None = Depends(get_optional_current_user),
):
    query = db.query(db_models.Problem).filter(~db_models.Problem.id.in_(SYSTEM_BOARD_IDS))
    if difficulty:
        query = query.filter(db_models.Problem.difficulty == difficulty)
    
    problems = query.order_by(db_models.Problem.created_at.asc()).all()
    
    if tag:
        problems = [p for p in problems if tag in p.tags]
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
        )
        for problem in problems
    ]

@router.put("/{id}", response_model=schemas.ProblemRead)
def update_problem(id: str, problem: schemas.ProblemCreate, db: Session = Depends(get_db), current_user: db_models.User = Depends(require_admin)):
    db_problem = db.query(db_models.Problem).filter(db_models.Problem.id == id).first()
    if not db_problem:
        raise HTTPException(status_code=404, detail="Problem not found")    
    
    db_problem.title = problem.title
    db_problem.difficulty = problem.difficulty
    db_problem.tags = problem.tags
    db_problem.description = problem.description
    db_problem.points = problem.points
    db_problem.test_cases = {
        "sample": [tc.model_dump() for tc in problem.test_cases],
        "hidden": [tc.model_dump() for tc in problem.hidden_test_cases],
    }
    
    db.commit()
    db.refresh(db_problem)
    invalidate_rating_cache()
    return _serialize_problem(db_problem, include_hidden=True)

@router.delete("/{id}")
def delete_problem(id: str, db: Session = Depends(get_db), current_user: db_models.User = Depends(require_admin)):
    db_problem = db.query(db_models.Problem).filter(db_models.Problem.id == id).first()
    if not db_problem:
        raise HTTPException(status_code=404, detail="Problem not found")
    if id in SYSTEM_BOARD_IDS:
        raise HTTPException(status_code=400, detail="System board cannot be deleted")
    
    db.query(db_models.Comment).filter(db_models.Comment.problem_id == id).delete(synchronize_session=False)
    db.query(db_models.Submission).filter(db_models.Submission.problem_id == id).delete(synchronize_session=False)
    db.query(db_models.CompileQueueRecord).filter(db_models.CompileQueueRecord.problem_id == id).delete(synchronize_session=False)
    db.query(db_models.UserProblemScore).filter(db_models.UserProblemScore.challenge_id == id).delete(synchronize_session=False)
    db.delete(db_problem)
    db.commit()
    invalidate_rating_cache()
    return {"message": "Successfully deleted"}

@router.get("/leaderboard", response_model=List[schemas.LeaderboardRead])
def get_leaderboard(
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    cache_key = redis_key("leaderboard", str(limit))
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
        user.total_score += awarded_points
        db.add(
            db_models.UserProblemScore(
                user_id=user.id,
                challenge_id=score.challenge_id,
                points_awarded=awarded_points,
            )
        )

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
    return schemas.SubmissionRead(
        id=submission.id,
        problem_id=submission.problem_id,
        problem_title=problem.title if problem else None,
        user_id=submission.user_id,
        username=user.username if user else None,
        language=submission.language,
        status=submission.status,
        verdict=submission.verdict or _submission_verdict_from_status(submission.status),
        sample_total_cases=submission.sample_total_cases,
        sample_passed_cases=submission.sample_passed_cases,
        grading_completed=submission.grading_completed,
        grading_passed=submission.grading_passed,
        awarded_points=submission.awarded_points,
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
    query = db.query(db_models.Submission)
    if problem_id:
        query = query.filter(db_models.Submission.problem_id == problem_id)
    if status:
        query = query.filter(db_models.Submission.status == status)
    if verdict:
        query = query.filter(db_models.Submission.verdict == verdict)
    if mine:
        if current_user is None:
            raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
        query = query.filter(db_models.Submission.user_id == current_user.id)
    elif user_id:
        query = query.filter(db_models.Submission.user_id == user_id)
    elif username:
        matched_user = (
            db.query(db_models.User)
            .filter(db_models.User.username == username.strip())
            .first()
        )
        if matched_user is None:
            return {"submissions": [], "total": db.query(db_models.Submission).count(), "filtered_total": 0}
        query = query.filter(db_models.Submission.user_id == matched_user.id)

    total = db.query(db_models.Submission).count()
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


@router.get("/{id}", response_model=schemas.ProblemRead)
def get_problem(
    id: str,
    db: Session = Depends(get_db),
    current_user: db_models.User | None = Depends(get_optional_current_user),
):
    problem = db.query(db_models.Problem).filter(db_models.Problem.id == id).first()
    if not problem or problem.id in SYSTEM_BOARD_IDS:
        raise HTTPException(status_code=404, detail="Problem not found")

    progress_by_problem = _problem_progress_map(
        db,
        current_user.id if current_user else None,
        [problem.id],
    )
    return _serialize_problem(
        problem,
        include_hidden=current_user is not None
        and (current_user.role == "admin" or problem.creator_id == current_user.id),
        progress=progress_by_problem.get(problem.id),
    )

@router.post("/{id}/submit", response_model=schemas.SubmissionResponse, tags=["Grading"])
async def submit_problem(
    id: str, 
    request: schemas.SubmissionRequest, 
    db: Session = Depends(get_db),
    current_user: db_models.User | None = Depends(get_optional_current_user)
):
    _validate_submission_code_size(request.code)
    problem = db.query(db_models.Problem).filter(db_models.Problem.id == id).first()
    if not problem:
        raise HTTPException(status_code=404, detail="Problem not found")

    already_solved = False
    if current_user is not None:
        already_solved = db.query(db_models.UserProblemScore).filter_by(
            user_id=current_user.id, challenge_id=id
        ).first() is not None

    sample_cases, hidden_cases = _normalize_problem_test_cases(problem.test_cases)
    details: list[schemas.TestCaseResult] = []
    sample_passed_count = 0
    hidden_passed_count = 0
    first_failed_verdict: schemas.CompileQueueVerdict | None = None

    async def run_case(tc: dict, case_number: int, phase: str, visible: bool) -> schemas.TestCaseResult:
        expected_output = tc.get("expected_output", "").strip()
        result = await compile_queue.run(
            kind="grading",
            language=request.language,
            source_code=request.code,
            user_id=current_user.id if current_user else None,
            username=current_user.username if current_user else None,
            problem_id=problem.id,
            problem_title=problem.title,
            result_classifier=lambda case_result: classify_grading_result(case_result, expected_output),
            task=lambda: compiler_instance.run(
                source_code=request.code,
                language=request.language,
                stdin=tc.get("input", ""),
            ),
        )

        actual_output = result.get("stdout", "").strip()
        verdict = classify_grading_result(result, expected_output)
        status = "Correct" if verdict == "accepted" else ("Wrong" if verdict == "wrong_answer" else "Error")
        return schemas.TestCaseResult(
            case_number=case_number,
            phase=phase,
            is_visible=visible,
            status=status,
            verdict=verdict,
            input=tc.get("input", "") if visible else "",
            expected=expected_output if visible else "",
            actual=(actual_output if status != "Error" else result.get("stderr", "Error")) if visible else "",
        )

    for index, tc in enumerate(sample_cases, start=1):
        case_result = await run_case(tc, index, "sample", True)
        details.append(case_result)
        if case_result.status == "Correct":
            sample_passed_count += 1
        elif first_failed_verdict is None:
            first_failed_verdict = case_result.verdict

    grading_completed = sample_passed_count == len(sample_cases)

    if grading_completed:
        for index, tc in enumerate(hidden_cases, start=1):
            case_result = await run_case(tc, index, "grading", False)
            if case_result.status == "Correct":
                hidden_passed_count += 1
            elif first_failed_verdict is None:
                first_failed_verdict = case_result.verdict

    grading_passed = grading_completed and hidden_passed_count == len(hidden_cases)

    if sample_passed_count != len(sample_cases):
        final_status = "SampleFailed"
    elif grading_passed:
        final_status = "Accepted"
    else:
        final_status = "Rejected"
    final_verdict = "accepted" if final_status == "Accepted" else (first_failed_verdict or "wrong_answer")
    final_message = _submission_message(final_verdict)

    total_score = current_user.total_score if current_user is not None else 0
    awarded_points = 0
    should_invalidate_rating = False
    if final_status == "Accepted" and current_user is not None and not already_solved:
        awarded_points = problem.points
        current_user.total_score += awarded_points
        total_score = current_user.total_score

        score_record = db_models.UserProblemScore(
            user_id=current_user.id,
            challenge_id=id,
            points_awarded=awarded_points
        )
        db.add(score_record)
        should_invalidate_rating = True
    elif current_user is not None:
        total_score = current_user.total_score

    db.add(
        db_models.Submission(
            user_id=current_user.id if current_user is not None else None,
            problem_id=id,
            language=request.language,
            code=request.code,
            status=final_status,
            verdict=final_verdict,
            sample_total_cases=len(sample_cases),
            sample_passed_cases=sample_passed_count,
            grading_completed=grading_completed,
            grading_passed=grading_passed,
            awarded_points=awarded_points,
        )
    )
    if current_user is not None:
        _prune_old_submissions(db, current_user.id)
    db.commit()
    if should_invalidate_rating and current_user is not None:
        invalidate_rating_cache(current_user.id)

    return schemas.SubmissionResponse(
        status=final_status,
        verdict=final_verdict,
        total_cases=len(sample_cases),
        passed_cases=sample_passed_count,
        sample_total_cases=len(sample_cases),
        sample_passed_cases=sample_passed_count,
        grading_completed=grading_completed,
        grading_passed=grading_passed,
        total_score=total_score,
        details=[detail for detail in details if detail.is_visible],
        message=final_message,
    )
