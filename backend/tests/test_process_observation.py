"""Kernel absence is distinct from invisible/unknown and never mutates state."""
from dataclasses import replace
import errno
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.models.database import ActiveApiRequest, ApiProcessRecord, ExecutionJob, WorkerProcessRecord
from app.services import process_observation as module
from app.services.api_lifecycle import RuntimeRequests
from app.services.durable_queue import DurableQueue
from app.services.process_observation import ProcessObserver
from app.services.runtime_registry import RuntimeRegistry
from app.services.worker_lifecycle import WorkerLifecycle
from app.services.worker_process import ProcessIdentity
from tests.test_durable_queue import replicas, add
from tests.test_runtime_registry import runtime, lane


@pytest.fixture
def process(monkeypatch):
    identity = ProcessIdentity(uuid4().hex, 123, 'linux:boot:456', 'fixture', 'a'*64)
    monkeypatch.setattr(module.socket, 'gethostname', lambda:identity.hostname)
    monkeypatch.setattr(module, 'local_namespace_token', lambda:'fixture-namespace')
    monkeypatch.setattr(module, 'configured_scope', lambda:identity.scope)
    return identity


def test_exact_kernel_start_token_distinguishes_alive_and_pid_reuse(process, monkeypatch):
    observed = []
    def start_token(pid):
        observed.append(pid)
        return process.start_token
    monkeypatch.setattr(module, 'process_start_token', start_token)
    assert module.local_process_state(process) == 'alive'
    assert observed == [process.pid]
    observed.clear()
    def reused_start_token(pid):
        observed.append(pid)
        return 'linux:boot:457'
    monkeypatch.setattr(module, 'process_start_token', reused_start_token)
    assert module.local_process_state(process) == 'absent'
    assert observed == [process.pid]


@pytest.mark.parametrize('field,value', [('hostname','other'),('scope','b'*64)])
def test_foreign_namespace_or_host_is_unknown_without_probing_pid(process, monkeypatch, field, value):
    def unexpected(pid):
        pytest.fail('Foreign namespace PID was inspected')
    monkeypatch.setattr(module, 'process_start_token', unexpected)
    assert module.local_process_state(replace(process, **{field:value})) == 'unknown'


def test_unsupported_namespace_is_not_evidence_of_absence(process, monkeypatch):
    monkeypatch.setattr(module, 'local_namespace_token', lambda:None)
    assert module.local_process_state(process) == 'unknown'


@pytest.mark.parametrize('error', [PermissionError('fixture secret'), OSError('unavailable'),
    ValueError('malformed'), IndexError('bad proc stat')])
def test_read_errors_fail_unknown(process, monkeypatch, error):
    def fail(pid):
        raise error
    monkeypatch.setattr(module, 'process_start_token', fail)
    assert module.local_process_state(process) == 'unknown'


@pytest.mark.parametrize('missing', ['target', 'boot', 'other-target'])
@pytest.mark.parametrize('signal_state', ['absent','exists','denied'])
def test_missing_proc_entry_requires_independent_kernel_absence(process, monkeypatch, missing, signal_state):
    def missing_file(pid):
        if missing == 'target':
            path = f'/proc/{pid}/stat'
        elif missing == 'boot':
            path = '/proc/sys/kernel/random/boot_id'
        else:
            path = '/proc/other-target/stat'
        raise FileNotFoundError(errno.ENOENT,'fixture missing',path)
    def signal_zero(pid, value):
        assert pid == process.pid and value == 0
        if signal_state == 'absent':
            raise ProcessLookupError(errno.ESRCH,'fixture absent')
        if signal_state == 'denied':
            raise PermissionError(errno.EPERM,'fixture denied')
    monkeypatch.setattr(module, 'process_start_token', missing_file)
    monkeypatch.setattr(module.os, 'kill', signal_zero)
    expected = 'absent' if missing == 'target' and signal_state == 'absent' else 'unknown'
    assert module.local_process_state(process) == expected


def test_kernel_zombie_state_is_not_running(process, monkeypatch):
    def exited(pid):
        raise ProcessLookupError('fixture zombie')
    monkeypatch.setattr(module, 'process_start_token', exited)
    assert module.local_process_state(process) == 'absent'


@pytest.mark.parametrize('role', ['api','worker'])
def test_observation_never_clears_unresolved_requests_claims_or_stop_state(replicas, process, monkeypatch, role):
    owner = runtime()
    registry = RuntimeRegistry(replicas[0])
    assert registry.register(owner)
    if role == 'api':
        service = RuntimeRequests(replicas[0], owner, process)
        assert service.register()
        work = service.begin('websocket')
    else:
        service = WorkerLifecycle(replicas[0], owner, process)
        assert service.register()
        queue = DurableQueue(replicas[0])
        work = add(queue)
        assert queue.claim(worker=replace(lane(owner), process_id=process.epoch)).id == work
    registry.begin_drain(owner)
    monkeypatch.setattr(module, 'local_process_state', lambda item:'absent')
    with replicas[0]() as db:
        before = db.execute(text('SELECT revision FROM execution_queue_lock')).all()
    observer = ProcessObserver(replicas[1], owner)
    assert observer.observe(role, process.epoch) == {
        'runtime_id':owner.id,'role':role,'epoch':process.epoch,'state':'absent'}
    with replicas[0]() as db:
        assert db.execute(text('SELECT revision FROM execution_queue_lock')).all() == before
        if role == 'api':
            assert db.get(ActiveApiRequest,work) is not None
            assert db.get(ApiProcessRecord,process.epoch).stopped_at is None
        else:
            assert db.get(ExecutionJob,work).status == 'running'
            assert db.get(WorkerProcessRecord,process.epoch).stopped_at is None
    with pytest.raises(ValueError, match='registered process'):
        observer.observe(role, uuid4().hex)
    with pytest.raises(ValueError, match='identity mismatch'):
        ProcessObserver(replicas[1],replace(owner,pool_id='other-pool')).observe(role,process.epoch)
