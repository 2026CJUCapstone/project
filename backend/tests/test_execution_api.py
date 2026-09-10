from types import SimpleNamespace
from uuid import uuid4
from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.core.database import Base, get_db
from app.api.routes import executions
from app.models.database import ExecutionJob
from app.services.durable_queue import DurableQueue
from app.services.execution_results import publish_result, publish_transition
from app.services.execution_worker import ExecutionWorker


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{(tmp_path/'api.db').as_posix()}", connect_args={'check_same_thread':False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    queue = DurableQueue(factory, on_terminal=publish_result, on_transition=publish_transition)
    def database():
        with factory() as db: yield db
    app.dependency_overrides[get_db] = database
    monkeypatch.setattr(executions, 'execution_queue', lambda:queue)
    yield queue, factory
    app.dependency_overrides.pop(get_db,None)
    engine.dispose()


@pytest.mark.asyncio
async def test_receipt_commits_code_before_judging_and_is_readable_after_worker_restart(runtime):
    queue, factory = runtime
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://isolated') as client:
        response = await client.post('/api/v1/executions', json={'kind':'run', 'language':'python', 'code':'print(42)'})
        assert response.status_code == 202
        job_id = response.json()['id']
        assert response.json()['status'] == 'queued'
        with factory() as db:
            job = db.get(ExecutionJob, job_id)
            assert job.payload['code'] == 'print(42)'
            assert job.result is None
        class Runner:
            def __init__(self, **kwargs): pass
            async def run(self, **kwargs): return {'stdout':'42', 'stderr':'', 'exit_code':0, 'execution_time':1}
        restarted = ExecutionWorker(DurableQueue(factory, on_terminal=publish_result, on_transition=publish_transition),
            pool=SimpleNamespace(labels=lambda *args:{}, reap=lambda *args:None), runner_factory=Runner)
        assert await restarted.run_once()
        result = await client.get(f'/api/v1/executions/{job_id}')
        assert result.json()['result']['value']['stdout'] == '42'
        assert 'payload' not in result.json() and 'code' not in result.json()
        assert result.headers['cache-control'] == 'no-store'


@pytest.mark.asyncio
async def test_same_ip_cannot_read_another_anonymous_sessions_job(runtime):
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://isolated') as first:
        response = await first.post('/api/v1/executions', json={'language':'python','code':'private code'})
        job_id = response.json()['id']
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://isolated') as other:
            assert (await other.get(f'/api/v1/executions/{job_id}')).status_code == 404
        assert (await first.get(f'/api/v1/executions/{job_id}')).status_code == 200


@pytest.mark.asyncio
async def test_request_retry_returns_same_receipt_but_changed_code_is_conflict(runtime):
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://isolated') as client:
        headers = {'X-Request-ID':str(uuid4())}
        data = {'language':'python','code':'print(1)'}
        first = await client.post('/api/v1/executions', headers=headers, json=data)
        second = await client.post('/api/v1/executions', headers=headers, json=data)
        assert first.status_code == second.status_code == 202
        assert first.json()['id'] == second.json()['id']
        assert (await client.post('/api/v1/executions', headers=headers, json={**data,'code':'different'})).status_code == 409
        assert (await client.post('/api/v1/executions', headers={'X-Request-ID':'not-a-uuid'}, json=data)).status_code == 400


@pytest.mark.asyncio
async def test_expired_content_is_private_gone_and_retry_cannot_recreate_queue_record(runtime):
    from app.models.database import CompileQueueRecord
    from app.services.contest_access import now_utc
    from app.services.execution_retention import expire_execution_content
    queue, factory = runtime
    data = {'language': 'python', 'code': 'private source'}
    headers = {'X-Request-ID': str(uuid4())}
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://isolated') as client:
        first = await client.post('/api/v1/executions', json=data, headers=headers)
        assert first.status_code == 202
        job_id = first.json()['id']
        claim = queue.claim()
        assert queue.finish(job_id, claim.token, {'verdict': 'finished', 'value': {'stdout': 'private output'}})
        with factory() as db:
            db.get(ExecutionJob, job_id).finished_at = now_utc()-timedelta(days=8)
            db.flush()
            assert expire_execution_content(db, retention_days=7) == 1
            db.query(CompileQueueRecord).filter_by(id=job_id).delete()
            db.commit()
        expired = await client.get('/api/v1/executions/'+job_id)
        assert expired.status_code == 410 and expired.headers['cache-control'] == 'no-store'
        assert 'private source' not in expired.text and 'private output' not in expired.text
        for retry in (data, {**data, 'code': 'different source'}):
            response = await client.post('/api/v1/executions', json=retry, headers=headers)
            assert response.status_code == 410 and response.headers['cache-control'] == 'no-store'
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://isolated') as other:
            assert (await other.get('/api/v1/executions/'+job_id)).status_code == 404
        with factory() as db:
            assert db.query(ExecutionJob).count() == 1 and db.query(CompileQueueRecord).count() == 0
        assert queue.claim() is None


@pytest.mark.asyncio
async def test_retry_of_pruned_unexpired_receipt_does_not_recreate_permanently_queued_observation(runtime):
    from app.models.database import CompileQueueRecord
    from app.services.queue_retention import purge_queue_history
    queue, factory = runtime
    data = {'language': 'python', 'code': 'print(1)'}
    headers = {'X-Request-ID': str(uuid4())}
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://isolated') as client:
        first = await client.post('/api/v1/executions', json=data, headers=headers)
        assert first.status_code == 202
        job_id = first.json()['id']
        claim = queue.claim()
        assert queue.finish(job_id, claim.token, {'verdict': 'finished', 'value': {
            'stdout': '1', 'stderr': '', 'exit_code': 0, 'execution_time': 0,
        }})
        with factory() as db:
            assert purge_queue_history(db, history_limit=0) == 1
            assert db.get(ExecutionJob, job_id).content_expired_at is None
            db.commit()
        retry = await client.post('/api/v1/executions', json=data, headers=headers)
        assert retry.status_code == 202 and retry.json()['id'] == job_id
        assert retry.json()['status'] == 'completed'
        result = await client.get('/api/v1/executions/'+job_id)
        assert result.status_code == 200 and result.json()['result']['value']['stdout'] == '1'
        with factory() as db:
            assert db.query(CompileQueueRecord).count() == 0
            assert db.query(ExecutionJob).count() == 1
        assert queue.claim() is None
