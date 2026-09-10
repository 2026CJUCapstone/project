import asyncio
import logging

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.core.database import SessionLocal
from app.models import database as m
from app.services.contest_access import now_utc, utc_naive, iso
from app.services.rating import invalidate_rating_cache
from app.services.scoreboard_cache import (
    bump_scoreboard_revision,
    cache_safe_session,
    current_revision,
    read_public,
    write_public,
)

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


def _scoreboard_projection(db, contest):
    """Compute the cache-safe scoreboard shape from receipt-ordered facts."""
    # ContestProblem.snapshot includes private statement/test material.  Score
    # computation needs only the stable public identifier, position and points.
    problems = db.query(
        m.ContestProblem.id,
        m.ContestProblem.position,
        m.ContestProblem.points,
    ).filter_by(contest_id=contest.id).order_by(m.ContestProblem.position).all()
    submissions = db.query(
        m.ContestSubmission.id,
        m.ContestSubmission.contest_problem_id,
        m.ContestSubmission.user_id,
        m.ContestSubmission.received_at,
        m.ContestSubmission.status,
        m.ContestSubmission.verdict,
    ).filter_by(contest_id=contest.id).order_by(
        m.ContestSubmission.received_at, m.ContestSubmission.id).all()
    by_user = {}
    for s in submissions:
        by_user.setdefault(s.user_id, []).append(s)
    rows = []
    participant_ids = [user_id for (user_id,) in db.query(m.ContestParticipant.user_id).join(
        m.User, m.User.id == m.ContestParticipant.user_id).filter(
            m.ContestParticipant.contest_id == contest.id).all()]
    for user_id in participant_ids:
        cells, total, penalty_count, last_seconds = [], 0, 0, 0
        user_submissions = by_user.get(user_id, [])
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
        rows.append({"userId": user_id, "totalPoints": total,
                     "penaltySeconds": last_seconds + penalty_count * 300, "problems": cells})
    rows.sort(key=lambda r: (-r["totalPoints"], r["penaltySeconds"], r["userId"]))
    previous, rank = None, 0
    for position, row in enumerate(rows, 1):
        key = (row["totalPoints"], row["penaltySeconds"])
        if key != previous:
            rank = position
        row["rank"] = rank
        previous = key
    return {"rows": rows, "pendingCount": sum(s.status in PENDING for s in submissions),
            "problems": [{"id": p.id, "label": chr(65 + p.position), "points": p.points} for p in problems]}


def _scoreboard_names(db, rows):
    user_ids = [row["userId"] for row in rows]
    if not user_ids:
        return {}
    return {
        user_id: nickname or username
        for user_id, nickname, username in db.query(m.User.id, m.User.nickname, m.User.username).filter(
            m.User.id.in_(user_ids)).all()
    }


def _scoreboard_response(db, contest, projection, at):
    names = _scoreboard_names(db, projection["rows"])
    rows = []
    for row in projection["rows"]:
        # Never mutate a Redis-decoded object: a cache hit must remain the
        # name-free, public projection written by the original request.
        rows.append({
            "userId": row["userId"],
            "username": names.get(row["userId"], row["userId"]),
            "totalPoints": row["totalPoints"],
            "penaltySeconds": row["penaltySeconds"],
            "problems": [dict(cell) for cell in row["problems"]],
            "rank": row["rank"],
        })
    return {"rows": rows, "state": contest_state(contest, at), "serverTime": iso(at),
            "pendingCount": projection["pendingCount"],
            "problems": [dict(problem) for problem in projection["problems"]]}


def scoreboard(db, contest, *, public_cache=False, at=None):
    """Return a fresh public response, optionally reusing a safe Redis shape."""
    at = at or now_utc()
    use_cache = public_cache and cache_safe_session(db)
    # A long-lived SQLAlchemy session can hold an old Contest instance.  Use
    # an explicit scalar so the Redis key always tracks DB state, not identity
    # map state from a prior request.
    revision = current_revision(db, contest.id) if use_cache else None
    projection = read_public(contest.id, revision) if revision is not None else None
    if projection is None:
        projection = _scoreboard_projection(db, contest)
        # A writer may commit between the ledger projection and this query.
        # Never place a mixed-generation board in Redis; a later request can
        # calculate it again against one generation.
        if use_cache and revision is not None and cache_safe_session(db) and current_revision(db, contest.id) == revision:
            write_public(contest.id, revision, projection)
    return _scoreboard_response(db, contest, projection, at)


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
            bump_scoreboard_revision(db, contest_id)
            db.commit()
            for user_id in awarded_users:
                invalidate_rating_cache(user_id)


async def contest_maintenance():
    while True:
        try:
            finalize_contests()
        except Exception:
            logger.exception("Contest finalization failed; retrying")
        await asyncio.sleep(1)
