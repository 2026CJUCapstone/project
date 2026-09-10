import copy
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.routes.auth import get_current_user, get_optional_current_user, require_admin
from app.core.database import get_db
from app.core.config import settings
from app.core.bootstrap import SYSTEM_BOARD_IDS
from app.models import database as m
from app.models.contest_schemas import ContestWrite, ContestSubmit
from app.services import contests as service
from app.services.contest_access import now_utc, utc_naive, private_problem_ids
from app.services.execution_admission import admit_execution

router = APIRouter()


def snapshot(problem):
    raw = problem.test_cases
    sample, hidden = (raw, []) if isinstance(raw, list) else (raw.get("sample", []), raw.get("hidden", []))
    def cases(items):
        return [{"input": x.get("input", ""), "expectedOutput": x.get("expected_output", x.get("expectedOutput", ""))} for x in items]
    return {"title": problem.title, "description": problem.description, "difficulty": problem.difficulty,
            "tags": copy.deepcopy(problem.tags), "practicePoints": problem.points, "sample": cases(sample), "hidden": cases(hidden)}


def save_contest(db, contest, data, user):
    at = now_utc()
    was_published = bool(contest and contest.published)
    if data.published and utc_naive(data.starts_at) <= at:
        raise HTTPException(400, "공개할 대회의 시작 시각은 현재보다 늦어야 합니다.")
    if contest:
        locked = db.query(m.Contest).filter(m.Contest.id == contest.id, or_(m.Contest.published.is_(False), m.Contest.starts_at > at)).update({
            "title": data.title.strip(), "description": data.description, "starts_at": utc_naive(data.starts_at),
            "ends_at": utc_naive(data.ends_at), "published": data.published,
        }, synchronize_session=False)
        if not locked:
            raise HTTPException(409, "시작한 대회는 수정할 수 없습니다.")
        old = {p.problem_id: p for p in service.problem_rows(db, contest.id)}
        db.query(m.ContestProblem).filter_by(contest_id=contest.id).delete(synchronize_session=False)
        db.flush()
    else:
        contest = m.Contest(creator_id=user.id, title=data.title.strip(), description=data.description,
                            starts_at=utc_naive(data.starts_at), ends_at=utc_naive(data.ends_at), published=data.published)
        db.add(contest)
        db.flush()
        old = {}
    used = set()
    for position, item in enumerate(data.problems):
        problem = db.get(m.Problem, item.problem_id) if item.problem_id else None
        is_new = bool(item.problem_id in old and old[item.problem_id].is_new)
        if item.problem_id:
            if not problem or problem.deleted_at is not None or problem.id in SYSTEM_BOARD_IDS:
                raise HTTPException(400, "문제를 찾을 수 없습니다.")
            if not is_new and db.query(m.Problem.id).filter(m.Problem.id == problem.id, m.Problem.id.in_(private_problem_ids())).first():
                raise HTTPException(400, "다른 대회의 비공개 문제는 사용할 수 없습니다.")
            if item.new_problem and not is_new:
                raise HTTPException(400, "기존 공개 문제는 원래 문제 관리 화면에서 수정하세요.")
        if item.new_problem:
            new = item.new_problem
            if not problem:
                problem = m.Problem(creator_id=user.id)
                db.add(problem)
                is_new = True
            problem.title, problem.description = new.title, new.description
            problem.difficulty, problem.tags, problem.points = new.difficulty, new.tags, new.points
            problem.test_cases = {"sample": [c.model_dump() for c in new.test_cases], "hidden": [c.model_dump() for c in new.hidden_test_cases]}
            db.flush()
        if problem.id in used:
            raise HTTPException(400, "동일한 문제를 중복 등록할 수 없습니다.")
        used.add(problem.id)
        snap = snapshot(problem)
        if was_published and data.published and problem.id in old and not item.new_problem:
            # Editing dates/points must not silently import later source edits.
            snap = copy.deepcopy(old[problem.id].snapshot)
        if data.published and not snap["sample"] and not snap["hidden"]:
            raise HTTPException(400, "공개할 문제에는 테스트가 한 개 이상 필요합니다.")
        if len(snap["sample"]) + len(snap["hidden"]) > 200:
            raise HTTPException(400, "문제당 테스트는 200개 이하로 등록하세요.")
        db.add(m.ContestProblem(contest_id=contest.id, problem_id=problem.id, position=position,
                                points=item.points, is_new=is_new, snapshot=snap))
    db.flush()
    for problem_id, previous in old.items():
        if previous.is_new and problem_id not in used:
            # Pre-start drafts have no contest submissions or public discussions.
            db.query(m.Comment).filter_by(problem_id=problem_id).delete()
            db.query(m.Problem).filter_by(id=problem_id).delete()
    # Contest composition and publication/schedule state become visible with
    # this same commit, so an old public scoreboard revision cannot survive it.
    service.bump_scoreboard_revision(db, contest.id)
    db.commit()
    db.refresh(contest)
    return service.contest_read(db, contest, user)


@router.get("")
def list_contests(response: Response, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
                  state: str | None = Query(None), search: str | None = Query(None, max_length=100),
                  db: Session = Depends(get_db), user=Depends(get_optional_current_user)):
    query = db.query(m.Contest)
    if not user or user.role != "admin":
        query = query.filter(m.Contest.published.is_(True))
    at = now_utc()
    if state == "draft":
        query = query.filter(m.Contest.published.is_(False))
    elif state == "upcoming":
        query = query.filter(m.Contest.published.is_(True), m.Contest.starts_at > at)
    elif state == "running":
        query = query.filter(m.Contest.published.is_(True), m.Contest.starts_at <= at, m.Contest.ends_at > at)
    elif state == "finalizing":
        query = query.filter(m.Contest.published.is_(True), m.Contest.ends_at <= at, m.Contest.finalized_at.is_(None))
    elif state == "finished":
        # The existing UI's "finished" filter also includes finalizing contests.
        query = query.filter(m.Contest.published.is_(True), m.Contest.ends_at <= at)
    if search and search.strip():
        query = query.filter(m.Contest.title.contains(search.strip(), autoescape=True))
    response.headers["X-Total-Count"] = str(query.count())
    contests = query.order_by(m.Contest.starts_at.desc()).offset(offset).limit(limit).all()
    return [service.contest_read(db, c, user) for c in contests]


@router.post("", status_code=201)
def create_contest(data: ContestWrite, db: Session = Depends(get_db), user=Depends(require_admin)):
    return save_contest(db, None, data, user)


@router.get("/library")
def problem_library(response: Response, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
                    db: Session = Depends(get_db), user=Depends(require_admin)):
    query = db.query(m.Problem).filter(
        m.Problem.deleted_at.is_(None), ~m.Problem.id.in_(private_problem_ids()), ~m.Problem.id.in_(SYSTEM_BOARD_IDS))
    response.headers["X-Total-Count"] = str(query.count())
    problems = query.order_by(m.Problem.title, m.Problem.id).offset(offset).limit(limit).all()
    return [{"id": p.id, "title": p.title, "points": p.points} for p in problems]


@router.get("/{contest_id}")
def read_contest(contest_id: str, db: Session = Depends(get_db), user=Depends(get_optional_current_user)):
    return service.contest_read(db, service.get_contest(db, contest_id, user), user)


@router.put("/{contest_id}")
def update_contest(contest_id: str, data: ContestWrite, db: Session = Depends(get_db), user=Depends(require_admin)):
    return save_contest(db, service.get_contest(db, contest_id, user), data, user)


@router.get("/{contest_id}/manage")
def manage_contest(contest_id: str, db: Session = Depends(get_db), user=Depends(require_admin)):
    contest = service.get_contest(db, contest_id, user)
    result = service.contest_read(db, contest, user)
    result["problems"] = [{"problemId": p.problem_id, "points": p.points, "newProblem": {
        "title": p.snapshot["title"], "description": p.snapshot["description"], "difficulty": p.snapshot["difficulty"],
        "tags": p.snapshot["tags"], "points": p.snapshot["practicePoints"], "testCases": p.snapshot["sample"],
        "hiddenTestCases": p.snapshot["hidden"],
    } if p.is_new else None} for p in service.problem_rows(db, contest_id)]
    return result


@router.post("/{contest_id}/join")
def join_contest(contest_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    contest = service.get_contest(db, contest_id, user)
    if not contest.published or now_utc() >= utc_naive(contest.ends_at):
        raise HTTPException(400, "참가 신청 기간이 아닙니다.")
    if not service.participant(db, contest_id, user):
        db.add(m.ContestParticipant(contest_id=contest_id, user_id=user.id))
        try:
            service.bump_scoreboard_revision(db, contest.id)
            db.commit()
        except IntegrityError:
            db.rollback()
    return service.contest_read(db, contest, user)


@router.get("/{contest_id}/scoreboard")
def read_scoreboard(contest_id: str, db: Session = Depends(get_db), user=Depends(get_optional_current_user)):
    contest = service.get_contest(db, contest_id, user)
    at = now_utc()
    state = service.contest_state(contest, at)
    # Only the ordinary public, visible scoreboard gets a shared cache entry.
    # Admin and pre-start views may expose a different policy and must never
    # populate or consume that public cache.
    public_cache = state in ("running", "finalizing", "finished") and not (user and user.role == "admin")
    result = service.scoreboard(db, contest, public_cache=public_cache, at=at)
    if state in ("draft", "upcoming") and (not user or user.role != "admin"):
        result["problems"] = []
        for row in result["rows"]:
            row["problems"] = []
    return result


@router.get("/{contest_id}/problems/{contest_problem_id}")
def read_problem(contest_id: str, contest_problem_id: str, db: Session = Depends(get_db), user=Depends(get_optional_current_user)):
    contest = service.get_contest(db, contest_id, user)
    admin = user and user.role == "admin"
    state = service.contest_state(contest)
    if not admin and (state in ("draft", "upcoming") or (state == "running" and not service.participant(db, contest_id, user))):
        raise HTTPException(403, "시작 후 참가자만 문제를 볼 수 있습니다.")
    problem = db.query(m.ContestProblem).filter_by(id=contest_problem_id, contest_id=contest_id).first()
    if not problem:
        raise HTTPException(404, "문제를 찾을 수 없습니다.")
    return {**service.problem_read(problem, detail=True), "contest": service.contest_read(db, contest, user)}


@router.post("/{contest_id}/problems/{contest_problem_id}/submit", status_code=202)
def submit(contest_id: str, contest_problem_id: str, data: ContestSubmit, http_request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)):
    from app.services.execution_runtime import execution_queue
    from app.services.durable_queue import QueueFull, IdempotencyConflict
    received = now_utc()
    admit_execution(http_request, user_id=user.id)
    if not data.code.strip() or len(data.code.encode("utf-8")) > settings.SUBMISSION_CODE_MAX_BYTES:
        raise HTTPException(400, "코드가 비어 있거나 제출 크기 제한을 초과했습니다.")
    service.get_contest(db, contest_id, user)
    queue = execution_queue()
    # Always acquire queue before contest/user locks, including retries.
    queue._lock(db)
    previous = db.query(m.ContestSubmission).filter_by(contest_id=contest_id, user_id=user.id, request_id=data.request_id).first()
    if previous:
        if previous.contest_problem_id != contest_problem_id or previous.language != data.language or previous.code != data.code:
            raise HTTPException(409, "동일 요청 ID에 다른 제출을 사용할 수 없습니다.")
        return service.submission_read(previous)
    if not service.participant(db, contest_id, user):
        raise HTTPException(403, "먼저 대회에 참가 신청하세요.")
    # A pre-deadline request may wait for a DB lock until after maintenance
    # finalizes. Reopen finalization for that recorded receipt, not for late
    # requests. Repeated awards remain safe through the unique solve key.
    valid = db.query(m.Contest).filter(m.Contest.id == contest_id, m.Contest.published.is_(True),
        m.Contest.starts_at <= received, m.Contest.ends_at > received).update({"finalized_at": None}, synchronize_session=False)
    if not valid:
        raise HTTPException(403, "대회 진행 시간에만 제출할 수 있습니다.")
    problem = db.query(m.ContestProblem).filter_by(id=contest_problem_id, contest_id=contest_id).first()
    if problem is None:
        raise HTTPException(404, "문제를 찾을 수 없습니다.")
    if db.query(m.ContestSubmission.id).filter(m.ContestSubmission.contest_id == contest_id,
            m.ContestSubmission.user_id == user.id, m.ContestSubmission.status.in_(service.PENDING)).count() >= 5:
        raise HTTPException(429, "대기 중인 제출이 많습니다. 채점 완료 후 다시 제출하세요.")
    try:
        # Namespace each contest's client request ID; general execution and
        # practice idempotency keys cannot collide with a contest receipt.
        import hashlib
        key = 'contest:' + hashlib.sha256(f'{contest_id}:{data.request_id}'.encode()).hexdigest()
        job = queue.enqueue_in_session(db, owner_key=f'account:{user.id}', quota_key=f'account:{user.id}',
            request_id=key, kind='contest', at=received,
            payload={'code':data.code, 'language':data.language, 'contest_id':contest_id,
                'contest_problem_id':contest_problem_id, 'sample':problem.snapshot['sample'], 'hidden':problem.snapshot['hidden']})
    except QueueFull:
        raise HTTPException(429, '실행 대기열이 가득 찼습니다.', headers={'Retry-After':'5'}) from None
    except IdempotencyConflict:
        raise HTTPException(409, '동일 요청 ID에 다른 제출을 사용할 수 없습니다.') from None
    except ValueError:
        raise HTTPException(413, '채점 요청이 너무 큽니다. 관리자에게 문의하세요.') from None
    record = m.ContestSubmission(execution_job_id=job.id, contest_id=contest_id, contest_problem_id=contest_problem_id, user_id=user.id,
                                request_id=data.request_id, code=data.code, language=data.language, received_at=received)
    db.add(record)
    # No public queue metadata for contest jobs: private titles/identities and
    # submitted code remain visible only via the participant's own endpoint.
    try:
        # Receipt, reopening an end race, and the queued status are one atomic
        # scoreboard fact.  Failed/idempotent admission leaves no revision bump.
        service.bump_scoreboard_revision(db, contest_id)
        db.commit()
    except IntegrityError:
        db.rollback()
        record = db.query(m.ContestSubmission).filter_by(contest_id=contest_id, user_id=user.id, request_id=data.request_id).one()
        if record.contest_problem_id != contest_problem_id or record.language != data.language or record.code != data.code:
            raise HTTPException(409, "동일 요청 ID에 다른 제출을 사용할 수 없습니다.")
    db.refresh(record)
    return service.submission_read(record)


@router.get("/{contest_id}/submissions")
def my_submissions(contest_id: str, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                   db: Session = Depends(get_db), user=Depends(get_current_user)):
    service.get_contest(db, contest_id, user)
    query = db.query(m.ContestSubmission).filter_by(contest_id=contest_id, user_id=user.id)
    return {"total": query.count(), "submissions": [service.submission_read(s) for s in query.order_by(
        m.ContestSubmission.received_at.desc(), m.ContestSubmission.id.desc()).offset(offset).limit(limit).all()]}


@router.get("/{contest_id}/submissions/{submission_id}")
def my_submission(contest_id: str, submission_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    service.get_contest(db, contest_id, user)
    record = db.query(m.ContestSubmission).filter_by(id=submission_id, contest_id=contest_id, user_id=user.id).first()
    if not record:
        raise HTTPException(404, "제출을 찾을 수 없습니다.")
    return service.submission_read(record, include_code=True)
