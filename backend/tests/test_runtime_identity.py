from dataclasses import FrozenInstanceError

import pytest

from app.services.runtime_identity import RuntimeIdentity


INSTANCE_ID = 'a' * 32
POOL_ID = 'blue_pool-1'
DEPLOYMENT_SHA = 'b' * 40
SANDBOX_POOL_ID = 'sandbox_pool-1'


def identity(**overrides):
    values = {
        'id': INSTANCE_ID,
        'pool_id': POOL_ID,
        'deployment_sha': DEPLOYMENT_SHA,
        'sandbox_pool_id': SANDBOX_POOL_ID,
    }
    values.update(overrides)
    return RuntimeIdentity(**values)


@pytest.mark.parametrize('deployment_sha', ['', DEPLOYMENT_SHA, '0' * 40])
def test_runtime_identity_accepts_local_or_exact_release_sha(deployment_sha):
    result = identity(deployment_sha=deployment_sha)

    assert result.id == INSTANCE_ID
    assert result.pool_id == POOL_ID
    assert result.deployment_sha == deployment_sha
    assert result.sandbox_pool_id == SANDBOX_POOL_ID


@pytest.mark.parametrize('field,value', [
    ('id', '1' * 32),
    ('pool_id', 'a'),
    ('pool_id', 'a' * 80),
    ('sandbox_pool_id', '1'),
    ('sandbox_pool_id', 'b' * 80),
])
def test_runtime_identity_accepts_simple_boundary_values(field, value):
    result = identity(**{field: value})

    assert getattr(result, field) == value


def test_runtime_identity_is_frozen():
    result = identity()

    with pytest.raises(FrozenInstanceError):
        result.pool_id = 'green'


@pytest.mark.parametrize('instance_id', [
    None,
    123,
    b'a' * 32,
    '',
    'a' * 31,
    'a' * 33,
    'A' * 32,
    'g' * 32,
    '0' * 32,
    'a' * 32 + '\n',
    'a' * 32 + '\r\n',
])
def test_runtime_identity_rejects_invalid_id_types_boundaries_and_suffixes(instance_id):
    with pytest.raises((TypeError, ValueError)):
        identity(id=instance_id)


@pytest.mark.parametrize('pool_id', [
    None,
    123,
    b'a',
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
def test_runtime_identity_rejects_invalid_pool_types_boundaries_and_suffixes(pool_id):
    with pytest.raises((TypeError, ValueError)):
        identity(pool_id=pool_id)


@pytest.mark.parametrize('sandbox_pool_id', [
    None,
    123,
    b'a',
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
def test_runtime_identity_rejects_invalid_sandbox_pool_types_boundaries_and_suffixes(sandbox_pool_id):
    with pytest.raises((TypeError, ValueError)):
        identity(sandbox_pool_id=sandbox_pool_id)


@pytest.mark.parametrize('deployment_sha', [
    None,
    123,
    b'b' * 40,
    'b' * 39,
    'b' * 41,
    'B' * 40,
    'g' * 40,
    'b' * 40 + '\n',
    'b' * 40 + '\r\n',
])
def test_runtime_identity_rejects_invalid_release_types_boundaries_and_suffixes(deployment_sha):
    with pytest.raises((TypeError, ValueError)):
        identity(deployment_sha=deployment_sha)
