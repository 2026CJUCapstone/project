"""Durable runtime admission and active HTTP/WebSocket process accounting."""
import os
import socket
from contextlib import asynccontextmanager
from uuid import uuid4

from app.models.database import ApiProcessRecord, ActiveApiRequest, ExecutionRuntimeRecord
from app.services.contest_access import now_utc
from app.services.runtime_identity import RuntimeIdentity
from app.services.runtime_registry import check_identity, execution_lock
from app.services.worker_process import ProcessIdentity, configured_scope, process_start_token


class RuntimeRequests:
    def __init__(self,sessions,runtime,process,*,capacity=512):
        if not isinstance(runtime,RuntimeIdentity) or not isinstance(process,ProcessIdentity):
            raise ValueError('Explicit runtime and process identity required')
        if type(capacity) is not int or not 1 <= capacity <= 4096:
            raise ValueError('Invalid runtime request capacity')
        self.sessions, self.runtime, self.process, self.capacity = sessions,runtime,process,capacity

    @classmethod
    def configured(cls):
        from app.core.config import settings
        from app.core.database import SessionLocal
        process = ProcessIdentity(uuid4().hex,os.getpid(),process_start_token(os.getpid()),
                                  socket.gethostname(),configured_scope())
        return cls(SessionLocal,RuntimeIdentity.configured(),process,
                   capacity=settings.RUNTIME_MAX_ACTIVE_REQUESTS)

    def _process(self,db):
        check_identity(db.get(ExecutionRuntimeRecord,self.runtime.id),self.runtime)
        row = db.get(ApiProcessRecord,self.process.epoch)
        if row is not None and (row.runtime_id,row.pid,row.start_token,row.hostname,row.scope) != (
                self.runtime.id,self.process.pid,self.process.start_token,self.process.hostname,self.process.scope):
            raise ValueError('API process identity mismatch')
        return row

    def _runtime(self,db):
        runtime = db.get(ExecutionRuntimeRecord,self.runtime.id)
        check_identity(runtime,self.runtime)
        return runtime

    def register(self):
        with self.sessions() as db:
            execution_lock(db)
            runtime = self._runtime(db)
            if runtime is None or runtime.draining_at is not None:
                return False
            process = self._process(db)
            if process is None:
                process = ApiProcessRecord(id=self.process.epoch,runtime_id=self.runtime.id,
                    pid=self.process.pid,start_token=self.process.start_token,
                    hostname=self.process.hostname,scope=self.process.scope)
                db.add(process)
            accepting = process.stopped_at is None
            db.commit()
            return accepting

    def begin(self,kind,*,at=None):
        if kind not in ('http','websocket'):
            raise ValueError('Invalid runtime request kind')
        with self.sessions() as db:
            execution_lock(db)
            runtime, process = self._runtime(db), self._process(db)
            if (runtime is None or runtime.draining_at is not None or process is None
                    or process.stopped_at is not None):
                return None
            active = db.query(ActiveApiRequest.id).join(ApiProcessRecord).filter(
                ApiProcessRecord.runtime_id==self.runtime.id).count()
            if active >= self.capacity:
                return None
            request_id = uuid4().hex
            db.add(ActiveApiRequest(id=request_id,process_id=self.process.epoch,kind=kind,
                                    started_at=at or now_utc()))
            db.commit()
            return request_id

    def finish(self,request_id):
        with self.sessions() as db:
            execution_lock(db)
            self._process(db)
            count = db.query(ActiveApiRequest).filter_by(id=request_id,
                process_id=self.process.epoch).delete(synchronize_session=False)
            db.commit()
            return count == 1

    def stop(self,*,at=None):
        with self.sessions() as db:
            execution_lock(db)
            process = self._process(db)
            if process is None:
                return False
            if db.query(ActiveApiRequest.id).filter_by(process_id=self.process.epoch).first() is not None:
                return False  # Unresolved requests do not expire into "closed".
            if process.stopped_at is None:
                process.stopped_at = at or now_utc()
            db.commit()
            return True


@asynccontextmanager
async def owned_api_lifecycle():
    from app.core.config import settings
    from app.services.thread_resource import acquired_in_thread
    if not settings.RUNTIME_INSTANCE_ID:
        yield None
        return
    def acquire():
        service = RuntimeRequests.configured()
        try:
            if not service.register():
                raise RuntimeError('Runtime does not accept API processes')
            return service
        except BaseException:
            service.stop()
            raise
    async with acquired_in_thread(acquire, lambda service:service.stop()) as service:
        yield service
