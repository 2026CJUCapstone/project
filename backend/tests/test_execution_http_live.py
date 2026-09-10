"""Real two-API/process-worker integration on the isolated Docker test host."""
import asyncio
import os
import socket
import subprocess
import sys
import tempfile
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import text

from app.models import database as m
from app.services.auth import create_access_token
from app.services.contest_access import now_utc
from app.services.execution_retention import expire_execution_content
from app.services.queue_retention import purge_queue_history
from tests.test_durable_queue import replicas

pytestmark = pytest.mark.skipif(os.getenv('RUN_SANDBOX_INTEGRATION') != '1', reason='Explicit isolated sandbox host required')


def port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0))
        return listener.getsockname()[1]


async def healthy(client, url, process):
    async with asyncio.timeout(20):
        while True:
            assert process.poll() is None, 'Isolated API exited before readiness'
            try:
                if (await client.get(url+'/health')).status_code == 200:
                    return
            except httpx.TransportError:
                pass
            await asyncio.sleep(.1)


def stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


@pytest.mark.asyncio
async def test_other_api_reads_receipt_after_producer_exit_and_separate_worker_grades(replicas):
    engine = replicas[0].kw['bind']
    child_env = dict(os.environ, AUTO_INITIALIZE_DB='false', EMBEDDED_EXECUTION_WORKER='false',
        COMPILER_QUEUE_CONCURRENCY='1', EXECUTION_QUEUE_CAPACITY='8', EXECUTION_LEASE_SECONDS='10',
        REDIS_KEY_PREFIX='audit-http-'+uuid4().hex, SANDBOX_POOL_ID='audit-http-'+uuid4().hex)
    if engine.dialect.name == 'postgresql':
        with engine.connect() as db:
            schema = db.execute(text('SELECT current_schema()')).scalar_one()
        assert schema.startswith('audit_queue_')
        child_env.update(DATABASE_URL=os.environ['TEST_POSTGRES_URL'], PGOPTIONS='-csearch_path='+schema)
    else:
        child_env['DATABASE_URL'] = str(engine.url)
    child_env['REDIS_URL'] = os.getenv('TEST_REDIS_URL', '')
    with replicas[0]() as db:
        db.add(m.User(id='http-solver', username='http-solver', hashed_password=''))
        db.flush()
        db.add(m.Problem(id='http-problem', creator_id='http-solver', title='integration', description='',
            difficulty='iron5', tags=[], points=17, test_cases={'sample':[{'input':'','expected_output':'42'}],
                                                              'hidden':[{'input':'private-case','expected_output':'42'}]}))
        db.commit()
    first_port, second_port = port(), port()
    root = Path(__file__).resolve().parents[1]
    processes = []
    # API processes deliberately have an unusable Docker endpoint. A hidden
    # request-local execution would fail instead of accidentally passing.
    api_env = dict(child_env, DOCKER_HOST='tcp://127.0.0.1:1')
    with tempfile.TemporaryFile() as log:
        try:
            for api_port in (first_port, second_port):
                processes.append(subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1',
                    '--port',str(api_port),'--no-proxy-headers','--log-level','error'], cwd=root, env=api_env,
                    stdout=log, stderr=log))
            a, b = f'http://127.0.0.1:{first_port}', f'http://127.0.0.1:{second_port}'
            async with httpx.AsyncClient(timeout=5) as client:
                await healthy(client,a,processes[0]); await healthy(client,b,processes[1])
                identity = {'X-Request-ID':str(uuid4())}
                data = {'code':'print(42)', 'language':'python', 'kind':'run'}
                receipt = await client.post(a+'/api/v1/executions', headers=identity, json=data)
                assert receipt.status_code == 202, receipt.text
                job_id = receipt.json()['id']
                assert receipt.json()['status'] == 'queued'
                # There is no worker yet: losing the accepting API must neither
                # cancel this job nor prevent another replica from serving it.
                await asyncio.to_thread(stop, processes[0])
                repeated = await client.post(b+'/api/v1/executions', headers=identity, json=data)
                assert repeated.status_code == 202 and repeated.json()['id'] == job_id
                assert (await client.get(b+'/api/v1/executions/'+job_id)).json()['status'] == 'queued'
                headers = {'Authorization':'Bearer '+create_access_token({'sub':'http-solver'}),
                           'X-Request-ID':str(uuid4())}
                submission = await client.post(b+'/api/v1/problems/http-problem/submit', headers=headers,
                    json={'code':'print(42)','language':'python'})
                assert submission.status_code == 202, submission.text
                with replicas[1]() as db:
                    assert db.get(m.User,'http-solver').total_score == 0
                    assert db.query(m.ExecutionJob).count() == 2
                processes.append(subprocess.Popen([sys.executable,'-m','app.worker'], cwd=root, env=child_env,
                    stdout=log, stderr=log))
                async with asyncio.timeout(45):
                    while True:
                        generic = await client.get(b+'/api/v1/executions/'+job_id)
                        graded = await client.get(b+'/api/v1/executions/'+submission.json()['executionId'], headers=headers)
                        if generic.json()['status'] == graded.json()['status'] == 'completed':
                            break
                        assert processes[-1].poll() is None, 'Separate worker exited'
                        await asyncio.sleep(.1)
                assert generic.json()['result']['value']['stdout'].strip() == '42'
                assert graded.json()['result']['value']['status'] == 'Accepted'
                assert graded.json()['result']['value']['totalScore'] == 17
                assert 'private-case' not in graded.text
                async with httpx.AsyncClient() as stranger:
                    assert (await stranger.get(b+'/api/v1/executions/'+job_id)).status_code == 404

                # Stop the real worker, expire only this fixture's completed
                # content, then restart the API. Durable 410 receipts must
                # survive both processes, not depend on in-memory state.
                await asyncio.to_thread(stop, processes[-1])
                with replicas[1]() as db:
                    assert expire_execution_content(db, retention_days=7, at=now_utc()+timedelta(days=8)) == 2
                    assert purge_queue_history(db, history_limit=0) == 2
                    db.commit()
                await asyncio.to_thread(stop, processes[1])
                processes.append(subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1',
                    '--port',str(second_port),'--no-proxy-headers','--log-level','error'], cwd=root, env=api_env,
                    stdout=log, stderr=log))
                await healthy(client,b,processes[-1])
                for path, request_headers, request_data in (
                    ('/api/v1/executions', identity, data),
                    ('/api/v1/problems/http-problem/submit', headers, {'code':'print(42)', 'language':'python'}),
                ):
                    for body in (request_data, {**request_data, 'code':'print(99)'}):
                        rejected = await client.post(b+path, headers=request_headers, json=body)
                        assert rejected.status_code == 410, rejected.text
                        assert rejected.headers['cache-control'] == 'no-store'
                for expired_id, auth in ((job_id, {}), (submission.json()['executionId'], headers)):
                    gone = await client.get(b+'/api/v1/executions/'+expired_id, headers=auth)
                    assert gone.status_code == 410 and gone.headers['cache-control'] == 'no-store'
                    assert 'private-case' not in gone.text and 'print(42)' not in gone.text
                    async with httpx.AsyncClient() as stranger:
                        assert (await stranger.get(b+'/api/v1/executions/'+expired_id)).status_code == 404
                with replicas[1]() as db:
                    assert db.query(m.ExecutionJob).count() == 2
                    assert db.query(m.CompileQueueRecord).count() == 0
                    assert db.get(m.User,'http-solver').total_score == 17
                    assert db.query(m.UserProblemScore).one().points_awarded == 17
                    assert all(job.content_expired_at is not None and job.payload == {} and job.result is None
                               for job in db.query(m.ExecutionJob).all())
        finally:
            for process in reversed(processes):
                await asyncio.to_thread(stop, process)
