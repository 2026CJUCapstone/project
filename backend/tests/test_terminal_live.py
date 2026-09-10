"""Actual WebSocket -> Redis -> separate worker -> isolated Docker tests."""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import text
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from app.models import database as m
from tests.test_durable_queue import replicas
from tests.test_execution_http_live import healthy, port, stop

pytestmark = pytest.mark.skipif(os.getenv('RUN_SANDBOX_INTEGRATION') != '1' or not os.getenv('TEST_REDIS_URL'),
    reason='Explicit isolated Docker and Redis test host required')


async def receive_until(ws, needle):
    output = ''
    async with asyncio.timeout(25):
        while needle not in output:
            output += await ws.recv()
    return output


@pytest.mark.asyncio
async def test_interactive_input_disconnect_and_worker_crash_do_not_replay(replicas):
    engine = replicas[0].kw['bind']
    prefix = 'audit-terminal-'+uuid4().hex
    child_env = dict(os.environ, AUTO_INITIALIZE_DB='false', EMBEDDED_EXECUTION_WORKER='false',
        COMPILER_QUEUE_CONCURRENCY='1', EXECUTION_QUEUE_CAPACITY='8', EXECUTION_LEASE_SECONDS='3',
        TERMINAL_CONNECTION_LEASE_SECONDS='6', TERMINAL_SESSION_TIMEOUT='45',
        REDIS_KEY_PREFIX=prefix, SANDBOX_POOL_ID=prefix, REDIS_URL=os.environ['TEST_REDIS_URL'],
        CORS_ORIGINS='http://terminal.test')
    if engine.dialect.name == 'postgresql':
        with engine.connect() as db:
            schema = db.execute(text('SELECT current_schema()')).scalar_one()
        assert schema.startswith('audit_queue_')
        child_env.update(DATABASE_URL=os.environ['TEST_POSTGRES_URL'],PGOPTIONS='-csearch_path='+schema)
    else:
        child_env['DATABASE_URL'] = str(engine.url)
    root = Path(__file__).resolve().parents[1]
    processes = []
    api_port = port()
    url, ws_url = f'http://127.0.0.1:{api_port}', f'ws://127.0.0.1:{api_port}/ws/terminal'
    def states():
        with replicas[1]() as db:
            return [(j.id,j.status,(j.result or {}).get('verdict'),j.attempts) for j in db.query(m.ExecutionJob).order_by(m.ExecutionJob.received_at).all()]
    with tempfile.TemporaryFile() as log:
        def spawn_worker():
            worker = subprocess.Popen([sys.executable,'-m','app.worker'],cwd=root,env=child_env,stdout=log,stderr=log)
            processes.append(worker)
            return worker
        try:
            processes.append(subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1',
                '--port',str(api_port),'--no-proxy-headers','--log-level','error'],cwd=root,
                env=dict(child_env,DOCKER_HOST='tcp://127.0.0.1:1'),stdout=log,stderr=log))
            async with httpx.AsyncClient(timeout=5) as client:
                await healthy(client,url,processes[0])
                worker = spawn_worker()
                async with connect(ws_url,origin='http://terminal.test') as ws:
                    await ws.send(json.dumps({'type':'start','language':'python',
                        'code':"print('ready',flush=True)\ns=input()\nprint('result:'+s,flush=True)"}))
                    await receive_until(ws,'ready')
                    await ws.send('안녕\n')
                    assert 'result:안녕' in await receive_until(ws,'프로그램이 종료')
                assert states()[0][1:] == ('completed','finished',1)
                async with connect(ws_url,origin='http://terminal.test') as ws:
                    await ws.send(json.dumps({'type':'start','language':'python','code':"print('waiting',flush=True)\ninput()"}))
                    await receive_until(ws,'waiting')
                async with asyncio.timeout(10):
                    while states()[-1][1] != 'completed':
                        await asyncio.sleep(.1)
                assert states()[-1][2:] == ('canceled',1)
                async with connect(ws_url,origin='http://terminal.test') as ws:
                    await ws.send(json.dumps({'type':'start','language':'python','code':"print('before-crash',flush=True)\ninput()"}))
                    await receive_until(ws,'before-crash')
                    worker.kill()
                    await asyncio.to_thread(worker.wait,timeout=5)
                    spawn_worker()
                    message = await receive_until(ws,'자동으로 다시 실행하지 않습니다')
                    assert '중단' in message
                assert states()[-1][1:] == ('failed','canceled',1)
                # The reaped interactive job cannot block the next ordinary job.
                response = await client.post(url+'/api/v1/executions',json={'code':'print(42)','language':'python'})
                assert response.status_code == 202
                async with asyncio.timeout(15):
                    while True:
                        result = (await client.get(url+'/api/v1/executions/'+response.json()['id'])).json()
                        if result['status']=='completed': break
                        await asyncio.sleep(.1)
                assert result['result']['value']['stdout'].strip() == '42'
                # API crash skips route finally; its renewable Redis connection
                # lease must still stop the separate worker's waiting sandbox.
                async with connect(ws_url,origin='http://terminal.test') as ws:
                    await ws.send(json.dumps({'type':'start','language':'python','code':"print('api-crash',flush=True)\ninput()"}))
                    await receive_until(ws,'api-crash')
                    processes[0].kill()
                    await asyncio.to_thread(processes[0].wait,timeout=5)
                    with pytest.raises(ConnectionClosed):
                        async with asyncio.timeout(5):
                            await ws.recv()
                async with asyncio.timeout(12):
                    while states()[-1][1] != 'completed':
                        await asyncio.sleep(.1)
                assert states()[-1][2:] == ('canceled',1)
        finally:
            for process in reversed(processes):
                await asyncio.to_thread(stop,process)
            # Only the test's UUID namespace; no operational Redis keys.
            from redis import Redis
            client = Redis.from_url(os.environ['TEST_REDIS_URL'],decode_responses=True)
            keys = list(client.scan_iter(match=prefix+':*'))
            if keys: client.delete(*keys)
            client.close()
