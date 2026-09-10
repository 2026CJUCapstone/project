"""Bound ordinary cleanup: crash recovery, short locks and exact pool fencing."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest
from docker.errors import DockerException
from sqlalchemy import event

from app.models.database import ExecutionJob
from app.services.durable_queue import DurableQueue, WorkerIdentity, SandboxOperationPending
from app.services.execution_worker import SandboxPool
from tests.test_durable_queue import replicas, add
from tests.test_sandbox_operations import AT, pending
from tests.test_sandbox_reconciliation import LATER


@pytest.fixture(autouse=True)
def work_root(tmp_path, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, 'SANDBOX_WORKDIR_ROOT', str(tmp_path / 'sandbox'))


def bound(replicas, *, kind='run'):
    queue = DurableQueue(replicas[0], concurrency=1)
    job_id = queue.enqueue(owner_key='owner', request_id='one', kind=kind,
        payload={'code': 'print(42)'}, at=AT)
    worker = WorkerIdentity(uuid4().hex, 'audit', '', 'audit')
    claim = queue.claim(at=AT, worker=worker, daemon_id='engine-a')
    assert claim.id == job_id and claim.daemon_id == 'engine-a'
    client = SimpleNamespace(info=lambda: {'ID': 'engine-a'},
        containers=SimpleNamespace(list=lambda **kwargs: []))
    pool = SandboxPool(lambda: client, pool_id='audit')
    return queue, claim, pool


def test_cleanup_intent_is_visible_and_does_not_block_unrelated_admission(replicas):
    queue, claim, pool = bound(replicas)
    peer = DurableQueue(replicas[1], concurrency=1)
    entered, release = Event(), Event()
    def cleanup():
        assert pending(replicas[1], claim.id)['kind'] == 'cleanup'
        entered.set()
        assert release.wait(10)
    with ThreadPoolExecutor(max_workers=2) as executor:
        task = executor.submit(queue.cleanup_lease, claim.id, claim.token, cleanup)
        try:
            assert entered.wait(5)
            admitted = executor.submit(add, peer, 'two', 'other', AT)
            assert admitted.result(2)
            assert peer.finish(claim.id, claim.token, {'verdict': 'accepted'}, at=AT) is False
            with pytest.raises(SandboxOperationPending):
                peer.sandbox_operation(claim.id, claim.token, 'create',
                    lambda _: pytest.fail('create during cleanup'), daemon_id='engine-a', at=AT)
        finally:
            release.set()
        assert task.result(5)
    assert pending(replicas[1], claim.id) is None


@pytest.mark.parametrize('failure', ['action', 'ack-commit'])
def test_lost_cleanup_outcome_is_recovered_after_restart(replicas, failure):
    queue, claim, pool = bound(replicas)
    def action():
        if failure == 'action':
            raise DockerException('fixture response lost')
    def failed_commit(session):
        if any(isinstance(row, ExecutionJob) and row.sandbox_operation is None for row in session.dirty):
            raise RuntimeError('fixture ACK commit lost')
    if failure == 'ack-commit':
        event.listen(replicas[0], 'before_commit', failed_commit)
    try:
        with pytest.raises((DockerException, RuntimeError)):
            queue.cleanup_lease(claim.id, claim.token, action)
    finally:
        if failure == 'ack-commit':
            event.remove(replicas[0], 'before_commit', failed_commit)
    operation = pending(replicas[1], claim.id)
    assert operation['kind'] == 'cleanup' and operation['resolved_daemon_id'] == 'engine-a'
    restarted = DurableQueue(replicas[1], concurrency=1)
    restarted.recover_expired(pool, at=LATER)
    replacement = restarted.claim(at=LATER, daemon_id='engine-a')
    assert replacement.id == claim.id and replacement.token != claim.token


def test_ordinary_recovery_refuses_foreign_pool_and_daemon_without_mutation(replicas):
    queue, claim, pool = bound(replicas)
    pool.pool_id = 'foreign'
    queue.recover_expired(pool, at=LATER)
    assert pending(replicas[1], claim.id) is None
    assert queue.read(claim.id, owner_key='owner')['status'] == 'running'
    pool.pool_id = 'audit'
    pool.client_factory = lambda: SimpleNamespace(info=lambda: {'ID': 'engine-b'},
        containers=SimpleNamespace(list=lambda **kwargs: pytest.fail('wrong daemon list')))
    with pytest.raises(RuntimeError, match='daemon mismatch'):
        queue.recover_expired(pool, at=LATER)
    assert pending(replicas[1], claim.id)['kind'] == 'cleanup'
    assert queue.read(claim.id, owner_key='owner')['status'] == 'running'


def test_slow_expired_reaper_does_not_hold_global_lock(replicas):
    queue, claim, pool = bound(replicas)
    peer = DurableQueue(replicas[1])
    entered, release = Event(), Event()
    original = pool.reap_claim
    def slow(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return original(*args, **kwargs)
    pool.reap_claim = slow
    with ThreadPoolExecutor(max_workers=2) as executor:
        task = executor.submit(queue.recover_expired, pool, at=LATER)
        try:
            assert entered.wait(5)
            assert executor.submit(add, peer, 'two', 'other', AT).result(2)
        finally:
            release.set()
        task.result(5)
    assert queue.read(claim.id, owner_key='owner')['status'] == 'queued'


def test_expired_bound_terminal_is_canceled_not_replayed(replicas):
    queue, claim, pool = bound(replicas, kind='terminal')
    queue.recover_expired(pool, at=LATER)
    result = queue.read(claim.id, owner_key='owner')
    assert result['status'] == 'failed' and result['result']['verdict'] == 'canceled'
    assert queue.claim(at=LATER) is None


def test_unbound_legacy_worker_is_not_assumed_to_use_current_daemon(replicas):
    queue = DurableQueue(replicas[0])
    job_id = add(queue, at=AT)
    queue.claim(at=AT, worker=WorkerIdentity(uuid4().hex, 'audit', '', 'audit'))
    pool = SandboxPool(lambda: pytest.fail('unbound legacy daemon queried'), pool_id='audit')
    queue.recover_expired(pool, at=LATER)
    assert queue.read(job_id, owner_key='owner')['status'] == 'running'


def test_bound_claim_refuses_unjournaled_start_and_changed_daemon(replicas):
    queue, claim, pool = bound(replicas)
    assert queue.start(claim.id, claim.token,
        lambda: pytest.fail('bound claim used legacy start'), at=AT) is False
    with pytest.raises(SandboxOperationPending, match='daemon mismatch'):
        queue.sandbox_operation(claim.id, claim.token, 'create',
            lambda _: pytest.fail('different daemon effect'), daemon_id='engine-b', at=AT)
    assert pending(replicas[1], claim.id) is None
