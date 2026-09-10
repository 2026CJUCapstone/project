import json

import pytest

from app import runtime_drain
from app.services.runtime_identity import RuntimeIdentity


RUNTIME_ID = 'a' * 32
POOL_ID = 'blue_pool'
DEPLOYMENT_SHA = 'b' * 40
SANDBOX_POOL_ID = 'sandbox_pool'


def arguments(identity, *, begin=False):
    result = [
        '--runtime', identity.id,
        '--pool', identity.pool_id,
        '--release', identity.deployment_sha,
        '--sandbox-pool', identity.sandbox_pool_id,
    ]
    if begin:
        result.append('--begin')
    return result


@pytest.fixture
def configured(monkeypatch):
    result = RuntimeIdentity(RUNTIME_ID, POOL_ID, DEPLOYMENT_SHA, SANDBOX_POOL_ID)
    monkeypatch.setattr(
        runtime_drain.RuntimeIdentity,
        'configured',
        classmethod(lambda cls: result),
    )
    return result


class RecordingRegistry:
    def __init__(self, sessions, events, status=None):
        self.events = events
        self.result = status if status is not None else {
            'id': RUNTIME_ID,
            'draining': False,
            'active_claims': 0,
        }

    def begin_drain(self, identity):
        self.events.append(('begin_drain', identity))

    def status(self, identity):
        self.events.append(('status', identity))
        return self.result


def test_default_status_is_read_only(configured, monkeypatch, capsys):
    events = []
    monkeypatch.setattr(
        runtime_drain,
        'RuntimeRegistry',
        lambda sessions: RecordingRegistry(sessions, events),
    )

    runtime_drain.main(arguments(configured))

    assert events == [('status', configured)]
    assert json.loads(capsys.readouterr().out) == {
        'id': RUNTIME_ID,
        'draining': False,
        'active_claims': 0,
    }


def test_begin_only_fences_then_reads_status(configured, monkeypatch, capsys):
    events = []
    monkeypatch.setattr(
        runtime_drain,
        'RuntimeRegistry',
        lambda sessions: RecordingRegistry(sessions, events),
    )

    runtime_drain.main(arguments(configured, begin=True))

    assert events == [('begin_drain', configured), ('status', configured)]
    assert json.loads(capsys.readouterr().out)['id'] == RUNTIME_ID


@pytest.mark.parametrize('field,value', [
    ('id', 'c' * 32),
    ('pool_id', 'green_pool'),
    ('deployment_sha', 'd' * 40),
    ('sandbox_pool_id', 'other_sandbox'),
])
def test_exact_configured_target_is_required_before_registry_construction(
        configured, monkeypatch, field, value):
    target = {
        'id': configured.id,
        'pool': configured.pool_id,
        'release': configured.deployment_sha,
        'sandbox-pool': configured.sandbox_pool_id,
    }
    argument_name = {
        'id': 'id',
        'pool_id': 'pool',
        'deployment_sha': 'release',
        'sandbox_pool_id': 'sandbox-pool',
    }[field]
    target[argument_name] = value
    args = [
        '--runtime', target['id'],
        '--pool', target['pool'],
        '--release', target['release'],
        '--sandbox-pool', target['sandbox-pool'],
    ]
    monkeypatch.setattr(
        runtime_drain,
        'RuntimeRegistry',
        lambda sessions: pytest.fail('registry must not be constructed'),
    )

    with pytest.raises(SystemExit) as error:
        runtime_drain.main(args)

    assert error.value.code == 1


def test_missing_runtime_exits_one(configured, monkeypatch, capsys):
    events = []
    class MissingRegistry:
        def __init__(self, sessions):
            events.append(('constructed',))

        def status(self, identity):
            events.append(('status', identity))
            return None

    monkeypatch.setattr(runtime_drain, 'RuntimeRegistry', MissingRegistry)
    with pytest.raises(SystemExit) as error:
        runtime_drain.main(arguments(configured))

    assert error.value.code == 1
    assert events == [('constructed',), ('status', configured)]
    assert 'Runtime is not registered' in capsys.readouterr().err


@pytest.mark.parametrize('failure', [ValueError, OSError, RuntimeError])
def test_backend_errors_use_safe_messages_without_fixture_secret(
        configured, monkeypatch, capsys, failure):
    secret = 'fixture-secret-do-not-leak'

    class FailingRegistry:
        def __init__(self, sessions):
            pass

        def status(self, identity):
            raise failure(secret)

    monkeypatch.setattr(runtime_drain, 'RuntimeRegistry', FailingRegistry)

    with pytest.raises(SystemExit) as error:
        runtime_drain.main(arguments(configured))

    captured = capsys.readouterr()
    assert error.value.code == 1
    assert secret not in captured.out + captured.err
    if failure is RuntimeError:
        assert 'Runtime state unavailable; no retirement authorization' in captured.err
    else:
        assert 'Runtime operation failed; exact identity or state must be checked' in captured.err
