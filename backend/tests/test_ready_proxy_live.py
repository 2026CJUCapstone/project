"""Actual API/worker + Nginx/controller failure transitions, isolated Docker only."""
import asyncio
import ipaddress
import json
import os
import re
from pathlib import Path
import shutil
import socket
import tempfile
from uuid import uuid4

import docker
from docker.types import LogConfig
import httpx
import pytest
import redis
from sqlalchemy import text

from app.initialize import initialize
from app.services.api_proxy_config import render_managed
from tests.test_durable_queue import replicas
from tests.test_load_balancer_live import build_image, wait_http


pytestmark = pytest.mark.skipif(os.getenv('RUN_LB_INTEGRATION') != '1',
                              reason='Explicit isolated multi-container audit required')


@pytest.mark.asyncio
@pytest.mark.parametrize('replicas',['postgres'],indirect=True)
async def test_ready_only_membership_reload_and_controller_fail_closed(replicas):
    client = docker.from_env(timeout=15)
    parent = client.containers.get(socket.gethostname())
    project = parent.labels['com.docker.compose.project']
    assert project.startswith('webcompiler-audit-')
    network = project+'_default'
    assert network in parent.attrs['NetworkSettings']['Networks']
    base = parent.attrs['Config']['Image']
    assert base.startswith('webcompiler-audit-tests:')
    nginx_image = client.images.get('nginx:1.30.4-alpine-slim@sha256:77da26c31397bf6694b4bf93275f5b40b0b120ba1b8f114264b603e592c561d6')
    run_id = uuid4().hex
    prefix = 'audit-ready-'+run_id
    engine = replicas[0].kw['bind']
    initialize(bind=engine)
    with engine.connect() as db:
        schema = db.execute(text('SELECT current_schema()')).scalar_one()
    assert schema.startswith('audit_queue_')
    sandbox = os.environ['SANDBOX_WORKDIR_ROOT']
    assert sandbox.startswith(os.environ['AUDIT_ROOT']+'/')
    control = Path(tempfile.mkdtemp(prefix=prefix+'-',dir=sandbox))
    os.chmod(control,0o700)
    containers, images, private_networks = [], [], []
    api_network, frontend_network = prefix+'-api',prefix+'-frontend'
    store = redis.Redis.from_url(os.environ['TEST_REDIS_URL'])
    env = {'ENVIRONMENT':'development','AUTO_INITIALIZE_DB':'false','EMBEDDED_EXECUTION_WORKER':'false',
        'DATABASE_URL':os.environ['TEST_POSTGRES_URL'],'PGOPTIONS':'-csearch_path='+schema,
        'REDIS_URL':os.environ['TEST_REDIS_URL'],'REDIS_KEY_PREFIX':prefix,
        'SECRET_KEY':'isolated-ready-test-secret-012345678901234567890','DEPLOYMENT_SHA':'a'*40,'PROXY_POOL_ID':prefix,
        'RUNTIME_POOL_ID':prefix,'RUNTIME_INSTANCE_ID':run_id,'SANDBOX_POOL_ID':prefix,'SANDBOX_IMAGE':os.environ['SANDBOX_IMAGE'],
        'SANDBOX_WORKDIR_ROOT':sandbox,'SANDBOX_CPU_LIMIT':'0.25','SANDBOX_MEMORY_MB':'256',
        'COMPILER_QUEUE_CONCURRENCY':'1','EXECUTION_TIMEOUT':'10'}

    def start(image,role,command,*,extra=None,worker=False,proxy=None):
        initializing = role.startswith('init')
        volumes = {}
        if worker:
            volumes = {'/var/run/docker.sock':{'bind':'/var/run/docker.sock','mode':'rw'},
                       sandbox:{'bind':sandbox,'mode':'rw'}}
        if role in ('proxy','controller') or initializing:
            volumes[str(control)] = {'bind':'/control','mode':'ro' if role=='proxy' else 'rw'}
        networking = {'network':network}
        if initializing:
            networking = {'network_mode':'none'}
        if role.startswith('api'):
            networking['networking_config'] = {
                network:client.api.create_endpoint_config(),
                api_network:client.api.create_endpoint_config(aliases=[prefix+'-api'])}
        if role=='proxy':
            networking = {'network':api_network,'networking_config':{
                api_network:client.api.create_endpoint_config(),
                frontend_network:client.api.create_endpoint_config(aliases=['api-proxy'])}}
        if role=='frontend':
            networking = {'network':frontend_network}
        if proxy:
            networking = {'network_mode':'container:'+proxy.id,'pid_mode':'container:'+proxy.id}
        size = '384m' if worker else ('96m' if role in ('proxy','controller') else '128m' if role=='frontend' else '256m')
        role_env = env if worker or role.startswith('api') else {}
        if initializing or role=='controller':
            role_env = {'DEPLOYMENT_SHA':env['DEPLOYMENT_SHA'],'PROXY_POOL_ID':prefix,'RUNTIME_INSTANCE_ID':run_id}
        options = dict(image=image,command=command,detach=True,
            name=prefix+'-'+role,labels={'webcompiler.audit':run_id},environment={**role_env,'FIXTURE_INSTANCE':role,**(extra or {})},
            group_add=[str(os.stat('/var/run/docker.sock').st_gid)] if worker else [],
            volumes=volumes,read_only=True,cap_drop=['ALL'],
            cap_add=['CHOWN','DAC_OVERRIDE'] if initializing else [],
            security_opt=['no-new-privileges'],
            tmpfs={'/tmp':'rw,noexec,nosuid,size=32m,mode=1777'},pids_limit=64,
            mem_limit=size,memswap_limit=size,nano_cpus=125_000_000,
            log_config=LogConfig(type='json-file',config={'max-size':'1m','max-file':'1'}),**networking)
        # The frontend intentionally inherits its final-stage USER, ENTRYPOINT
        # and CMD. Passing root or entrypoint=[] would mask a regression.
        if role!='frontend':
            options['entrypoint'] = []
            options['user'] = ('0:0' if initializing else
                               f'{os.stat(sandbox).st_uid}:{os.stat(sandbox).st_gid}' if worker else '10001:10001')
        container = client.containers.run(**options)
        containers.append(container)
        return container

    def address(container, plane=None):
        container.reload()
        attached = container.attrs['NetworkSettings']['Networks']
        return attached[plane or (network if network in attached else frontend_network)]['IPAddress']

    try:
        # Use the exact production pin and independently verify its binary.
        version = await asyncio.to_thread(client.containers.run,nginx_image.id,
            command=['nginx','-v'],entrypoint=[],remove=True,stdout=True,stderr=True,
            network_mode='none',mem_limit='32m',memswap_limit='32m',nano_cpus=50_000_000,pids_limit=16,
            user='10001:10001',read_only=True,cap_drop=['ALL'],labels={'webcompiler.audit':run_id})
        assert b'nginx/1.30.4' in version
        for name in (api_network,frontend_network):
            private_networks.append(client.networks.create(name,driver='bridge',internal=True,
                                                           labels={'webcompiler.audit':run_id}))
        private_networks[0].reload()
        subnet = next(item['Subnet'] for item in private_networks[0].attrs['IPAM']['Config'] if ':' not in item['Subnet'])
        assert ipaddress.ip_network(subnet).prefixlen >= 16
        # Test observer only: attach the disposable runner, never a production
        # service, to inspect HTTP traffic without publishing any host port.
        private_networks[1].connect(parent)
        app_root = Path(__file__).resolve().parents[1]/'app'
        files = {'app/'+str(path.relative_to(app_root)).replace('\\','/'):path.read_bytes() for path in app_root.rglob('*.py')}
        # Instance tracing exists only in the disposable test image, not in
        # public application responses or deploy renderer configuration.
        files['ready_api.py'] = b'''import os
from app.main import app
@app.middleware('http')
async def trace(request, call_next):
    response = await call_next(request)
    response.headers['X-Fixture-Instance'] = os.environ['FIXTURE_INSTANCE']
    return response
'''
        image = await asyncio.to_thread(build_image,client,tag='webcompiler-audit-ready:'+run_id,
                                       base=base,files=files,label=run_id)
        images.append(image)
        frontend_root = Path('/frontend') if Path('/frontend/Dockerfile').exists() else Path(__file__).resolve().parents[2]/'frontend'
        # Execute the real production final Docker stage, including its strict
        # upstream build argument. Only the React build output is a fixture;
        # this is not evidence of a full frontend dependency/build pipeline.
        final_stage = frontend_root.joinpath('Dockerfile').read_text().split('FROM nginx:',1)[1]
        assert final_stage.startswith('1.30.4-alpine-slim@sha256:77da26c31397bf6694b4bf93275f5b40b0b120ba1b8f114264b603e592c561d6\n')
        frontend_files = {'Dockerfile':(f'FROM {nginx_image.id} AS build\nCOPY fixture-index.html /app/dist/index.html\nFROM '+nginx_image.id+'\n'+final_stage.split('\n',1)[1]).encode(),
                          'nginx.conf':frontend_root.joinpath('nginx.conf').read_bytes(),
                          'fixture-index.html':b'isolated frontend runtime fixture'}
        # Execute the real Dockerfile validator, not a test-local reimplementation.
        for invalid,mode,message in (
                ('a'*40+'\nignored','production','Production frontend DEPLOY_SHA must contain only lowercase hexadecimal bytes'),
                ('A'*40,'production','Production frontend DEPLOY_SHA must contain only lowercase hexadecimal bytes'),
                ('a'*39,'production','Production frontend DEPLOY_SHA must be 40 bytes'),
                ('','production','Production frontend DEPLOY_SHA must contain only lowercase hexadecimal bytes'),
                ('a'*40,'prod','Frontend ENVIRONMENT must be production, development, or test')):
            with pytest.raises(docker.errors.BuildError) as rejected:
                await asyncio.to_thread(build_image,client,tag='webcompiler-audit-invalid:'+run_id,
                    base=nginx_image.id,files=frontend_files,label=run_id,
                    buildargs={'ENVIRONMENT':mode,'DEPLOY_SHA':invalid})
            output=[re.sub(r'\x1b\[[0-9;]*m','',line).strip()
                    for event in rejected.value.build_log for line in event.get('stream','').splitlines()]
            assert message in output, '\n'.join(output)  # Fixture-only build diagnostics, never production secrets.
        frontend_image = await asyncio.to_thread(build_image,client,tag='webcompiler-audit-front:'+run_id,
            base=nginx_image.id,files=frontend_files,label=run_id,
            buildargs={'FRONTEND_API_UPSTREAM':'api-proxy:8080','ENVIRONMENT':'production','DEPLOY_SHA':'a'*40})
        images.append(frontend_image)
        initializer = await asyncio.to_thread(start,image.id,'init',['python','-m','app.proxy_initialize'])
        assert (await asyncio.to_thread(initializer.wait,timeout=15))['StatusCode'] == 0
        assert control.stat().st_uid == 10001 and control.stat().st_mode & 0o777 == 0o700
        command = ['python','-m','uvicorn','ready_api:app','--host','0.0.0.0','--port','8000',
                   '--no-proxy-headers','--log-level','error']
        apis = [await asyncio.to_thread(start,image.id,'api'+str(n),command) for n in range(2)]
        bad = await asyncio.to_thread(start,image.id,'api-wrong-release',command,
                                     extra={'DEPLOYMENT_SHA':'b'*40,'RUNTIME_INSTANCE_ID':uuid4().hex})
        worker = await asyncio.to_thread(start,image.id,'worker',['python','-m','app.worker'],worker=True)
        async with httpx.AsyncClient(timeout=4,trust_env=False) as http:
            for api in apis:
                await wait_http(http,'http://'+address(api)+':8000/ready')
            # A runtime ID is immutable. A different deployment must use a
            # distinct incarnation; conflicting reuse must fail at startup,
            # not merely become an unready peer. Start only after registration
            # so the impostor cannot win this fixture's initial identity race.
            for name, overrides in (
                    ('release', {'DEPLOYMENT_SHA':'b'*40}),
                    ('pool', {'RUNTIME_POOL_ID':prefix+'-conflict'})):
                conflict = await asyncio.to_thread(start,image.id,'api-conflicting-'+name,
                                                   command,extra=overrides)
                assert (await asyncio.to_thread(conflict.wait,timeout=15))['StatusCode'] != 0
                assert b'Runtime instance identity mismatch' in await asyncio.to_thread(conflict.logs)
            await wait_http(http,'http://'+address(bad)+':8000/health')
            # A worker from release A cannot ready an API from release B.
            assert (await http.get('http://'+address(bad)+':8000/ready')).status_code == 503
            proxy = await asyncio.to_thread(start,nginx_image.id,'proxy',
                                           ['nginx','-c','/control/nginx.conf','-g','daemon off;'])
            url = 'http://'+address(proxy)+':8080'
            await wait_http(http,url+'/health',status=503)
            controller = await asyncio.to_thread(start,image.id,'controller',['python','-m','app.proxy_controller'],
                extra={'PROXY_DISCOVERY_SERVICE':prefix+'-api','PROXY_ALLOWED_CIDRS':subnet},proxy=proxy)
            await wait_http(http,url+'/health')
            proxy.reload()
            assert set(proxy.attrs['NetworkSettings']['Networks']) == {api_network,frontend_network}
            for api in apis:
                api.reload()
                assert set(api.attrs['NetworkSettings']['Networks']) == {api_network,network}
            worker.reload()
            assert set(worker.attrs['NetworkSettings']['Networks']) == {network}
            frontend = await asyncio.to_thread(start,frontend_image.id,'frontend',None)
            front_url = 'http://'+address(frontend)+':8080'
            await wait_http(http,front_url+'/health')
            frontend.reload()
            assert set(frontend.attrs['NetworkSettings']['Networks']) == {frontend_network}
            assert frontend.attrs['Config']['User'] == '10001:10001'
            assert frontend.attrs['Config']['Entrypoint'] == ['nginx']
            assert frontend.attrs['Config']['Cmd'] == ['-g','daemon off;']
            assert frontend.attrs['HostConfig']['ReadonlyRootfs'] is True
            assert frontend.attrs['HostConfig']['CapDrop'] == ['ALL']
            assert not frontend.attrs['HostConfig'].get('CapAdd')
            assert set(frontend.attrs['HostConfig'].get('SecurityOpt') or ()) & {'no-new-privileges','no-new-privileges:true'}
            assert frontend.attrs['HostConfig']['Tmpfs'] == {'/tmp':'rw,noexec,nosuid,size=32m,mode=1777'}
            for path in ('/.well-known/webcompiler-release.json','/webcompiler/.well-known/webcompiler-release.json'):
                marker=await http.get(front_url+path)
                assert marker.status_code==200
                assert marker.json()=={'deployment_sha':'a'*40}
                assert marker.headers['content-type'].startswith('application/json')
                assert marker.headers['cache-control']=='no-store'
                assert 'X-Fixture-Instance' not in marker.headers  # Not an API response.
            # All frontend API entry points hit the same managed pool. They
            # have no network path or DNS backend alias to bypass membership.
            for path in ('/health','/webcompiler/health','/api/v1/contests','/webcompiler/api/v1/contests'):
                assert (await http.get(front_url+path)).status_code == 200
            controller.reload()
            assert controller.attrs['HostConfig']['PidMode'] == 'container:'+proxy.id
            assert controller.attrs['HostConfig']['NetworkMode'] == 'container:'+proxy.id
            assert all(m['Type']=='tmpfs' or m['Destination']=='/control' for m in controller.attrs['Mounts'])
            assert controller.attrs['HostConfig']['CapDrop'] == ['ALL']
            assert not controller.attrs['HostConfig'].get('PortBindings')
            assert not any(v.startswith(('DATABASE_URL=','SECRET_KEY=','REDIS_URL=')) for v in controller.attrs['Config']['Env'])
            promotion = await asyncio.to_thread(controller.exec_run,
                ['python','-m','app.proxy_promotion','--release','a'*40,'--pool',prefix,'--runtime',run_id])
            assert promotion.exit_code == 0, promotion.output.decode()
            active_config = (control/'nginx.conf').read_text()
            for api in apis:
                assert f'server {address(api,api_network)}:8000 ' in active_config
            assert f'server {address(bad,api_network)}:8000 ' not in active_config
            repeated = await asyncio.to_thread(start,image.id,'init-repeat',['python','-m','app.proxy_initialize'])
            assert (await asyncio.to_thread(repeated.wait,timeout=15))['StatusCode'] == 0
            assert (control/'nginx.conf').read_text() == active_config
            wrong = await asyncio.to_thread(start,image.id,'init-wrong-release',['python','-m','app.proxy_initialize'],
                                           extra={'DEPLOYMENT_SHA':'b'*40})
            assert (await asyncio.to_thread(wrong.wait,timeout=15))['StatusCode'] != 0
            assert (control/'nginx.conf').read_text() == active_config
            wrong_pool = await asyncio.to_thread(start,image.id,'init-wrong-pool',['python','-m','app.proxy_initialize'],
                                                extra={'PROXY_POOL_ID':prefix+'-other-color'})
            assert (await asyncio.to_thread(wrong_pool.wait,timeout=15))['StatusCode'] != 0
            assert (control/'nginx.conf').read_text() == active_config
            # Generation diagnostics cannot be fetched from another container.
            wrong_runtime = await asyncio.to_thread(start,image.id,'init-wrong-runtime',['python','-m','app.proxy_initialize'],
                                                   extra={'RUNTIME_INSTANCE_ID':uuid4().hex})
            assert (await asyncio.to_thread(wrong_runtime.wait,timeout=15))['StatusCode'] != 0
            assert (control/'nginx.conf').read_text() == active_config
            assert (await http.get(url+'/_proxy_generation')).status_code == 403
            assert (await http.get(url+'/_proxy_membership')).status_code == 404
            seen = set()
            for _ in range(12):
                response = await http.get(url+'/health')
                assert response.status_code == 200 and response.json()['deploymentSha']=='a'*40
                assert 'x-audit-upstream' not in response.headers
                seen.add(response.headers['x-fixture-instance'])
            assert seen == {'api0','api1'}
            assert (await http.get(url+'/health',headers={'Cookie':'a='+'x'*6000})).status_code == 200
            await asyncio.to_thread(bad.stop,timeout=15)
            unready = await asyncio.to_thread(start,image.id,'api-unready',command,
                                             extra={'RUNTIME_POOL_ID':prefix+'-other-color',
                                                    'RUNTIME_INSTANCE_ID':uuid4().hex})
            await wait_http(http,'http://'+address(unready)+':8000/health')
            assert (await http.get('http://'+address(unready)+':8000/ready')).status_code == 503
            await asyncio.sleep(4)
            assert f'server {address(unready,api_network)}:8000 ' not in (control/'nginx.conf').read_text()
            # A stale same-pool/same-SHA API may be genuinely ready through
            # its own old worker; it still must not join the new incarnation.
            stale_id=uuid4().hex
            stale_worker=await asyncio.to_thread(start,image.id,'worker-stale',['python','-m','app.worker'],
                                                worker=True,extra={'RUNTIME_INSTANCE_ID':stale_id})
            stale_api=await asyncio.to_thread(start,image.id,'api-stale',command,extra={'RUNTIME_INSTANCE_ID':stale_id})
            await wait_http(http,'http://'+address(stale_api)+':8000/ready')
            assert (await http.get('http://'+address(stale_api)+':8000/health')).json()['runtimeInstanceId']==stale_id
            await asyncio.sleep(4)
            assert f'server {address(stale_api,api_network)}:8000 ' not in (control/'nginx.conf').read_text()
            await asyncio.to_thread(stale_api.stop,timeout=15)
            await asyncio.to_thread(stale_worker.stop,timeout=15)
            dead_ip = address(apis[0],api_network)
            await asyncio.to_thread(apis[0].kill)
            async with asyncio.timeout(15):
                while f'server {dead_ip}:8000 ' in (control/'nginx.conf').read_text():
                    await asyncio.sleep(.2)
            await wait_http(http,url+'/health')  # one surviving valid peer remains usable
            degraded_gate = await asyncio.to_thread(controller.exec_run,['python','-c',
                "import asyncio; from app.proxy_promotion import wait_for_pool; "
                f"asyncio.run(wait_for_pool({'a'*40!r},{prefix!r},runtime_id={run_id!r},timeout=8))"])
            assert degraded_gate.exit_code != 0 and b'TimeoutError' in degraded_gate.output
            # A stalled controller cannot keep serving its last-known peers.
            await asyncio.to_thread(controller.kill,signal='SIGSTOP')
            await wait_http(http,url+'/health',status=503)
            await wait_http(http,front_url+'/health',status=503)
            await asyncio.to_thread(controller.kill,signal='SIGCONT')
            await wait_http(http,url+'/health')
            await asyncio.to_thread(controller.kill)
            await wait_http(http,url+'/health',status=503)
            await asyncio.to_thread(controller.start)
            await wait_http(http,url+'/health')
            await asyncio.to_thread(worker.stop,timeout=15)
            await wait_http(http,url+'/health',status=503)
            await asyncio.to_thread(worker.start)
            await wait_http(http,url+'/health')
    except Exception:
        for container in containers:
            container.reload()
            log = container.logs(tail=10).decode(errors='replace')[-2200:]
            for key in ('DATABASE_URL','REDIS_URL','SECRET_KEY'):
                log = log.replace(env[key],'[redacted]')
            print(container.name,container.status,log)
        raise
    finally:
        for container in reversed(containers):
            container.reload()
            assert container.labels.get('webcompiler.audit') == run_id
            # A SIGSTOP failure path still needs bounded cleanup.
            container.remove(force=True)
        for image in reversed(images):
            assert image.labels.get('webcompiler.audit') == run_id
            client.images.remove(image.id)
        if private_networks:
            private_networks[-1].reload()
            if parent.id in private_networks[-1].attrs.get('Containers',{}):
                private_networks[-1].disconnect(parent)
        for isolated in reversed(private_networks):
            isolated.reload()
            assert isolated.attrs['Labels']['webcompiler.audit']==run_id
            assert not isolated.attrs.get('Containers')
            isolated.remove()
        assert control.parent == Path(sandbox) and control.name.startswith(prefix+'-')
        shutil.rmtree(control)
        keys = list(store.scan_iter(match=prefix+':*'))
        if keys:
            store.delete(*keys)
        store.close()
        client.close()
