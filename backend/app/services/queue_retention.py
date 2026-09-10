"""Bounded retention for public queue observations.

The public ``compile_queue_jobs`` table is presentation history only.  This
module deliberately never deletes, transitions, or otherwise repairs the
private execution receipt and its submission/contest ledgers.
"""
from sqlalchemy import exists, or_, select, tuple_, union_all

from app.models.database import CompileQueueRecord, ExecutionJob
from app.services.runtime_registry import execution_lock


_TERMINAL_STATUSES = ("completed", "failed")
_ACTIVE_JOB_STATUSES = ("queued", "running")
_MAX_BATCH_SIZE = 500


def _validate_limits(history_limit, batch_size) -> None:
    # ``bool`` is an ``int`` subclass, but accepting it would make a
    # configuration typo silently select a destructive retention policy.
    if type(history_limit) is not int or not 0 <= history_limit <= 10_000:
        raise ValueError("history_limit must be an integer from 0 to 10000")
    if type(batch_size) is not int or not 1 <= batch_size <= _MAX_BATCH_SIZE:
        raise ValueError("batch_size must be an integer from 1 to 500")


def _protected_execution_job():
    """Correlated predicate for a public row that must remain visible.

    A terminal-looking public observation is never authority to discard an
    unresolved private claim.  Treat either half of a lease as protective too:
    a partially-written legacy row is safer retained than inferred terminal.
    """
    return exists().where(
        ExecutionJob.id == CompileQueueRecord.id,
        or_(
            ExecutionJob.status.in_(_ACTIVE_JOB_STATUSES),
            ExecutionJob.lease_token.is_not(None),
            ExecutionJob.lease_until.is_not(None),
            ExecutionJob.sandbox_operation.is_not(None),
        ),
    )


def _ordered_history(*, newest, limit, before=None):
    """Merge at most two bounded index scans, using the database's collation.

    Receipt order matches public history; completion order can be reversed or
    absent on legacy rows. Each status uses (status, queued_at, id), avoiding
    sorting the entire historical overflow while holding the execution lock.
    Only identifiers and timestamps are read, never code or error content.
    """
    record = CompileQueueRecord
    parts = []
    for status in _TERMINAL_STATUSES:
        part = select(record.id, record.queued_at).where(
            record.status == status, ~_protected_execution_job(),
        )
        if before is not None:
            part = part.where(tuple_(record.queued_at, record.id) < tuple_(before.queued_at, before.id))
        order = (record.queued_at, record.id)
        part = part.order_by(*(column.desc() if newest else column.asc() for column in order))
        # Wrapping each limited SELECT is required for SQLite UNION syntax.
        parts.append(select(part.limit(limit).subquery()))
    bounded = union_all(*parts).subquery()
    return select(bounded.c.id, bounded.c.queued_at).order_by(*(
        column.desc() if newest else column.asc()
        for column in (bounded.c.queued_at, bounded.c.id)
    )).limit(limit)


def purge_queue_history(db, *, history_limit, batch_size=500):
    """Delete at most one bounded batch of stale public terminal observations.

    The caller owns the surrounding transaction and commit/rollback decision.
    Queue transitions use the same execution lock, so selecting the overflow
    and deleting it are ordered with admission, claims, leases, and results.
    """
    _validate_limits(history_limit, batch_size)

    execution_lock(db)
    boundary = None
    if history_limit:
        retained = db.execute(_ordered_history(newest=True, limit=history_limit)).all()
        if len(retained) < history_limit:
            return 0
        boundary = retained[-1]
    candidate_ids = [row.id for row in db.execute(
        _ordered_history(newest=False, limit=batch_size, before=boundary)
    ).all()]
    if not candidate_ids:
        return 0

    # Reapply the safety predicate in the mutation.  This is redundant under
    # the shared execution lock, but keeps a stale candidate from deleting a
    # row if a future caller changes job state without using that lock.
    return (
        db.query(CompileQueueRecord)
        .filter(
            CompileQueueRecord.id.in_(candidate_ids),
            CompileQueueRecord.status.in_(_TERMINAL_STATUSES),
            ~_protected_execution_job(),
        )
        .delete(synchronize_session=False)
    )
