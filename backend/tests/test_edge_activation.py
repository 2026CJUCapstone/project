import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
TRANSACTION_SPEC = importlib.util.spec_from_file_location(
    'edge_transaction', ROOT / 'scripts' / 'edge_transaction.py'
)
edge_transaction = importlib.util.module_from_spec(TRANSACTION_SPEC)
# Dataclasses resolve the defining module through sys.modules while executing.
sys.modules[TRANSACTION_SPEC.name] = edge_transaction
TRANSACTION_SPEC.loader.exec_module(edge_transaction)

RUNTIME_SPEC = importlib.util.spec_from_file_location(
    'edge_runtime', ROOT / 'scripts' / 'edge_runtime.py'
)
edge_runtime = importlib.util.module_from_spec(RUNTIME_SPEC)
sys.modules[RUNTIME_SPEC.name] = edge_runtime
RUNTIME_SPEC.loader.exec_module(edge_runtime)

Runtime = edge_runtime.Runtime
EdgeError = edge_runtime.EdgeError

IMAGE_ID = 'sha256:test-image'
CONTAINER_ID = 'edge-container-id'


def runtime_with_call(call):
    return Runtime(SimpleNamespace(path=Path('edge-store')), call=call)


def image_call(events, *, syntax_error=None):
    def call(args):
        args = list(args)
        events.append(('docker', args))
        if args[:2] == ['image', 'inspect']:
            return json.dumps([{'Id': IMAGE_ID}])
        if syntax_error is not None and args[:4] == [
                'exec', CONTAINER_ID, 'nginx', '-t']:
            raise syntax_error('syntax rejected')
        return ''

    return call


def live_container():
    return {'Id': CONTAINER_ID, 'State': {'Running': True}}


def test_activate_validates_live_container_syntax_reloads_and_waits_for_exact_ack():
    events = []
    runtime = runtime_with_call(image_call(events))
    release = object()
    container = live_container()

    runtime.inspect = lambda: events.append(('inspect',)) or container
    runtime.validate = lambda actual, image_id: events.append(
        ('validate', actual, image_id)
    )
    runtime.wait_ack = lambda actual_release: events.append(
        ('wait_ack', actual_release)
    ) or True

    assert runtime.activate(release) is True
    assert events == [
        ('docker', ['image', 'inspect', runtime.image]),
        ('inspect',),
        ('validate', container, IMAGE_ID),
        ('docker', ['exec', CONTAINER_ID, 'nginx', '-t', '-c', '/control/nginx.conf']),
        ('docker', ['exec', CONTAINER_ID, 'nginx', '-s', 'reload', '-c', '/control/nginx.conf']),
        ('wait_ack', release),
    ]
    assert not any(event[0] == 'docker' and event[1][0] == 'kill' for event in events)


@pytest.mark.parametrize('container', [None, {'Id': CONTAINER_ID, 'State': {'Running': False}}])
def test_activate_refuses_absent_or_stopped_container_before_mutation(container):
    events = []
    runtime = runtime_with_call(image_call(events))
    runtime.inspect = lambda: container
    runtime.validate = lambda *_: pytest.fail('validation must not run')
    runtime.wait_ack = lambda *_: pytest.fail('acknowledgment must not run')

    with pytest.raises(EdgeError, match='Cold/stopped'):
        runtime.activate(object())

    assert events == [('docker', ['image', 'inspect', runtime.image])]


def test_activate_validation_failure_does_not_reload():
    events = []
    runtime = runtime_with_call(image_call(events))
    runtime.inspect = lambda: live_container()
    runtime.validate = lambda *_: (_ for _ in ()).throw(EdgeError('not owned'))
    runtime.wait_ack = lambda *_: pytest.fail('acknowledgment must not run')

    with pytest.raises(EdgeError, match='not owned'):
        runtime.activate(object())

    assert events == [('docker', ['image', 'inspect', runtime.image])]


def test_activate_failed_syntax_check_does_not_reload_or_acknowledge():
    events = []
    runtime = runtime_with_call(image_call(events, syntax_error=EdgeError))
    runtime.inspect = lambda: live_container()
    runtime.validate = lambda *_: None
    runtime.wait_ack = lambda *_: pytest.fail('acknowledgment must not run')

    with pytest.raises(EdgeError, match='syntax rejected'):
        runtime.activate(object())

    assert events == [
        ('docker', ['image', 'inspect', runtime.image]),
        ('docker', ['exec', CONTAINER_ID, 'nginx', '-t', '-c', '/control/nginx.conf']),
    ]
