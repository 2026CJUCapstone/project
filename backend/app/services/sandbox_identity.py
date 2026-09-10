"""Pure, exact ownership labels for durable execution sandboxes."""
import re

from app.services.durable_queue import WorkerIdentity
from app.services.runtime_identity import RuntimeIdentity


_JOB_ID = re.compile(
    r'(?:[a-f0-9]{32}|[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})'
)
_LEASE_TOKEN = re.compile(r'[a-f0-9]{32}')
_RELEASE_SHA = re.compile(r'[a-f0-9]{40}')


def _valid_job_id(value):
    if not isinstance(value, str) or _JOB_ID.fullmatch(value) is None or value.replace('-', '') == '0'*32:
        raise ValueError('Exact nonzero sandbox job identity required')
    return value


def _valid_token(value):
    if not isinstance(value, str) or _LEASE_TOKEN.fullmatch(value) is None or value == '0'*32:
        raise ValueError('Exact nonzero sandbox lease required')
    return value


def _valid_worker(worker):
    if not isinstance(worker, WorkerIdentity):
        raise ValueError('Explicit worker identity required')
    # Reconstruct rather than trust a potentially tampered frozen instance.
    return WorkerIdentity(worker.id, worker.pool_id, worker.deployment_sha,
                          worker.sandbox_pool_id, worker.runtime_id, worker.process_id)


def sandbox_labels(job_id, token, worker: WorkerIdentity):
    """Return only stable ownership provenance; never inspect DB or Docker."""
    job_id, token, worker = _valid_job_id(job_id), _valid_token(token), _valid_worker(worker)
    labels = {
        'webcompiler.pool': worker.sandbox_pool_id,
        'webcompiler.job': job_id,
        'webcompiler.lease': token,
    }
    if not worker.runtime_id:
        # Local/dev workers retain the legacy three-label contract.
        return labels
    if not worker.process_id or _RELEASE_SHA.fullmatch(worker.deployment_sha) is None:
        raise ValueError('Managed sandbox provenance requires process and release identities')
    # RuntimeIdentity repeats the exact pool/runtime validation at the boundary.
    RuntimeIdentity(worker.runtime_id, worker.pool_id, worker.deployment_sha,
                    worker.sandbox_pool_id)
    return labels | {
        'webcompiler.runtime-version': '1',
        'webcompiler.runtime': worker.runtime_id,
        'webcompiler.runtime-pool': worker.pool_id,
        'webcompiler.release': worker.deployment_sha,
        'webcompiler.worker': worker.id,
        'webcompiler.process': worker.process_id,
    }
