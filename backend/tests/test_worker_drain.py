"""Real DB lock races: a drain acknowledgment fences all later claims."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Event
from uuid import uuid4

import pytest

from app.models.database import ExecutionJob, ExecutionWorkerRecord
from app.services.durable_queue import DurableQueue, WorkerIdentity
from tests.test_durable_queue import replicas, add


def identity(pool='blue'):
    return WorkerIdentity(uuid4().hex, pool, 'a'*40, 'shared-sandbox')


def test_drain_before_registration_is_persistent_and_cannot_be_resurrected(replicas):
    a, b = [DurableQueue(factory) for factory in replicas]
    old, new = identity(), identity('green')
    assert a.worker_status(old) is None
    at = datetime(2030, 1, 1)
    a.begin_worker_drain(old, at=at)
    b.begin_worker_drain(old, at=at+timedelta(seconds=1))
    job = add(a)
    assert b.claim(worker=old) is None
    assert b.worker_status(old) == {'id':old.id, 'draining':True, 'active_claims':0}
    with replicas[0]() as db:
        assert db.get(ExecutionWorkerRecord,old.id).draining_at == at
        assert db.get(ExecutionJob,job).worker_id is None
    impostor = WorkerIdentity(old.id,'another-pool',old.deployment_sha,old.sandbox_pool_id)
    assert b.register_worker(old) is False
    for operation in (b.begin_worker_drain, b.worker_status, b.register_worker, lambda item:b.claim(worker=item)):
        with pytest.raises(ValueError, match='identity mismatch'):
            operation(impostor)
    assert b.claim(worker=new).id == job


def test_registration_waiting_for_common_lock_observes_stop_without_claim(replicas):
    a, b = [DurableQueue(factory) for factory in replicas]
    worker = identity()
    job = add(a)
    entered, stop = Event(), Event()
    original = b._lock
    def observed_lock(db):
        entered.set()
        original(db)
    b._lock = observed_lock
    with ThreadPoolExecutor(1) as executor:
        with replicas[0]() as db:
            a._lock(db)
            future = executor.submit(b.register_worker, worker, stop_requested=stop.is_set)
            assert entered.wait(3)
            stop.set()
            db.commit()
        assert future.result(timeout=5) is False
    assert a.worker_status(worker) == {'id': worker.id, 'draining': True, 'active_claims': 0}
    assert a.register_worker(worker) is False
    with replicas[0]() as db:
        record = db.get(ExecutionJob, job)
        assert record.status == 'queued' and record.attempts == 0 and record.worker_id is None


def test_prior_claim_finishes_but_backlog_goes_only_to_new_worker(replicas):
    a, b = [DurableQueue(factory,concurrency=1) for factory in replicas]
    old, new = identity(), identity('green')
    first, second = add(a), add(a,request='second')
    claim = a.claim(worker=old)
    assert claim.id == first
    a.begin_worker_drain(old)
    assert b.worker_status(old)['active_claims'] == 1
    assert a.claim(worker=old) is None
    assert b.claim(worker=new) is None  # Global budget is not split by pool.
    assert a.renew(first,claim.token)
    called = []
    assert a.start(first,claim.token,lambda:called.append('prior claim'))
    assert called == ['prior claim']
    assert a.finish(first,claim.token,{'verdict':'accepted'})
    assert b.worker_status(old)['active_claims'] == 0
    assert a.claim(worker=old) is None
    assert b.claim(worker=new).id == second
    with replicas[0]() as db:
        assert db.get(ExecutionJob,first).worker_id == old.id
        assert db.get(ExecutionJob,second).worker_id == new.id


def test_stop_received_while_claim_waits_for_lock_prevents_late_assignment(replicas):
    old, new = identity(), identity('green')
    a, b = [DurableQueue(factory) for factory in replicas]
    job = add(a)
    entered, stop = Event(), Event()
    original = b._lock
    def observed_lock(db):
        entered.set()
        original(db)
    b._lock = observed_lock
    with ThreadPoolExecutor(1) as executor:
        with replicas[0]() as db:
            a._lock(db)
            future = executor.submit(b.claim,worker=old,stop_requested=stop.is_set)
            assert entered.wait(3)
            stop.set()
            db.commit()
        assert future.result(timeout=5) is None
    assert a.worker_status(old)['draining'] is True
    assert a.claim(worker=old) is None  # Not merely the transient stop flag.
    assert a.claim(worker=new).id == job


def test_claim_that_owns_lock_before_drain_is_preserved(replicas):
    claimed, release, draining = Event(), Event(), Event()
    old = identity()
    def hold_claim(db, job):
        if job.status == 'running':
            claimed.set()
            assert release.wait(5)
    a = DurableQueue(replicas[0],on_transition=hold_claim)
    b = DurableQueue(replicas[1])
    job = add(a)
    def drain():
        draining.set()
        b.begin_worker_drain(old)
    with ThreadPoolExecutor(2) as executor:
        claim_future = executor.submit(a.claim,worker=old)
        try:
            assert claimed.wait(3)
            drain_future = executor.submit(drain)
            assert draining.wait(3)
            assert not drain_future.done()
        finally:
            release.set()
        claim = claim_future.result(timeout=5)
        drain_future.result(timeout=5)
    assert claim.id == job
    assert b.worker_status(old) == {'id':old.id, 'draining':True, 'active_claims':1}
    assert b.claim(worker=old) is None
    assert b.finish(job,claim.token,{'verdict':'accepted'})


def test_stop_during_expired_cleanup_does_not_take_a_new_claim(replicas):
    at = datetime(2030,1,1)
    old, new = identity(), identity('green')
    stop, reaped = Event(), []
    a = DurableQueue(replicas[0],lease_seconds=1)
    job = add(a,at=at)
    claim = a.claim(worker=old,at=at)
    a.begin_worker_drain(old,at=at)
    def reap(*args):
        reaped.append(args)
        stop.set()
    b = DurableQueue(replicas[1],lease_seconds=1,reap_expired=reap)
    assert b.claim(worker=new,at=at+timedelta(seconds=1),stop_requested=stop.is_set) is None
    assert reaped == [(job,claim.token)]
    assert b.worker_status(new)['draining'] is True
    assert b.worker_status(old)['active_claims'] == 0
    with replicas[0]() as db:
        record = db.get(ExecutionJob,job)
        assert record.status == 'queued' and record.attempts == 1
        assert record.lease_token is None
    assert b.claim(worker=new) is None
    recovered = b.claim(worker=identity('green'),at=at+timedelta(seconds=2))
    assert recovered.id == job and recovered.token != claim.token
    assert not a.finish(job,claim.token,{'verdict':'accepted'},at=at)


def test_unconfirmed_recovery_keeps_old_owner_and_capacity(replicas):
    at = datetime(2030,1,1)
    old, new = identity(), identity('green')
    a = DurableQueue(replicas[0],lease_seconds=1,concurrency=1)
    job = add(a,at=at)
    claim = a.claim(worker=old,at=at)
    a.begin_worker_drain(old)
    def unavailable(*args):
        raise RuntimeError('fixture Docker unavailable')
    b = DurableQueue(replicas[1],lease_seconds=1,reap_expired=unavailable)
    with pytest.raises(RuntimeError,match='fixture Docker unavailable'):
        b.claim(worker=new,at=at+timedelta(seconds=1))
    assert a.worker_status(old)['active_claims'] == 1
    with replicas[0]() as db:
        record = db.get(ExecutionJob,job)
        assert record.worker_id == old.id and record.lease_token == claim.token


def test_transition_failure_rolls_back_owner_registration_and_claim(replicas):
    old = identity()
    def fail(db,job):
        raise RuntimeError('fixture publication failure')
    queue = DurableQueue(replicas[0],on_transition=fail)
    job = add(queue)
    with pytest.raises(RuntimeError,match='fixture publication failure'):
        queue.claim(worker=old)
    assert queue.worker_status(old) is None
    with replicas[1]() as db:
        record = db.get(ExecutionJob,job)
        assert record.worker_id is None and record.lease_token is None and record.status == 'queued'
