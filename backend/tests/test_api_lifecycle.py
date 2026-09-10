"""Independent DB connections order API admission, completion and runtime drain."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime
from threading import Barrier, Event
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.models.database import ActiveApiRequest, ApiProcessRecord
from app.services import api_lifecycle, runtime_registry
from app.services.api_lifecycle import RuntimeRequests
from app.services.runtime_registry import RuntimeRegistry
from app.services.worker_process import ProcessIdentity
from tests.test_durable_queue import replicas
from tests.test_runtime_registry import runtime


def services(replicas, capacity=2):
    owner = runtime()
    registry = RuntimeRegistry(replicas[0])
    assert registry.register(owner)
    requests = [RuntimeRequests(factory, owner,
        ProcessIdentity(uuid4().hex, 123, 'test:123', 'api-host', 'a'*64), capacity=capacity)
        for factory in replicas]
    for service in requests:
        assert service.register()
    return owner, registry, requests


def test_shared_capacity_and_owner_only_idempotent_completion(replicas):
    owner, registry, (a, b) = services(replicas)
    http = a.begin('http')
    ws = b.begin('websocket')
    assert http and ws and http != ws
    assert a.begin('http') is None and b.begin('websocket') is None
    assert not b.finish(http)
    assert registry.status(owner)['active_http'] == 1
    assert registry.status(owner)['active_websockets'] == 1
    registry.begin_drain(owner)
    assert a.begin('http') is None and b.begin('websocket') is None
    assert not a.stop() and not b.stop()
    assert a.finish(http) and not a.finish(http)
    assert b.finish(ws)
    assert a.stop() and b.stop()
    assert registry.status(owner)['active_http'] == 0
    assert registry.status(owner)['active_websockets'] == 0
    # A new process cannot reopen the same drained runtime.
    restarted = RuntimeRequests(replicas[1], owner, replace(a.process, epoch=uuid4().hex))
    assert not restarted.register() and restarted.begin('http') is None
    other = runtime()
    assert registry.register(other)
    green = RuntimeRequests(replicas[1], other, replace(b.process, epoch=uuid4().hex))
    assert green.register() and green.begin('http')


def test_concurrent_replicas_cannot_overbook_last_slot(replicas):
    owner, registry, (a, b) = services(replicas, capacity=1)
    barrier = Barrier(2)
    def enter(service):
        barrier.wait(timeout=5)
        return service.begin('http')
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(enter, [a, b]))
    assert sum(item is not None for item in results) == 1
    assert registry.status(owner)['active_http'] == 1
    winner = a if results[0] else b
    assert winner.finish(next(item for item in results if item))
    assert b.begin('websocket')


@pytest.mark.parametrize('drain_first', [False, True])
def test_database_lock_orders_admission_and_drain(replicas, monkeypatch, drain_first):
    owner, registry, (a, _) = services(replicas)
    locked, release, waiting = Event(), Event(), Event()
    original = runtime_registry.execution_lock
    def hold(db):
        original(db)
        locked.set()
        assert release.wait(10)
    def observe(db):
        waiting.set()
        original(db)
    monkeypatch.setattr(runtime_registry, 'execution_lock', hold if drain_first else observe)
    monkeypatch.setattr(api_lifecycle, 'execution_lock', observe if drain_first else hold)
    first = (lambda:registry.begin_drain(owner)) if drain_first else (lambda:a.begin('http'))
    second = (lambda:a.begin('http')) if drain_first else (lambda:registry.begin_drain(owner))
    with ThreadPoolExecutor(2) as pool:
        first_future = pool.submit(first)
        try:
            assert locked.wait(5)
            second_future = pool.submit(second)
            assert waiting.wait(5)
            assert not second_future.done()
        finally:
            release.set()
        first_result = first_future.result(timeout=10)
        second_result = second_future.result(timeout=10)
    admission = second_result if drain_first else first_result
    assert (admission is None) == drain_first
    assert registry.status(owner)['draining'] is True
    assert registry.status(owner)['active_http'] == (0 if drain_first else 1)
    if admission:
        assert a.finish(admission)


def test_old_unresolved_requests_do_not_expire_or_become_new_process_property(replicas):
    owner, registry, (a, b) = services(replicas, capacity=1)
    request_id = a.begin('websocket', at=datetime(2000, 1, 1))
    assert not a.stop(at=datetime(2099, 1, 1))
    assert not b.finish(request_id)
    assert b.begin('http') is None
    with replicas[1]() as db:
        assert db.get(ActiveApiRequest, request_id).process_id == a.process.epoch
        assert db.get(ApiProcessRecord, a.process.epoch).stopped_at is None
    assert registry.status(owner)['active_websockets'] == 1


def test_stopped_epoch_cannot_resurrect_and_identity_cannot_be_reassigned(replicas):
    owner, registry, (a, b) = services(replicas)
    for bad_process in (replace(a.process, pid=124), replace(a.process, start_token='test:124'),
                        replace(a.process, scope='b'*64), replace(a.process, hostname='other-api')):
        impostor = RuntimeRequests(replicas[1], owner, bad_process)
        for operation in (impostor.register, lambda:impostor.begin('http'), impostor.stop):
            with pytest.raises(ValueError, match='identity mismatch'):
                operation()
    at = datetime(2030, 1, 1)
    assert a.stop(at=at) and a.stop(at=datetime(2031, 1, 1))
    assert not a.register() and a.begin('http') is None
    assert b.begin('http')
    with replicas[1]() as db:
        assert db.get(ApiProcessRecord, a.process.epoch).stopped_at == at


def test_unknown_registration_and_commit_failure_do_not_publish_requests(replicas):
    owner, registry, (a, _) = services(replicas)
    unknown = RuntimeRequests(replicas[1], runtime(), replace(a.process, epoch=uuid4().hex))
    assert not unknown.register() and unknown.begin('http') is None and not unknown.stop()
    def fail_commit(db):
        raise RuntimeError('fixture commit failure')
    event.listen(replicas[0], 'before_commit', fail_commit)
    try:
        with pytest.raises(RuntimeError, match='fixture commit failure'):
            a.begin('http')
    finally:
        event.remove(replicas[0], 'before_commit', fail_commit)
    assert registry.status(owner)['active_http'] == 0
    with replicas[1]() as db:
        assert db.query(ActiveApiRequest).count() == 0


@pytest.mark.parametrize('field,value', [('pool_id','other-pool'),('deployment_sha','b'*40),
    ('sandbox_pool_id','other-sandbox')])
def test_wrong_runtime_metadata_cannot_finish_request_or_stop_api(replicas, field, value):
    owner, registry, (a, _) = services(replicas)
    request_id = a.begin('http')
    impostor = RuntimeRequests(replicas[1], replace(owner, **{field:value}), a.process)
    for operation in (lambda:impostor.finish(request_id), impostor.stop):
        with pytest.raises(ValueError, match='identity mismatch'):
            operation()
    assert registry.status(owner)['active_http'] == 1
    assert a.finish(request_id)
