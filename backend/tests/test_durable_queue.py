from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier
import os
import uuid

import pytest
from sqlalchemy import create_engine, text, event
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.services.durable_queue import DurableQueue, IdempotencyConflict, QueueFull


@pytest.fixture(params=['sqlite', 'postgres'])
def replicas(tmp_path, request):
    control = None
    schema = None
    if request.param == 'postgres':
        url = os.getenv('TEST_POSTGRES_URL')
        if not url:
            pytest.skip('Explicit isolated PostgreSQL test URL required')
        schema = f'audit_queue_{uuid.uuid4().hex}'
        control = create_engine(url)
        with control.begin() as db:
            db.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection_args = {'options': f'-csearch_path={schema}'}
    else:
        url = f"sqlite:///{(tmp_path / 'durable.db').as_posix()}"
        connection_args = {"check_same_thread": False, "timeout": 10}
    engines = [create_engine(url, connect_args=connection_args) for _ in range(2)]
    if request.param == 'sqlite':
        for engine in engines:
            @event.listens_for(engine, 'connect')
            def enforce_foreign_keys(connection, _record):
                connection.execute('PRAGMA foreign_keys=ON')
    Base.metadata.create_all(engines[0])
    factories = [sessionmaker(bind=engine, autoflush=False) for engine in engines]
    yield factories
    for engine in engines:
        engine.dispose()
    if control is not None:
        # Remove only this fixture's generated schema, never a shared/public one.
        assert schema.startswith('audit_queue_') and len(schema) == 44
        with control.begin() as db:
            db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        control.dispose()


def add(queue, request='r1', owner='owner', at=None):
    return queue.enqueue(owner_key=owner, request_id=request, kind='run', payload={'code': 'print(1)'}, at=at)


def test_restart_reads_durable_payload_without_request_closure(replicas):
    producer, restarted = [DurableQueue(factory) for factory in replicas]
    job_id = add(producer)
    claim = restarted.claim()
    assert claim.id == job_id
    assert claim.payload == {'code': 'print(1)'}
    assert restarted.finish(job_id, claim.token, {'stdout': '1'})
    assert producer.read(job_id, owner_key='owner')['result'] == {'stdout': '1'}
    assert producer.read(job_id, owner_key='stranger') is None
    assert 'payload' not in producer.read(job_id, owner_key='owner')


def test_expired_interactive_execution_is_reaped_but_never_replayed(replicas):
    events = []
    queue = DurableQueue(replicas[0],lease_seconds=1,reap_expired=lambda *args:events.append(args))
    job_id = queue.enqueue(owner_key='terminal',request_id='session',kind='terminal',payload={'code':'input()'})
    at = datetime(2030,1,1)
    claim = queue.claim(at=at)
    assert queue.claim(at=at+timedelta(seconds=1)) is None
    result = queue.read(job_id,owner_key='terminal')
    assert events == [(job_id,claim.token)]
    assert result['status'] == 'failed' and result['result']['verdict'] == 'canceled'
    assert not queue.finish(job_id,claim.token,{'verdict':'finished'},at=at)


def test_interactive_system_failure_is_not_automatically_retried(replicas):
    queue = DurableQueue(replicas[0])
    job_id = queue.enqueue(owner_key='terminal',request_id='session',kind='terminal',payload={'code':'input()'})
    claim = queue.claim()
    assert queue.finish(job_id,claim.token,{'verdict':'system_error'})
    assert queue.claim() is None
    assert queue.read(job_id,owner_key='terminal')['status'] == 'completed'


def test_concurrent_idempotency_single_job_and_content_conflict(replicas):
    queues = [DurableQueue(factory) for factory in replicas]
    barrier = Barrier(2)

    def send(queue):
        barrier.wait()
        return add(queue)

    with ThreadPoolExecutor(2) as pool:
        ids = list(pool.map(send, queues))
    assert ids[0] == ids[1]
    with pytest.raises(IdempotencyConflict):
        queues[0].enqueue(owner_key='owner', request_id='r1', kind='run', payload={'code': 'print(2)'})
    assert queues[0].claim().id == ids[0]
    assert queues[1].claim() is None


@pytest.mark.parametrize('owners,capacity,per_owner,expected', [
    (['a']*8, 10, 2, 2),
    ([str(i) for i in range(8)], 3, 4, 3),
])
def test_admission_caps_are_atomic_across_replicas(replicas, owners, capacity, per_owner, expected):
    queues = [DurableQueue(factory, capacity=capacity, per_owner=per_owner) for factory in replicas]
    barrier = Barrier(8)

    def send(index):
        barrier.wait()
        try:
            return add(queues[index % 2], request=str(index), owner=owners[index])
        except QueueFull:
            return None

    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(send, range(8)))
    assert len([result for result in results if result]) == expected


def test_global_claim_budget_not_multiplied_by_worker_count(replicas):
    queues = [DurableQueue(factory, concurrency=2, per_owner=10) for factory in replicas]
    for index in range(6):
        add(queues[0], request=str(index))
    barrier = Barrier(6)

    def claim(index):
        barrier.wait()
        return queues[index % 2].claim()

    with ThreadPoolExecutor(6) as pool:
        claims = [item for item in pool.map(claim, range(6)) if item]
    assert len(claims) == 2
    assert len({claim.id for claim in claims}) == 2


def test_lease_boundary_and_stale_worker_fencing(replicas):
    queues = [DurableQueue(factory, concurrency=1, lease_seconds=10, reap_expired=lambda *args: None) for factory in replicas]
    start = datetime(2030, 1, 1)
    job_id = add(queues[0], at=start)
    first = queues[0].claim(at=start)
    boundary = start + timedelta(seconds=10)
    assert not queues[0].renew(job_id, first.token, at=boundary)
    assert not queues[0].finish(job_id, first.token, {'stale': True}, at=boundary)
    recovered = queues[1].claim(at=boundary)
    assert recovered.id == first.id and recovered.token != first.token
    assert recovered.attempts == 2
    assert not queues[0].finish(job_id, first.token, {'stale': True}, at=boundary)
    assert queues[1].finish(job_id, recovered.token, {'accepted': True}, at=boundary)
    assert not queues[1].finish(job_id, recovered.token, {'duplicate': True}, at=boundary)
    assert queues[0].read(job_id, owner_key='owner')['result'] == {'accepted': True}


def test_expired_attempt_limit_does_not_block_next_job(replicas):
    queue = DurableQueue(replicas[0], concurrency=1, lease_seconds=10, max_attempts=1, reap_expired=lambda *args: None)
    start = datetime(2030, 1, 1)
    old = add(queue, at=start)
    next_id = add(queue, request='next', at=start+timedelta(seconds=1))
    assert queue.claim(at=start).id == old
    assert queue.claim(at=start+timedelta(seconds=10)).id == next_id
    assert queue.read(old, owner_key='owner')['status'] == 'failed'


def test_renewed_lease_prevents_second_claim(replicas):
    queues = [DurableQueue(factory, concurrency=1, lease_seconds=10) for factory in replicas]
    start = datetime(2030, 1, 1)
    job_id = add(queues[0], at=start)
    claim = queues[0].claim(at=start)
    assert queues[0].renew(job_id, claim.token, at=start+timedelta(seconds=9))
    assert queues[1].claim(at=start+timedelta(seconds=10)) is None


def test_expiry_does_not_free_capacity_without_confirmed_sandbox_cleanup(replicas):
    queue = DurableQueue(replicas[0], concurrency=1, lease_seconds=10)
    at = datetime(2030, 1, 1)
    old = add(queue, at=at)
    claim = queue.claim(at=at)
    add(queue, request='next', at=at+timedelta(seconds=1))
    assert queue.claim(at=at+timedelta(seconds=11)) is None
    assert queue.read(old, owner_key='owner')['status'] == 'running'
    calls = []
    def failed_cleanup(*args):
        calls.append(args)
        raise RuntimeError('Docker unreachable')
    queue.reap_expired = failed_cleanup
    with pytest.raises(RuntimeError, match='Docker unreachable'):
        queue.claim(at=at+timedelta(seconds=11))
    assert calls == [(old, claim.token)]
    assert queue.read(old, owner_key='owner')['status'] == 'running'


def test_old_worker_cannot_start_after_recovery_or_exact_expiry(replicas):
    at = datetime(2030, 1, 1)
    reaped = []
    queue = DurableQueue(replicas[0], concurrency=1, lease_seconds=10, reap_expired=lambda *args: reaped.append(args))
    job_id = add(queue, at=at)
    first = queue.claim(at=at)
    started = []
    assert queue.start(job_id, first.token, lambda: started.append('first'), at=at)
    boundary = at+timedelta(seconds=10)
    assert not queue.start(job_id, first.token, lambda: started.append('expired'), at=boundary)
    second = queue.claim(at=boundary)
    assert reaped == [(job_id, first.token)]
    assert not queue.start(job_id, first.token, lambda: started.append('stale'), at=boundary)
    assert queue.start(job_id, second.token, lambda: started.append('second'), at=boundary)
    assert started == ['first','second']


def test_receipt_and_queue_payload_rollback_together(replicas):
    from app.models.database import ExecutionJob, ExecutionQueueLock
    queue = DurableQueue(replicas[0])
    with replicas[0]() as db:
        job = queue.enqueue_in_session(db, owner_key='owner', request_id='atomic', kind='run', payload={'code':'receipt'})
        job_id = job.id
        db.add(ExecutionQueueLock(id='receipt-marker', revision=1))
        db.rollback()
    with replicas[1]() as db:
        assert db.get(ExecutionJob, job_id) is None
        assert db.get(ExecutionQueueLock, 'receipt-marker') is None


def test_result_and_award_commit_atomically_and_only_once(replicas):
    from app.models.database import ExecutionQueueLock
    def award(db, job_id, result):
        db.add(ExecutionQueueLock(id='award-marker', revision=1))
        db.flush()
        raise RuntimeError('Finalization interrupted')
    queue = DurableQueue(replicas[0], on_terminal=award)
    job_id = add(queue)
    claim = queue.claim()
    with pytest.raises(RuntimeError, match='Finalization interrupted'):
        queue.finish(job_id, claim.token, {'accepted':True})
    assert queue.read(job_id, owner_key='owner')['status'] == 'running'
    with replicas[1]() as db:
        assert db.get(ExecutionQueueLock, 'award-marker') is None
    queue.on_terminal = lambda db, *_: db.add(ExecutionQueueLock(id='award-marker', revision=1))
    assert queue.finish(job_id, claim.token, {'accepted':True})
    assert not queue.finish(job_id, claim.token, {'accepted':True})
    with replicas[1]() as db:
        assert db.get(ExecutionQueueLock, 'award-marker').revision == 1
