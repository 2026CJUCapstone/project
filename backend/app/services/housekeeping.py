"""Bounded, idempotent retention; durable active jobs and contest records stay."""
import asyncio
import logging
from datetime import timedelta

from sqlalchemy import exists, or_

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.database import Submission, ExecutionJob
from app.services.contest_access import now_utc
from app.services.execution_retention import expire_execution_content
from app.services.queue_retention import purge_queue_history
from app.services.runtime_registry import execution_lock

logger = logging.getLogger(__name__)


def purge_expired_anonymous_submissions(db, *, at=None, batch_size=500):
    if type(batch_size) is not int or not 1 <= batch_size <= 500:
        raise ValueError('Bounded submission retention batch required')
    # An explicit zero preserves legacy records during a migration/rollout.
    # Do not interpret "disabled" as a one-day destructive retention policy.
    if settings.ANONYMOUS_SUBMISSION_RETENTION_DAYS == 0:
        return 0
    # Match worker publication lock order: execution lock, then submission rows.
    execution_lock(db)
    cutoff = (at or now_utc()) - timedelta(days=max(1, settings.ANONYMOUS_SUBMISSION_RETENTION_DAYS))
    ids = [row_id for (row_id,) in db.query(Submission.id).filter(
        Submission.user_id.is_(None), Submission.created_at < cutoff,
        ~Submission.status.in_(["queued", "running"]),
        ~exists().where(ExecutionJob.id == Submission.execution_job_id).where(or_(
            ExecutionJob.status.in_(['queued', 'running']), ExecutionJob.lease_token.is_not(None),
            ExecutionJob.lease_until.is_not(None), ExecutionJob.sandbox_operation.is_not(None))),
    ).order_by(Submission.created_at, Submission.id).limit(batch_size).all()]
    if ids:
        db.query(Submission).filter(Submission.id.in_(ids)).delete(synchronize_session=False)
    return len(ids)


def retention_pass():
    with SessionLocal() as db:
        count = purge_expired_anonymous_submissions(db)
        count += expire_execution_content(db, retention_days=settings.EXECUTION_CONTENT_RETENTION_DAYS)
        count += purge_queue_history(db, history_limit=settings.COMPILER_QUEUE_HISTORY_LIMIT)
        db.commit()
        return count


async def retention_maintenance():
    while True:
        try:
            await asyncio.to_thread(retention_pass)
        except Exception:
            logger.exception("Submission retention pass failed")
        await asyncio.sleep(60)
