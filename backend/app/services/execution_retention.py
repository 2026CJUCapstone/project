"""Bounded content removal, not receipt deletion or permission to release a lease."""
from datetime import timedelta

from sqlalchemy import exists

from app.models.database import ExecutionJob, ContestSubmission
from app.services.contest_access import now_utc, utc_naive
from app.services.runtime_registry import execution_lock


def expire_execution_content(db, *, retention_days, at=None, batch_size=500):
    """Caller commits. Zero is disabled until a retention policy is approved.

    Keep receipt identity/hash, terminal state, lease/provenance and score records.
    No source/result/snapshot is read into Python while selecting expired jobs.
    """
    if (type(retention_days) is not int or not 0 <= retention_days <= 3650
            or type(batch_size) is not int or not 1 <= batch_size <= 500):
        raise ValueError('Explicit bounded execution retention policy required')
    if retention_days == 0:
        return 0
    at = utc_naive(at or now_utc())
    cutoff = at - timedelta(days=retention_days)
    execution_lock(db)
    eligible = db.query(ExecutionJob.id).filter(
        ExecutionJob.kind.in_(('compile', 'run', 'practice', 'terminal')),
        ExecutionJob.status.in_(('completed', 'failed')),
        ExecutionJob.finished_at < cutoff,
        ExecutionJob.content_expired_at.is_(None),
        ExecutionJob.lease_token.is_(None), ExecutionJob.lease_until.is_(None),
        ExecutionJob.sandbox_operation.is_(None),
        ~exists().where(ContestSubmission.execution_job_id == ExecutionJob.id),
    )
    ids = [row_id for (row_id,) in eligible.order_by(ExecutionJob.finished_at, ExecutionJob.id).limit(batch_size)]
    if not ids:
        return 0
    # All worker transitions/retries use the same lock; no active payload can
    # become a candidate between this bounded selection and update.
    return db.query(ExecutionJob).filter(ExecutionJob.id.in_(ids)).update({
        ExecutionJob.payload: {}, ExecutionJob.result: None,
        ExecutionJob.content_expired_at: at,
    }, synchronize_session=False)
