"""Durable per-incarnation admission. No record or lease count proves retirement."""
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.database import ExecutionJob, ExecutionRuntimeRecord, ExecutionWorkerRecord, ApiProcessRecord, ActiveApiRequest
from app.services.contest_access import now_utc
from app.services.runtime_identity import RuntimeIdentity


def execution_lock(db):
    # Shared with enqueue/claim/start/renew/finish: drain acknowledgment orders
    # all claims, including registration by a just-restarted worker process.
    db.execute(text("INSERT INTO execution_queue_lock (id, revision) VALUES ('execution', 0) ON CONFLICT (id) DO NOTHING"))
    db.execute(text("UPDATE execution_queue_lock SET revision = revision + 1 WHERE id = 'execution'"))


def check_identity(record, identity):
    if not isinstance(identity,RuntimeIdentity):
        raise ValueError('Explicit runtime identity required')
    if record is not None and (record.pool_id,record.deployment_sha,record.sandbox_pool_id)!=(
            identity.pool_id,identity.deployment_sha,identity.sandbox_pool_id):
        raise ValueError('Runtime instance identity mismatch')


def ensure_runtime_locked(db, identity, at):
    check_identity(None,identity)
    record=db.get(ExecutionRuntimeRecord,identity.id)
    check_identity(record,identity)
    if record is None:
        # Existing v3 lanes are evidence of identity, not evidence that an
        # entire runtime is active/drained. Reject conflicts; never backfill
        # unknown legacy owners or silently reassign a known incarnation.
        previous=db.query(ExecutionWorkerRecord.pool_id,ExecutionWorkerRecord.deployment_sha,
            ExecutionWorkerRecord.sandbox_pool_id).filter_by(runtime_id=identity.id).distinct().all()
        if any(tuple(values)!=(identity.pool_id,identity.deployment_sha,identity.sandbox_pool_id)
               for values in previous):
            raise ValueError('Existing worker runtime identity mismatch')
        record=ExecutionRuntimeRecord(id=identity.id,pool_id=identity.pool_id,
            deployment_sha=identity.deployment_sha,sandbox_pool_id=identity.sandbox_pool_id,registered_at=at)
        db.add(record)
        db.flush()
    return record


def runtime_accepting(bind,identity):
    """Read-only readiness check; missing/mismatched/fenced runtimes are closed."""
    check_identity(None,identity)
    with Session(bind=bind) as db:
        record=db.get(ExecutionRuntimeRecord,identity.id)
        check_identity(record,identity)
        return record is not None and record.draining_at is None


class RuntimeRegistry:
    def __init__(self,sessions):
        self.sessions=sessions

    def register(self,identity):
        with self.sessions() as db:
            execution_lock(db)
            record=ensure_runtime_locked(db,identity,now_utc())
            accepting=record.draining_at is None
            db.commit()
            return accepting

    def begin_drain(self,identity,*,at=None):
        with self.sessions() as db:
            execution_lock(db)
            record=ensure_runtime_locked(db,identity,at or now_utc())
            if record.draining_at is None:
                record.draining_at=at or now_utc()
            db.commit()

    def status(self,identity):
        check_identity(None,identity)
        with self.sessions() as db:
            record=db.get(ExecutionRuntimeRecord,identity.id)
            check_identity(record,identity)
            if record is None:
                return None
            active=db.query(ExecutionJob.id).join(ExecutionWorkerRecord,
                ExecutionJob.worker_id==ExecutionWorkerRecord.id).filter(
                ExecutionWorkerRecord.runtime_id==identity.id,ExecutionJob.status=='running').count()
            requests = db.query(ActiveApiRequest).join(ApiProcessRecord).filter(
                ApiProcessRecord.runtime_id==identity.id)
            return {'id':identity.id,'draining':record.draining_at is not None,'active_claims':active,
                'active_http':requests.filter(ActiveApiRequest.kind=='http').count(),
                'active_websockets':requests.filter(ActiveApiRequest.kind=='websocket').count()}


def register_configured_runtime():
    from app.core.config import settings
    from app.core.database import SessionLocal
    if settings.RUNTIME_INSTANCE_ID and not RuntimeRegistry(SessionLocal).register(RuntimeIdentity.configured()):
        raise RuntimeError('Runtime is draining; it cannot restart admission')
