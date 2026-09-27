from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import or_, select
from app.models.database import Contest, ContestProblem, Problem


def now_utc():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def utc_naive(value):
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def iso(value):
    return utc_naive(value).isoformat() + "Z" if value else None


def private_problem_ids(at=None):
    contest_private = select(ContestProblem.problem_id).join(Contest, Contest.id == ContestProblem.contest_id).where(
        ContestProblem.is_new.is_(True),
        or_(Contest.published.is_(False), Contest.ends_at > (at or now_utc())),
    )
    reviewed_drafts = select(Problem.id).where(
        Problem.publication_review_required.is_(True),
        Problem.publication_approved_at.is_(None),
    )
    return contest_private.union(reviewed_drafts)


def require_public_problem(db, problem_id, user=None):
    # Archival is not an admin draft view: no new grading/discussion is allowed.
    if db.query(Problem.id).filter(Problem.id == problem_id, Problem.deleted_at.is_not(None)).first():
        raise HTTPException(status_code=404, detail="Problem not found")
    # Administrators may inspect drafts, but contest grading uses snapshots.
    if user is not None and user.role == "admin":
        return
    if db.query(Problem.id).filter(
        Problem.id == problem_id,
        Problem.id.in_(private_problem_ids()),
    ).first():
        raise HTTPException(status_code=404, detail="Problem not found")
