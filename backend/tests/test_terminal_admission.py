import asyncio
import json
from unittest.mock import AsyncMock
from types import SimpleNamespace

import pytest

from app.api.routes.terminal import _receive_start_payload, terminal_endpoint
from app.api.routes import terminal
from app.core.config import settings
from app.services.terminal_broker import TerminalUnavailable


@pytest.mark.asyncio
@pytest.mark.parametrize('origin', [None, 'null', 'https://untrusted.test', 'https://trusted.test.evil.test'])
async def test_untrusted_origin_is_rejected_before_accept_or_execution(monkeypatch, origin):
    monkeypatch.setattr(settings, 'CORS_ORIGINS', ['https://trusted.test'])
    ws = AsyncMock()
    ws.headers = {'origin': origin} if origin is not None else {}
    await terminal_endpoint(ws)
    ws.close.assert_awaited_once_with(code=1008)
    ws.accept.assert_not_awaited()
    ws.receive_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_start_deadline_closes_idle_socket_without_starting_sandbox(monkeypatch):
    monkeypatch.setattr(settings, 'CORS_ORIGINS', ['https://trusted.test'])
    monkeypatch.setattr(settings, 'TERMINAL_START_TIMEOUT', 0.01)
    ws = AsyncMock()
    ws.headers = {'origin': 'https://trusted.test'}
    ws.client = SimpleNamespace(host='192.0.2.1')

    class FakeBroker:
        def reserve(self, sid, ip):
            pass

        def close(self, sid):
            pass

    monkeypatch.setattr(terminal, 'TerminalBroker', FakeBroker)

    async def idle():
        await asyncio.Event().wait()

    ws.receive_text.side_effect = idle
    await terminal_endpoint(ws)
    ws.accept.assert_awaited_once()
    ws.close.assert_awaited_once()
    assert '대기 시간' in ws.send_text.call_args.args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', [
    [],
    {'type': 'start', 'code': '가'*4, 'language': 'python'},
    {'type': 'start', 'code': 'print(1)', 'language': 'python', 'token': 123},
    {'type': 'start', 'code': 'print(1)', 'language': 'python', 'token': 'x' * 2049},
])
async def test_invalid_shape_and_utf8_code_budget(monkeypatch, payload):
    monkeypatch.setattr(settings, 'SUBMISSION_CODE_MAX_BYTES', 10)
    ws = AsyncMock()
    ws.receive_text.return_value = json.dumps(payload, ensure_ascii=False)
    with pytest.raises(ValueError):
        await _receive_start_payload(ws)


@pytest.mark.asyncio
async def test_missing_redis_broker_rejects_before_websocket_accept(monkeypatch):
    monkeypatch.setattr(settings, 'CORS_ORIGINS', ['https://trusted.test'])

    def unavailable_broker():
        raise TerminalUnavailable()

    monkeypatch.setattr(terminal, 'TerminalBroker', unavailable_broker)
    ws = AsyncMock()
    ws.headers = {'origin': 'https://trusted.test'}
    ws.client = SimpleNamespace(host='192.0.2.1')

    await terminal_endpoint(ws)

    ws.close.assert_awaited_once_with(code=1013)
    ws.accept.assert_not_awaited()
