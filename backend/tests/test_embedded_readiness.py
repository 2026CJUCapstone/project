"""Development embedded workers must publish and withdraw dependency health."""
import asyncio

import pytest

from app import main, worker


@pytest.mark.asyncio
@pytest.mark.parametrize('embedded', [True, False])
async def test_embedded_health_task_is_owned_and_awaited_by_lifespan(monkeypatch, embedded):
    events = []
    published = asyncio.Event()
    async def health(stop):
        events.append('published')
        published.set()
        try:
            await asyncio.Event().wait()
        finally:
            assert stop.is_set()
            events.append('health-stopped')
    async def pending():
        await asyncio.Event().wait()
    class FakeWorker:
        async def run(self):
            await pending()
    monkeypatch.setattr(main.settings, 'ENVIRONMENT', 'development')
    monkeypatch.setattr(main.settings, 'EMBEDDED_EXECUTION_WORKER', embedded)
    monkeypatch.setattr(main, 'build_worker', FakeWorker)
    monkeypatch.setattr(main, 'contest_maintenance', pending)
    monkeypatch.setattr(main, 'retention_maintenance', pending)
    monkeypatch.setattr(worker, 'health_loop', health)
    monkeypatch.setattr(worker, 'withdraw_worker', lambda:events.append('withdrawn'))
    async with main.lifespan(main.app):
        if embedded:
            await asyncio.wait_for(published.wait(), 1)
        else:
            await asyncio.sleep(0)
            assert events == []
    assert events == (['published', 'health-stopped', 'withdrawn'] if embedded else [])
