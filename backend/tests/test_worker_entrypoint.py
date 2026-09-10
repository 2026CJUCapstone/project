import asyncio

import pytest

from app import worker
from app.core.config import settings


@pytest.mark.asyncio
async def test_health_probe_closes_docker_client_and_publishes_only_after_dependencies(monkeypatch):
    import docker
    from types import SimpleNamespace
    calls = []
    stop = asyncio.Event()
    # DockerClient is not a context manager; model its actual close() contract.
    client = SimpleNamespace(ping=lambda:calls.append('ping'),
        images=SimpleNamespace(get=lambda image:calls.append(('image',image))),
        close=lambda:calls.append('close'))
    monkeypatch.setattr(docker, 'from_env', lambda **kwargs:client)
    monkeypatch.setattr(worker, 'dependencies_ready', lambda **kwargs:True)
    monkeypatch.setattr(worker, 'ensure_worker_process_registered', lambda:None)
    def report():
        calls.append('ready')
        stop.set()
    monkeypatch.setattr(worker, 'report_worker_ready', report)
    await asyncio.wait_for(worker.health_loop(stop),timeout=2)
    assert calls == ['ping',('image',settings.SANDBOX_IMAGE),'close','ready']


def patch_worker_runtime(monkeypatch, fake_worker, contest_maintenance, retention_maintenance):
    security_calls = []
    if not hasattr(fake_worker, 'begin_drain'):
        fake_worker.begin_drain = lambda: None
    monkeypatch.setattr(worker, "validate_runtime_security", lambda: security_calls.append(True))
    monkeypatch.setattr(worker, "build_worker", lambda: fake_worker)
    monkeypatch.setattr(worker, "contest_maintenance", contest_maintenance)
    monkeypatch.setattr(worker, "retention_maintenance", retention_maintenance)
    monkeypatch.setattr(settings, "COMPILER_QUEUE_CONCURRENCY", 1)
    return security_calls


async def wait_until_cancelled(cleaned):
    try:
        await asyncio.Event().wait()
    finally:
        cleaned.set()


@pytest.mark.asyncio
async def test_serve_returns_without_hanging_when_external_stop_is_already_set(monkeypatch):
    worker_cleaned = asyncio.Event()
    contest_cleaned = asyncio.Event()
    retention_cleaned = asyncio.Event()

    class FakeWorker:
        async def run(self, stop):
            try:
                assert stop.is_set()
            finally:
                worker_cleaned.set()

    security_calls = patch_worker_runtime(
        monkeypatch,
        FakeWorker(),
        lambda: wait_until_cancelled(contest_cleaned),
        lambda: wait_until_cancelled(retention_cleaned),
    )
    stop = asyncio.Event()
    stop.set()

    await asyncio.wait_for(worker.serve(stop), timeout=1)

    assert security_calls == [True]
    assert worker_cleaned.is_set()
    assert contest_cleaned.is_set()
    assert retention_cleaned.is_set()


@pytest.mark.asyncio
async def test_serve_drains_running_worker_before_exiting_after_stop(monkeypatch):
    from threading import Event
    fenced = Event()
    revoked = Event()
    started = asyncio.Event()
    release = asyncio.Event()
    worker_cleaned = asyncio.Event()
    contest_cleaned = asyncio.Event()
    retention_cleaned = asyncio.Event()

    class FakeWorker:
        def begin_drain(self):
            fenced.set()

        async def run(self, stop):
            started.set()
            try:
                await release.wait()
            finally:
                worker_cleaned.set()

    patch_worker_runtime(
        monkeypatch,
        FakeWorker(),
        lambda: wait_until_cancelled(contest_cleaned),
        lambda: wait_until_cancelled(retention_cleaned),
    )
    stop = asyncio.Event()
    monkeypatch.setattr(worker,'revoke_worker_readiness',revoked.set)
    task = asyncio.create_task(worker.serve(stop))
    await started.wait()

    stop.set()
    assert await asyncio.to_thread(fenced.wait,1)
    assert await asyncio.to_thread(revoked.wait,1)
    assert not task.done()
    release.set()
    await asyncio.wait_for(task, timeout=1)

    assert worker_cleaned.is_set()
    assert contest_cleaned.is_set()
    assert retention_cleaned.is_set()


@pytest.mark.asyncio
async def test_serve_cancels_and_awaits_all_tasks_when_outer_task_is_cancelled(monkeypatch):
    started = asyncio.Event()
    worker_cleaned = asyncio.Event()
    contest_cleaned = asyncio.Event()
    retention_cleaned = asyncio.Event()

    class FakeWorker:
        async def run(self, stop):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                worker_cleaned.set()

    patch_worker_runtime(
        monkeypatch,
        FakeWorker(),
        lambda: wait_until_cancelled(contest_cleaned),
        lambda: wait_until_cancelled(retention_cleaned),
    )
    task = asyncio.create_task(worker.serve(asyncio.Event()))
    await started.wait()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert worker_cleaned.is_set()
    assert contest_cleaned.is_set()
    assert retention_cleaned.is_set()
