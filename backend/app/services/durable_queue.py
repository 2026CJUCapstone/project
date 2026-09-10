"""Database-backed admission, claim and fenced completion primitives.

This is the worker queue foundation, not an HTTP request closure registry.
API/worker integration and sandbox cleanup on expired leases are separate steps.
All mutating paths acquire one short database lock before reading queue state;
no lock is held while executing untrusted code.
"""
from dataclasses import dataclass
from datetime import timedelta
import hashlib
import json
import re
import uuid

from app.models.database import ExecutionJob, ExecutionWorkerRecord, ExecutionRuntimeRecord, WorkerProcessRecord
from app.services.contest_access import now_utc
from app.services.runtime_identity import RuntimeIdentity
from app.services.runtime_registry import execution_lock, ensure_runtime_locked


class QueueFull(Exception):
    pass


class IdempotencyConflict(Exception):
    pass


class ExecutionExpired(Exception):
    """A receipt still exists, but its content is no longer available."""


EXECUTION_EXPIRED_MESSAGE = '보관 기간이 지나 실행 코드와 결과가 삭제되었습니다. 자동으로 다시 실행하지 않습니다.'


class SandboxOperationPending(RuntimeError):
    """A Docker mutation has no proven terminal outcome; retain its claim."""


@dataclass(frozen=True)
class WorkerIdentity:
    id: str
    pool_id: str
    deployment_sha: str
    sandbox_pool_id: str
    runtime_id: str = ''
    process_id: str = ''

    def __post_init__(self):
        from app.services.runtime_identity import validate_runtime_id
        validate_runtime_id(self.runtime_id, allow_empty=True)
        validate_runtime_id(self.process_id, allow_empty=True)
        if self.process_id and not self.runtime_id:
            raise ValueError('A bound worker process requires a runtime identity')
        if not isinstance(self.id,str) or not re.fullmatch('[a-f0-9]{32}',self.id) or self.id=='0'*32:
            raise ValueError('Fresh worker instance ID required')
        for name in (self.pool_id,self.sandbox_pool_id):
            if not isinstance(name,str) or not re.fullmatch('[a-z0-9][a-z0-9_-]{0,79}',name):
                raise ValueError('Invalid worker pool identity')
        if not isinstance(self.deployment_sha,str) or (self.deployment_sha and not re.fullmatch('[a-f0-9]{40}',self.deployment_sha)):
            raise ValueError('Invalid worker release identity')


@dataclass(frozen=True)
class Claim:
    id: str
    token: str
    kind: str
    payload: dict
    attempts: int
    daemon_id: str | None = None


class DurableQueue:
    def __init__(self, session_factory, *, concurrency=2, capacity=200, per_owner=4, lease_seconds=120, max_attempts=3, reap_expired=None, on_terminal=None, on_transition=None):
        if min(concurrency, capacity, per_owner, lease_seconds, max_attempts) < 1:
            raise ValueError("Queue limits must be positive")
        self.sessions = session_factory
        self.concurrency, self.capacity, self.per_owner = concurrency, capacity, per_owner
        self.lease_seconds, self.max_attempts = lease_seconds, max_attempts
        self.reap_expired = reap_expired
        self.on_terminal = on_terminal
        self.on_transition = on_transition

    def _lock(self, db):
        # PostgreSQL and SQLite support this upsert. It serializes first creation
        # too, so two API processes cannot both admit past the configured cap.
        execution_lock(db)

    def enqueue(self, *, owner_key, request_id, kind, payload, at=None, quota_key=None):
        with self.sessions() as db:
            job = self.enqueue_in_session(db, owner_key=owner_key, request_id=request_id, kind=kind, payload=payload, at=at, quota_key=quota_key)
            job_id = job.id
            db.commit()
            return job_id

    def enqueue_in_session(self, db, *, owner_key, request_id, kind, payload, at=None, quota_key=None):
        """Bind submission receipt and durable execution in the caller's commit."""
        if not owner_key or len(owner_key) > 200 or not request_id or len(request_id) > 100:
            raise ValueError("Invalid queue identity")
        quota_key = quota_key or owner_key
        if len(quota_key) > 200:
            raise ValueError('Invalid quota identity')
        encoded = json.dumps({"kind": kind, "payload": payload}, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
        if len(encoded) > 2_000_000:
            raise ValueError("Job payload too large")
        digest = hashlib.sha256(encoded).hexdigest()
        self._lock(db)
        old = db.query(ExecutionJob).filter_by(owner_key=owner_key, request_id=request_id).first()
        if old:
            if old.content_expired_at is not None:
                raise ExecutionExpired(EXECUTION_EXPIRED_MESSAGE)
            if old.payload_hash != digest:
                raise IdempotencyConflict("Request ID is already bound to different content")
            return old
        live = db.query(ExecutionJob).filter(ExecutionJob.status.in_(['queued', 'running']))
        if live.count() >= self.capacity or live.filter_by(quota_key=quota_key).count() >= self.per_owner:
            raise QueueFull("Execution queue capacity reached")
        job = ExecutionJob(owner_key=owner_key, quota_key=quota_key, request_id=request_id, kind=kind,
                           payload=payload, payload_hash=digest, received_at=at or now_utc())
        db.add(job)
        db.flush()
        return job

    def _worker(self, db, worker, at):
        if not isinstance(worker,WorkerIdentity):
            raise ValueError('Explicit worker identity required')
        if worker.runtime_id:
            ensure_runtime_locked(db,RuntimeIdentity(worker.runtime_id,worker.pool_id,
                worker.deployment_sha,worker.sandbox_pool_id),at)
        process = None
        if worker.process_id:
            process = db.get(WorkerProcessRecord,worker.process_id)
            if process is None or process.runtime_id != worker.runtime_id:
                raise ValueError('Worker process registration or identity mismatch')
        record=db.get(ExecutionWorkerRecord,worker.id)
        if record is None:
            record=ExecutionWorkerRecord(id=worker.id,pool_id=worker.pool_id,
                deployment_sha=worker.deployment_sha,sandbox_pool_id=worker.sandbox_pool_id,
                runtime_id=worker.runtime_id,process_id=worker.process_id or None,started_at=at,
                draining_at=(process.draining_at or process.stopped_at) if process is not None else None)
            db.add(record)
            db.flush()
        elif (record.pool_id,record.deployment_sha,record.sandbox_pool_id,record.runtime_id,record.process_id)!=(
                worker.pool_id,worker.deployment_sha,worker.sandbox_pool_id,worker.runtime_id,worker.process_id or None):
            raise ValueError('Worker instance identity mismatch')
        return record

    def register_worker(self, worker, *, at=None, stop_requested=None):
        """Record a lane before dependency probes, without accepting any work.

        Docker being unavailable must not erase process-to-lane lifecycle evidence.
        Registration does not publish readiness or reopen any existing drain fence.
        """
        with self.sessions() as db:
            self._lock(db)
            at = at or now_utc()
            record = self._worker(db, worker, at)
            runtime = db.get(ExecutionRuntimeRecord, worker.runtime_id) if worker.runtime_id else None
            process = db.get(WorkerProcessRecord, worker.process_id) if worker.process_id else None
            if stop_requested is not None and stop_requested() and record.draining_at is None:
                record.draining_at = at
            allowed = (record.draining_at is None
                and (runtime is None or runtime.draining_at is None)
                and (process is None or (process.draining_at is None and process.stopped_at is None)))
            db.commit()
            return allowed

    def begin_worker_drain(self, worker, *, at=None):
        """Linearization point: after commit this identity cannot claim again.

        May run before first claim. The tombstone then prevents late startup
        from resurrecting admission; existing claims retain their lease.
        """
        with self.sessions() as db:
            self._lock(db)
            at=at or now_utc()
            record=self._worker(db,worker,at)
            if record.draining_at is None:
                record.draining_at=at
            db.commit()

    def worker_status(self, worker):
        """Private read-only evidence, never a container-stop authorization."""
        if not isinstance(worker,WorkerIdentity):
            raise ValueError('Explicit worker identity required')
        with self.sessions() as db:
            record=db.get(ExecutionWorkerRecord,worker.id)
            if record is None:
                return None
            if (record.pool_id,record.deployment_sha,record.sandbox_pool_id,record.runtime_id,record.process_id)!=(
                    worker.pool_id,worker.deployment_sha,worker.sandbox_pool_id,worker.runtime_id,worker.process_id or None):
                raise ValueError('Worker instance identity mismatch')
            active=db.query(ExecutionJob.id).filter_by(worker_id=worker.id,status='running').count()
            return {'id':worker.id,'draining':record.draining_at is not None,'active_claims':active}

    def claim(self, *, at=None, worker=None, stop_requested=None, daemon_id=None):
        if daemon_id is not None and (not isinstance(daemon_id, str)
                or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9:_.-]{0,127}', daemon_id)):
            raise ValueError('Exact sandbox daemon identity required')
        with self.sessions() as db:
            self._lock(db)
            at = at or now_utc()
            record=self._worker(db,worker,at) if worker is not None else None
            runtime=db.get(ExecutionRuntimeRecord,worker.runtime_id) if worker is not None and worker.runtime_id else None
            process=db.get(WorkerProcessRecord,worker.process_id) if worker is not None and worker.process_id else None
            def admission_stopped():
                if stop_requested is not None and stop_requested():
                    if record is not None and record.draining_at is None:
                        record.draining_at=at
                    return True
                return ((record is not None and record.draining_at is not None)
                        or (runtime is not None and runtime.draining_at is not None)
                        or (process is not None and (process.draining_at is not None or process.stopped_at is not None)))
            if admission_stopped():
                db.commit()
                return None
            # Cleanup and a fenced start share this lock. A stale worker cannot
            # start an old sandbox after cleanup has released its capacity.
            expired = db.query(ExecutionJob).filter(ExecutionJob.status == 'running', ExecutionJob.lease_until <= at).all()
            for job in expired:
                if job.sandbox_operation is not None:
                    # Empty Docker listings do not retract an in-flight or
                    # transport-ambiguous daemon request. No timeout releases it.
                    continue
                if job.sandbox_daemon_id is not None:
                    continue  # Bound claims use journaled, unlocked recovery.
                if self.reap_expired is None:
                    continue  # Fail closed: expiration alone proves no termination.
                self.reap_expired(job.id, job.lease_token)
                job.lease_token = None
                job.lease_until = None
                if job.attempts >= self.max_attempts or job.kind == 'terminal':
                    job.status, job.finished_at = 'failed', at
                    job.result = {"verdict": "system_error", "message": "Worker retry limit reached"}
                    if job.kind == 'terminal':
                        job.result = {'verdict':'canceled', 'message':'터미널 연결이 중단되었습니다. 자동으로 다시 실행하지 않습니다.'}
                    if self.on_terminal:
                        self.on_terminal(db, job.id, job.result)
                else:
                    job.status = 'queued'
                    if self.on_transition:
                        self.on_transition(db, job)
            db.flush()
            # Reaping can take time; a stop received during cleanup must not
            # be followed by a fresh claim. The DB fence also serializes a
            # coordinator's drain against this worker's claim transaction.
            if admission_stopped():
                db.commit()
                return None
            if db.query(ExecutionJob).filter_by(status='running').count() >= self.concurrency:
                db.commit()
                return None
            job = db.query(ExecutionJob).filter_by(status='queued').order_by(ExecutionJob.received_at, ExecutionJob.id).first()
            if job is None:
                db.commit()
                return None
            job.status, job.lease_token = 'running', uuid.uuid4().hex
            job.sandbox_daemon_id = daemon_id
            job.worker_id = worker.id if worker is not None else None
            job.lease_until, job.started_at = at + timedelta(seconds=self.lease_seconds), at
            job.attempts += 1
            if self.on_transition:
                self.on_transition(db, job)
            result = Claim(job.id, job.lease_token, job.kind, job.payload, job.attempts, job.sandbox_daemon_id)
            db.commit()
            return result

    def start(self, job_id, token, action, *, at=None):
        """Execute a sandbox start only while this claim is still exclusive."""
        with self.sessions() as db:
            self._lock(db)
            at = at or now_utc()
            valid = db.query(ExecutionJob.id).filter(ExecutionJob.id == job_id, ExecutionJob.lease_token == token,
                ExecutionJob.status == 'running', ExecutionJob.lease_until > at,
                ExecutionJob.sandbox_operation.is_(None),
                ExecutionJob.sandbox_daemon_id.is_(None)).first()
            if not valid:
                return False
            action()
            db.commit()
            return True

    def sandbox_operation(self, job_id, token, kind, action, *, container_id=None, daemon_id=None, at=None):
        """Persist mutation intent before Docker; settle only its exact receipt.

        No DB lock is held across a daemon request. The outstanding operation
        retains global capacity and forbids expired-lease reuse until a positive
        response is durably acknowledged. Exceptions/process death deliberately
        leave intent unresolved; listing absence is not an outcome certificate.
        """
        if kind not in ('create','start') or not callable(action):
            raise ValueError('Exact sandbox operation required')
        if ((kind=='create' and container_id is not None)
                or (kind=='start' and (not isinstance(container_id,str)
                    or not re.fullmatch('[a-f0-9]{64}',container_id)))):
            raise ValueError('Exact sandbox container identity required')
        operation_id=uuid.uuid4().hex
        with self.sessions() as db:
            self._lock(db)
            at=at or now_utc()
            job=db.query(ExecutionJob).filter(ExecutionJob.id==job_id,ExecutionJob.lease_token==token,
                ExecutionJob.status=='running',ExecutionJob.lease_until>at).first()
            if job is None or job.sandbox_operation is not None:
                raise SandboxOperationPending('Sandbox operation cannot acquire this claim')
            if job.sandbox_daemon_id is not None and job.sandbox_daemon_id != daemon_id:
                raise SandboxOperationPending('Sandbox operation daemon mismatch')
            operation={'version':1,'id':operation_id,'kind':kind,'lease_token':token,
                'name':'compiler-'+token+'-'+operation_id if kind=='create' else None,
                'container_id':container_id,'begun_at':at.isoformat()}
            job.sandbox_operation=operation
            db.commit()
        # A transport exception here must never clear durable intent. A crash
        # after successful response but before the next commit also retains it.
        result=action(operation)
        if kind=='create' and (not isinstance(getattr(result,'id',None),str)
                or not re.fullmatch('[a-f0-9]{64}',result.id)):
            raise SandboxOperationPending('Sandbox allocation acknowledgment is incomplete')
        with self.sessions() as db:
            self._lock(db)
            job=db.get(ExecutionJob,job_id)
            if (job is None or job.status!='running' or job.lease_token!=token
                    or job.sandbox_operation!=operation):
                raise SandboxOperationPending('Sandbox operation acknowledgment is stale')
            # A response may arrive after the lease deadline. Acknowledging the
            # exact operation allows cleanup; it does NOT renew/start/finish it.
            job.sandbox_operation=None
            db.commit()
        return result

    def renew(self, job_id, token, *, at=None):
        with self.sessions() as db:
            self._lock(db)
            at = at or now_utc()
            count = db.query(ExecutionJob).filter(ExecutionJob.id == job_id, ExecutionJob.lease_token == token,
                ExecutionJob.status == 'running', ExecutionJob.lease_until > at).update(
                    {"lease_until": at + timedelta(seconds=self.lease_seconds)}, synchronize_session=False)
            db.commit()
            return count == 1

    def reconcile_pending(self, pool, *, at=None):
        """Recover expired ambiguous effects using durable, exact-ID evidence.

        A never-observed create retains capacity. Persisting the observed ID
        before removal makes recovery resumable even if its acknowledgment or
        this process is lost. Ordinary claim recovery performs final reaping
        and retry accounting; reconciliation alone never grants a new lease.
        """
        from app.services.sandbox_identity import sandbox_labels
        at = at or now_utc()
        with self.sessions() as db:
            candidates = db.query(ExecutionJob.id).join(
                ExecutionWorkerRecord, ExecutionJob.worker_id == ExecutionWorkerRecord.id
            ).filter(ExecutionJob.status == 'running', ExecutionJob.lease_until <= at,
                ExecutionJob.sandbox_operation.is_not(None),
                ExecutionWorkerRecord.sandbox_pool_id == pool.pool_id
            ).order_by(ExecutionJob.lease_until, ExecutionJob.id).limit(self.capacity).all()
        settled = 0
        for (job_id,) in candidates:
            with self.sessions() as db:
                self._lock(db)
                job = db.get(ExecutionJob, job_id)
                if (job is None or job.status != 'running' or job.lease_until > at
                        or job.sandbox_operation is None):
                    continue
                worker = db.get(ExecutionWorkerRecord, job.worker_id)
                if worker is None or worker.sandbox_pool_id != pool.pool_id:
                    continue
                labels = sandbox_labels(job.id, job.lease_token, WorkerIdentity(
                    worker.id, worker.pool_id, worker.deployment_sha,
                    worker.sandbox_pool_id, worker.runtime_id, worker.process_id or ''))
                operation = dict(job.sandbox_operation)
                token = job.lease_token
                daemon_id = job.sandbox_daemon_id
            if operation.get('kind') == 'cleanup':
                if (operation.get('version') != 1 or operation.get('lease_token') != token
                        or not isinstance(operation.get('id'), str)
                        or not re.fullmatch('[a-f0-9]{32}', operation['id'])):
                    raise SandboxOperationPending('Invalid cleanup journal')
                if daemon_id is None or operation.get('resolved_daemon_id') != daemon_id:
                    continue
                pool.reap_claim(labels, daemon_id=daemon_id)
                pool.confirm_claim_absent(labels, daemon_id)
                with self.sessions() as db:
                    self._lock(db)
                    job = db.get(ExecutionJob, job_id)
                    if (job is None or job.status != 'running' or job.lease_token != token
                            or job.lease_until > at or job.sandbox_operation != operation):
                        continue
                    job.sandbox_operation = None
                    db.commit()
                    settled += 1
                continue
            if operation.get('phase') != 'removing':
                observation = pool.observe_operation(operation, labels)
                if observation is None:
                    continue
                if (not isinstance(observation, dict)
                        or set(observation) != {'container_id', 'daemon_id'}
                        or not isinstance(observation['container_id'], str)
                        or not re.fullmatch('[a-f0-9]{64}', observation['container_id'])
                        or not isinstance(observation['daemon_id'], str)
                        or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9:_.-]{0,127}', observation['daemon_id'])):
                    raise SandboxOperationPending('Incomplete reconciliation identity')
                with self.sessions() as db:
                    self._lock(db)
                    job = db.get(ExecutionJob, job_id)
                    if (job is None or job.status != 'running' or job.lease_token != token
                            or job.lease_until > at or job.sandbox_operation != operation):
                        continue
                    operation = operation | {'phase': 'removing',
                        'resolved_container_id': observation['container_id'],
                        'resolved_daemon_id': observation['daemon_id']}
                    job.sandbox_operation = operation
                    # Positive original-container observation also binds legacy
                    # journaled claims; absence alone never does so.
                    if job.sandbox_daemon_id not in (None, observation['daemon_id']):
                        raise SandboxOperationPending('Claim daemon identity mismatch')
                    job.sandbox_daemon_id = observation['daemon_id']
                    db.commit()  # Must precede the first destructive request.
            # A committed phase fences the original ACK and any new mutation.
            # Slow Docker I/O must not hold the global queue admission lock.
            pool.remove_operation(operation, labels)
            pool.reap_claim(labels, daemon_id=operation['resolved_daemon_id'])
            pool.confirm_operation_absent(operation, labels)
            with self.sessions() as db:
                self._lock(db)
                job = db.get(ExecutionJob, job_id)
                if (job is None or job.status != 'running' or job.lease_token != token
                        or job.lease_until > at or job.sandbox_operation != operation):
                    continue
                job.sandbox_operation = None
                db.commit()
                settled += 1
        return settled

    def cleanup_lease(self, job_id, token, action):
        """Keep uncertain-operation evidence until explicit reconciliation.

        Persist intent under the admission lock, then release the lock before
        external I/O. Pending cleanup fences new create/start and completion;
        lost acknowledgments can be recovered with a full exact-claim sweep.
        """
        if not callable(action):
            raise ValueError('Explicit cleanup action required')
        with self.sessions() as db:
            self._lock(db)
            job=db.get(ExecutionJob,job_id)
            if (job is None or job.status!='running' or job.lease_token!=token
                    or job.sandbox_operation is not None):
                return False
            operation = {'version': 1, 'kind': 'cleanup', 'id': uuid.uuid4().hex,
                'lease_token': token, 'resolved_daemon_id': job.sandbox_daemon_id}
            job.sandbox_operation = operation
            db.commit()
        action()
        with self.sessions() as db:
            self._lock(db)
            job = db.get(ExecutionJob, job_id)
            if (job is None or job.status != 'running' or job.lease_token != token
                    or job.sandbox_operation != operation):
                return False
            job.sandbox_operation = None
            db.commit()
            return True

    def recover_expired(self, pool, *, at=None):
        """Reap only bound original-pool claims, outside the global DB lock."""
        from app.services.sandbox_identity import sandbox_labels
        at = at or now_utc()
        self.reconcile_pending(pool, at=at)
        with self.sessions() as db:
            candidates = db.query(ExecutionJob.id).join(ExecutionWorkerRecord,
                ExecutionJob.worker_id == ExecutionWorkerRecord.id).filter(
                ExecutionJob.status == 'running', ExecutionJob.lease_until <= at,
                ExecutionJob.sandbox_operation.is_(None),
                ExecutionJob.sandbox_daemon_id.is_not(None),
                ExecutionWorkerRecord.sandbox_pool_id == pool.pool_id
            ).order_by(ExecutionJob.lease_until, ExecutionJob.id).limit(self.capacity).all()
        for (job_id,) in candidates:
            with self.sessions() as db:
                self._lock(db)
                job = db.get(ExecutionJob, job_id)
                if (job is None or job.status != 'running' or job.lease_until > at
                        or job.sandbox_operation is not None or job.sandbox_daemon_id is None):
                    continue
                worker = db.get(ExecutionWorkerRecord, job.worker_id)
                if worker is None or worker.sandbox_pool_id != pool.pool_id:
                    continue
                labels = sandbox_labels(job.id, job.lease_token, WorkerIdentity(worker.id,
                    worker.pool_id, worker.deployment_sha, worker.sandbox_pool_id,
                    worker.runtime_id, worker.process_id or ''))
                token, daemon_id = job.lease_token, job.sandbox_daemon_id
                operation = {'version': 1, 'kind': 'cleanup', 'id': uuid.uuid4().hex,
                    'lease_token': token, 'resolved_daemon_id': daemon_id}
                job.sandbox_operation = operation
                db.commit()
            pool.reap_claim(labels, daemon_id=daemon_id)
            pool.confirm_claim_absent(labels, daemon_id)
            with self.sessions() as db:
                self._lock(db)
                job = db.get(ExecutionJob, job_id)
                if (job is None or job.status != 'running' or job.lease_token != token
                        or job.lease_until > at or job.sandbox_operation != operation):
                    continue
                job.sandbox_operation, job.lease_token, job.lease_until = None, None, None
                if job.attempts >= self.max_attempts or job.kind == 'terminal':
                    job.status, job.finished_at = 'failed', at
                    job.result = {'verdict': 'system_error', 'message': 'Worker retry limit reached'}
                    if job.kind == 'terminal':
                        job.result = {'verdict': 'canceled', 'message': '터미널 연결이 중단되었습니다. 자동으로 다시 실행하지 않습니다.'}
                    if self.on_terminal:
                        self.on_terminal(db, job.id, job.result)
                else:
                    job.status = 'queued'
                    if self.on_transition:
                        self.on_transition(db, job)
                db.commit()

    def finish(self, job_id, token, result, *, at=None):
        if len(json.dumps(result, ensure_ascii=False).encode('utf-8')) > 2_000_000:
            raise ValueError("Job result too large")
        with self.sessions() as db:
            self._lock(db)
            at = at or now_utc()
            job=db.get(ExecutionJob,job_id)
            if job is not None and job.sandbox_operation is not None:
                return False
            if result.get('verdict') == 'system_error':
                retry = db.query(ExecutionJob).filter(ExecutionJob.id == job_id, ExecutionJob.lease_token == token,
                    ExecutionJob.status == 'running', ExecutionJob.lease_until > at,
                    ExecutionJob.kind != 'terminal',
                    ExecutionJob.attempts < self.max_attempts).first()
                if retry is not None:
                    retry.status, retry.lease_token, retry.lease_until = 'queued', None, None
                    if self.on_transition:
                        self.on_transition(db, retry)
                    db.commit()
                    return True
            count = db.query(ExecutionJob).filter(ExecutionJob.id == job_id, ExecutionJob.lease_token == token,
                ExecutionJob.status == 'running', ExecutionJob.lease_until > at).update(
                    {"status": "completed", "result": result, "finished_at": at, "lease_token": None, "lease_until": None},
                    synchronize_session=False)
            if count and self.on_terminal:
                self.on_terminal(db, job_id, result)
                # Publication may augment the caller-visible grading result.
                db.query(ExecutionJob).filter_by(id=job_id).update({'result':result}, synchronize_session=False)
            db.commit()
            return count == 1

    def read(self, job_id, *, owner_key):
        with self.sessions() as db:
            job = db.query(ExecutionJob).filter_by(id=job_id, owner_key=owner_key).first()
            if job is None:
                return None
            if job.content_expired_at is not None:
                raise ExecutionExpired(EXECUTION_EXPIRED_MESSAGE)
            # Read result only to the same server-derived owner; never return payload.
            return {"id": job.id, "status": job.status, "result": job.result, "received_at": job.received_at}
