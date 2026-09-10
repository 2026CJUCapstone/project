"""Process-wide fences order every lane's claims across DB connections."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta
from threading import Event
from uuid import uuid4

import pytest

from app.models.database import ExecutionJob, ExecutionWorkerRecord, WorkerProcessRecord
from app.services import worker_lifecycle
from app.services.durable_queue import DurableQueue
from app.services.runtime_registry import RuntimeRegistry
from app.services.worker_lifecycle import WorkerLifecycle
from app.services.worker_process import ProcessIdentity
from tests.test_durable_queue import replicas, add
from tests.test_runtime_registry import runtime, lane


def setup(replicas):
    owner = runtime()
    assert RuntimeRegistry(replicas[0]).register(owner)
    process = ProcessIdentity(uuid4().hex, 123, 'test:123', 'worker-host', 'a'*64)
    lifecycle = WorkerLifecycle(replicas[0], owner, process)
    assert lifecycle.register()
    worker = replace(lane(owner), process_id=process.epoch)
    return owner, lifecycle, worker


def test_process_drain_blocks_new_lane_ids_but_preserves_prior_claim(replicas):
    owner, lifecycle, worker = setup(replicas)
    queue = DurableQueue(replicas[1], concurrency=1)
    first, second = add(queue), add(queue, request='second')
    claim = queue.claim(worker=worker)
    assert claim.id == first
    assert lifecycle.begin_drain()
    assert not lifecycle.stop()  # Still owns a running claim.
    assert not lifecycle.register()
    for _ in range(3):
        late_lane = replace(worker, id=uuid4().hex)
        assert queue.claim(worker=late_lane) is None
        assert queue.worker_status(late_lane)['draining'] is True
    with replicas[0]() as db:
        assert db.get(WorkerProcessRecord, worker.process_id).stopped_at is None
        assert db.get(ExecutionWorkerRecord, worker.id).process_id == worker.process_id
    started = []
    assert queue.start(first, claim.token, lambda:started.append(first))
    assert queue.renew(first, claim.token)
    assert queue.finish(first, claim.token, {'verdict':'accepted'})
    assert started == [first]
    assert lifecycle.stop() and not lifecycle.register()
    # A different process in this still-active runtime remains eligible.
    other = WorkerLifecycle(replicas[1], owner, replace(lifecycle.process, epoch=uuid4().hex))
    assert other.register()
    assert queue.claim(worker=replace(worker, id=uuid4().hex, process_id=other.process.epoch)).id == second


@pytest.mark.parametrize('fence_first', [False, True])
def test_process_fence_and_claim_share_one_commit_order(replicas, monkeypatch, fence_first):
    _, lifecycle, worker = setup(replicas)
    queue = DurableQueue(replicas[1])
    add(queue)
    locked, waiting, release = Event(), Event(), Event()
    original = worker_lifecycle.execution_lock
    def hold(db):
        original(db)
        locked.set()
        assert release.wait(10)
    def observe(db):
        waiting.set()
        original(db)
    monkeypatch.setattr(worker_lifecycle, 'execution_lock', hold if fence_first else observe)
    monkeypatch.setattr(queue, '_lock', observe if fence_first else hold)
    first = lifecycle.begin_drain if fence_first else lambda:queue.claim(worker=worker)
    second = (lambda:queue.claim(worker=worker)) if fence_first else lifecycle.begin_drain
    with ThreadPoolExecutor(2) as pool:
        a = pool.submit(first)
        try:
            assert locked.wait(5)
            b = pool.submit(second)
            assert waiting.wait(5) and not b.done()
        finally:
            release.set()
        first_result, second_result = a.result(timeout=10), b.result(timeout=10)
    claim = second_result if fence_first else first_result
    assert (claim is None) == fence_first
    if claim:
        assert queue.finish(claim.id, claim.token, {'verdict':'accepted'})


def test_expired_claim_without_confirmed_reap_is_not_process_completion(replicas):
    _, lifecycle, worker = setup(replicas)
    queue = DurableQueue(replicas[1], lease_seconds=1)
    at = datetime(2000, 1, 1)
    job = add(queue, at=at)
    claim = queue.claim(worker=worker, at=at)
    assert not lifecycle.stop(at=at+timedelta(days=10000))
    with replicas[0]() as db:
        assert db.get(WorkerProcessRecord, worker.process_id).stopped_at is None
        assert db.get(ExecutionJob, job).lease_token == claim.token


def test_existing_lane_cannot_change_or_infer_process_owner(replicas):
    owner, lifecycle, worker = setup(replicas)
    queue = DurableQueue(replicas[1])
    assert queue.claim(worker=worker) is None  # Registers the idle lane.
    other = WorkerLifecycle(replicas[1], owner, replace(lifecycle.process, epoch=uuid4().hex))
    assert other.register()
    for replacement in (replace(worker, process_id=other.process.epoch), replace(worker, process_id='')):
        for operation in (queue.claim,):
            with pytest.raises(ValueError, match='identity mismatch'):
                operation(worker=replacement)
        with pytest.raises(ValueError, match='identity mismatch'):
            queue.worker_status(replacement)
    legacy = lane(owner)
    assert queue.claim(worker=legacy) is None
    with pytest.raises(ValueError, match='identity mismatch'):
        queue.claim(worker=replace(legacy, process_id=worker.process_id))
    with replicas[0]() as db:
        assert db.get(ExecutionWorkerRecord, legacy.id).process_id is None


def test_unknown_and_wrong_runtime_process_binding_cannot_publish_lane(replicas):
    owner, lifecycle, worker = setup(replicas)
    queue = DurableQueue(replicas[1])
    for bad in (replace(worker, process_id=uuid4().hex),
                replace(lane(runtime()), process_id=worker.process_id)):
        with pytest.raises(ValueError, match='registration or identity mismatch'):
            queue.claim(worker=bad)
    with replicas[0]() as db:
        assert db.query(ExecutionWorkerRecord).count() == 0
    impostor = WorkerLifecycle(replicas[1], owner, replace(lifecycle.process, start_token='test:124'))
    for operation in (impostor.register, impostor.begin_drain, impostor.stop):
        with pytest.raises(ValueError, match='identity mismatch'):
            operation()


def test_empty_process_stop_fences_before_new_lane_and_preserves_timestamp(replicas):
    _, lifecycle, worker = setup(replicas)
    at = datetime(2030, 1, 1)
    assert lifecycle.stop(at=at)
    assert lifecycle.stop(at=at+timedelta(days=1))
    queue = DurableQueue(replicas[1])
    add(queue)
    assert queue.claim(worker=worker) is None
    with replicas[1]() as db:
        row = db.get(WorkerProcessRecord, worker.process_id)
        assert row.draining_at == row.stopped_at == at


@pytest.mark.parametrize('field,value', [('pool_id','other-pool'),('deployment_sha','b'*40),
    ('sandbox_pool_id','other-sandbox')])
def test_same_runtime_id_with_wrong_metadata_cannot_fence_process(replicas, field, value):
    owner, lifecycle, worker = setup(replicas)
    impostor = WorkerLifecycle(replicas[1], replace(owner, **{field:value}), lifecycle.process)
    for operation in (impostor.register, impostor.begin_drain, impostor.stop):
        with pytest.raises(ValueError, match='identity mismatch'):
            operation()
    with replicas[0]() as db:
        row = db.get(WorkerProcessRecord, worker.process_id)
        assert row.draining_at is None and row.stopped_at is None
