import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from app.services import execution_wakeup as wakeup


def test_hint_is_bounded_expiring_and_contains_no_job_data(monkeypatch):
    client = Mock()
    monkeypatch.setattr(wakeup, '_configured_client', lambda blocking: client)
    wakeup.notify_execution_work()
    client.eval.assert_called_once_with(wakeup._PUBLISH, 1, wakeup._key())
    assert "'LPUSH', KEYS[1], '1'" in wakeup._PUBLISH
    assert "'LTRIM', KEYS[1], 0, 0" in wakeup._PUBLISH
    assert "'EXPIRE', KEYS[1], 1" in wakeup._PUBLISH


def test_unavailable_hint_does_not_fail_accepted_submission(monkeypatch):
    monkeypatch.setattr(wakeup, '_configured_client', Mock(side_effect=OSError('offline')))
    wakeup.notify_execution_work()


@pytest.mark.asyncio
async def test_hint_wakes_without_sleep_and_without_executing_any_job(monkeypatch):
    client = Mock()
    client.blpop.return_value = (b'queue', b'1')
    sleep = AsyncMock()
    monkeypatch.setattr(wakeup, '_configured_client', lambda blocking: client)
    monkeypatch.setattr(wakeup.asyncio, 'sleep', sleep)
    await wakeup.wait_for_execution_work()
    client.blpop.assert_called_once_with(wakeup._key(), timeout=0.20)
    sleep.assert_not_awaited()


@pytest.mark.parametrize('mode', ['disabled', 'offline', 'empty'])
@pytest.mark.asyncio
async def test_missing_hint_retains_polling_cadence(monkeypatch, mode):
    client = Mock()
    client.blpop.return_value = None
    if mode == 'offline':
        client.blpop.side_effect = OSError('offline')
    monkeypatch.setattr(wakeup, '_configured_client', lambda blocking: None if mode == 'disabled' else client)
    monkeypatch.setattr(wakeup, 'time', Mock(monotonic=Mock(side_effect=[10.0, 10.05])))
    sleep = AsyncMock()
    monkeypatch.setattr(wakeup.asyncio, 'sleep', sleep)
    await wakeup.wait_for_execution_work()
    assert sleep.await_args.args[0] == pytest.approx(0.20)


@pytest.mark.asyncio
async def test_cancellation_propagates_without_fallback_sleep(monkeypatch):
    client = Mock()
    monkeypatch.setattr(wakeup, '_configured_client', lambda blocking: client)
    monkeypatch.setattr(wakeup.asyncio, 'to_thread', AsyncMock(side_effect=asyncio.CancelledError))
    sleep = AsyncMock()
    monkeypatch.setattr(wakeup.asyncio, 'sleep', sleep)
    with pytest.raises(asyncio.CancelledError):
        await wakeup.wait_for_execution_work()
    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_stalled_subscription_is_bounded(monkeypatch):
    monkeypatch.setattr(wakeup, '_configured_client', lambda blocking: Mock())
    entered = asyncio.Event()
    async def stalled(*args, **kwargs):
        entered.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(wakeup.asyncio, 'to_thread', stalled)
    await asyncio.wait_for(wakeup.wait_for_execution_work(), timeout=1)
    assert entered.is_set()
