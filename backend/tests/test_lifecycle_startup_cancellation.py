"""Cancellation must settle the acquisition thread before releasing its owner."""
import asyncio
from contextlib import asynccontextmanager
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app import main, worker
from app.core.config import settings
from app.models.database import ApiProcessRecord, WorkerProcessRecord
from app.services import api_lifecycle, runtime_health, runtime_registry, worker_lifecycle
from app.services.api_lifecycle import RuntimeRequests
from app.services.runtime_registry import RuntimeRegistry
from app.services.worker_lifecycle import WorkerLifecycle
from app.services.worker_process import ProcessIdentity
from tests.test_durable_queue import replicas
from tests.test_runtime_registry import runtime


@pytest.mark.asyncio
@pytest.mark.parametrize('entrypoint', ['dedicated', 'embedded'])
@pytest.mark.parametrize('phase', ['start', 'register'])
@pytest.mark.parametrize('repeated_cancel', [False, True])
async def test_cancelled_worker_startup_cannot_leave_marker_or_late_open_row(
        replicas, monkeypatch, entrypoint, phase, repeated_cancel):
    owner = runtime()
    assert RuntimeRegistry(replicas[0]).register(owner)
    identity = ProcessIdentity(uuid4().hex, 123, 'test:123', 'fixture', 'a'*64)
    lifecycle = WorkerLifecycle(replicas[1], owner, identity)
    blocked, release, cleaned = Event(), Event(), Event()
    held, entered = [], []
    def start():
        held.append(identity)
        if phase == 'start':
            blocked.set()
            assert release.wait(8)
        return identity
    register = lifecycle.register
    def delayed_register():
        result = register()
        if phase == 'register':
            blocked.set()
            assert release.wait(8)
        return result
    def stop(*, expected):
        assert expected == identity and held == [identity]
        held.clear()
        cleaned.set()
    @asynccontextmanager
    async def no_api():
        yield None
    monkeypatch.setattr(lifecycle, 'register', delayed_register)
    monkeypatch.setattr(worker_lifecycle, 'configured_worker_lifecycle', lambda _:lifecycle)
    monkeypatch.setattr(worker, 'start_worker_process', start)
    monkeypatch.setattr(worker, 'stop_worker_process', stop)
    monkeypatch.setattr(worker, 'validate_runtime_security', lambda:None)
    monkeypatch.setattr(worker, 'register_configured_runtime', lambda:None)
    monkeypatch.setattr(runtime_registry, 'register_configured_runtime', lambda:None)
    monkeypatch.setattr(settings, 'ENVIRONMENT', 'development')
    monkeypatch.setattr(settings, 'EMBEDDED_EXECUTION_WORKER', True)
    monkeypatch.setattr(api_lifecycle, 'owned_api_lifecycle', no_api)
    async def must_not_serve(*args, **kwargs):
        entered.append(True)
    monkeypatch.setattr(worker, 'serve_registered', must_not_serve)
    async def run():
        if entrypoint == 'dedicated':
            await worker.serve()
        else:
            async with main.lifespan(main.app):
                entered.append(True)
    task = asyncio.create_task(run())
    try:
        assert await asyncio.to_thread(blocked.wait, 5)
        task.cancel()
        await asyncio.sleep(0)
        assert not cleaned.is_set()  # The acquisition thread still owns startup.
        if repeated_cancel:
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()  # Even repeated cancellation must await acquisition.
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await asyncio.to_thread(cleaned.wait, 5)
    assert held == [] and entered == []
    with replicas[0]() as db:
        row = db.get(WorkerProcessRecord, identity.epoch)
        assert row.draining_at is not None and row.stopped_at is not None


@pytest.mark.asyncio
async def test_api_registration_finishes_before_cancelled_lifespan_cleanup(replicas, monkeypatch):
    owner = runtime()
    assert RuntimeRegistry(replicas[0]).register(owner)
    identity = ProcessIdentity(uuid4().hex, 123, 'test:123', 'fixture-api', 'b'*64)
    service = RuntimeRequests(replicas[1], owner, identity)
    blocked, release = Event(), Event()
    register = service.register
    def delayed():
        result = register()
        blocked.set()
        assert release.wait(8)
        return result
    monkeypatch.setattr(service, 'register', delayed)
    monkeypatch.setattr(RuntimeRequests, 'configured', classmethod(lambda cls:service))
    monkeypatch.setattr(settings, 'RUNTIME_INSTANCE_ID', owner.id)
    monkeypatch.setattr(settings, 'EMBEDDED_EXECUTION_WORKER', False)
    monkeypatch.setattr(runtime_registry, 'register_configured_runtime', lambda:None)
    async def run():
        async with main.lifespan(main.app):
            pytest.fail('Cancelled API startup reached serving state')
    task = asyncio.create_task(run())
    try:
        assert await asyncio.to_thread(blocked.wait, 5)
        task.cancel()
        await asyncio.sleep(0)
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    with replicas[0]() as db:
        assert db.get(ApiProcessRecord, identity.epoch).stopped_at is not None


def test_late_process_cleanup_cannot_close_a_replacement_owner(monkeypatch):
    old = ProcessIdentity(uuid4().hex, 123, 'test:123', 'fixture', 'a'*64)
    current = ProcessIdentity(uuid4().hex, 124, 'test:124', 'fixture', 'a'*64)
    closed, withdrawn = [], []
    state = SimpleNamespace(identity=current, close=lambda:closed.append(current))
    monkeypatch.setattr(runtime_health, '_process_state', state)
    monkeypatch.setattr(runtime_health, '_withdraw', lambda identity, **kwargs:withdrawn.append(identity))
    assert runtime_health.stop_worker_process(expected=old) is False
    assert runtime_health._process_state is state and closed == [] and withdrawn == []
    runtime_health.stop_worker_process(expected=current)
    assert runtime_health._process_state is None and closed == [current] and withdrawn == [current]


@pytest.mark.asyncio
async def test_failed_registration_unwinds_partial_worker_acquisition(replicas, monkeypatch):
    owner = runtime()
    assert RuntimeRegistry(replicas[0]).register(owner)
    process = ProcessIdentity(uuid4().hex, 123, 'test:123', 'fixture', 'a'*64)
    lifecycle = WorkerLifecycle(replicas[1], owner, process)
    register = lifecycle.register
    stopped = []
    def failed():
        assert register()
        raise RuntimeError('fixture registration result lost')
    monkeypatch.setattr(lifecycle, 'register', failed)
    monkeypatch.setattr(worker_lifecycle, 'configured_worker_lifecycle', lambda _:lifecycle)
    with pytest.raises(RuntimeError, match='fixture registration result lost'):
        async with worker_lifecycle.owned_worker_lifecycle(lambda:process,
                lambda **kwargs:stopped.append(kwargs['expected'])):
            pytest.fail('Failed acquisition reached body')
    assert stopped == [process]
    with replicas[0]() as db:
        assert db.get(WorkerProcessRecord, process.epoch).stopped_at is not None
