from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import or_, select
from app.models.database import Contest, ContestProblem


def now_utc():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def utc_naive(value):
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def iso(value):
    return utc_naive(value).isoformat() + "Z" if value else None


def private_problem_ids(at=None):
    return select(ContestProblem.problem_id).join(Contest, Contest.id == ContestProblem.contest_id).where(
        ContestProblem.is_new.is_(True),
        or_(Contest.published.is_(False), Contest.ends_at > (at or now_utc())),
    )


def require_public_problem(db, problem_id, user=None):
    # Administrators may inspect drafts, but contest grading uses snapshots.
    if user is not None and user.role == "admin":
        return
    if db.query(ContestProblem.id).filter(
        ContestProblem.problem_id == problem_id,
        ContestProblem.problem_id.in_(private_problem_ids()),
    ).first():
        raise HTTPException(status_code=404, detail="Problem not found")
