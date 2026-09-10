from app.core.config import settings
from app.core.database import SessionLocal
from app.services.durable_queue import DurableQueue
from app.services.execution_results import publish_result, publish_transition


def execution_queue():
    return DurableQueue(SessionLocal, concurrency=settings.COMPILER_QUEUE_CONCURRENCY,
        capacity=settings.EXECUTION_QUEUE_CAPACITY, per_owner=settings.EXECUTION_QUEUE_PER_OWNER,
        lease_seconds=settings.EXECUTION_LEASE_SECONDS, on_terminal=publish_result, on_transition=publish_transition)


def build_worker():
    from app.services.execution_worker import ExecutionWorker
    from app.services.durable_queue import WorkerIdentity
    from app.services.runtime_health import worker_process_identity
    from uuid import uuid4
    process_id = worker_process_identity().epoch if settings.RUNTIME_INSTANCE_ID else ''
    identity = WorkerIdentity(uuid4().hex, settings.RUNTIME_POOL_ID, settings.DEPLOYMENT_SHA,
        settings.SANDBOX_POOL_ID, settings.RUNTIME_INSTANCE_ID, process_id)
    return ExecutionWorker(execution_queue(), identity=identity)
