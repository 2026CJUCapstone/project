"""Real middleware ordering must not turn accounting into an admin mutation."""
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import app
from app.models.database import AdminAuditEvent
from app.services.api_lifecycle import RuntimeRequests
from app.services.runtime_registry import RuntimeRegistry
from app.services.worker_process import ProcessIdentity
from tests.test_admin_audit_api import audit_env, auth_headers
from tests.test_runtime_registry import runtime


@pytest.fixture
def managed_api(audit_env, monkeypatch):
    owner = runtime()
    registry = RuntimeRegistry(audit_env.factory)
    assert registry.register(owner)
    service = RuntimeRequests(audit_env.factory, owner,
        ProcessIdentity(uuid4().hex, 123, 'test:123', 'api-host', 'a'*64))
    assert service.register()
    monkeypatch.setattr(settings, 'RUNTIME_INSTANCE_ID', owner.id)
    monkeypatch.setattr(app.state, 'runtime_requests', service, raising=False)
    return owner, registry


@pytest.mark.asyncio
@pytest.mark.parametrize('missing', [False, True])
async def test_managed_admin_request_does_not_audit_lifecycle_commits(audit_env, managed_api, missing):
    target = 'missing-user' if missing else audit_env.target.id
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        response = await client.patch('/api/v1/admin/users/'+target,
            headers=auth_headers(audit_env.admin), json={'nickname':'updated'})
    assert response.status_code == (404 if missing else 200)
    with audit_env.factory() as db:
        assert db.query(AdminAuditEvent).count() == (0 if missing else 1)
    owner, registry = managed_api
    assert registry.status(owner)['active_http'] == 0


@pytest.mark.asyncio
async def test_cors_preflight_is_admitted_and_drained_with_safe_cors_headers(audit_env, managed_api):
    owner, registry = managed_api
    origin = settings.CORS_ORIGINS[0]
    headers = {'Origin':origin, 'Access-Control-Request-Method':'PATCH'}
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        response = await client.options('/api/v1/admin/users/target', headers=headers)
        assert response.status_code == 200
        registry.begin_drain(owner)
        response = await client.options('/api/v1/admin/users/target', headers=headers)
        assert response.status_code == 503
        assert response.headers['access-control-allow-origin'] == origin
        assert response.headers['cache-control'] == 'no-store'
        response = await client.get('/api/v1/problems', headers={'Origin':origin})
        assert response.status_code == 503 and response.headers['access-control-allow-origin'] == origin
