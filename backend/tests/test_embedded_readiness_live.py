"""Actual dev API, embedded worker and dependency health on test-owned stores."""
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

from app.initialize import RUNTIME_SCHEMA_VERSION
from app.models.database import ExecutionWorkerRecord
from tests.test_durable_queue import replicas
from tests.test_execution_http_live import healthy, port, stop

pytestmark = pytest.mark.skipif(
    os.getenv('RUN_SANDBOX_INTEGRATION') != '1' or not os.getenv('TEST_REDIS_URL'),
    reason='Explicit isolated Docker and Redis test host required')


@pytest.mark.asyncio
async def test_development_embedded_worker_becomes_ready_and_withdraws_on_shutdown(replicas):
    engine = replicas[0].kw['bind']
    prefix, runtime_id = 'audit-embedded-'+uuid4().hex, uuid4().hex
    child_env = dict(os.environ, ENVIRONMENT='development', AUTO_INITIALIZE_DB='true',
        EMBEDDED_EXECUTION_WORKER='true', COMPILER_QUEUE_CONCURRENCY='1',
        REDIS_URL=os.environ['TEST_REDIS_URL'], REDIS_KEY_PREFIX=prefix,
        SANDBOX_POOL_ID=prefix, RUNTIME_POOL_ID=prefix, RUNTIME_INSTANCE_ID=runtime_id,
        DEPLOYMENT_SHA='a'*40)
    if engine.dialect.name == 'postgresql':
        with engine.connect() as db:
            schema = db.execute(text('SELECT current_schema()')).scalar_one()
        assert schema.startswith('audit_queue_')
        child_env.update(DATABASE_URL=os.environ['TEST_POSTGRES_URL'], PGOPTIONS='-csearch_path='+schema)
    else:
        child_env['DATABASE_URL'] = str(engine.url)
        child_env.pop('PGOPTIONS', None)
    import redis
    store = redis.Redis.from_url(os.environ['TEST_REDIS_URL'])
    process = None
    with tempfile.TemporaryFile() as log:
        try:
            api_port = port()
            url = f'http://127.0.0.1:{api_port}'
            process = subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app',
                '--host','127.0.0.1','--port',str(api_port),'--no-proxy-headers','--log-level','error'],
                cwd=Path(__file__).resolve().parents[1],env=child_env,stdout=log,stderr=log)
            async with httpx.AsyncClient(timeout=5) as client:
                await healthy(client,url,process)
                async with asyncio.timeout(20):
                    while (await client.get(url+'/ready')).status_code != 200:
                        assert process.poll() is None
                        await asyncio.sleep(.2)
                with replicas[1]() as db:
                    assert db.execute(text('SELECT COUNT(*) FROM schema_migrations WHERE version=:version'),
                        {'version':RUNTIME_SCHEMA_VERSION}).scalar_one() == 1
                    async with asyncio.timeout(10):
                        while not db.query(ExecutionWorkerRecord).filter_by(runtime_id=runtime_id).count():
                            db.rollback()
                            await asyncio.sleep(.1)
            await asyncio.to_thread(stop,process)
            health_key = ':'.join((prefix,'health','workers-v2',prefix,'a'*40,runtime_id))
            assert store.zcard(health_key) == 0
            with replicas[1]() as db:
                lanes = db.query(ExecutionWorkerRecord).filter_by(runtime_id=runtime_id).all()
                assert len(lanes) == 1 and lanes[0].draining_at is not None
        finally:
            if process is not None:
                await asyncio.to_thread(stop,process)
            keys = list(store.scan_iter(match=prefix+':*'))
            if keys:
                store.delete(*keys)
            store.close()
