"""Administrator source review stays separate from participant-owned receipts."""
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event

from app.main import app
from app.models import database as m
from tests.test_compile_history_filters import history_env, auth
from tests.test_durable_queue import replicas


@pytest.mark.asyncio
async def test_admin_lists_metadata_and_reads_one_source_without_hidden_tests(history_env):
    statements = []
    engine = history_env.factory.kw['bind']
    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)
    event.listen(engine, 'before_cursor_execute', capture)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            listing = await client.get('/api/v1/contests/a/admin/submissions?limit=1', headers=auth('admin'))
            assert listing.status_code == 200, listing.text
            assert listing.headers['cache-control'] == 'no-store'
            assert listing.json()['total'] == 2
            assert listing.json()['submissions'][0]['username'] == 'bob'
            assert listing.json()['submissions'][0]['contestProblemId'] == 'A'
            assert 'code' not in listing.json()['submissions'][0]
            assert all('contest_submissions.code' not in sql.lower().split('from')[0] for sql in statements)
            next_page = await client.get('/api/v1/contests/a/admin/submissions?limit=1&offset=1', headers=auth('admin'))
            assert next_page.json()['submissions'][0]['username'] == 'alice'
            detail = await client.get('/api/v1/contests/a/admin/submissions/bob-a', headers=auth('admin'))
            assert detail.status_code == 200, detail.text
            assert detail.json()['code'] == 'SECRET_SOURCE'
            assert detail.headers['cache-control'] == 'no-store'
            assert not any(secret in detail.text for secret in ['SECRET_INPUT', 'SECRET_EXPECTED', 'SECRET_STATEMENT', 'SECRET_OUTPUT'])
            assert (await client.get('/api/v1/contests/b/admin/submissions/bob-a', headers=auth('admin'))).status_code == 404
            assert (await client.get('/api/v1/contests/missing/admin/submissions', headers=auth('admin'))).status_code == 404
            assert (await client.get('/api/v1/contests/draft/admin/submissions', headers=auth('admin'))).status_code == 200
    finally:
        event.remove(engine, 'before_cursor_execute', capture)


@pytest.mark.asyncio
async def test_guest_user_and_revoked_admin_cannot_read_other_sources(history_env):
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        for identity in (None, 'alice', 'bob'):
            headers = auth(identity) if identity else {}
            for path in ('/a/admin/submissions', '/a/admin/submissions/bob-a'):
                result = await client.get('/api/v1/contests' + path + '?isAdmin=true', headers=headers)
                assert result.status_code in (401, 403), result.text
                assert 'SECRET_SOURCE' not in result.text
        mine = await client.get('/api/v1/contests/a/submissions', headers=auth('alice'))
        assert mine.status_code == 200 and mine.json()['total'] == 1
        own = await client.get('/api/v1/contests/a/submissions/alice-a', headers=auth('alice'))
        assert own.status_code == 200 and own.json()['code'] == 'SECRET_SOURCE'
        assert (await client.get('/api/v1/contests/a/submissions/bob-a', headers=auth('alice'))).status_code == 404
        assert (await client.get('/api/v1/contests/a/submissions/bob-a', headers=auth('admin'))).status_code == 404
        old_token = auth('admin')
        with history_env.factory() as db:
            db.get(m.User, 'admin').role = 'user'
            db.commit()
        assert (await client.get('/api/v1/contests/a/admin/submissions/bob-a', headers=old_token)).status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize('query', ['limit=0', 'limit=201', 'offset=-1'])
async def test_admin_list_rejects_invalid_page_bounds(history_env, query):
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        result = await client.get('/api/v1/contests/a/admin/submissions?' + query, headers=auth('admin'))
        assert result.status_code == 422
