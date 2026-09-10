"""Positive recovery, loss of removal receipts, and late original ACK fencing."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest
from docker.errors import DockerException, NotFound
from sqlalchemy import event

from app.models.database import ExecutionJob
from app.services.durable_queue import DurableQueue, SandboxOperationPending, WorkerIdentity
from app.services.execution_worker import SandboxPool
from app.services.sandbox_identity import sandbox_labels
from tests.test_durable_queue import replicas, add
from tests.test_sandbox_operations import AT, CONTAINER, pending

LATER = AT + timedelta(hours=1)


@pytest.fixture(autouse=True)
def isolated_workdirs(tmp_path, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, 'SANDBOX_WORKDIR_ROOT', str(tmp_path / 'sandboxes'))


def fixture(replicas):
    queue = DurableQueue(replicas[0], concurrency=1)
    add(queue, at=AT)
    worker = WorkerIdentity(uuid4().hex, 'test', '', 'test')
    claim = queue.claim(at=AT, worker=worker)
    labels = sandbox_labels(claim.id, claim.token, worker)
    objects, removals = {}, []

    def get(target):
        for obj in objects.values():
            if target in (obj.id, obj.name):
                return obj
        raise NotFound('fixture absent')

    def create(operation):
        def remove(**kwargs):
            assert pending(replicas[1], claim.id)['resolved_container_id'] == CONTAINER
            removals.append(CONTAINER)
            objects.pop(CONTAINER)
        obj = SimpleNamespace(id=CONTAINER, name=operation['name'],
            labels=labels | {'webcompiler.operation': operation['id']}, remove=remove)
        objects[obj.id] = obj
        return obj

    pool = SandboxPool(lambda: SimpleNamespace(info=lambda: {'ID': 'fixture-engine-a'},
        containers=SimpleNamespace(get=get, list=lambda **kwargs: list(objects.values()))), pool_id='test')
    return queue, claim, pool, create, objects, removals


def lose_create(queue, claim, action):
    def lost(operation):
        action(operation)
        raise DockerException('fixture lost response')
    with pytest.raises(DockerException):
        queue.sandbox_operation(claim.id, claim.token, 'create', lost, at=AT)


def test_missing_create_retains_capacity_until_positively_observed(replicas):
    queue, claim, pool, create, objects, removed = fixture(replicas)
    lose_create(queue, claim, lambda _: None)
    assert queue.reconcile_pending(pool, at=LATER) == 0
    assert pending(replicas[1], claim.id)['kind'] == 'create'
    assert queue.claim(at=LATER) is None
    create(pending(replicas[1], claim.id))  # Daemon finally materializes request.
    assert queue.reconcile_pending(pool, at=LATER) == 1
    assert objects == {} and removed == [CONTAINER]
    assert queue.read(claim.id, owner_key='owner')['status'] == 'running'
    queue.reap_expired = lambda *args: pytest.fail('Bound lease used legacy recovery')
    assert queue.claim(at=LATER) is None
    queue.recover_expired(pool, at=LATER)
    replacement = queue.claim(at=LATER)
    assert replacement.id == claim.id and replacement.token != claim.token


@pytest.mark.parametrize('failure', ['remove-response', 'settlement-commit'])
def test_restart_resumes_durable_id_after_removal_acknowledgment_is_lost(replicas, failure):
    queue, claim, pool, create, objects, removed = fixture(replicas)
    lose_create(queue, claim, create)
    obj = objects[CONTAINER]
    original_remove = obj.remove
    if failure == 'remove-response':
        def remove(**kwargs):
            original_remove(**kwargs)
            raise DockerException('fixture lost remove response')
        obj.remove = remove
    def fail_commit(session):
        for record in session.dirty:
            if isinstance(record, ExecutionJob) and record.sandbox_operation is None:
                raise RuntimeError('fixture lost settlement commit')
    if failure == 'settlement-commit':
        event.listen(replicas[0], 'before_commit', fail_commit)
    try:
        with pytest.raises((DockerException, RuntimeError)):
            queue.reconcile_pending(pool, at=LATER)
    finally:
        if failure == 'settlement-commit':
            event.remove(replicas[0], 'before_commit', fail_commit)
    assert objects == {} and removed == [CONTAINER]
    assert pending(replicas[1], claim.id)['phase'] == 'removing'
    restarted = DurableQueue(replicas[1])
    assert restarted.reconcile_pending(pool, at=LATER) == 1
    assert pending(replicas[0], claim.id) is None
    assert removed == [CONTAINER]


def test_late_original_ack_cannot_undo_reconciliation_or_start_removed_id(replicas):
    queue, claim, pool, create, objects, removed = fixture(replicas)
    entered, release = Event(), Event()
    def delayed(operation):
        obj = create(operation)
        entered.set()
        assert release.wait(10)
        return obj
    with ThreadPoolExecutor(max_workers=1) as executor:
        task = executor.submit(queue.sandbox_operation, claim.id, claim.token,
            'create', delayed, at=AT)
        try:
            assert entered.wait(5)
            peer = DurableQueue(replicas[1], reap_expired=lambda *args: None)
            assert peer.reconcile_pending(pool, at=LATER) == 1
            peer.recover_expired(pool, at=LATER)
            replacement = peer.claim(at=LATER)
            assert replacement.token != claim.token
        finally:
            release.set()
        with pytest.raises(SandboxOperationPending):
            task.result(5)
    assert removed == [CONTAINER] and objects == {}
    assert queue.start(claim.id, claim.token, lambda: pytest.fail('stale start'), at=AT) is False


def test_ownership_mismatch_and_different_pool_do_not_remove_or_clear(replicas):
    queue, claim, pool, create, objects, removed = fixture(replicas)
    lose_create(queue, claim, create)
    original = pending(replicas[1], claim.id)
    pool.pool_id = 'foreign'
    assert queue.reconcile_pending(pool, at=LATER) == 0
    pool.pool_id = 'test'
    objects[CONTAINER].labels['webcompiler.lease'] = 'f' * 32
    with pytest.raises(RuntimeError, match='ownership'):
        queue.reconcile_pending(pool, at=LATER)
    assert pending(replicas[1], claim.id) == original and removed == []


def test_failed_observation_commit_never_sends_removal(replicas):
    queue, claim, pool, create, objects, removed = fixture(replicas)
    lose_create(queue, claim, create)
    original = pending(replicas[1], claim.id)
    def fail_commit(session):
        raise RuntimeError('fixture observation commit failed')
    event.listen(replicas[0], 'before_commit', fail_commit)
    try:
        with pytest.raises(RuntimeError):
            queue.reconcile_pending(pool, at=LATER)
    finally:
        event.remove(replicas[0], 'before_commit', fail_commit)
    assert removed == [] and pending(replicas[1], claim.id) == original


@pytest.mark.parametrize('stage', ['observe', 'remove'])
def test_slow_docker_observation_and_removal_do_not_hold_global_admission_lock(replicas, stage):
    queue, claim, pool, create, objects, removed = fixture(replicas)
    lose_create(queue, claim, create)
    entered, release = Event(), Event()
    method = 'observe_operation' if stage == 'observe' else 'remove_operation'
    original = getattr(pool, method)
    def blocked(*args):
        entered.set()
        assert release.wait(10)
        return original(*args)
    setattr(pool, method, blocked)
    peer = DurableQueue(replicas[1], concurrency=1)
    with ThreadPoolExecutor(max_workers=2) as executor:
        recovery = executor.submit(queue.reconcile_pending, pool, at=LATER)
        try:
            assert entered.wait(5)
            accepted = executor.submit(add, peer, 'second', 'another', LATER)
            assert accepted.result(2)  # This takes the actual common DB lock.
            assert peer.claim(at=LATER) is None
        finally:
            release.set()
        assert recovery.result(5) == 1


def test_original_ack_during_observation_prevents_destructive_phase(replicas):
    queue, claim, pool, create, objects, removed = fixture(replicas)
    created, release_ack, observed, release_observe = Event(), Event(), Event(), Event()
    def delayed(operation):
        obj = create(operation)
        created.set()
        assert release_ack.wait(10)
        return obj
    original = pool.observe_operation
    def observe(*args):
        identity = original(*args)
        observed.set()
        assert release_observe.wait(10)
        return identity
    pool.observe_operation = observe
    with ThreadPoolExecutor(max_workers=2) as executor:
        request = executor.submit(queue.sandbox_operation, claim.id, claim.token,
            'create', delayed, at=AT)
        recovery = None
        try:
            assert created.wait(5)
            peer = DurableQueue(replicas[1])
            recovery = executor.submit(peer.reconcile_pending, pool, at=LATER)
            assert observed.wait(5)
            release_ack.set()
            assert request.result(5).id == CONTAINER
        finally:
            release_ack.set()
            release_observe.set()
        assert recovery.result(5) == 0
    assert removed == [] and CONTAINER in objects


def test_failed_full_claim_sweep_keeps_durable_phase_for_retry(replicas):
    queue, claim, pool, create, objects, removed = fixture(replicas)
    lose_create(queue, claim, create)
    original_sweep = pool.reap_claim
    def failed(expected, **kwargs):
        assert objects == {}
        assert pending(replicas[1], claim.id)['phase'] == 'removing'
        raise DockerException('fixture sweep observation failed')
    pool.reap_claim = failed
    with pytest.raises(DockerException):
        queue.reconcile_pending(pool, at=LATER)
    assert pending(replicas[1], claim.id)['phase'] == 'removing'
    pool.reap_claim = original_sweep
    assert queue.reconcile_pending(pool, at=LATER) == 1
    assert removed == [CONTAINER]


def test_same_pool_different_daemon_cannot_resume_absence_proof(replicas):
    queue, claim, pool, create, objects, removed = fixture(replicas)
    lose_create(queue, claim, create)
    original_remove = pool.remove_operation
    def fail_after_phase(*args):
        raise DockerException('fixture crash after binding')
    pool.remove_operation = fail_after_phase
    with pytest.raises(DockerException):
        queue.reconcile_pending(pool, at=LATER)
    assert pending(replicas[1], claim.id)['resolved_daemon_id'] == 'fixture-engine-a'
    pool.remove_operation = original_remove
    pool.client_factory = lambda: SimpleNamespace(info=lambda: {'ID': 'fixture-engine-b'},
        containers=SimpleNamespace(get=lambda _: pytest.fail('wrong daemon lookup')))
    with pytest.raises(RuntimeError, match='daemon mismatch'):
        queue.reconcile_pending(pool, at=LATER)
    assert removed == [] and CONTAINER in objects
    assert pending(replicas[1], claim.id)['phase'] == 'removing'


def test_start_missing_before_engine_binding_is_not_a_recovery_receipt(replicas):
    queue, claim, pool, create, objects, removed = fixture(replicas)
    with pytest.raises(DockerException):
        queue.sandbox_operation(claim.id, claim.token, 'start',
            lambda _: (_ for _ in ()).throw(DockerException('fixture lost response')),
            container_id=CONTAINER, at=AT)
    assert queue.reconcile_pending(pool, at=LATER) == 0
    assert pending(replicas[1], claim.id)['kind'] == 'start'
    assert removed == []


def test_auxiliary_sandbox_still_present_prevents_workdir_deletion_and_clear(replicas, tmp_path):
    from app.core.config import settings
    from pathlib import Path
    queue, claim, pool, create, objects, removed = fixture(replicas)
    lose_create(queue, claim, create)
    original = objects[CONTAINER]
    auxiliary = SimpleNamespace(id='b'*64, name='earlier-acknowledged',
        labels=dict(original.labels), remove=lambda **kwargs: None)
    objects[auxiliary.id] = auxiliary
    directory = Path(settings.SANDBOX_WORKDIR_ROOT) / f'job-{claim.id}-{claim.token}-fixture'
    directory.mkdir(parents=True)
    (directory / 'main.py').write_text('print(42)')
    with pytest.raises(RuntimeError, match='absence'):
        queue.reconcile_pending(pool, at=LATER)
    assert (directory / 'main.py').read_text() == 'print(42)'
    assert pending(replicas[1], claim.id)['phase'] == 'removing'
    assert auxiliary.id in objects and removed == [CONTAINER]
