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


def resolve_problem_identifier(db, value):
    return db.query(Problem).filter(or_(Problem.id == value, Problem.public_id == value)).first()


def require_public_problem(db, problem_id, user=None):
    problem = resolve_problem_identifier(db, problem_id)
    if problem is None:
        raise HTTPException(status_code=404, detail="Problem not found")
    internal_id = problem.id
    # Archival is not an admin draft view: no new grading/discussion is allowed.
    if problem.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Problem not found")
    # Administrators may inspect drafts, but contest grading uses snapshots.
    if user is not None and user.role == "admin":
        return problem
    if db.query(Problem.id).filter(
        Problem.id == internal_id,
        Problem.id.in_(private_problem_ids()),
    ).first():
        raise HTTPException(status_code=404, detail="Problem not found")
    return problem
