from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4
from datetime import timedelta

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.core.database import get_db
from app.models import database as m
from app.services import execution_runtime
from app.services.auth import create_access_token
from tests.test_durable_queue import replicas


@pytest.fixture
def environment(replicas, monkeypatch):
    def database():
        with replicas[0]() as db: yield db
    app.dependency_overrides[get_db] = database
    monkeypatch.setattr(execution_runtime, 'SessionLocal', replicas[1])
    with replicas[0]() as db:
        db.add(m.User(id='solver', username='solver', hashed_password='', role='user'))
        db.flush()
        db.add(m.Problem(id='problem', creator_id='solver', title='original', description='', difficulty='iron5',
            points=100, tags=[], test_cases={'sample':[{'input':'sample', 'expected_output':'42'}],
                                           'hidden':[{'input':'secret', 'expected_output':'42'}]}))
        db.commit()
    yield replicas, {'Authorization':f"Bearer {create_access_token({'sub':'solver'})}"}
    app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_expired_practice_receipt_never_reexecutes_or_changes_awarded_points(environment):
    from app.services.contest_access import now_utc
    from app.services.execution_retention import expire_execution_content
    factories, headers = environment
    headers = {**headers, 'X-Request-ID': str(uuid4())}
    data = {'code': 'private solution', 'language': 'python'}
    queue = execution_runtime.execution_queue()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        first = await client.post('/api/v1/problems/problem/submit', headers=headers, json=data)
        assert first.status_code == 202
        job_id = first.json()['executionId']
        claim = queue.claim()
        assert queue.finish(job_id, claim.token, {'verdict': 'accepted', 'value': {
            'sample_passed_cases': 1, 'grading_completed': True, 'grading_passed': True, 'details': []}})
        with factories[0]() as db:
            db.get(m.ExecutionJob, job_id).finished_at = now_utc()-timedelta(days=8)
            db.flush()
            assert expire_execution_content(db, retention_days=7) == 1
            db.query(m.Submission).filter_by(execution_job_id=job_id).delete()
            db.query(m.CompileQueueRecord).filter_by(id=job_id).delete()
            db.commit()
        for retry in (data, {**data, 'code': 'changed'}):
            response = await client.post('/api/v1/problems/problem/submit', headers=headers, json=retry)
            assert response.status_code == 410 and response.headers['cache-control'] == 'no-store'
        assert (await client.get('/api/v1/executions/'+job_id, headers=headers)).status_code == 410
    with factories[1]() as db:
        assert db.query(m.ExecutionJob).count() == 1
        assert db.query(m.Submission).count() == db.query(m.CompileQueueRecord).count() == 0
        assert db.get(m.User, 'solver').total_score == 100
        assert db.query(m.UserProblemScore).one().points_awarded == 100
    assert queue.claim() is None


@pytest.mark.asyncio
async def test_receipt_snapshot_survives_edit_and_retry_and_dual_workers_award_once(environment):
    factories, headers = environment
    data = {'code':'print(42)', 'language':'python'}
    first_key = {**headers, 'X-Request-ID':str(uuid4())}
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        first = await client.post('/api/v1/problems/problem/submit', headers=first_key, json=data)
        second = await client.post('/api/v1/problems/problem/submit', headers=headers, json=data)
        assert first.status_code == second.status_code == 202
        with factories[1]() as db:
            problem = db.get(m.Problem, 'problem')
            problem.points = 999
            problem.test_cases = {'sample':[], 'hidden':[]}
            db.commit()
        repeated = await client.post('/api/v1/problems/problem/submit', headers=first_key, json=data)
        assert repeated.status_code == 202 and repeated.json() == first.json()
        assert (await client.post('/api/v1/problems/problem/submit', headers=first_key,
                                  json={**data, 'code':'changed'})).status_code == 409
        queues = [execution_runtime.execution_queue() for _ in range(2)]
        claims = [queue.claim() for queue in queues]
        assert all(claim.payload['practice_points'] == 100 for claim in claims)
        assert all(claim.payload['hidden'][0]['input'] == 'secret' for claim in claims)
        with factories[0]() as db:
            assert db.get(m.User, 'solver').total_score == 0
            assert db.query(m.Submission).count() == 2
        barrier = Barrier(2)
        def finish(item):
            queue, claim = item
            barrier.wait()
            return queue.finish(claim.id, claim.token, {'verdict':'accepted', 'value':{
                'sample_passed_cases':1, 'grading_completed':True, 'grading_passed':True, 'details':[]}})
        with ThreadPoolExecutor(2) as pool:
            assert all(pool.map(finish, zip(queues,claims)))
        result = await client.get('/api/v1/executions/'+first.json()['executionId'], headers=headers)
        assert result.json()['result']['ok']
        assert result.json()['result']['value']['totalScore'] == 100
        assert 'secret' not in result.text and 'hidden' not in result.text
    with factories[1]() as db:
        assert db.get(m.User, 'solver').total_score == 100
        assert db.query(m.UserProblemScore).one().points_awarded == 100
        assert sorted(s.awarded_points for s in db.query(m.Submission).all()) == [0,100]


@pytest.mark.asyncio
async def test_admission_capacity_rolls_back_entire_submission_receipt(environment, monkeypatch):
    factories, headers = environment
    from app.core.config import settings
    monkeypatch.setattr(settings, 'EXECUTION_QUEUE_PER_OWNER', 1)
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        data = {'code':'print(42)', 'language':'python'}
        first = await client.post('/api/v1/problems/problem/submit', headers=headers, json=data)
        assert first.status_code == 202
        refused = await client.post('/api/v1/problems/problem/submit', headers=headers, json=data)
        assert refused.status_code == 429 and refused.headers['retry-after'] == '5'
    with factories[1]() as db:
        assert db.query(m.Submission).count() == db.query(m.ExecutionJob).count() == 1
        assert db.query(m.CompileQueueRecord).count() == 1
        assert db.query(m.UserProblemScore).count() == 0


@pytest.mark.asyncio
async def test_retry_after_ordinary_history_prune_returns_original_job(environment, monkeypatch):
    factories, headers = environment
    from app.core.config import settings
    from app.services import submission_acceptance
    from datetime import datetime, timedelta
    receipt_clock = [datetime(2026,1,1)]
    monkeypatch.setattr(submission_acceptance, 'now_utc', lambda:receipt_clock[0])
    monkeypatch.setattr(settings, 'SUBMISSION_RETENTION_PER_USER', 1)
    identity = {**headers, 'X-Request-ID':str(uuid4())}
    data = {'code':'print(42)', 'language':'python'}
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        first = await client.post('/api/v1/problems/problem/submit', headers=identity, json=data)
        receipt_clock[0] += timedelta(seconds=1)
        second = await client.post('/api/v1/problems/problem/submit', headers=headers, json=data)
        assert first.status_code == second.status_code == 202
        queue = execution_runtime.execution_queue()
        for _ in range(2):
            claim = queue.claim()
            queue.finish(claim.id, claim.token, {'verdict':'accepted', 'value':{
                'sample_passed_cases':1, 'grading_completed':True, 'grading_passed':True, 'details':[]}})
        with factories[1]() as db:
            assert db.query(m.Submission).count() == 1
            assert db.get(m.Submission, first.json()['id']) is None
        repeated = await client.post('/api/v1/problems/problem/submit', headers=identity, json=data)
        assert repeated.status_code == 202, repeated.text
        assert repeated.json()['id'] == first.json()['id']
        assert repeated.json()['executionId'] == first.json()['executionId']
    with factories[1]() as db:
        assert db.query(m.ExecutionJob).count() == 2
        assert db.get(m.User,'solver').total_score == 100
