"""Pure sandbox ownership labels preserve legacy and managed provenance."""
from uuid import uuid4

import pytest

from app.services.durable_queue import WorkerIdentity
from app.services.sandbox_identity import sandbox_labels


JOB_ID = 'a' * 32
LEASE = 'b' * 32
WORKER_ID = 'c' * 32
RUNTIME_ID = 'd' * 32
PROCESS_ID = 'e' * 32
POOL_ID = 'blue_pool'
SANDBOX_POOL_ID = 'sandbox_pool'
DEPLOYMENT_SHA = 'f' * 40


def worker(**overrides):
    values = {
        'id': WORKER_ID,
        'pool_id': POOL_ID,
        'deployment_sha': DEPLOYMENT_SHA,
        'sandbox_pool_id': SANDBOX_POOL_ID,
        'runtime_id': RUNTIME_ID,
        'process_id': PROCESS_ID,
    }
    values.update(overrides)
    return WorkerIdentity(**values)


def test_managed_sandbox_labels_include_exact_runtime_provenance_without_secrets():
    identity = worker()
    result = sandbox_labels(JOB_ID, LEASE, identity)

    assert result == {
        'webcompiler.pool': SANDBOX_POOL_ID,
        'webcompiler.job': JOB_ID,
        'webcompiler.lease': LEASE,
        'webcompiler.runtime-version': '1',
        'webcompiler.runtime': RUNTIME_ID,
        'webcompiler.runtime-pool': POOL_ID,
        'webcompiler.release': DEPLOYMENT_SHA,
        'webcompiler.worker': WORKER_ID,
        'webcompiler.process': PROCESS_ID,
    }
    assert identity == worker()
    assert not any('code' in key or 'credential' in key or 'password' in key for key in result)


def test_legacy_empty_runtime_keeps_only_existing_three_label_contract():
    identity = worker(runtime_id='', process_id='', deployment_sha='')
    job_id = str(uuid4())

    assert sandbox_labels(job_id, LEASE, identity) == {
        'webcompiler.pool': SANDBOX_POOL_ID,
        'webcompiler.job': job_id,
        'webcompiler.lease': LEASE,
    }


@pytest.mark.parametrize('job_id',[
    None, '', '0'*32, '00000000-0000-0000-0000-000000000000',
    'a'*31, 'a'*33, 'A'*32, '-'*32,
])
def test_job_identity_requires_exact_nonzero_uuid_or_hex(job_id):
    with pytest.raises(ValueError):
        sandbox_labels(job_id, LEASE, worker())


@pytest.mark.parametrize('token',[
    None, '', '0'*32, 'b'*31, 'b'*33, 'B'*32, 'b'*31+'-',
])
def test_lease_identity_requires_exact_nonzero_hex(token):
    with pytest.raises(ValueError):
        sandbox_labels(JOB_ID, token, worker())


@pytest.mark.parametrize('overrides',[
    {'process_id': ''},
    {'deployment_sha': ''},
])
def test_managed_runtime_requires_process_and_exact_release_identity(overrides):
    with pytest.raises(ValueError):
        sandbox_labels(JOB_ID, LEASE, worker(**overrides))


@pytest.mark.parametrize(('field','value'),[
    ('pool_id', 'bad pool'),
    ('id', '0'*32),
    ('runtime_id', '0'*32),
    ('process_id', '0'*32),
])
def test_worker_identity_is_revalidated_at_the_label_boundary(field,value):
    identity = worker()
    object.__setattr__(identity, field, value)
    with pytest.raises(ValueError):
        sandbox_labels(JOB_ID, LEASE, identity)


@pytest.mark.parametrize('invalid_worker',[None, object(), {'id': WORKER_ID}])
def test_explicit_worker_identity_is_required(invalid_worker):
    with pytest.raises(ValueError):
        sandbox_labels(JOB_ID, LEASE, invalid_worker)


def test_each_call_returns_a_fresh_pure_label_projection():
    identity = worker()
    first = sandbox_labels(JOB_ID, LEASE, identity)
    first['webcompiler.runtime'] = 'foreign'

    second = sandbox_labels(JOB_ID, LEASE, identity)
    assert second['webcompiler.runtime'] == RUNTIME_ID
    assert identity == worker()
