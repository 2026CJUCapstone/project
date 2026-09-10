"""Cross-connection DB ordering, not process-local flags, fences a runtime."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta
from threading import Event
from uuid import uuid4

import pytest

from app.models.database import ExecutionJob, ExecutionRuntimeRecord, ExecutionWorkerRecord
from app.services import runtime_registry as registry_module
from app.services.durable_queue import DurableQueue, WorkerIdentity
from app.services.runtime_identity import RuntimeIdentity
from app.services.runtime_registry import RuntimeRegistry, runtime_accepting
from tests.test_durable_queue import replicas, add


def runtime():
    return RuntimeIdentity(uuid4().hex, 'same-pool', 'a'*40, 'shared-sandbox')


def lane(owner):
    return WorkerIdentity(uuid4().hex, owner.pool_id, owner.deployment_sha,
                          owner.sandbox_pool_id, owner.id)


def test_unknown_status_is_read_only_and_missing_runtime_is_not_ready(replicas):
    owner = runtime()
    registry = RuntimeRegistry(replicas[0])
    assert registry.status(owner) is None
    assert not runtime_accepting(replicas[1].kw['bind'], owner)
    with replicas[1]() as db:
        assert db.query(ExecutionRuntimeRecord).count() == 0
        assert db.query(ExecutionWorkerRecord).count() == 0


def test_pre_registration_tombstone_survives_restart_with_new_lane_ids(replicas):
    owner, other = runtime(), runtime()  # Same SHA and pool, distinct incarnation.
    a, b = [RuntimeRegistry(factory) for factory in replicas]
    queue = DurableQueue(replicas[1])
    at = datetime(2030, 1, 1)
    a.begin_drain(owner, at=at)
    b.begin_drain(owner, at=at+timedelta(seconds=10))
    assert not b.register(owner)
    job = add(queue)
    for _ in range(3):
        restarted_lane = lane(owner)
        assert queue.claim(worker=restarted_lane) is None
        # Intrinsic lane state is distinct from the effective runtime fence.
        assert queue.worker_status(restarted_lane)['draining'] is False
    assert a.status(owner) == {'id':owner.id, 'draining':True, 'active_claims':0, 'active_http':0, 'active_websockets':0}
    assert not runtime_accepting(replicas[0].kw['bind'], owner)
    assert b.register(other)
    assert runtime_accepting(replicas[0].kw['bind'], other)
    assert queue.claim(worker=lane(other)).id == job
    with replicas[0]() as db:
        assert db.get(ExecutionRuntimeRecord, owner.id).draining_at == at


def test_prior_claim_can_start_renew_finish_but_new_lane_cannot_claim(replicas):
    owner, other = runtime(), runtime()
    a, b = [DurableQueue(factory, concurrency=1) for factory in replicas]
    registry = RuntimeRegistry(replicas[1])
    first, second = add(a), add(a, request='second')
    claim = a.claim(worker=lane(owner))
    assert claim.id == first
    registry.begin_drain(owner)
    assert registry.status(owner)['active_claims'] == 1
    assert b.claim(worker=lane(owner)) is None
    assert b.claim(worker=lane(other)) is None  # One shared budget, not per runtime.
    assert a.renew(first, claim.token)
    starts = []
    assert a.start(first, claim.token, lambda:starts.append(first))
    assert starts == [first]
    assert a.finish(first, claim.token, {'verdict':'accepted'})
    assert registry.status(owner)['active_claims'] == 0
    assert b.claim(worker=lane(owner)) is None
    assert b.claim(worker=lane(other)).id == second


@pytest.mark.parametrize('field,value', [
    ('pool_id', 'another-pool'), ('deployment_sha', 'b'*40),
    ('sandbox_pool_id', 'another-sandbox'),
])
def test_existing_runtime_identity_cannot_be_reassigned(replicas, field, value):
    owner = runtime()
    registry = RuntimeRegistry(replicas[0])
    assert registry.register(owner)
    impostor = replace(owner, **{field:value})
    queue = DurableQueue(replicas[1])
    for operation in (registry.register, registry.begin_drain, registry.status,
                      lambda item:runtime_accepting(replicas[1].kw['bind'], item),
                      lambda item:queue.claim(worker=lane(item))):
        with pytest.raises(ValueError, match='identity mismatch'):
            operation(impostor)
    assert registry.status(owner)['draining'] is False
    with replicas[1]() as db:
        assert db.query(ExecutionWorkerRecord).count() == 0


def test_explicit_registration_checks_v3_evidence_without_inventing_drain(replicas):
    owner = runtime()
    old_lane = lane(owner)
    at = datetime(2030, 1, 1)
    with replicas[0]() as db:
        db.add(ExecutionWorkerRecord(id=old_lane.id, runtime_id=owner.id,
            pool_id=owner.pool_id, deployment_sha=owner.deployment_sha,
            sandbox_pool_id=owner.sandbox_pool_id, started_at=at, draining_at=at))
        db.commit()
    registry = RuntimeRegistry(replicas[1])
    assert registry.status(owner) is None
    impostor = replace(owner, pool_id='impostor')
    for operation in (registry.register, registry.begin_drain):
        with pytest.raises(ValueError, match='identity mismatch'):
            operation(impostor)
    with replicas[0]() as db:
        assert db.get(ExecutionRuntimeRecord, owner.id) is None
        assert db.get(ExecutionWorkerRecord, old_lane.id).draining_at == at
    assert registry.register(owner)
    assert registry.status(owner)['draining'] is False
    queue = DurableQueue(replicas[0])
    add(queue)
    assert queue.claim(worker=old_lane) is None
    assert queue.claim(worker=lane(owner)) is not None


def test_claim_committed_before_runtime_fence_is_preserved(replicas):
    owner = runtime()
    claimed, release, draining = Event(), Event(), Event()
    def hold_claim(db, job):
        if job.status == 'running':
            claimed.set()
            assert release.wait(10)
    queue = DurableQueue(replicas[0], on_transition=hold_claim)
    registry = RuntimeRegistry(replicas[1])
    job = add(queue)
    def drain():
        draining.set()
        registry.begin_drain(owner)
    with ThreadPoolExecutor(2) as executor:
        claim_future = executor.submit(queue.claim, worker=lane(owner))
        try:
            assert claimed.wait(5)
            drain_future = executor.submit(drain)
            assert draining.wait(5)
            assert not drain_future.done()
        finally:
            release.set()
        claim = claim_future.result(timeout=10)
        drain_future.result(timeout=10)
    assert claim.id == job
    assert registry.status(owner) == {'id':owner.id, 'draining':True, 'active_claims':1, 'active_http':0, 'active_websockets':0}
    assert queue.claim(worker=lane(owner)) is None
    assert queue.finish(job, claim.token, {'verdict':'accepted'})


def test_claim_waiting_behind_fence_cannot_start_after_commit(replicas, monkeypatch):
    owner = runtime()
    queue = DurableQueue(replicas[1])
    registry = RuntimeRegistry(replicas[0])
    locked, release, waiting = Event(), Event(), Event()
    original = registry_module.execution_lock
    def hold_drain(db):
        original(db)
        locked.set()
        assert release.wait(10)
    def observed_claim(db):
        waiting.set()
        original(db)
    add(queue)
    monkeypatch.setattr(registry_module, 'execution_lock', hold_drain)
    monkeypatch.setattr(queue, '_lock', observed_claim)
    with ThreadPoolExecutor(2) as executor:
        drain_future = executor.submit(registry.begin_drain, owner)
        try:
            assert locked.wait(5)
            claim_future = executor.submit(queue.claim, worker=lane(owner))
            assert waiting.wait(5)
            assert not claim_future.done()
        finally:
            release.set()
        drain_future.result(timeout=10)
        assert claim_future.result(timeout=10) is None
    assert registry.status(owner)['draining'] is True


def test_claim_publication_failure_rolls_back_runtime_and_lane(replicas):
    owner = runtime()
    def fail(db, job):
        raise RuntimeError('fixture publication failure')
    queue = DurableQueue(replicas[0], on_transition=fail)
    job = add(queue)
    with pytest.raises(RuntimeError, match='fixture publication failure'):
        queue.claim(worker=lane(owner))
    assert RuntimeRegistry(replicas[1]).status(owner) is None
    with replicas[1]() as db:
        assert db.query(ExecutionWorkerRecord).count() == 0
        record = db.get(ExecutionJob, job)
        assert record.worker_id is None and record.status == 'queued'


def test_zero_count_does_not_adopt_unknown_legacy_workers(replicas):
    owner = runtime()
    registry = RuntimeRegistry(replicas[0])
    queue = DurableQueue(replicas[1])
    legacy = replace(lane(owner), runtime_id='')
    add(queue)
    assert queue.claim(worker=legacy) is not None
    registry.begin_drain(owner)
    assert registry.status(owner)['active_claims'] == 0
    with replicas[0]() as db:
        assert db.get(ExecutionWorkerRecord, legacy.id).runtime_id == ''
        assert db.query(ExecutionJob).filter_by(status='running').count() == 1
    # This status is only known-incarnation claim evidence, never retirement proof.
