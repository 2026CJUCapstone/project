from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import app
from app.services.execution_admission import admit_execution, execution_ip
from app.api.routes import terminal
from app.services import compiler as compiler_service


@pytest.fixture
def limits(monkeypatch):
    monkeypatch.setattr(settings, 'EXECUTION_IP_RATE_LIMIT', 2)
    monkeypatch.setattr(settings, 'EXECUTION_USER_RATE_LIMIT', 2)
    monkeypatch.setattr(settings, 'EXECUTION_GLOBAL_RATE_LIMIT', 100)


def peer(host):
    return SimpleNamespace(client=SimpleNamespace(host=host))


def test_accounts_cannot_bypass_ip_budget_and_ip_rotation_cannot_bypass_account(limits):
    admit_execution(peer('192.0.2.1'), user_id='one')
    admit_execution(peer('192.0.2.1'), user_id='two')
    with pytest.raises(HTTPException) as error:
        admit_execution(peer('192.0.2.1'), user_id='three')
    assert error.value.status_code == 429
    admit_execution(peer('192.0.2.2'), user_id='one')
    with pytest.raises(HTTPException) as error:
        admit_execution(peer('192.0.2.3'), user_id='one')
    assert error.value.status_code == 429


def test_ipv6_prefix_and_mapped_ipv4_have_stable_budgets():
    assert execution_ip(peer('2001:db8:1234:5678::1')) == execution_ip(peer('2001:db8:1234:5678::abcd'))
    assert execution_ip(peer('::ffff:192.0.2.1')) == '192.0.2.1'


@pytest.mark.asyncio
async def test_http_routes_and_websocket_share_admission_and_ignore_spoofed_forwarding(limits, monkeypatch):
    runner = AsyncMock(return_value={'stdout':'ok', 'stderr':'', 'exit_code':0, 'execution_time':0.1})
    monkeypatch.setattr(compiler_service.compiler_instance, 'run', runner)
    monkeypatch.setattr(settings, 'CORS_ORIGINS', ['https://trusted.test'])
    async with AsyncClient(transport=ASGITransport(app=app, client=('192.0.2.10', 1234)), base_url='http://isolated') as client:
        assert (await client.post('/api/v1/compiler/run', json={'code':'print(1)', 'language':'python'})).status_code == 202
        # A second accepted receipt exhausts the same IP budget without starting a sandbox.
        assert (await client.post('/api/v1/compiler/run', json={'code':'print(2)', 'language':'python'})).status_code == 202
        response = await client.post('/api/v1/compiler/compile', json={'code':'print(1)', 'language':'python'},
                                     headers={'X-Forwarded-For':'198.51.100.42', 'X-Real-IP':'198.51.100.43'})
        assert response.status_code == 429
    ws = AsyncMock()
    ws.client = peer('192.0.2.10').client
    ws.headers = {'origin':'https://trusted.test'}
    await terminal.terminal_endpoint(ws)
    ws.accept.assert_not_awaited()
    ws.close.assert_awaited_once_with(code=1013)
    runner.assert_not_awaited()


@pytest.mark.asyncio
async def test_code_and_stdin_utf8_limits_reject_before_queue(monkeypatch):
    monkeypatch.setattr(settings, 'SUBMISSION_CODE_MAX_BYTES', 8)
    monkeypatch.setattr(settings, 'EXECUTION_STDIN_MAX_BYTES', 8)
    runner = AsyncMock()
    monkeypatch.setattr(compiler_service.compiler_instance, 'run', runner)
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://isolated') as client:
        for data in ({'code':'가가가', 'language':'python'}, {'code':'ok','stdin':'가가가','language':'python'}):
            assert (await client.post('/api/v1/compiler/run', json=data)).status_code == 413
    runner.assert_not_awaited()


@pytest.mark.asyncio
async def test_redis_failure_rejects_http_and_ws_before_sandbox(monkeypatch):
    from app.core import rate_limit
    monkeypatch.setattr(settings, 'REDIS_URL', 'redis://unavailable.invalid')
    monkeypatch.setattr(rate_limit, 'get_redis', lambda: None)
    monkeypatch.setattr(settings, 'CORS_ORIGINS', ['https://trusted.test'])
    runner = AsyncMock()
    monkeypatch.setattr(compiler_service.compiler_instance, 'run', runner)
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://isolated') as client:
        assert (await client.post('/api/v1/compiler/run', json={'code':'print(1)','language':'python'})).status_code == 503
    ws = AsyncMock()
    ws.client = peer('192.0.2.10').client
    ws.headers = {'origin':'https://trusted.test'}
    await terminal.terminal_endpoint(ws)
    ws.accept.assert_not_awaited()
    ws.close.assert_awaited_once_with(code=1013)
    runner.assert_not_awaited()
