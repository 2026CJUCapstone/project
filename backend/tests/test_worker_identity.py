from dataclasses import FrozenInstanceError

import pytest

from app.services.durable_queue import WorkerIdentity


WORKER_ID = 'a' * 32
POOL_ID = 'blue_pool-1'
DEPLOYMENT_SHA = 'b' * 40
SANDBOX_POOL_ID = 'sandbox_pool-1'
RUNTIME_ID = 'c' * 32


def identity(**overrides):
    values = {
        'id': WORKER_ID,
        'pool_id': POOL_ID,
        'deployment_sha': DEPLOYMENT_SHA,
        'sandbox_pool_id': SANDBOX_POOL_ID,
    }
    values.update(overrides)
    return WorkerIdentity(**values)


@pytest.mark.parametrize('deployment_sha', ['', DEPLOYMENT_SHA, '0' * 40])
def test_worker_identity_accepts_valid_fields_and_local_or_deployed_sha(deployment_sha):
    result = identity(deployment_sha=deployment_sha)

    assert result.id == WORKER_ID
    assert result.pool_id == POOL_ID
    assert result.deployment_sha == deployment_sha
    assert result.sandbox_pool_id == SANDBOX_POOL_ID


@pytest.mark.parametrize('field,value', [
    ('pool_id', 'a'),
    ('pool_id', 'a' * 80),
    ('sandbox_pool_id', 'b'),
    ('sandbox_pool_id', 'b' * 80),
])
def test_worker_identity_accepts_pool_id_length_boundaries(field, value):
    result = identity(**{field: value})

    assert getattr(result, field) == value


@pytest.mark.parametrize('runtime_id', ['', RUNTIME_ID, '0' * 31 + '1'])
def test_worker_identity_accepts_optional_runtime_id(runtime_id):
    result = identity(runtime_id=runtime_id)

    assert result.runtime_id == runtime_id


def test_worker_identity_is_frozen():
    result = identity()

    with pytest.raises(FrozenInstanceError):
        result.pool_id = 'green'


@pytest.mark.parametrize('worker_id', [
    None,
    123,
    b'a' * 32,
    '',
    'a' * 31,
    'a' * 33,
    'A' * 32,
    'g' * 32,
    '0' * 32,
    'a' * 31 + '\n',
    'a' * 32 + '\n',
    'a' * 32 + '\r\n',
])
def test_worker_identity_rejects_invalid_id_types_and_boundaries(worker_id):
    with pytest.raises((TypeError, ValueError)):
        identity(id=worker_id)


@pytest.mark.parametrize('pool_id', [
    None,
    123,
    '',
    'a' * 81,
    'Blue',
    '_pool',
    '-pool',
    'pool:id',
    'pool/path',
    'pool\nid',
    'pool\n',
    'pool\r\n',
    'pool id',
])
def test_worker_identity_rejects_invalid_pool_id_types_and_boundaries(pool_id):
    with pytest.raises((TypeError, ValueError)):
        identity(pool_id=pool_id)


@pytest.mark.parametrize('deployment_sha', [
    None,
    123,
    b'b' * 40,
    'a' * 39,
    'a' * 41,
    'A' * 40,
    'g' * 40,
    'b' * 39 + '\n',
    'b' * 40 + '\n',
    'b' * 40 + '\r\n',
])
def test_worker_identity_rejects_invalid_deployment_sha_types_and_boundaries(deployment_sha):
    with pytest.raises((TypeError, ValueError)):
        identity(deployment_sha=deployment_sha)


@pytest.mark.parametrize('sandbox_pool_id', [
    None,
    123,
    '',
    'a' * 81,
    'Sandbox',
    '_sandbox',
    '-sandbox',
    'sandbox:id',
    'sandbox/path',
    'sandbox\nid',
    'sandbox\n',
    'sandbox\r\n',
    'sandbox pool',
])
def test_worker_identity_rejects_invalid_sandbox_pool_id_types_and_boundaries(sandbox_pool_id):
    with pytest.raises((TypeError, ValueError)):
        identity(sandbox_pool_id=sandbox_pool_id)


@pytest.mark.parametrize('runtime_id', [
    None,
    123,
    b'c' * 32,
    'c' * 31,
    'c' * 33,
    'C' * 32,
    'g' * 32,
    '0' * 32,
    'c' * 32 + '\n',
    'c' * 32 + '\r\n',
])
def test_worker_identity_rejects_invalid_runtime_id_types_and_boundaries(runtime_id):
    with pytest.raises((TypeError, ValueError)):
        identity(runtime_id=runtime_id)
