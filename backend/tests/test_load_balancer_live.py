"""Real Nginx + two mount-free API containers + isolated worker, no host ports.

Explicitly opt in on the resource-limited audit runner. Builds COPY-only images
from already-installed local bases; no registry pull and no production targets.
"""
import asyncio
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
import pytest
import redis
from sqlalchemy import text
from websockets.asyncio.client import connect

from app.initialize import initialize
from app.models import database as m
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
    containers, images = [], []
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
        'CORS_ORIGINS':'http://audit-lb.test'}
    env['DEPLOYMENT_SHA'] = '0123456789abcdef0123456789abcdef01234567'

    def start(image, role, command, *, worker=False):
        mounts = {'/var/run/docker.sock':{'bind':'/var/run/docker.sock','mode':'rw'},
            sandbox:{'bind':sandbox,'mode':'rw'}} if worker else {}
        container = client.containers.run(image.id, command=command, entrypoint=[],
            name=prefix+'-'+role, labels={'webcompiler.audit':run_id}, environment=env,
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
                    if result.status_code == 200 and result.json()['status'] == 'completed':
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
            # New phase: only this fixture's rate buckets are reset. This tests
            # a full window across both live replicas, without extra compilation.
            keys = list(store.scan_iter(match=prefix+':rate_limit:*'))
            if keys:
                store.delete(*keys)
            responses = []
            started = time.monotonic()
            for number in range(16):
                responses.append(await http.post(url+'/api/v1/executions',json=payload,
                    headers={'X-Request-ID':request_id,'X-Forwarded-For':f'198.51.100.{number+1}'}))
            assert time.monotonic()-started < 60
            assert [r.status_code for r in responses].count(202) == 8
            assert [r.status_code for r in responses].count(429) == 8
            assert all(r.headers.get('retry-after') for r in responses if r.status_code == 429)
            assert {final_upstream(r.headers['x-audit-upstream']) for r in responses} == set(endpoints)
            with replicas[0]() as db:
                assert db.query(m.ExecutionJob).count() == 2
                assert db.get(m.ExecutionJob,job_id).attempts == 1
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
