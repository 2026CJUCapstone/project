"""Actual Docker incarnation evidence on small isolated fixture containers.

Roles run sleep/true or a minimal Nginx listener, not application code. This
tests Docker identity and actual host-loopback routing, not cold Compose
deployment, application readiness or verified retirement.
"""
import hashlib
import json
import os
import time
from pathlib import Path
from uuid import uuid4

import pytest

from tests.test_edge_deploy import adapter, edge
from tests.test_runtime_inventory import container_set, LABEL


pytestmark = pytest.mark.skipif(os.getenv('RUN_SANDBOX_INTEGRATION')!='1',
    reason='Explicit isolated Docker inventory test required')


@pytest.mark.parametrize('mutation',['restart','replace','graceful-retirement','preserved-stateful'])
def test_real_container_identity_network_intruder_and_restart_or_replace(tmp_path,mutation):
    import docker
    audit = Path(os.environ['AUDIT_ROOT']).resolve()
    assert audit.name.startswith('webcompiler-audit-')
    nonce = uuid4().hex
    project = 'audit-inventory-'+nonce+'-blue'
    # Isolated high loopback ports; a collision fails without changing its owner.
    api_port = 30000+int(uuid4().hex[:4],16)%10000
    frontend_port = 40000+int(uuid4().hex[:4],16)%10000
    release = edge.Release('blue','a'*40,api_port,frontend_port,uuid4().hex,uuid4().hex)
    store = edge.Store(tmp_path/'ownership',edge.Layout(18000,15173))
    store.initialize()
    shared_name = project+'-shared'
    templates,_ = container_set(audit,project,release,shared_network=shared_name)
    client = docker.from_env(timeout=8)
    owned,networks = [],[]
    volume = probe = legacy = legacy_volume = None
    image = client.images.get('nginx:1.30.4-alpine-slim@sha256:77da26c31397bf6694b4bf93275f5b40b0b120ba1b8f114264b603e592c561d6').id  # Never pull a fixture image.
    api_name,front_name,ingress_name = project+'-api-plane',project+'_frontend_plane',project+'_edge_ingress'
    api_labels = {'io.webcompiler.network.role':'api-plane','io.webcompiler.pool':project,
                  'io.webcompiler.owner':hashlib.sha256(str(audit).encode()).hexdigest()}
    guard = {'webcompiler.audit.inventory':nonce}
    def own_create(template,*,foreign=False):
        role = template['Config']['Labels'][LABEL+'role']
        labels = {**template['Config']['Labels'],**guard}
        if foreign:
            labels['com.docker.compose.project'] = project+'-foreign'
        args = {'image':image,'entrypoint':['/bin/sh'],
            'command':['-c','true' if role in ('initialize','proxy-control-init') else
                "trap 'exit 0' TERM; while :; do sleep 1; done"],
            'stop_signal':'SIGQUIT' if role in ('frontend','api-proxy') else 'SIGTERM',
            'restart_policy':template['HostConfig']['RestartPolicy'],
            'labels':labels,'environment':template['Config']['Env'],'user':'10001:10001',
            'read_only':True,'cap_drop':['ALL'],'security_opt':['no-new-privileges'],
            'mem_limit':'16m','memswap_limit':'16m','nano_cpus':25000000,'pids_limit':16,
            'log_config':docker.types.LogConfig(type='none')}
        if role in ('api-proxy','frontend'):
            config = ('pid /tmp/nginx.pid; error_log /dev/stderr; events { worker_connections 16; } '
                'http { access_log off; client_body_temp_path /tmp/client; proxy_temp_path /tmp/proxy; '
                'fastcgi_temp_path /tmp/fastcgi; uwsgi_temp_path /tmp/uwsgi; scgi_temp_path /tmp/scgi; '
                'server { listen 8080; location = /'+nonce+' { return 200 '+nonce+'-'+role+'; } } }')
            args.update(command=['-c',"printf '%s' '"+config+"' > /tmp/nginx.conf; exec nginx -c /tmp/nginx.conf -g 'daemon off;'"],
                tmpfs={'/tmp':'size=16m,mode=1777,noexec,nosuid'},mem_limit='24m',memswap_limit='24m')
        if role in ('api-proxy','proxy-controller','proxy-control-init'):
            args['volumes'] = {volume.name:{'bind':'/control','mode':'ro' if role=='api-proxy' else 'rw'}}
        if role=='worker':
            args['volumes'] = {path:{'bind':path,'mode':'rw'} for path in
                ('/var/run/docker.sock',str(audit/'.sandbox-work'))}
        if role=='api-proxy':
            args['ports'] = {'8080/tcp':('127.0.0.1',release.api_port)}
        elif role=='frontend':
            args['ports'] = {'8080/tcp':('127.0.0.1',release.frontend_port)}
        if role=='proxy-controller':
            proxy = next(c for c in owned if c.labels.get(LABEL+'role')=='api-proxy')
            args.update(pid_mode='container:'+proxy.id,network_mode='container:'+proxy.id)
        else:
            args['network'] = (api_name if role in ('backend','api-proxy') else front_name if role=='frontend'
                else shared_name if role in ('worker','initialize','pgbouncer') else 'none')
        child = client.containers.create(**args)
        owned.append(child)
        if role=='api-proxy':
            networks[1].connect(child)
        if role in ('api-proxy','frontend'):
            networks[3].connect(child)
        if role=='backend':
            networks[2].connect(child)
        child.start()
        if role in ('initialize','proxy-control-init'):
            assert child.wait(timeout=10)['StatusCode']==0
        return child
    def call(args):
        # Production uses Docker CLI; this fixture uses the same read-only API
        # through the SDK because the restricted test image has no Docker CLI.
        if args[:2]==['container','ls']:
            assert '--all' in args and '--no-trunc' in args
            return '\n'.join(c.id for c in client.containers.list(all=True,
                filters={'label':'com.docker.compose.project='+project}))+'\n'
        if args[:2]==['container','inspect']:
            return json.dumps([client.api.inspect_container(args[2])])
        assert args[:2]==['network','inspect']
        return json.dumps([client.api.inspect_network(args[2])])
    try:
        networks.append(client.networks.create(api_name,driver='bridge',internal=True,labels={**api_labels,**guard}))
        networks.append(client.networks.create(front_name,driver='bridge',internal=True,labels={
            'com.docker.compose.project':project,'com.docker.compose.network':'frontend_plane',**guard}))
        networks.append(client.networks.create(shared_name,driver='bridge',internal=True,labels=guard))
        networks.append(client.networks.create(ingress_name,driver='bridge',internal=False,labels={
            'com.docker.compose.project':project,'com.docker.compose.network':'edge_ingress',**guard},
            options={'com.docker.network.bridge.host_binding_ipv4':'127.0.0.1'}))
        volume = client.volumes.create(project+'-proxy-'+release.sha+'-'+release.runtime_id,labels=guard)
        for template in templates.values():
            own_create(template)
        subject = adapter.Inventory(store,audit,project,release,'webcompiler',call,shared_network=shared_name)
        if mutation=='preserved-stateful':
            # A real, separate legacy Redis/AOF volume. Never attach it to the
            # new API/front planes or use it as the managed app's Redis.
            redis_image=client.images.get('redis:7-alpine@sha256:ff02b58f971e7d7d156a1267e283fcbbeee91773b6aa36c49dac28ecfe28eadf').id
            legacy_network=client.networks.create(project+'_default',driver='bridge',internal=True,labels={
                **guard,'com.docker.compose.project':project,'com.docker.compose.network':'default'})
            networks.append(legacy_network)
            legacy_volume=client.volumes.create(project+'-legacy-data',labels=guard)
            legacy=client.containers.create(redis_image,name=project+'-legacy-redis',
                entrypoint=['redis-server'],command=['--dir','/data','--appendonly','yes','--save','',
                    '--maxmemory','8mb','--maxmemory-policy','noeviction'],
                # The image seeds /data for its redis user. Root without
                # DAC_OVERRIDE cannot write that directory; do not restore
                # capabilities merely to make the fixture run.
                network=legacy_network.name,user='redis:redis',read_only=True,cap_drop=['ALL'],
                security_opt=['no-new-privileges'],mem_limit='64m',memswap_limit='64m',
                nano_cpus=25000000,pids_limit=16,log_config=docker.types.LogConfig(
                    type='json-file',config={'max-size':'16k','max-file':'1'}),
                volumes={legacy_volume.name:{'bind':'/data','mode':'rw'}},
                labels={**guard,'com.docker.compose.project':project,'com.docker.compose.service':'redis'})
            owned.append(legacy)
            legacy.start()
            deadline=time.monotonic()+10
            while True:
                legacy.reload()
                if not legacy.attrs['State']['Running']:
                    # This unauthenticated, network-isolated fixture contains
                    # no secrets. Keep startup diagnostics bounded as well.
                    detail=legacy.logs(tail=20).decode(errors='replace')[-4096:]
                    pytest.fail('Isolated legacy Redis exited during startup: '+detail)
                result=legacy.exec_run(['redis-cli','PING'])
                if result.exit_code==0 and result.output.strip()==b'PONG': break
                assert time.monotonic()<deadline, 'Isolated legacy Redis readiness timed out'
                time.sleep(.1)
            assert legacy.exec_run(['redis-cli','SET','audit-marker',nonce]).output.strip()==b'OK'
            with pytest.raises(edge.EdgeError,match='Foreign or unbound'): subject.capture()
            assert not subject.path.exists()
            subject=adapter.Inventory(store,audit,project,release,'webcompiler',call,
                shared_network=shared_name,preserved_stateful=(legacy.id,))
            # Explicit fixture enrollment mirrors prepare's durable baseline;
            # Inventory.capture itself must never enroll/reapprove a config.
            records=[adapter.preserved_stateful_record(client.api.inspect_container(legacy.id),
                legacy.id,project,shared_network=shared_name)]
            store.write(adapter.preservation_path(store,project),adapter.preservation_value(project,records))
        try:
            assert subject.capture() is True and subject.verify() is True
        except edge.EdgeError as error:
            # Only fixture-owned role/port/network shape, never Env or secrets.
            observed = []
            for child in owned:
                child.reload()
                assert child.labels.get('webcompiler.audit.inventory')==nonce
                value = child.attrs
                observed.append({'role':child.labels.get(LABEL+'role',child.labels.get('com.docker.compose.service')),
                    'declared_ports':value['HostConfig'].get('PortBindings'),
                    'effective_ports':value['NetworkSettings'].get('Ports'),
                    'network_mode':value['HostConfig'].get('NetworkMode'),
                    'networks':{name:{key:info.get(key) for key in
                        ('NetworkID','EndpointID','IPAddress','GlobalIPv6Address')}
                        for name,info in (value['NetworkSettings'].get('Networks') or {}).items()}})
            raise AssertionError(str(error)+'; fixture shapes='+json.dumps(observed)) from None
        before = subject.path.read_bytes()
        assert b'fixture-secret' not in before
        # Real Docker inspect can reorder its Mounts array without any runtime
        # mutation. Repeated reads of the two-bind worker must stay identical.
        worker = next(c for c in owned if c.labels.get(LABEL+'role')=='worker')
        recorded_worker = next(c for c in json.loads(before)['containers'] if c['id']==worker.id)
        for _ in range(24):
            assert subject._container(worker.id)==recorded_worker
        # This one bounded fixture joins the host network solely to GET the
        # two successfully bound, nonce-specific loopback listeners. It does
        # not join the runtime project or call any production address/port.
        checks = []
        for role,port in (('api-proxy',release.api_port),('frontend',release.frontend_port)):
            checks.append("got=''; for attempt in 1 2 3 4 5; do got=$(wget -T 2 -q -O - http://127.0.0.1:"
                +str(port)+'/'+nonce+") && break; sleep 1; done; [ \"$got\" = '"+nonce+'-'+role+"' ] || exit 1")
        probe = client.containers.create(image=image,entrypoint=['/bin/sh'],command=['-c','; '.join(checks)],
            network_mode='host',user='10001:10001',labels=guard,read_only=True,cap_drop=['ALL'],
            security_opt=['no-new-privileges'],mem_limit='16m',memswap_limit='16m',
            nano_cpus=25000000,pids_limit=16,log_config=docker.types.LogConfig(type='none'))
        probe.start()
        assert probe.wait(timeout=35)['StatusCode']==0, 'Owned host-loopback HTTP probes failed'
        # A foreign network member must be detected even when it has a
        # different project label and is absent from the project inventory.
        backend_template = next(iter(templates.values()))
        intruder = own_create(backend_template,foreign=True)
        with pytest.raises(edge.EdgeError,match='network membership'):
            subject.verify()
        assert intruder.labels.get('webcompiler.audit.inventory')==nonce
        intruder.remove(force=True)
        owned.remove(intruder)
        assert subject.verify() is True
        if mutation in ('graceful-retirement','preserved-stateful'):
            requested=set()
            for role in ('frontend','proxy-controller','api-proxy','backend','worker','pgbouncer'):
                for child in owned:
                    if child.labels.get(LABEL+'role')!=role:
                        continue
                    requested.add(child.id)
                    # The SDK sends the same indefinite daemon stop timeout;
                    # CLI disconnect semantics have their own host-level test.
                    child.stop(timeout=-1)
                    child.reload()
                    assert child.attrs['State']['Status']=='exited'
                    assert subject.verify_retiring(requested)==requested
                    assert subject.path.read_bytes()==before
            assert len(requested)==7
            if legacy is not None:
                assert legacy.id not in requested
                assert {r['id'] for r in json.loads(before)['preserved_stateful']}=={legacy.id}
                legacy.reload()
                assert legacy.attrs['State']['Running'] is True
                assert legacy.exec_run(['redis-cli','GET','audit-marker']).output.strip()==nonce.encode()
                assert any(m.get('Name')==legacy_volume.name for m in legacy.attrs['Mounts'])
                with pytest.raises(edge.EdgeError,match='cannot be retirement'):
                    subject.verify_retiring(requested|{legacy.id})
                # Real same-ID Docker configuration change must not become
                # a newly approved baseline on later verification/capture.
                legacy.update(mem_limit='80m',memswap_limit='80m')
                with pytest.raises(edge.EdgeError,match='preservation configuration'):
                    subject.verify_retiring(requested)
                assert subject.path.read_bytes()==before
                assert legacy.exec_run(['redis-cli','GET','audit-marker']).output.strip()==nonce.encode()
                return
            # Requested retirement must not authorize a later incarnation.
            backend=next(c for c in owned if c.labels.get(LABEL+'role')=='backend')
            backend.start()
            with pytest.raises(edge.EdgeError): subject.verify_retiring(requested)
            assert subject.path.read_bytes()==before
            return
        backend = next(c for c in owned if c.labels.get(LABEL+'role')=='backend')
        old_id = backend.id
        if mutation=='restart':
            backend.restart(timeout=1)
            backend.reload()
            assert backend.id==old_id
        else:
            assert backend.labels.get('webcompiler.audit.inventory')==nonce
            backend.remove(force=True)
            owned.remove(backend)
            replacement = own_create(backend_template)
            assert replacement.id!=old_id
        with pytest.raises(edge.EdgeError):
            subject.verify()
        with pytest.raises(edge.EdgeError):
            subject.capture()
        assert subject.path.read_bytes()==before
    finally:
        if probe is not None:
            probe.reload()
            assert probe.labels.get('webcompiler.audit.inventory')==nonce
            probe.remove(force=True)
        for child in reversed(owned):
            child.reload()
            assert child.labels.get('webcompiler.audit.inventory')==nonce
            child.remove(force=True)
        if volume is not None:
            volume.reload()
            assert volume.attrs['Labels'].get('webcompiler.audit.inventory')==nonce
            volume.remove()
        if legacy_volume is not None:
            legacy_volume.reload()
            assert legacy_volume.attrs['Labels'].get('webcompiler.audit.inventory')==nonce
            legacy_volume.remove()
        for network in reversed(networks):
            network.reload()
            assert network.attrs['Labels'].get('webcompiler.audit.inventory')==nonce
            network.remove()
        client.close()
