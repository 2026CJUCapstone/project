"""Opt-in against an explicitly supplied isolated Redis (never default settings)."""
import asyncio
import os
import uuid

import pytest

from app.services import execution_wakeup as wakeup


@pytest.mark.asyncio
async def test_real_redis_hint_cap_expiry_and_wakeup(monkeypatch):
    url = os.environ.get('WAKEUP_TEST_REDIS_URL')
    if not url:
        pytest.skip('WAKEUP_TEST_REDIS_URL must explicitly name an isolated Redis')
    monkeypatch.setattr(wakeup.settings, 'REDIS_URL', url)
    monkeypatch.setattr(wakeup.settings, 'REDIS_KEY_PREFIX', 'wakeup-test-' + uuid.uuid4().hex)
    client = wakeup._configured_client(False)
    key = wakeup._key()
    try:
        for _ in range(20):
            wakeup.notify_execution_work()
        assert client.lrange(key, 0, -1) == [b'1']
        assert 0 < client.pttl(key) <= 1000
        await asyncio.wait_for(wakeup.wait_for_execution_work(), timeout=1)
        assert client.llen(key) == 0
        task = asyncio.create_task(wakeup.wait_for_execution_work())
        await asyncio.sleep(0.025)
        wakeup.notify_execution_work()
        await asyncio.wait_for(task, timeout=1)
        assert client.llen(key) == 0
        wakeup.notify_execution_work()
        await asyncio.sleep(1.1)
        assert not client.exists(key)
    finally:
        client.delete(key)  # Only the unique key this test owns.
