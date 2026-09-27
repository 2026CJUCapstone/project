"""Access-scoped history filtering; actual SQL and HTTP, no sandbox required."""
from datetime import datetime, timedelta
from types import SimpleNamespace
import json

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event

from app.main import app
from app.core.database import get_db
from app.models import database as m
from app.services import compile_queue as queue_module, compile_history
from app.services.auth import create_access_token
from tests.test_durable_queue import replicas

AT = datetime(2030, 1, 1, 12)


def auth(name):
    return {'Authorization': f"Bearer {create_access_token({'sub': name})}"}


@pytest.fixture
def history_env(replicas, monkeypatch):
    factory = replicas[0]
    monkeypatch.setattr(queue_module, 'SessionLocal', factory)
    monkeypatch.setattr(compile_history, 'now_utc', lambda: AT)
    with factory() as db:
        db.add_all([m.User(id=name, username=name, hashed_password='unused',
                           role='admin' if name == 'admin' else 'user') for name in ('alice', 'bob', 'admin')])
        db.flush()
        for problem_id, title in [('shared', '공개 원본'), ('secret', '비공개 원본'), ('draft', '초안 원본'), ('upcoming', '예정 원본')]:
            db.add(m.Problem(id=problem_id, creator_id='admin', title=title,
                             description='SECRET_STATEMENT', difficulty='bronze5',
                             tags=[], test_cases=[]))
        for contest_id, title in [('a', '신입생 대회'), ('b', '연습 대회'), ('hidden', '참가자 대회'), ('draft', 'DRAFT_SECRET'), ('upcoming', '예정 대회')]:
            db.add(m.Contest(id=contest_id, creator_id='admin', title=title,
                             published=contest_id != 'draft',
                             starts_at=AT + timedelta(hours=1) if contest_id == 'upcoming' else AT - timedelta(hours=1),
                             ends_at=AT + timedelta(hours=2)))
        db.flush()
        for contest_id, problem_id, title in [('a', 'shared', 'A 스냅샷'), ('b', 'shared', 'B 스냅샷'),
                                              ('hidden', 'secret', '내 비공개 문제'), ('draft', 'draft', 'DRAFT_PROBLEM'),
                                              ('upcoming', 'upcoming', 'UPCOMING_PROBLEM')]:
            db.add(m.ContestProblem(id=f'cp-{contest_id}', contest_id=contest_id, problem_id=problem_id,
                                    position=0, points=100, is_new=contest_id not in ('a', 'b'),
                                    snapshot={'title': title, 'description': 'SECRET_STATEMENT',
                                              'hidden': [{'input': 'SECRET_INPUT', 'expected_output': 'SECRET_EXPECTED'}]}))
            db.add(m.ContestParticipant(contest_id=contest_id, user_id='alice'))
        db.add(m.ContestParticipant(contest_id='a', user_id='bob'))
        db.flush()
        db.add(m.ExecutionJob(id='contest-job', owner_key='account:alice', quota_key='account:alice',
                              request_id='private-request', payload_hash='a' * 64, kind='contest',
                              payload={'code': 'SECRET_SOURCE'}, result={'stdout': 'SECRET_OUTPUT'},
                              status='queued', received_at=AT))
        db.flush()
        for index, (submission_id, owner, contest_id, verdict) in enumerate([
            ('alice-a', 'alice', 'a', 'pending'), ('alice-b', 'alice', 'b', 'wrong_answer'),
            ('alice-hidden', 'alice', 'hidden', 'running'), ('bob-a', 'bob', 'a', 'accepted'),
            ('alice-draft', 'alice', 'draft', 'accepted'), ('alice-upcoming', 'alice', 'upcoming', 'accepted'),
        ]):
            db.add(m.ContestSubmission(id=submission_id, user_id=owner, contest_id=contest_id,
                                       contest_problem_id=f'cp-{contest_id}', request_id=submission_id,
                                       execution_job_id='contest-job' if submission_id == 'alice-a' else None,
                                       language='python', code='SECRET_SOURCE', received_at=AT + timedelta(seconds=index),
                                       status=verdict if verdict in ('queued', 'running') else ('queued' if verdict == 'pending' else 'completed'),
                                       verdict=verdict))
        for job_id, owner, problem_id, language in [
            ('ide-alice', 'alice', None, 'python'), ('ide-bob', 'bob', None, 'cpp'),
            ('practice-alice', 'alice', 'shared', 'python'), ('practice-bob', 'bob', 'shared', 'java'),
            ('anonymous', None, None, 'c'), ('leaked-hidden', 'alice', 'secret', 'python'),
            ('contest-job', 'alice', 'shared', 'python'),
        ]:
            db.add(m.CompileQueueRecord(id=job_id, user_id=owner, username=owner, problem_id=problem_id,
                                        problem_title='공개 원본' if problem_id == 'shared' else ('SECRET_HIDDEN_TITLE' if problem_id else None),
                                        kind='grading' if job_id.startswith('practice') else 'run',
                                        language=language, status='completed',
                                        verdict='process_limit_exceeded' if job_id == 'practice-alice' else 'finished',
                                        source_size_bytes=7, queued_at=AT - timedelta(minutes=1)))
        db.commit()

    def session_override():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = session_override
    yield SimpleNamespace(factory=factory)
    app.dependency_overrides.pop(get_db, None)


async def get_history(client, owner=None, **params):
    return await client.get('/api/v1/compiler/queue', params=params, headers=auth(owner) if owner else {})


@pytest.mark.asyncio
async def test_guest_projection_and_facets_cannot_reveal_contest_or_hidden_metadata(history_env):
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        result = await get_history(client)
        assert result.status_code == 200, result.text
        body = result.json()
        assert body['total'] == body['filteredTotal'] == 5
        assert body['contestOptions'] == []
        assert {row['source'] for row in body['jobs']} == {'ide', 'practice'}
        assert 'SECRET' not in result.text and '스냅샷' not in result.text and '내 비공개' not in result.text
        assert result.headers['cache-control'] == 'no-store'
        assert 'Authorization' in result.headers['vary']
        for params in ({'source': 'contest'}, {'contestId': 'a'}, {'mine': 'true'}):
            assert (await get_history(client, **params)).status_code == 401


@pytest.mark.asyncio
async def test_owner_scope_is_not_bypassed_by_user_filter_or_admin_role(history_env):
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        for owner, expected in [('alice', {'contest:alice-a', 'contest:alice-b', 'contest:alice-hidden'}),
                                ('bob', {'contest:bob-a'}), ('admin', set())]:
            result = await get_history(client, owner, source='contest')
            assert result.status_code == 200, result.text
            body = result.json()
            assert {row['id'] for row in body['jobs']} == expected
            assert body['filteredTotal'] == len(expected)
            assert all('SECRET' not in json.dumps(row) for row in body['jobs'])
            assert all(row['sourceSizeBytes'] is None and row['error'] is None for row in body['jobs'])
        for filters in ({'userId': 'bob'}, {'username': 'bob'}, {'contestId': 'draft'}, {'contestId': 'upcoming'}):
            body = (await get_history(client, 'alice', source='contest', **filters)).json()
            assert body['filteredTotal'] == 0 and body['jobs'] == []
            assert body['problemOptions'] == []


@pytest.mark.asyncio
async def test_combined_filters_counts_and_immutable_contest_title(history_env):
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        body = (await get_history(client, 'alice', source='contest', contestId='a', problemId='shared',
                                  problemSearch='스냅샷', language='python', status='queued',
                                  verdict='pending', kind='grading', mine=True)).json()
        assert body['total'] == 8 and body['filteredTotal'] == 1
        assert body['jobs'][0]['problemTitle'] == 'A 스냅샷'
        assert body['jobs'][0]['contestProblemId'] == 'cp-a'
        assert body['problemOptions'] == [{'id': 'shared', 'title': 'A 스냅샷', 'contestId': 'a'}]
        assert len(body['contestOptions']) == 3
        assert body['problemGroups'][0]['contestId'] == 'a'
        for filters, expected in [({'source': 'ide'}, 3), ({'source': 'practice'}, 2),
                                  ({'mine': True}, 5), ({'language': 'java'}, 1),
                                  ({'verdict': 'process_limit_exceeded'}, 1),
                                  ({'problemId': 'shared'}, 4), ({'problemSearch': '스냅샷'}, 2),
                                  ({'username': ' ALICE '}, 5), ({'source': 'ide', 'contestId': 'a'}, 0)]:
            assert (await get_history(client, 'alice', **filters)).json()['filteredTotal'] == expected


@pytest.mark.asyncio
async def test_filter_applied_before_pagination_and_stable_tie_order(history_env):
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        whole = (await get_history(client, 'alice', problemId='shared')).json()
        pages = [(await get_history(client, 'alice', problemId='shared', limit=1, offset=i)).json() for i in range(4)]
        assert [page['jobs'][0]['id'] for page in pages] == [row['id'] for row in whole['jobs']]
        assert all(page['filteredTotal'] == 4 for page in pages)
        assert len(whole['problemGroups']) == 3  # practice + two separate contest snapshots
        beyond = (await get_history(client, 'alice', problemId='shared', offset=100)).json()
        assert beyond['jobs'] == [] and beyond['filteredTotal'] == 4


@pytest.mark.asyncio
async def test_problem_search_treats_percent_underscore_as_literal(history_env):
    with history_env.factory() as db:
        db.get(m.CompileQueueRecord, 'practice-alice').problem_title = '완료율 100%_확인'
        db.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        body = (await get_history(client, 'alice', problemSearch='%_')).json()
        assert body['filteredTotal'] == 1 and body['jobs'][0]['id'] == 'practice-alice'
        for query in ('missing', "' OR 1=1 --"):
            assert (await get_history(client, 'alice', problemSearch=query)).json()['jobs'] == []


@pytest.mark.asyncio
async def test_membership_lifecycle_and_ended_archive(history_env):
    with history_env.factory() as db:
        db.query(m.ContestParticipant).filter_by(contest_id='hidden', user_id='alice').delete()
        db.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        body = (await get_history(client, 'alice', source='contest')).json()
        assert body['filteredTotal'] == 2 and '내 비공개' not in json.dumps(body, ensure_ascii=False)
        with history_env.factory() as db:
            db.get(m.Contest, 'hidden').ends_at = AT
            db.commit()
        body = (await get_history(client, 'alice', source='contest')).json()
        assert body['filteredTotal'] == 3
        guest = (await get_history(client)).json()
        assert guest['contestOptions'] == []  # ending never publishes someone else's contest attempts


@pytest.mark.asyncio
async def test_options_are_bounded_but_search_reaches_beyond_options(history_env, monkeypatch):
    monkeypatch.setattr(compile_history, 'OPTION_LIMIT', 1)
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        body = (await get_history(client, 'alice', problemSearch='B 스냅샷')).json()
        assert body['optionLimit'] == 1 and body['optionsTruncated'] is True
        assert len(body['contestOptions']) == len(body['problemOptions']) == 1
        assert body['filteredTotal'] == 1 and body['jobs'][0]['id'] == 'contest:alice-b'


@pytest.mark.asyncio
async def test_observation_queries_no_private_payload_or_code_and_never_write(history_env):
    statements = []
    bind = history_env.factory.kw['bind']
    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)
    event.listen(bind, 'before_cursor_execute', capture)
    try:
        result = await queue_module.compile_queue.snapshot(viewer_id='alice', source='contest')
        assert len(result['jobs']) == 3
        assert {sql.lstrip().split()[0].upper() for sql in statements} == {'SELECT'}
        combined = '\n'.join(statements).lower()
        assert 'execution_jobs' not in combined and 'contest_submissions.code' not in combined
        assert 'secret_source' not in json.dumps(result, default=str).lower()
    finally:
        event.remove(bind, 'before_cursor_execute', capture)


@pytest.mark.asyncio
async def test_validation_and_invalid_auth(history_env):
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        for params in ({'source': 'private-everyone'}, {'language': 'ruby'}, {'offset': -1},
                       {'limit': 501}, {'problemSearch': 'x' * 201}, {'mine': 'invalid'}):
            assert (await get_history(client, 'alice', **params)).status_code == 422
        result = await client.get('/api/v1/compiler/queue', headers={'Authorization': 'Bearer invalid'})
        # Optional authentication intentionally falls back to guest on public
        # APIs; an invalid token must never preserve the last account's scope.
        assert result.status_code == 200 and result.json()['total'] == 5
        assert result.json()['contestOptions'] == []
        private = await client.get('/api/v1/compiler/queue?source=contest', headers={'Authorization': 'Bearer invalid'})
        assert private.status_code == 401
