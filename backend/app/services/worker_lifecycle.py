"""DB process identity/fence shared by every execution lane in that process."""
from contextlib import asynccontextmanager
from app.models.database import ExecutionJob, ExecutionRuntimeRecord, ExecutionWorkerRecord, WorkerProcessRecord
from app.services.contest_access import now_utc
from app.services.runtime_identity import RuntimeIdentity
from app.services.runtime_registry import check_identity, execution_lock
from app.services.worker_process import ProcessIdentity


class WorkerLifecycle:
    def __init__(self, sessions, runtime, process):
        if not isinstance(runtime, RuntimeIdentity) or not isinstance(process, ProcessIdentity):
            raise ValueError('Explicit runtime and process identity required')
        self.sessions, self.runtime, self.process = sessions, runtime, process

    def _record(self, db):
        check_identity(db.get(ExecutionRuntimeRecord, self.runtime.id), self.runtime)
        row = db.get(WorkerProcessRecord, self.process.epoch)
        if row is not None and (row.runtime_id, row.pid, row.start_token, row.hostname, row.scope) != (
                self.runtime.id, self.process.pid, self.process.start_token, self.process.hostname, self.process.scope):
            raise ValueError('Worker process identity mismatch')
        return row

    def register(self):
        with self.sessions() as db:
            execution_lock(db)
            runtime = db.get(ExecutionRuntimeRecord, self.runtime.id)
            check_identity(runtime, self.runtime)
            if runtime is None or runtime.draining_at is not None:
                return False
            row = self._record(db)
            if row is None:
                row = WorkerProcessRecord(id=self.process.epoch, runtime_id=self.runtime.id,
                    pid=self.process.pid, start_token=self.process.start_token,
                    hostname=self.process.hostname, scope=self.process.scope)
                db.add(row)
            accepting = row.draining_at is None and row.stopped_at is None
            db.commit()
            return accepting

    def begin_drain(self, *, at=None):
        with self.sessions() as db:
            execution_lock(db)
            row = self._record(db)
            if row is None:
                return False
            if row.draining_at is None:
                row.draining_at = at or now_utc()
            db.commit()
            return True

    def stop(self, *, at=None):
        with self.sessions() as db:
            execution_lock(db)
            row = self._record(db)
            if row is None:
                return False
            if row.draining_at is None:
                row.draining_at = at or now_utc()
            active = db.query(ExecutionJob.id).join(ExecutionWorkerRecord,
                ExecutionJob.worker_id == ExecutionWorkerRecord.id).filter(
                ExecutionWorkerRecord.process_id == self.process.epoch,
                ExecutionJob.status == 'running').first()
            if active is not None:
                db.commit()  # Keep the admission fence, not a fabricated stop.
                return False
            if row.stopped_at is None:
                row.stopped_at = at or now_utc()
            db.commit()
            return True


def configured_worker_lifecycle(process):
    from app.core.config import settings
    from app.core.database import SessionLocal
    if not settings.RUNTIME_INSTANCE_ID:
        return None
    return WorkerLifecycle(SessionLocal, RuntimeIdentity.configured(), process)


@asynccontextmanager
async def owned_worker_lifecycle(start, stop):
    from app.services.thread_resource import acquired_in_thread
    def release(owned):
        process, lifecycle = owned
        try:
            if lifecycle is not None:
                lifecycle.stop()
        finally:
            if process is None:
                stop()  # Unmanaged test fixtures may not supply an identity.
            else:
                stop(expected=process)
    def acquire():
        process = start()
        lifecycle = None
        try:
            lifecycle = configured_worker_lifecycle(process)
            if lifecycle is not None and not lifecycle.register():
                raise RuntimeError('Runtime does not accept worker processes')
            return process, lifecycle
        except BaseException:
            release((process, lifecycle))
            raise
    async with acquired_in_thread(acquire, release) as owned:
        yield owned[1]
