"""Real initializer CLI and production API/worker readiness, isolated DB only."""
import asyncio
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import text
from app.models.database import ExecutionWorkerRecord, ExecutionRuntimeRecord, WorkerProcessRecord

from tests.test_durable_queue import replicas
from tests.test_execution_http_live import healthy, port, stop

pytestmark = pytest.mark.skipif(os.getenv('RUN_SANDBOX_INTEGRATION') != '1' or not os.getenv('TEST_REDIS_URL'),
    reason='Explicit isolated Docker and Redis test host required')


@pytest.mark.asyncio
@pytest.mark.parametrize('same_pool',[False,True])
async def test_initialized_api_requires_live_worker_and_withdraws_readiness_on_drain(replicas,same_pool):
    engine = replicas[0].kw['bind']
    prefix = 'audit-readiness-'+uuid4().hex
    child_env = dict(os.environ, ENVIRONMENT='production', AUTO_INITIALIZE_DB='false',
        EMBEDDED_EXECUTION_WORKER='false', REDIS_URL=os.environ['TEST_REDIS_URL'],
        REDIS_KEY_PREFIX=prefix, SANDBOX_POOL_ID=prefix, COMPILER_QUEUE_CONCURRENCY='1',
        DEPLOYMENT_SHA='a'*40,RUNTIME_INSTANCE_ID=uuid4().hex)
    if engine.dialect.name == 'postgresql':
        with engine.connect() as db:
            schema = db.execute(text('SELECT current_schema()')).scalar_one()
        assert schema.startswith('audit_queue_')
        child_env.update(DATABASE_URL=os.environ['TEST_POSTGRES_URL'],PGOPTIONS='-csearch_path='+schema)
    else:
        child_env['DATABASE_URL'] = str(engine.url)
    root = Path(__file__).resolve().parents[1]
    processes = []
    with tempfile.TemporaryFile() as log:
        try:
            initialized = await asyncio.to_thread(subprocess.run, [sys.executable,'-m','app.initialize'],
                cwd=root,env=child_env,stdout=log,stderr=log,timeout=30)
            assert initialized.returncode == 0
            apis, urls = {}, {}
            pool_env = {color:dict(child_env, RUNTIME_POOL_ID=prefix+('-same' if same_pool else '-'+color),
                                  RUNTIME_INSTANCE_ID=uuid4().hex) for color in ('blue','green')}
            def start_worker(color, **overrides):
                process = subprocess.Popen([sys.executable,'-m','app.worker'],cwd=root,
                    env=dict(pool_env[color],**overrides),stdout=log,stderr=log)
                processes.append(process)
                return process
            async def cli_ready(color):
                result = await asyncio.to_thread(subprocess.run,[sys.executable,'-m','app.readiness'],
                    cwd=root,env=pool_env[color],stdout=log,stderr=log,timeout=5)
                return result.returncode
            for color in ('blue','green'):
                api_port = port()
                urls[color] = f'http://127.0.0.1:{api_port}'
                apis[color] = subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1',
                    '--port',str(api_port),'--no-proxy-headers','--log-level','error'],cwd=root,
                    env=dict(pool_env[color],DOCKER_HOST='tcp://127.0.0.1:1'),stdout=log,stderr=log)
                processes.append(apis[color])
            async with httpx.AsyncClient(timeout=5) as client:
                for color in ('blue','green'):
                    await healthy(client,urls[color],apis[color])
                    assert (await client.get(urls[color]+'/health')).json()['deploymentSha'] == 'a'*40
                    assert (await client.get(urls[color]+'/health')).json()['runtimeInstanceId'] == pool_env[color]['RUNTIME_INSTANCE_ID']
                    assert (await client.get(urls[color]+'/ready')).status_code == 503
                    assert await cli_ready(color) == 1
                blue_worker = start_worker('blue')
                async with asyncio.timeout(20):
                    while (await client.get(urls['blue']+'/ready')).status_code != 200:
                        assert blue_worker.poll() is None
                        await asyncio.sleep(.2)
                # Same release/DB/Redis namespace/sandbox pool, different color.
                # An old worker cannot make an empty target pool deployable.
                assert (await client.get(urls['green']+'/ready')).status_code == 503
                assert await cli_ready('blue') == 0
                assert await cli_ready('green') == 1
                green_worker = start_worker('green')
                async with asyncio.timeout(20):
                    while (await client.get(urls['green']+'/ready')).status_code != 200:
                        assert green_worker.poll() is None
                        await asyncio.sleep(.2)
                assert await cli_ready('green') == 0
                # Crash leaves an unexpired Redis heartbeat, but the CLI must
                # reject the dead PID/start token. A replacement process with
                # unavailable Docker must not borrow the old process's probe.
                blue_worker.kill()
                await asyncio.to_thread(blue_worker.wait,timeout=10)
                assert await cli_ready('blue') == 1
                unavailable_worker = start_worker('blue',DOCKER_HOST='tcp://127.0.0.1:1')
                async with asyncio.timeout(20):
                    while (await client.get(urls['blue']+'/ready')).status_code != 503:
                        assert unavailable_worker.poll() is None
                        await asyncio.sleep(.2)
                assert await cli_ready('blue') == 1
                assert (await client.get(urls['green']+'/ready')).status_code == 200
                # Observe lane startup before sending SIGTERM, rather than
                # racing installation of the replacement process's handlers.
                async with asyncio.timeout(10):
                    while True:
                        with replicas[0]() as db:
                            count = db.query(ExecutionWorkerRecord).filter_by(
                                runtime_id=pool_env['blue']['RUNTIME_INSTANCE_ID']).count()
                        if count == 2:
                            break
                        assert unavailable_worker.poll() is None
                        await asyncio.sleep(.1)
                await asyncio.to_thread(stop,unavailable_worker)
                blue_worker = start_worker('blue')
                async with asyncio.timeout(20):
                    while (await client.get(urls['blue']+'/ready')).status_code != 200:
                        assert blue_worker.poll() is None
                        await asyncio.sleep(.2)
                assert await cli_ready('blue') == 0
                # Fence the actual blue incarnation while its worker is alive.
                # Read-only status must not begin drain; only explicit --begin does.
                blue_env = pool_env['blue']
                command = [sys.executable,'-m','app.runtime_drain',
                    '--runtime',blue_env['RUNTIME_INSTANCE_ID'],
                    '--pool',blue_env['RUNTIME_POOL_ID'], '--release',blue_env['DEPLOYMENT_SHA'],
                    '--sandbox-pool',blue_env['SANDBOX_POOL_ID']]
                status = await asyncio.to_thread(subprocess.run,command,cwd=root,
                    env=blue_env,capture_output=True,text=True,timeout=10)
                assert status.returncode == 0
                import json
                assert json.loads(status.stdout)['draining'] is False
                fenced = await asyncio.to_thread(subprocess.run,command+['--begin'],cwd=root,
                    env=blue_env,capture_output=True,text=True,timeout=10)
                assert fenced.returncode == 0
                assert json.loads(fenced.stdout)['draining'] is True
                assert blue_worker.poll() is None
                # Readiness cannot be reopened by even a still-live Redis marker.
                import redis
                health_store = redis.Redis.from_url(os.environ['TEST_REDIS_URL'])
                try:
                    health_key = ':'.join((prefix,'health','workers-v2',blue_env['RUNTIME_POOL_ID'],
                                          blue_env['DEPLOYMENT_SHA'],blue_env['RUNTIME_INSTANCE_ID']))
                    health_store.hset(health_key+':owners','fixture-stale-ready','f'*32)
                    health_store.expire(health_key+':owners',60)
                    health_store.zadd(health_key, {'fixture-stale-ready:'+('f'*32):health_store.time()[0]+30})
                    health_store.expire(health_key,60)
                    assert (await client.get(urls['blue']+'/ready')).status_code == 503
                    assert await cli_ready('blue') == 1
                finally:
                    health_store.close()
                assert (await client.get(urls['green']+'/ready')).status_code == 200
                await asyncio.to_thread(stop,blue_worker)
                restarted = start_worker('blue')
                assert await asyncio.to_thread(restarted.wait,timeout=15) != 0
                async with asyncio.timeout(5):
                    while (await client.get(urls['blue']+'/ready')).status_code != 503:
                        await asyncio.sleep(.1)
                assert (await client.get(urls['green']+'/ready')).status_code == 200
                assert await cli_ready('blue') == 1
                assert await cli_ready('green') == 0
                for color in ('blue','green'):
                    assert (await client.get(urls[color]+'/health')).status_code == 200
                with replicas[0]() as db:
                    blue_records = db.query(ExecutionWorkerRecord).filter_by(runtime_id=pool_env['blue']['RUNTIME_INSTANCE_ID']).all()
                    green_records = db.query(ExecutionWorkerRecord).filter_by(runtime_id=pool_env['green']['RUNTIME_INSTANCE_ID']).all()
                    assert len(blue_records) == 3 and len(green_records) == 1
                    assert sum(record.draining_at is not None for record in blue_records) == 2
                    assert green_records[0].draining_at is None
                    assert all(record.process_id for record in blue_records+green_records)
                    blue_processes = db.query(WorkerProcessRecord).filter_by(runtime_id=pool_env['blue']['RUNTIME_INSTANCE_ID']).all()
                    assert len(blue_processes) == 3
                    assert {row.id for row in blue_processes} == {row.process_id for row in blue_records}
                    # Crash leaves unresolved process evidence; the two orderly
                    # worker exits have explicit DB fences and stopped lifecycle.
                    assert sum(row.stopped_at is not None for row in blue_processes) == 2
                    green_process = db.get(WorkerProcessRecord, green_records[0].process_id)
                    assert green_process.pid == green_worker.pid and green_process.stopped_at is None
                    assert db.get(ExecutionRuntimeRecord,pool_env['blue']['RUNTIME_INSTANCE_ID']).draining_at is not None
                    assert db.get(ExecutionRuntimeRecord,pool_env['green']['RUNTIME_INSTANCE_ID']).draining_at is None
        finally:
            for process in reversed(processes):
                await asyncio.to_thread(stop,process)
            import redis
            client = redis.Redis.from_url(os.environ['TEST_REDIS_URL'])
            keys = list(client.scan_iter(match=prefix+':*'))
            if keys:
                client.delete(*keys)
            client.close()
