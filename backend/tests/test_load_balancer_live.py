"""Real Nginx + two mount-free API containers + isolated worker, no host ports.

Explicitly opt in on the resource-limited audit runner. Builds COPY-only images
from already-installed local bases; no registry pull and no production targets.
"""
import asyncio
from datetime import datetime, timedelta, timezone
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import tarfile
import time
from uuid import uuid4

import docker
from docker.types import LogConfig
import httpx
import jwt
import pytest
import redis
from sqlalchemy import text
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from app.initialize import initialize
from app.models import database as m
from app.services.auth import ALGORITHM
from tests.test_durable_queue import replicas
from tests.test_terminal_live import receive_until
from tests.proxy_helpers import final_upstream

pytestmark = pytest.mark.skipif(os.getenv('RUN_LB_INTEGRATION') != '1',
    reason='Explicit isolated multi-container audit test required')


def build_image(client, *, tag, base, files, label, buildargs=None):
    # Docker SDK's build context contains only explicitly supplied app/config
    # files, never .env, repository metadata, credentials, or a workspace root.
    context = io.BytesIO()
    dockerfile = f'FROM {base}\nCOPY . /app/\nWORKDIR /app\nENV PYTHONDONTWRITEBYTECODE=1\n'
    files = {'Dockerfile':dockerfile.encode(), **files}
    with tarfile.open(fileobj=context, mode='w') as archive:
        for name, data in files.items():
            entry = tarfile.TarInfo(name)
            entry.size, entry.mode = len(data), 0o644
            archive.addfile(entry, io.BytesIO(data))
    context.seek(0)
    image, _ = client.images.build(fileobj=context, custom_context=True, tag=tag,
        pull=False, rm=True, forcerm=True, labels={'webcompiler.audit':label},buildargs=buildargs or {})
    return image


async def wait_http(http, url, status=200):
    async with asyncio.timeout(35):
        while True:
            try:
                response = await http.get(url)
                if response.status_code == status:
                    return response
            except httpx.HTTPError:
                pass
            await asyncio.sleep(.2)


@pytest.mark.asyncio
@pytest.mark.parametrize('replicas', ['postgres'], indirect=True)
async def test_proxy_distribution_api_loss_restart_shared_limits_and_websocket(replicas):
    assert os.getenv('TEST_REDIS_URL') and os.getenv('TEST_POSTGRES_URL')
    client = docker.from_env(timeout=15)
    parent = client.containers.get(socket.gethostname())
    project = parent.labels.get('com.docker.compose.project', '')
    assert project.startswith('webcompiler-audit-')
    network = project+'_default'
    assert network in parent.attrs['NetworkSettings']['Networks']
    base = parent.attrs['Config']['Image']
    assert base.startswith('webcompiler-audit-tests:')
    client.images.get('nginx:1.30.4-alpine-slim@sha256:77da26c31397bf6694b4bf93275f5b40b0b120ba1b8f114264b603e592c561d6')  # fail, never pull an unexpected image
    run_id = uuid4().hex
    prefix = 'audit-lb-'+run_id
    containers, images, unique_clients = [], [], []
    store = redis.Redis.from_url(os.environ['TEST_REDIS_URL'])
    engine = replicas[0].kw['bind']
    initialize(bind=engine)
    with engine.connect() as db:
        schema = db.execute(text('SELECT current_schema()')).scalar_one()
    assert schema.startswith('audit_queue_')
    sandbox = os.environ['SANDBOX_WORKDIR_ROOT']
    assert sandbox.startswith(os.environ['AUDIT_ROOT']+'/')
    env = {'ENVIRONMENT':'development', 'AUTO_INITIALIZE_DB':'false', 'EMBEDDED_EXECUTION_WORKER':'false',
        'DATABASE_URL':os.environ['TEST_POSTGRES_URL'], 'PGOPTIONS':'-csearch_path='+schema,
        'REDIS_URL':os.environ['TEST_REDIS_URL'], 'REDIS_KEY_PREFIX':prefix,
        'SECRET_KEY':'isolated-lb-test-secret-012345678901234567890',
        'COMPILER_QUEUE_CONCURRENCY':'1', 'EXECUTION_QUEUE_CAPACITY':'8',
        'EXECUTION_QUEUE_PER_OWNER':'4', 'EXECUTION_IP_RATE_LIMIT':'8',
        'SANDBOX_POOL_ID':prefix, 'SANDBOX_IMAGE':os.environ['SANDBOX_IMAGE'],
        'SANDBOX_WORKDIR_ROOT':sandbox, 'SANDBOX_CPU_LIMIT':'0.25',
        'SANDBOX_MEMORY_MB':'256', 'EXECUTION_TIMEOUT':'10',
        'TERMINAL_CONNECTION_LEASE_SECONDS':'3', 'TERMINAL_SESSION_TIMEOUT':'30',
        'CORS_ORIGINS':'http://audit-lb.test'}
    env['DEPLOYMENT_SHA'] = '0123456789abcdef0123456789abcdef01234567'

    def start(image, role, command, *, worker=False, environment=None):
        mounts = {'/var/run/docker.sock':{'bind':'/var/run/docker.sock','mode':'rw'},
            sandbox:{'bind':sandbox,'mode':'rw'}} if worker else {}
        container = client.containers.run(image.id, command=command, entrypoint=[],
            name=prefix+'-'+role, labels={'webcompiler.audit':run_id},
            environment=env if environment is None else environment,
            network=network, detach=True,
            networking_config={network:client.api.create_endpoint_config(aliases=[prefix+'-api'])} if role.startswith('api-') else None,
            user=f'{os.stat(sandbox).st_uid}:{os.stat(sandbox).st_gid}' if worker else '10001:10001',
            group_add=[str(os.stat('/var/run/docker.sock').st_gid)] if worker else [],
            read_only=True, volumes=mounts, cap_drop=['ALL'], security_opt=['no-new-privileges'],
            tmpfs={'/tmp':'rw,noexec,nosuid,size=64m,mode=1777'}, pids_limit=96,
            mem_limit='384m' if worker else '256m', memswap_limit='384m' if worker else '256m',
            nano_cpus=250_000_000, log_config=LogConfig(type='json-file',config={'max-size':'1m','max-file':'1'}))
        containers.append(container)
        container.reload()
        assert container.attrs['HostConfig']['PortBindings'] in ({}, None)
        return container

    def address(container):
        container.reload()
        return container.attrs['NetworkSettings']['Networks'][network]['IPAddress']

    try:
        root = Path(__file__).resolve().parents[1]
        files = {'app/'+str(path.relative_to(root/'app')).replace('\\','/'):path.read_bytes()
            for path in (root/'app').rglob('*.py')}
        app_image = await asyncio.to_thread(build_image, client, tag='webcompiler-audit-runtime:'+run_id,
            base=base, files=files, label=run_id)
        images.append(app_image)
        command = ['python','-m','uvicorn','app.main:app','--host','0.0.0.0','--port','8000',
            '--no-proxy-headers','--log-level','error']
        apis = [await asyncio.to_thread(start,app_image,'api-'+str(number),command) for number in range(2)]
        for api in apis:
            assert all(mount['Type'] == 'tmpfs' for mount in api.attrs['Mounts'])
            check = api.exec_run(['python','-c',
                "import os; assert os.geteuid()==10001; assert not os.path.exists('/var/run/docker.sock'); assert not os.access('/app/app/main.py',os.W_OK)"])
            assert check.exit_code == 0
        endpoints = [address(api)+':8000' for api in apis]
        async with httpx.AsyncClient(timeout=5) as probe:
            for endpoint in endpoints:
                health = await wait_http(probe,'http://'+endpoint+'/health')
                assert health.json()['deploymentSha'] == env['DEPLOYMENT_SHA']
                assert health.headers['cache-control'] == 'no-store'
        spec = importlib.util.spec_from_file_location('audit_proxy',Path('/scripts/render_api_proxy.py'))
        renderer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(renderer)
        proxy_image = await asyncio.to_thread(build_image, client, tag='webcompiler-audit-proxy:'+run_id,
            base='nginx:1.30.4-alpine-slim@sha256:77da26c31397bf6694b4bf93275f5b40b0b120ba1b8f114264b603e592c561d6', files={'nginx.conf':renderer.render([prefix+'-api:8000'],
                diagnostic_header=True,resolve_docker=True).encode()}, label=run_id)
        images.append(proxy_image)
        proxy = await asyncio.to_thread(start,proxy_image,'proxy',['nginx','-c','/app/nginx.conf','-g','daemon off;'])
        url = 'http://'+address(proxy)+':8080'
        async with httpx.AsyncClient(timeout=8) as http:
            await wait_http(http,url+'/health')
            seen = {final_upstream((await http.get(url+'/health')).headers['x-audit-upstream']) for _ in range(12)}
            assert seen == set(endpoints)
            request_id = str(uuid4())
            payload = {'code':'print(42)','language':'python'}
            receipt = await http.post(url+'/api/v1/executions',json=payload,headers={'X-Request-ID':request_id})
            assert receipt.status_code == 202
            job_id = receipt.json()['id']
            accepted_by = final_upstream(receipt.headers['x-audit-upstream'])
            killed = apis[endpoints.index(accepted_by)]
            await asyncio.to_thread(killed.kill)
            surviving = await wait_http(http,url+'/api/v1/executions/'+job_id)
            assert surviving.json()['status'] == 'queued'
            assert final_upstream(surviving.headers['x-audit-upstream']) != accepted_by
            worker = await asyncio.to_thread(start,app_image,'worker',['python','-m','app.worker'],worker=True)
            check = worker.exec_run(['python','-c',
                "import os; from app.core.config import settings; assert os.access(settings.SANDBOX_WORKDIR_ROOT,os.W_OK); assert os.access('/var/run/docker.sock',os.W_OK)"])
            assert check.exit_code == 0
            async with asyncio.timeout(35):
                while True:
                    result = await http.get(url+'/api/v1/executions/'+job_id)
                    if result.status_code == 200 and result.json()['status'] in ('completed','failed'):
                        assert result.json()['status'] == 'completed', result.json()
                        break
                    await asyncio.sleep(.2)
            assert result.json()['result']['value']['stdout'].strip() == '42'
            probe_result = proxy.exec_run(['wget','-q','-O','/dev/null','http://127.0.0.1:8080/ready'])
            assert probe_result.exit_code == 0, probe_result.output
            async with connect(url.replace('http:','ws:')+'/ws/terminal',origin='http://audit-lb.test') as ws:
                await ws.send(json.dumps({'type':'start','language':'python',
                    'code':"print('waiting',flush=True)\ns=input()\nprint('echo:'+s,flush=True)"}))
                await receive_until(ws,'waiting')
                await ws.send('안녕\n')
                assert 'echo:안녕' in await receive_until(ws,'프로그램이 종료')
            await asyncio.to_thread(killed.start)
            await wait_http(http,'http://'+address(killed)+':8000/health')
            endpoints = [address(api)+':8000' for api in apis]
            # Let Nginx's short failed-peer quarantine expire before probing.
            async with asyncio.timeout(8):
                seen = set()
                while seen != set(endpoints):
                    response = await http.get(url+'/health')
                    assert response.status_code == 200
                    seen.add(final_upstream(response.headers['x-audit-upstream']))
                    await asyncio.sleep(.1)
            # Kill the exact API holding an active terminal WebSocket. The
            # durable terminal receipt must be canceled once that API's Redis
            # connection lease expires, and the surviving peer must accept a
            # fresh terminal without replaying the interrupted program.
            with replicas[0]() as db:
                terminal_before = {row.id for row in db.query(m.ExecutionJob).filter_by(kind='terminal').all()}
            crashed_peer = None
            with pytest.raises(ConnectionClosed):
                async with connect(url.replace('http:','ws:')+'/ws/terminal',origin='http://audit-lb.test') as ws:
                    crashed_peer = final_upstream(ws.response.headers['x-audit-upstream'])
                    assert crashed_peer in endpoints
                    await ws.send(json.dumps({'type':'start','language':'python',
                        'code':"print('lb-api-crash',flush=True)\ninput()"}))
                    await receive_until(ws,'lb-api-crash')
                    with replicas[0]() as db:
                        crash_jobs = [row.id for row in db.query(m.ExecutionJob).filter_by(kind='terminal').all()
                                      if row.id not in terminal_before]
                    assert len(crash_jobs) == 1
                    crashed_api = apis[endpoints.index(crashed_peer)]
                    await asyncio.to_thread(crashed_api.kill)
                    async with asyncio.timeout(5):
                        while True:
                            await ws.recv()
            async with asyncio.timeout(15):
                while True:
                    with replicas[0]() as db:
                        crashed_job = db.get(m.ExecutionJob, crash_jobs[0])
                        state = crashed_job.status, (crashed_job.result or {}).get('verdict'), crashed_job.attempts
                    if state[0] == 'completed':
                        break
                    await asyncio.sleep(.2)
            assert state == ('completed','canceled',1)
            async with connect(url.replace('http:','ws:')+'/ws/terminal',origin='http://audit-lb.test') as ws:
                assert final_upstream(ws.response.headers['x-audit-upstream']) != crashed_peer
                await ws.send(json.dumps({'type':'start','language':'python',
                    'code':"print('survivor-terminal',flush=True)"}))
                assert 'survivor-terminal' in await receive_until(ws,'프로그램이 종료')
            await asyncio.to_thread(crashed_api.start)
            await wait_http(http,'http://'+address(crashed_api)+':8000/health')
            endpoints = [address(api)+':8000' for api in apis]
            async with asyncio.timeout(8):
                seen = set()
                while seen != set(endpoints):
                    response = await http.get(url+'/health')
                    assert response.status_code == 200
                    seen.add(final_upstream(response.headers['x-audit-upstream']))
                    await asyncio.sleep(.1)
            # New phase: only this fixture's rate buckets are reset. This tests
            # a full window across both live replicas, without extra compilation.
            keys = list(store.scan_iter(match=prefix+':rate_limit:*'))
            if keys:
                store.delete(*keys)
            with replicas[0]() as db:
                jobs_before_idempotent_ramp = db.query(m.ExecutionJob).count()
            responses = []
            started = time.monotonic()
            concurrency = asyncio.Semaphore(10)

            async def submit(number):
                async with concurrency:
                    return await http.post(url+'/api/v1/executions',json=payload,
                        headers={'X-Request-ID':request_id,
                                 'X-Forwarded-For':f'198.51.100.{number+1}'})

            # One cumulative rate window ramps through 10 -> 50 -> 100 actual
            # proxy requests. The same request ID makes accepted retries safe;
            # the shared Redis admission budget must still cap the window at 8.
            for target in (10,50,100):
                batch = await asyncio.gather(*(submit(number) for number in range(len(responses),target)))
                responses.extend(batch)
                statuses = [response.status_code for response in responses]
                assert statuses.count(202) == 8
                assert statuses.count(429) == target-8
                assert set(statuses) == {202,429}
            assert time.monotonic()-started < 120
            assert all(r.headers.get('retry-after') for r in responses if r.status_code == 429)
            assert {final_upstream(r.headers['x-audit-upstream']) for r in responses} == set(endpoints)
            with replicas[0]() as db:
                assert db.query(m.ExecutionJob).count() == jobs_before_idempotent_ramp
                assert db.get(m.ExecutionJob,job_id).attempts == 1
            # A second rate window uses one real terminal plus distinct HTTP
            # owners and request IDs. Exactly eight unique receipts are admitted
            # across both protocols; every accepted HTTP job completes once.
            keys = list(store.scan_iter(match=prefix+':rate_limit:*'))
            if keys:
                store.delete(*keys)
            usernames = [prefix+'-owner-'+str(number) for number in range(9)]
            with replicas[0]() as db:
                db.add_all([m.User(username=username,hashed_password='not-used',auth_version=0)
                            for username in usernames])
                db.commit()
            expires = datetime.now(timezone.utc)+timedelta(minutes=5)
            owner_tokens = [jwt.encode({'sub':username,'ver':0,'exp':expires},env['SECRET_KEY'],
                                       algorithm=ALGORITHM) for username in usernames]
            with replicas[0]() as db:
                jobs_before_unique = db.query(m.ExecutionJob).count()
            async with connect(url.replace('http:','ws:')+'/ws/terminal',origin='http://audit-lb.test') as unique_ws:
                await unique_ws.send(json.dumps({'type':'start','language':'python',
                    'code':"print('unique-window',flush=True)\ns=input()\nprint(s,flush=True)"}))
                await receive_until(unique_ws,'unique-window')

                async def unique_submit(number):
                    client_for_receipt = httpx.AsyncClient(timeout=8,
                        headers={'Authorization':'Bearer '+owner_tokens[number]})
                    unique_clients.append(client_for_receipt)
                    response = await client_for_receipt.post(url+'/api/v1/executions',json=payload,
                        headers={'X-Request-ID':str(uuid4())})
                    return client_for_receipt,response

                unique_responses = await asyncio.gather(*(unique_submit(number) for number in range(9)))
                assert [response.status_code for _,response in unique_responses].count(202) == 7
                assert [response.status_code for _,response in unique_responses].count(429) == 2
                assert all(response.headers.get('retry-after') for _,response in unique_responses
                           if response.status_code == 429)
                assert {final_upstream(response.headers['x-audit-upstream'])
                        for _,response in unique_responses} == set(endpoints)
                await unique_ws.send('done\n')
                assert 'done' in await receive_until(unique_ws,'프로그램이 종료')

            accepted = [(client_for_receipt,response.json()['id'])
                        for client_for_receipt,response in unique_responses if response.status_code == 202]
            assert len({job for _,job in accepted}) == 7

            async def completed_once(client_for_receipt, accepted_job):
                async with asyncio.timeout(90):
                    while True:
                        response = await client_for_receipt.get(url+'/api/v1/executions/'+accepted_job)
                        assert response.status_code == 200
                        if response.json()['status'] == 'completed':
                            assert response.json()['result']['value']['stdout'].strip() == '42'
                            return
                        await asyncio.sleep(.2)

            await asyncio.gather(*(completed_once(*item) for item in accepted))
            with replicas[0]() as db:
                assert db.query(m.ExecutionJob).count() == jobs_before_unique + 8
                for _,accepted_job in accepted:
                    row = db.get(m.ExecutionJob,accepted_job)
                    assert row.status == 'completed' and row.attempts == 1
            # DNS membership must grow/shrink without regenerating the proxy
            # or losing previously committed receipts. No extra code is run.
            third = await asyncio.to_thread(start,app_image,'api-2',command)
            await wait_http(http,'http://'+address(third)+':8000/health')
            expanded = set(endpoints+[address(third)+':8000'])
            async with asyncio.timeout(12):
                seen = set()
                while seen != expanded:
                    response = await http.get(url+'/api/v1/executions/'+job_id)
                    assert response.status_code == 200 and response.json()['status'] == 'completed'
                    seen.add(final_upstream(response.headers['x-audit-upstream']))
                    await asyncio.sleep(.1)
            await asyncio.to_thread(third.stop,timeout=15)
            # A removed endpoint can appear once in the upstream retry trace;
            # each final response must come from a surviving peer and succeed.
            async with asyncio.timeout(12):
                seen = set()
                while seen != set(endpoints):
                    response = await http.get(url+'/api/v1/executions/'+job_id)
                    assert response.status_code == 200 and response.json()['status'] == 'completed'
                    peer = final_upstream(response.headers['x-audit-upstream'])
                    assert peer in endpoints
                    seen.add(peer)
                    await asyncio.sleep(.1)
            await asyncio.to_thread(worker.stop,timeout=15)
            await wait_http(http,url+'/ready',status=503)
            assert proxy.exec_run(['wget','-q','-O','/dev/null','http://127.0.0.1:8080/ready']).exit_code != 0
            # A definitive Docker ImageNotFound response must settle the exact
            # create journal and remove every per-attempt work directory. It is
            # safe to retry as a system error, but it must not retain capacity
            # or require an impossible observation of a container that never
            # existed.
            assert list(Path(sandbox).iterdir()) == []
            keys = list(store.scan_iter(match=prefix+':rate_limit:*'))
            if keys:
                store.delete(*keys)
            missing_receipt = await http.post(url+'/api/v1/executions',json=payload,
                headers={'X-Request-ID':str(uuid4())})
            assert missing_receipt.status_code == 202
            missing_job = missing_receipt.json()['id']
            missing_env = {**env,'SANDBOX_IMAGE':'sha256:'+'0'*64}
            missing_worker = await asyncio.to_thread(start,app_image,'missing-worker',
                ['python','-m','app.worker'],worker=True,environment=missing_env)
            async with asyncio.timeout(35):
                while True:
                    failed = await http.get(url+'/api/v1/executions/'+missing_job)
                    if failed.status_code == 200 and failed.json()['status'] == 'completed':
                        break
                    await asyncio.sleep(.2)
            assert failed.json()['result']['verdict'] == 'system_error'
            with replicas[0]() as db:
                missing_row = db.get(m.ExecutionJob,missing_job)
                assert missing_row.attempts == 3 and missing_row.sandbox_operation is None
            await asyncio.to_thread(missing_worker.stop,timeout=15)
            assert list(Path(sandbox).iterdir()) == []
    except Exception:
        # These are newly-created test services only. Redact even the isolated
        # credentials before showing bounded startup diagnostics on failure.
        for container in containers:
            container.reload()
            log = container.logs(tail=12).decode(errors='replace')[-2500:]
            for name in ('DATABASE_URL','SECRET_KEY','REDIS_URL'):
                log = log.replace(env[name], '[redacted]')
            print(container.name, container.status, log)
        raise
    finally:
        for client_for_receipt in unique_clients:
            await client_for_receipt.aclose()
        # Only handles created here and exact matching fixture labels may be
        # stopped/removed. Never prune global Docker state or touch production.
        for container in reversed(containers):
            container.reload()
            assert container.labels.get('webcompiler.audit') == run_id
            if container.status == 'running':
                container.stop(timeout=15)
            container.remove(force=True)
        for sandbox_container in client.containers.list(all=True,filters={'label':'webcompiler.pool='+prefix}):
            assert sandbox_container.labels.get('webcompiler.pool') == prefix
            sandbox_container.remove(force=True)
        for image in reversed(images):
            assert image.labels.get('webcompiler.audit') == run_id
            client.images.remove(image.id)
        keys = list(store.scan_iter(match=prefix+':*'))
        if keys:
            store.delete(*keys)
        store.close()
        client.close()
