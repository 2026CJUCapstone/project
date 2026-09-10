"""Actual API replicas, streaming HTTP and established WS across a DB drain."""
import asyncio
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import text
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from app.models.database import ApiProcessRecord
from app.services.runtime_identity import RuntimeIdentity
from app.services.runtime_registry import RuntimeRegistry
from tests.test_durable_queue import replicas
from tests.test_execution_http_live import healthy, port, stop

pytestmark = pytest.mark.skipif(os.getenv('RUN_SANDBOX_INTEGRATION') != '1' or not os.getenv('TEST_REDIS_URL'),
    reason='Explicit isolated process/Redis integration host required')


@pytest.mark.asyncio
async def test_real_replicas_drain_held_http_and_ws_without_admitting_new_requests(replicas):
    engine = replicas[0].kw['bind']
    prefix = 'audit-api-lifetime-'+uuid4().hex
    blue = RuntimeIdentity(uuid4().hex, prefix+'-blue', 'a'*40, prefix)
    green = RuntimeIdentity(uuid4().hex, prefix+'-green', 'a'*40, prefix)
    env = dict(os.environ, ENVIRONMENT='production', AUTO_INITIALIZE_DB='false',
        EMBEDDED_EXECUTION_WORKER='false', REDIS_URL=os.environ['TEST_REDIS_URL'],
        REDIS_KEY_PREFIX=prefix, SANDBOX_POOL_ID=prefix, DEPLOYMENT_SHA='a'*40,
        DOCKER_HOST='tcp://127.0.0.1:1')
    if engine.dialect.name == 'postgresql':
        with engine.connect() as db:
            schema = db.execute(text('SELECT current_schema()')).scalar_one()
        assert schema.startswith('audit_queue_')
        env.update(DATABASE_URL=os.environ['TEST_POSTGRES_URL'], PGOPTIONS='-csearch_path='+schema)
    else:
        env['DATABASE_URL'] = str(engine.url)
    root = Path(__file__).resolve().parents[1]
    registry = RuntimeRegistry(replicas[0])
    processes, urls = [], []
    with tempfile.TemporaryFile() as log:
        try:
            for runtime in (blue, blue, green):
                api_port = port()
                child = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'tests.api_lifecycle_server:app',
                    '--host', '127.0.0.1', '--port', str(api_port), '--no-proxy-headers', '--log-level', 'error'],
                    cwd=root, env=dict(env, RUNTIME_POOL_ID=runtime.pool_id, RUNTIME_INSTANCE_ID=runtime.id),
                    stdout=log, stderr=log)
                processes.append(child)
                urls.append(f'http://127.0.0.1:{api_port}')
            async with httpx.AsyncClient(timeout=8) as client:
                for url, process in zip(urls, processes):
                    await healthy(client, url, process)
                    assert (await client.get(url+'/audit-ping')).status_code == 200
                async with connect(urls[0].replace('http:', 'ws:')+'/audit-socket') as ws:
                    assert await ws.recv() == 'connected'
                    async with client.stream('GET', urls[0]+'/audit-stream') as response:
                        assert response.status_code == 200
                        lines = response.aiter_lines()
                        assert await anext(lines) == 'first'
                        await asyncio.to_thread(registry.begin_drain, blue)
                        assert registry.status(blue)['active_http'] == 1
                        assert registry.status(blue)['active_websockets'] == 1
                        for url in urls[:2]:
                            assert (await client.get(url+'/audit-ping')).status_code == 503
                            assert (await client.get(url+'/health')).status_code == 200
                            assert (await client.get(url+'/ready')).status_code == 503
                            # A pre-accept ASGI close becomes an HTTP 403 handshake refusal.
                            with pytest.raises(InvalidStatus) as refused:
                                async with connect(url.replace('http:', 'ws:')+'/audit-socket'):
                                    pytest.fail('Drained API admitted a new WebSocket')
                            assert refused.value.response.status_code == 403
                        assert (await client.get(urls[2]+'/audit-ping')).status_code == 200
                        await ws.send('release')
                        assert await ws.recv() == 'released'
                        assert await anext(lines) == 'last'
                        with pytest.raises(StopAsyncIteration):
                            await anext(lines)
                    await ws.send('close')
                    await ws.wait_closed()
                async with asyncio.timeout(8):
                    while registry.status(blue)['active_http'] or registry.status(blue)['active_websockets']:
                        await asyncio.sleep(.05)
                # Graceful lifecycle is recorded for both API processes, not
                # inferred merely from zero requests. No container retirement.
                for process in processes[:2]:
                    await asyncio.to_thread(stop, process)
                    # Uvicorn 0.52 re-raises the captured SIGTERM after its
                    # graceful lifespan shutdown. The DB assertion below is
                    # the evidence of completed lifecycle, not exit code alone.
                    assert process.returncode in (0, -signal.SIGTERM)
                with replicas[0]() as db:
                    rows = db.query(ApiProcessRecord).filter_by(runtime_id=blue.id).all()
                    assert len(rows) == 2 and all(row.stopped_at is not None for row in rows)
                assert (await client.get(urls[2]+'/audit-ping')).status_code == 200
                async with connect(urls[2].replace('http:', 'ws:')+'/audit-socket') as ws:
                    assert await ws.recv() == 'connected'
                    assert registry.status(green)['active_websockets'] == 1
                    processes[2].kill()  # Only this fixture's API process.
                    await asyncio.to_thread(processes[2].wait, timeout=5)
                    with pytest.raises(ConnectionClosed):
                        await ws.recv()
                # A crash must not fabricate graceful completion or erase an
                # unresolved socket just because the transport disappeared.
                assert registry.status(green)['active_websockets'] == 1
                with replicas[0]() as db:
                    old = db.query(ApiProcessRecord).filter_by(runtime_id=green.id).one()
                    old_id = old.id
                    assert old.stopped_at is None
                api_port = port()
                replacement = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'tests.api_lifecycle_server:app',
                    '--host', '127.0.0.1', '--port', str(api_port), '--no-proxy-headers', '--log-level', 'error'],
                    cwd=root, env=dict(env, RUNTIME_POOL_ID=green.pool_id, RUNTIME_INSTANCE_ID=green.id),
                    stdout=log, stderr=log)
                processes.append(replacement)
                replacement_url = f'http://127.0.0.1:{api_port}'
                await healthy(client, replacement_url, replacement)
                assert (await client.get(replacement_url+'/audit-ping')).status_code == 200
                assert registry.status(green)['active_websockets'] == 1
                with replicas[0]() as db:
                    rows = db.query(ApiProcessRecord).filter_by(runtime_id=green.id).all()
                    assert len(rows) == 2 and {row.id for row in rows} != {old_id}
                    assert db.get(ApiProcessRecord, old_id).stopped_at is None
        finally:
            for process in processes:
                await asyncio.to_thread(stop, process)
