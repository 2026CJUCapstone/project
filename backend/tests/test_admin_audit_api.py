import json
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_db
from app.main import app
from app.models.database import AdminAuditEvent, User
from app.services.auth import create_access_token


@pytest.fixture
def audit_env(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'admin-audit.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = factory()
    admin = User(id='admin-actor', username='audit_admin', hashed_password='unused', role='admin')
    regular_user = User(id='regular-actor', username='audit_user', hashed_password='unused', role='user')
    target = User(id='target-user', username='audit_target', hashed_password='unused', role='user')
    db.add_all([admin, regular_user, target])
    db.commit()
    db.close()

    def override_get_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield SimpleNamespace(factory=factory, admin=admin, regular_user=regular_user, target=target)
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def auth_headers(user):
    token = create_access_token({'sub': user.username, 'ver': user.auth_version})
    return {'Authorization': f'Bearer {token}'}


async def patch_target(client, env, headers):
    return await client.patch(
        f'/api/v1/admin/users/{env.target.id}?accessToken=query-secret',
        headers=headers,
        json={
            'email': 'private@example.com',
            'nickname': 'Updated target',
            'avatarUrl': 'https://example.test/avatar?token=body-secret',
        },
    )


@pytest.mark.asyncio
async def test_admin_patch_records_only_actor_and_route_metadata(audit_env):
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        response = await patch_target(client, audit_env, auth_headers(audit_env.admin))

    assert response.status_code == 200
    db = audit_env.factory()
    try:
        events = db.query(AdminAuditEvent).all()
        assert len(events) == 1
        event = events[0]
        assert event.actor_id == audit_env.admin.id
        assert event.action == f'PATCH /api/v1/admin/users/{audit_env.target.id}'
        persisted_event = json.dumps(
            {column.name: getattr(event, column.name) for column in AdminAuditEvent.__table__.columns},
            default=str,
        )
        for secret in ('private@example.com', 'body-secret', 'query-secret', 'Bearer'):
            assert secret not in persisted_event
    finally:
        db.close()


@pytest.mark.asyncio
async def test_admin_get_does_not_create_an_audit_event(audit_env):
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        response = await client.get('/api/v1/admin/users?search=read-only', headers=auth_headers(audit_env.admin))

    assert response.status_code == 200
    db = audit_env.factory()
    try:
        assert db.query(AdminAuditEvent).count() == 0
    finally:
        db.close()


@pytest.mark.asyncio
async def test_regular_user_patch_is_forbidden_without_data_or_audit_changes(audit_env):
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        response = await patch_target(client, audit_env, auth_headers(audit_env.regular_user))

    assert response.status_code == 403
    db = audit_env.factory()
    try:
        target = db.get(User, audit_env.target.id)
        assert target.email is None
        assert target.nickname is None
        assert target.avatar_url is None
        assert target.role == 'user'
        assert db.query(AdminAuditEvent).count() == 0
    finally:
        db.close()
