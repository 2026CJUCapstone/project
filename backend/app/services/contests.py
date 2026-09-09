import asyncio
import contextlib
import logging
import uuid
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError

from app.core.database import SessionLocal
from app.models import database as m
from app.services import compiler as compiler_service
from app.services.compile_queue import compile_queue, classify_grading_result
from app.services.contest_access import now_utc, utc_naive, iso
from app.services.rating import invalidate_rating_cache

logger = logging.getLogger(__name__)
PENALTY_VERDICTS = {"wrong_answer", "runtime_error", "time_limit_exceeded", "memory_limit_exceeded"}
PENDING = ("queued", "running")


def contest_state(contest, at=None):
    at = at or now_utc()
    if not contest.published:
        return "draft"
    if at < utc_naive(contest.starts_at):
        return "upcoming"
    if at < utc_naive(contest.ends_at):
        return "running"
    return "finished" if contest.finalized_at else "finalizing"


def get_contest(db, contest_id, user=None):
    contest = db.get(m.Contest, contest_id)
    if not contest or (not contest.published and (not user or user.role != "admin")):
        raise HTTPException(404, "대회를 찾을 수 없습니다.")
    return contest


def participant(db, contest_id, user):
    return bool(user and db.query(m.ContestParticipant.id).filter_by(contest_id=contest_id, user_id=user.id).first())


def problem_rows(db, contest_id):
    return db.query(m.ContestProblem).filter_by(contest_id=contest_id).order_by(m.ContestProblem.position).all()


def contest_read(db, contest, user=None):
    at = now_utc()
    joined = participant(db, contest.id, user)
    is_admin = bool(user and user.role == "admin")
    state = contest_state(contest, at)
    can_view = is_admin or state in ("finalizing", "finished") or (state == "running" and joined)
    return {
        "id": contest.id, "title": contest.title, "description": contest.description,
        "startsAt": iso(contest.starts_at), "endsAt": iso(contest.ends_at), "serverTime": iso(at),
        "state": state, "published": contest.published, "joined": joined, "canManage": is_admin,
        "participantCount": db.query(m.ContestParticipant).filter_by(contest_id=contest.id).count(),
        "problems": [problem_read(p) for p in problem_rows(db, contest.id)] if can_view else [],
    }


def problem_read(problem, detail=False):
    snap = problem.snapshot
    result = {"id": problem.id, "problemId": problem.problem_id, "label": chr(65 + problem.position),
              "title": snap["title"], "points": problem.points, "difficulty": snap["difficulty"]}
    if detail:
        result.update(description=snap["description"], tags=snap["tags"], testCases=snap["sample"])
    return result


def submission_read(submission, include_code=False):
    result = {"id": submission.id, "contestProblemId": submission.contest_problem_id,
              "language": submission.language, "receivedAt": iso(submission.received_at),
              "status": submission.status, "verdict": submission.verdict, "finishedAt": iso(submission.finished_at)}
    if include_code:
        result["code"] = submission.code
    return result


def scoreboard(db, contest):
    problems = problem_rows(db, contest.id)
    submissions = db.query(m.ContestSubmission).filter_by(contest_id=contest.id).order_by(
        m.ContestSubmission.received_at, m.ContestSubmission.id).all()
    by_user = {}
    for s in submissions:
        by_user.setdefault(s.user_id, []).append(s)
    rows = []
    users = db.query(m.User).join(m.ContestParticipant, m.ContestParticipant.user_id == m.User.id).filter(
        m.ContestParticipant.contest_id == contest.id).all()
    for user in users:
        cells, total, penalty_count, last_seconds = [], 0, 0, 0
        user_submissions = by_user.get(user.id, [])
        for p in problems:
            attempts = [s for s in user_submissions if s.contest_problem_id == p.id]
            accepted = next((s for s in attempts if s.verdict == "accepted" and s.status == "completed"), None)
            wrong = 0
            for s in attempts:
                if accepted is not None and s.id == accepted.id:
                    break
                if s.status == "completed" and s.verdict in PENALTY_VERDICTS:
                    wrong += 1
            elapsed = max(0, (utc_naive(accepted.received_at) - utc_naive(contest.starts_at)).total_seconds()) if accepted else None
            if accepted:
                total += p.points
                penalty_count += wrong
                last_seconds = max(last_seconds, elapsed)
            pending = any(s.status in PENDING for s in attempts)
            cells.append({"contestProblemId": p.id, "label": chr(65 + p.position),
                          "points": p.points if accepted else 0, "wrongAttempts": wrong,
                          "acceptedAt": iso(accepted.received_at) if accepted else None,
                          "elapsedSeconds": elapsed, "pending": pending,
                          "verdict": "accepted" if accepted else ("pending" if pending else attempts[-1].verdict if attempts else None)})
        rows.append({"userId": user.id, "username": user.nickname or user.username,
                     "totalPoints": total, "penaltySeconds": last_seconds + penalty_count * 300, "problems": cells})
    rows.sort(key=lambda r: (-r["totalPoints"], r["penaltySeconds"], r["userId"]))
    previous, rank = None, 0
    for position, row in enumerate(rows, 1):
        key = (row["totalPoints"], row["penaltySeconds"])
        if key != previous:
            rank = position
        row["rank"] = rank
        previous = key
    return {"rows": rows, "state": contest_state(contest), "serverTime": iso(now_utc()),
            "pendingCount": sum(s.status in PENDING for s in submissions),
            "problems": [{"id": p.id, "label": chr(65 + p.position), "points": p.points} for p in problems]}


def finalize_contests():
    at = now_utc()
    with SessionLocal() as db:
        ids = [c.id for c in db.query(m.Contest).filter(m.Contest.published.is_(True), m.Contest.ends_at <= at,
                                                      m.Contest.finalized_at.is_(None)).all()]
    for contest_id in ids:
        with SessionLocal() as db:
            # This conditional write serializes finalizers across backend processes.
            claimed = db.query(m.Contest).filter_by(id=contest_id, finalized_at=None).update({"finalized_at": at})
            if not claimed:
                db.rollback()
                continue
            # Check after taking the same row lock used by submission admission.
            if db.query(m.ContestSubmission.id).filter(m.ContestSubmission.contest_id == contest_id,
                                                     m.ContestSubmission.status.in_(PENDING)).first():
                db.rollback()
                continue
            accepted = db.query(m.ContestSubmission).filter_by(contest_id=contest_id, verdict="accepted", status="completed").order_by(
                m.ContestSubmission.received_at, m.ContestSubmission.id).all()
            problem_map = {p.id: p for p in problem_rows(db, contest_id)}
            awarded_users = set()
            # Shared award lock order: user first, then unique solve. Stable
            # ordering also prevents two contest finalizers from deadlocking.
            for user_id in sorted({s.user_id for s in accepted}):
                db.query(m.User).filter_by(id=user_id).update({"id": user_id}, synchronize_session=False)
            for s in accepted:
                p = problem_map[s.contest_problem_id]
                if db.query(m.UserProblemScore.id).filter_by(user_id=s.user_id, challenge_id=p.problem_id).first():
                    continue
                points = p.snapshot["practicePoints"]
                try:
                    with db.begin_nested():
                        db.add(m.UserProblemScore(user_id=s.user_id, challenge_id=p.problem_id, points_awarded=points,
                                                  solved_at=s.received_at))
                        db.flush()
                except IntegrityError:
                    continue
                db.query(m.User).filter_by(id=s.user_id).update({m.User.total_score: m.User.total_score + points})
                awarded_users.add(s.user_id)
            db.commit()
            for user_id in awarded_users:
                invalidate_rating_cache(user_id)


def claim_submission():
    at, token = now_utc(), uuid.uuid4().hex
    eligible = or_(m.ContestSubmission.status == "queued", and_(m.ContestSubmission.status == "running",
                      or_(m.ContestSubmission.lease_until.is_(None), m.ContestSubmission.lease_until < at)))
    with SessionLocal() as db:
        candidate = db.query(m.ContestSubmission.id).filter(eligible).order_by(m.ContestSubmission.received_at).first()
        if candidate is None:
            return None
        updated = db.query(m.ContestSubmission).filter(m.ContestSubmission.id == candidate.id, eligible).update({
            "status": "running", "verdict": "running", "lease_token": token,
            "lease_until": at + timedelta(seconds=120), "attempts": m.ContestSubmission.attempts + 1,
        }, synchronize_session=False)
        db.commit()
        return (candidate.id, token) if updated else None


def renew_lease(submission_id, token):
    with SessionLocal() as db:
        count = db.query(m.ContestSubmission).filter_by(id=submission_id, lease_token=token, status="running").update({
            "lease_until": now_utc() + timedelta(seconds=120)})
        db.commit()
        return count


async def judge_submission(submission_id, token):
    with SessionLocal() as db:
        s = db.get(m.ContestSubmission, submission_id)
        if not s or s.lease_token != token:
            return
        code, language, attempts = s.code, s.language, s.attempts
        snap = db.get(m.ContestProblem, s.contest_problem_id).snapshot

    async def heartbeat():
        while True:
            await asyncio.sleep(20)
            if not renew_lease(submission_id, token):
                return

    heartbeat_task = asyncio.create_task(heartbeat())
    verdict = "system_error"
    async def private_execution(method, **kwargs):
        try:
            return await method(**kwargs)
        except Exception:
            # Queue failures are public. Never propagate sandbox diagnostics
            # that might contain source code or a hidden test's input.
            logger.exception("Contest sandbox failure for %s", submission_id)
            raise RuntimeError("Contest sandbox unavailable") from None
    try:
        if attempts > 3:
            return
        # Omit identifying metadata from the public compile queue for contest jobs.
        compiled = await compile_queue.run(
            kind="compile", language=language, source_code=code,
            result_classifier=lambda r: "compile_success" if r["exit_code"] == 0 else "compile_error",
            task=lambda: private_execution(compiler_service.compiler_instance._execute, mode="compile", source_code=code, language=language),
        )
        if compiled["exit_code"] != 0:
            verdict = "compile_error" if compiled["exit_code"] not in (124, 137) else "system_error"
        else:
            cases = snap["sample"] + snap["hidden"]
            verdict = "accepted" if cases else "system_error"
            for case in cases:
                result = await compile_queue.run(
                    kind="grading", language=language, source_code=code,
                    result_classifier=lambda r, expected=case["expectedOutput"]: classify_grading_result(r, expected),
                    task=lambda case=case: private_execution(compiler_service.compiler_instance.run, source_code=code, language=language, stdin=case["input"]),
                )
                verdict = classify_grading_result(result, case["expectedOutput"])
                if verdict != "accepted":
                    break
    except asyncio.CancelledError:
        # Graceful shutdown releases the lease; crashes recover on lease expiry.
        with SessionLocal() as db:
            db.query(m.ContestSubmission).filter_by(id=submission_id, lease_token=token).update({"status": "queued", "verdict": "pending"})
            db.commit()
        raise
    except Exception:
        logger.exception("Contest judging failed for %s", submission_id)
    finally:
        heartbeat_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat_task
        with SessionLocal() as db:
            retry = verdict == "system_error" and attempts < 3
            db.query(m.ContestSubmission).filter_by(id=submission_id, lease_token=token, status="running").update({
                "status": "queued" if retry else "completed", "verdict": "pending" if retry else verdict,
                "finished_at": None if retry else now_utc(), "lease_until": None, "lease_token": None,
            })
            db.commit()


async def contest_worker():
    while True:
        try:
            claim = claim_submission()
            if claim:
                await judge_submission(*claim)
            else:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Contest worker iteration failed")
            await asyncio.sleep(2)


async def contest_maintenance():
    while True:
        try:
            finalize_contests()
        except Exception:
            logger.exception("Contest finalization failed; retrying")
        await asyncio.sleep(1)
