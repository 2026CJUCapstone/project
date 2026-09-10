from dataclasses import FrozenInstanceError

import pytest

from app.services.worker_process import ProcessIdentity


EPOCH = 'a' * 31 + '1'
PID = 1234
START_TOKEN = 'start:token-123'
HOSTNAME = 'worker-01.example'
SCOPE = 'c' * 64


def identity(**overrides):
    values = {
        'epoch': EPOCH,
        'pid': PID,
        'start_token': START_TOKEN,
        'hostname': HOSTNAME,
        'scope': SCOPE,
    }
    values.update(overrides)
    return ProcessIdentity(**values)


@pytest.mark.parametrize('field,value', [
    ('epoch', '0' * 31 + '1'),
    ('pid', 1),
    ('pid', 65535),
    ('start_token', 'a'),
    ('start_token', 'a' * 160),
    ('hostname', 'a'),
    ('hostname', 'a' * 253),
    ('scope', '0' * 64),
])
def test_process_identity_accepts_valid_boundary_values(field, value):
    result = identity(**{field: value})

    assert getattr(result, field) == value


def test_process_identity_is_frozen():
    result = identity()

    with pytest.raises(FrozenInstanceError):
        result.pid = 1


@pytest.mark.parametrize('missing_field', [
    'epoch',
    'pid',
    'start_token',
    'hostname',
    'scope',
])
def test_process_identity_requires_every_field(missing_field):
    values = {
        'epoch': EPOCH,
        'pid': PID,
        'start_token': START_TOKEN,
        'hostname': HOSTNAME,
        'scope': SCOPE,
    }
    values.pop(missing_field)

    with pytest.raises(TypeError):
        ProcessIdentity(**values)


@pytest.mark.parametrize('epoch', [
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
def test_process_identity_rejects_invalid_epoch_types_boundaries_and_suffixes(epoch):
    with pytest.raises((TypeError, ValueError)):
        identity(epoch=epoch)


@pytest.mark.parametrize('pid', [
    None,
    '1234',
    b'1234',
    True,
    False,
    0,
    -1,
    1.0,
])
def test_process_identity_rejects_invalid_pid_types_and_boundaries(pid):
    with pytest.raises((TypeError, ValueError)):
        identity(pid=pid)


@pytest.mark.parametrize('start_token', [
    None,
    123,
    b'token',
    '',
    'a' * 161,
    'Token',
    'token_value',
    'token/path',
    'token\nid',
    'token\n',
    'token\r\n',
    'token id',
])
def test_process_identity_rejects_invalid_start_token_types_boundaries_and_suffixes(start_token):
    with pytest.raises((TypeError, ValueError)):
        identity(start_token=start_token)


@pytest.mark.parametrize('hostname', [
    None,
    123,
    b'worker',
    '',
    'a' * 254,
    '-worker',
    '_worker',
    'worker:name',
    'worker/name',
    'worker\nid',
    'worker\n',
    'worker\r\n',
    'worker name',
])
def test_process_identity_rejects_invalid_hostname_types_boundaries_and_suffixes(hostname):
    with pytest.raises((TypeError, ValueError)):
        identity(hostname=hostname)


@pytest.mark.parametrize('scope', [
    None,
    123,
    b'c' * 64,
    '',
    'c' * 63,
    'c' * 65,
    'A' * 64,
    'g' * 64,
    'c' * 64 + '\n',
    'c' * 64 + '\r\n',
])
def test_process_identity_rejects_invalid_scope_types_boundaries_and_suffixes(scope):
    with pytest.raises((TypeError, ValueError)):
        identity(scope=scope)
