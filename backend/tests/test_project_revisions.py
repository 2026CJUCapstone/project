import asyncio
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.core.database import SessionLocal
from app.main import app
from app.models import database as m
from app.services.auth import create_access_token


@pytest.fixture
def project_owner():
    with SessionLocal() as db:
        user = m.User(username=f'project_{uuid.uuid4().hex}', hashed_password='')
        db.add(user)
        db.commit()
        user_id = user.id
        headers = {'Authorization': f'Bearer {create_access_token({"sub": user.username})}'}
    yield headers
    with SessionLocal() as db:
        db.query(m.CodeProject).filter_by(user_id=user_id).delete()
        db.query(m.User).filter_by(id=user_id).delete()
        db.commit()


@pytest.mark.asyncio
async def test_project_compare_and_swap_and_utc_timestamps(project_owner):
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://isolated', headers=project_owner) as client:
        created = await client.put('/api/v1/projects/main', json={'code':'v1'})
        assert created.status_code == 200
        revision = created.json()['revision']
        assert created.json()['createdAt'].endswith('Z')
        assert created.json()['updatedAt'].endswith('Z')
        # An old client without a base revision cannot silently overwrite.
        assert (await client.put('/api/v1/projects/main', json={'code':'blind overwrite'})).status_code == 409
        updated = await client.put('/api/v1/projects/main', json={'code':'v2', 'expectedRevision':revision})
        assert updated.status_code == 200
        assert updated.json()['revision'] != revision
        assert (await client.put('/api/v1/projects/main', json={'code':'stale', 'expectedRevision':revision})).status_code == 409
        assert (await client.get('/api/v1/projects/main')).json()['code'] == 'v2'


@pytest.mark.asyncio
async def test_simultaneous_edits_have_exactly_one_winner(project_owner):
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://isolated', headers=project_owner) as client:
        created = await client.put('/api/v1/projects/main', json={'code':'base'})
        revision = created.json()['revision']
        responses = await asyncio.gather(*[
            client.put('/api/v1/projects/main', json={'code':code, 'expectedRevision':revision})
            for code in ('first tab', 'second tab')
        ])
        assert sorted(response.status_code for response in responses) == [200,409]
        winner = next(response.json()['code'] for response in responses if response.status_code == 200)
        assert (await client.get('/api/v1/projects/main')).json()['code'] == winner


@pytest.mark.asyncio
async def test_delete_recreate_cannot_accept_old_revision(project_owner):
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://isolated', headers=project_owner) as client:
        old = (await client.put('/api/v1/projects/main', json={'code':'old'})).json()
        assert (await client.delete('/api/v1/projects/main')).status_code == 204
        assert (await client.put('/api/v1/projects/main', json={'code':'stale', 'expectedRevision':old['revision']})).status_code == 409
        new = (await client.put('/api/v1/projects/main', json={'code':'recreated'})).json()
        assert old['revision'] != new['revision']
        assert (await client.put('/api/v1/projects/main', json={'code':'stale', 'expectedRevision':old['revision']})).status_code == 409
        assert (await client.get('/api/v1/projects/main')).json()['code'] == 'recreated'


@pytest.mark.asyncio
async def test_concurrent_project_creation_respects_owner_capacity(project_owner, monkeypatch):
    monkeypatch.setattr(settings, 'CODE_PROJECT_MAX_PER_USER', 1)
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://isolated', headers=project_owner) as client:
        responses = await asyncio.gather(*[
            client.put(f'/api/v1/projects/{scope}', json={'code':scope}) for scope in ('one','two')
        ])
        assert sorted(response.status_code for response in responses) == [200,409]
        assert len((await client.get('/api/v1/projects/')).json()) == 1
