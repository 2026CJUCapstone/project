"""Exact container incarnation capture and edge transaction failure boundaries."""
import hashlib
import json

import pytest

from tests.test_edge_deploy import adapter, edge, deployment
from runtime_inventory import MAX_DATABASE_URL_BYTES


LABEL = 'io.webcompiler.runtime.'
ROLES = ('backend','backend','worker','initialize','frontend','pgbouncer',
         'api-proxy','proxy-controller','proxy-control-init')
AUDIT_DATABASE_URL = 'postgresql+psycopg2://audit_user:audit_password@audit-pooler:5432/audit_db'


def container_set(root,project,release,sandbox_pool='webcompiler',shared_network='webcompiler-shared'):
    containers, networks = {}, {}
    api, frontend, ingress = project+'-api-plane',project+'_frontend_plane',project+'_edge_ingress'
    network_ids = {api:'d'*64,frontend:'e'*64,ingress:'a'*64,shared_network:'b'*64,'none':'9'*64}
    replicas = {}
    for index,role in enumerate(ROLES,1):
        identity = f'{index:064x}'
        replicas[role] = replicas.get(role,0)+1
        hostname = role+'-'+str(replicas[role])
        labels = {LABEL+'version':'1',LABEL+'id':release.runtime_id,LABEL+'pool':project,
            LABEL+'release':release.sha,LABEL+'sandbox-pool':sandbox_pool,LABEL+'role':role,
            'com.docker.compose.project':project,'com.docker.compose.service':role,
            'com.docker.compose.container-number':str(replicas[role]),'com.docker.compose.config-hash':'c'*64}
        env = ['SECRET_KEY=fixture-secret-must-not-be-stored','DATABASE_URL='+AUDIT_DATABASE_URL]
        if role in ('backend','worker','initialize'):
            env += ['DEPLOYMENT_SHA='+release.sha,'RUNTIME_INSTANCE_ID='+release.runtime_id,
                    'SANDBOX_POOL_ID='+sandbox_pool,'RUNTIME_POOL_ID='+project]
        if role in ('proxy-controller','proxy-control-init'):
            env += ['DEPLOYMENT_SHA='+release.sha,'RUNTIME_INSTANCE_ID='+release.runtime_id,'PROXY_POOL_ID='+project]
        initializer = role in ('initialize','proxy-control-init')
        mounts = []
        if role in ('api-proxy','proxy-controller','proxy-control-init'):
            mounts = [{'Type':'volume','Name':project+'-proxy-'+release.sha+'-'+release.runtime_id,
                       'Destination':'/control','RW':role!='api-proxy'}]
        if role=='worker':
            workdir = str(root/'.sandbox-work')
            env.append('SANDBOX_WORKDIR_ROOT='+workdir)
            mounts = [{'Type':'bind','Source':path,'Destination':path,'RW':True}
                      for path in ('/var/run/docker.sock',workdir)]
        attached = ([api,shared_network] if role=='backend' else [shared_network] if role in ('worker','initialize','pgbouncer')
                    else [frontend,ingress] if role=='frontend'
                    else [api,frontend,ingress] if role=='api-proxy'
                    else ['none'] if role=='proxy-control-init' else [])
        ports = ({'8080/tcp':[{'HostIp':'127.0.0.1','HostPort':str(release.api_port)}]}
            if role=='api-proxy' else {'8080/tcp':[{'HostIp':'127.0.0.1','HostPort':str(release.frontend_port)}]}
            if role=='frontend' else {})
        containers[identity] = {'Id':identity,'Image':'sha256:'+'f'*64,'Created':'2026-09-10T00:00:00Z',
            'RestartCount':0,'Config':{'Labels':labels,'Env':env,'User':'10001:10001','Hostname':hostname},
            'State':{'Running':not initializer,'Status':'exited' if initializer else 'running',
                'Pid':0 if initializer else index+100,'ExitCode':0,'Restarting':False,'Paused':False,
                'StartedAt':'2026-09-10T00:00:01Z',
                'FinishedAt':'2026-09-10T00:00:02Z' if initializer else '0001-01-01T00:00:00Z'},
            'HostConfig':{'PidMode':'','NetworkMode':attached[0] if attached else 'none','PortBindings':ports,
                'RestartPolicy':{'Name':'no' if initializer else 'unless-stopped','MaximumRetryCount':0},
                'ReadonlyRootfs':True,'CapDrop':['ALL'],'SecurityOpt':['no-new-privileges']},'Mounts':mounts,
            'NetworkSettings':{'Ports':ports,'Networks':{name:{'NetworkID':network_ids[name],'EndpointID':f'{index+20:064x}',
                'IPAddress':f'192.168.10.{index}','GlobalIPv6Address':''} for name in attached}}}
        if role=='proxy-control-init':
            containers[identity]['NetworkSettings']['Networks']['none'].update(EndpointID='',IPAddress='')
    proxy = next(i for i,c in containers.items() if c['Config']['Labels'][LABEL+'role']=='api-proxy')
    controller = next(c for c in containers.values() if c['Config']['Labels'][LABEL+'role']=='proxy-controller')
    controller['HostConfig'].update(PidMode='container:'+proxy,NetworkMode='container:'+proxy)
    for name in (api,frontend,ingress):
        labels = ({'io.webcompiler.network.role':'api-plane','io.webcompiler.pool':project,
            'io.webcompiler.owner':hashlib.sha256(str(root.resolve()).encode()).hexdigest()}
            if name==api else {'com.docker.compose.project':project,
                'com.docker.compose.network':'frontend_plane' if name==frontend else 'edge_ingress'})
        networks[name] = {'Id':network_ids[name],'Name':name,'Driver':'bridge','Scope':'local',
            'Internal':name!=ingress,'Labels':labels,'Containers':{identity:{} for identity,c in containers.items()
                if name in c['NetworkSettings']['Networks']}}
    return containers,networks


@pytest.fixture
def inventory(tmp_path,monkeypatch):
    deploy = deployment(tmp_path,monkeypatch)
    release = deploy.candidate('blue','a'*40)
    containers,networks = container_set(tmp_path,'webcompiler-blue',release)
    calls = []
    def call(args):
        calls.append(args)
        if args[:2]==['container','ls']:
            assert args==['container','ls','--all','--no-trunc','--filter',
                'label=com.docker.compose.project=webcompiler-blue','--format','{{.ID}}']
            return '\n'.join(containers)+'\n'
        if args[:2]==['container','inspect']:
            return json.dumps([containers[args[2]]])
        assert args[:2]==['network','inspect']
        return json.dumps([networks[args[2]]])
    deploy.call = call
    return deploy,release,deploy.inventory(release),containers,networks,calls


def test_capture_is_private_exact_repeatable_and_contains_no_raw_secrets(inventory):
    deploy,release,subject,containers,networks,calls = inventory
    assert subject.capture() is True
    before = subject.path.read_bytes()
    assert subject.capture() is True and subject.path.read_bytes()==before
    assert subject.verify() is True
    data = json.loads(before)
    assert data['release']['runtime_id']==release.runtime_id
    assert {c['id'] for c in data['containers']}==set(containers)
    assert {c['hostname'] for c in data['containers']} == {
        c['Config']['Hostname'] for c in containers.values()
    }
    assert (b'fixture-secret' not in before and b'SECRET_KEY' not in before
            and AUDIT_DATABASE_URL.encode() not in before and b'audit_password' not in before)
    assert all(call[:2] in (['container','ls'],['container','inspect'],['network','inspect']) for call in calls)
    assert not list((deploy.store.path/'state'/'drains').iterdir())


@pytest.mark.parametrize('role',['backend','worker','frontend','api-proxy','proxy-controller','pgbouncer','initialize','proxy-control-init'])
@pytest.mark.parametrize('policy',[
    None, {'Name':'always','MaximumRetryCount':0},
    {'Name':'on-failure','MaximumRetryCount':3},
    {'Name':'unless-stopped','MaximumRetryCount':False},
])
def test_unsafe_or_unproven_restart_policy_is_not_adopted(inventory,role,policy):
    deploy,release,subject,containers,networks,calls=inventory
    target=next(c for c in containers.values() if c['Config']['Labels'][LABEL+'role']==role)
    target['HostConfig']['RestartPolicy']=policy
    with pytest.raises(edge.EdgeError,match='restart policy'): subject.capture()
    assert not subject.path.exists()


@pytest.mark.parametrize(('role','hostname'),[
    ('backend',None),('worker',''),('frontend','bad host'),('proxy-controller','a'*254),
])
def test_all_persisted_container_hostnames_are_bounded_and_exact(inventory,role,hostname):
    deploy,release,subject,containers,networks,calls = inventory
    target = next(c for c in containers.values() if c['Config']['Labels'][LABEL+'role']==role)
    target['Config']['Hostname'] = hostname
    with pytest.raises(edge.EdgeError,match='container hostname'):
        subject.capture()
    assert not subject.path.exists()


@pytest.mark.parametrize(('first_role','second_role'),[
    ('backend','backend'),('backend','worker'),
])
def test_duplicate_api_or_worker_container_hostnames_are_refused(
    inventory,first_role,second_role,
):
    deploy,release,subject,containers,networks,calls = inventory
    first = next(c for c in containers.values() if c['Config']['Labels'][LABEL+'role']==first_role)
    candidates = [c for c in containers.values()
                  if c['Config']['Labels'][LABEL+'role']==second_role and c is not first]
    assert candidates
    candidates[0]['Config']['Hostname'] = first['Config']['Hostname']
    with pytest.raises(edge.EdgeError,match='duplicate process container hostname'):
        subject.capture()
    assert not subject.path.exists()


def test_controller_hostname_may_match_shared_proxy_namespace_but_is_persisted(inventory):
    deploy,release,subject,containers,networks,calls = inventory
    proxy = next(c for c in containers.values() if c['Config']['Labels'][LABEL+'role']=='api-proxy')
    controller = next(c for c in containers.values()
                      if c['Config']['Labels'][LABEL+'role']=='proxy-controller')
    # PID/network sharing does not make the controller an API DB-process
    # container, so a matching hostname is not process-owner ambiguity.
    controller['Config']['Hostname'] = proxy['Config']['Hostname']
    assert subject.capture()
    observed = json.loads(subject.path.read_bytes())['containers']
    names = {record['role']:record['hostname'] for record in observed}
    assert names['proxy-controller']==names['api-proxy']==proxy['Config']['Hostname']


@pytest.mark.parametrize('role',['backend','worker'])
def test_process_container_requires_database_url_before_capture(inventory,role):
    deploy,release,subject,containers,networks,calls = inventory
    target = next(c for c in containers.values() if c['Config']['Labels'][LABEL+'role']==role)
    target['Config']['Env'] = [entry for entry in target['Config']['Env']
                               if not entry.startswith('DATABASE_URL=')]
    with pytest.raises(edge.EdgeError,match='PostgreSQL target') as error:
        subject.capture()
    assert AUDIT_DATABASE_URL not in str(error.value)
    assert not subject.path.exists()


@pytest.mark.parametrize('value',[
    '', 'sqlite:///audit.db', 'postgresql://', 'postgresql://audit-pooler/',
    'postgresql://audit-pooler/'+('a'*MAX_DATABASE_URL_BYTES),
])
def test_process_database_url_is_bounded_and_managed_postgresql(inventory,value):
    deploy,release,subject,containers,networks,calls = inventory
    target = next(c for c in containers.values() if c['Config']['Labels'][LABEL+'role']=='backend')
    target['Config']['Env'] = [
        'DATABASE_URL='+value if entry.startswith('DATABASE_URL=') else entry
        for entry in target['Config']['Env']
    ]
    with pytest.raises(edge.EdgeError,match='PostgreSQL target') as error:
        subject.capture()
    assert AUDIT_DATABASE_URL not in str(error.value)
    if value:
        assert value not in str(error.value)
    assert not subject.path.exists()


def test_process_containers_must_share_exact_ephemeral_database_target(inventory):
    deploy,release,subject,containers,networks,calls = inventory
    worker = next(c for c in containers.values() if c['Config']['Labels'][LABEL+'role']=='worker')
    alternate = 'postgresql://other_user:other_password@other-pooler:5432/other_db'
    worker['Config']['Env'] = [
        'DATABASE_URL='+alternate if entry.startswith('DATABASE_URL=') else entry
        for entry in worker['Config']['Env']
    ]
    with pytest.raises(edge.EdgeError,match='share one managed database target') as error:
        subject.capture()
    assert alternate not in str(error.value) and 'other_password' not in str(error.value)
    assert not subject.path.exists()


def test_libpq_override_cannot_create_a_different_process_context(inventory):
    deploy,release,subject,containers,networks,calls = inventory
    worker = next(c for c in containers.values() if c['Config']['Labels'][LABEL+'role']=='worker')
    worker['Config']['Env'].append('PGOPTIONS=-csearch_path=foreign_secret_schema')
    with pytest.raises(edge.EdgeError,match='Unsupported libpq') as error:
        subject.capture()
    assert 'foreign_secret_schema' not in str(error.value)
    assert not subject.path.exists()


@pytest.mark.parametrize('change',['internal-ingress','public-api','public-frontend-plane','foreign-ingress',
    'backend-ingress','missing-effective-port','live-none-endpoint','root-frontend','unrestricted-frontend'])
def test_ingress_does_not_weaken_isolation_or_listener_evidence(inventory,change):
    deploy,release,subject,containers,networks,calls = inventory
    frontend = next(c for c in containers.values() if c['Config']['Labels'][LABEL+'role']=='frontend')
    if change=='internal-ingress':
        networks['webcompiler-blue_edge_ingress']['Internal'] = True
    elif change=='public-api':
        networks['webcompiler-blue-api-plane']['Internal'] = False
    elif change=='public-frontend-plane':
        networks['webcompiler-blue_frontend_plane']['Internal'] = False
    elif change=='foreign-ingress':
        networks['webcompiler-blue_edge_ingress']['Containers']['f'*64] = {}
    elif change=='backend-ingress':
        next(iter(containers.values()))['NetworkSettings']['Networks']['webcompiler-blue_edge_ingress'] = {}
    elif change=='missing-effective-port':
        frontend['NetworkSettings']['Ports'] = {'8080/tcp':None}
    elif change=='live-none-endpoint':
        initializer = next(c for c in containers.values() if c['Config']['Labels'][LABEL+'role']=='proxy-control-init')
        initializer['NetworkSettings']['Networks']['none']['IPAddress'] = '127.0.0.1'
    elif change=='root-frontend':
        frontend['Config']['User'] = '0:0'
    else:
        frontend['HostConfig']['ReadonlyRootfs'] = False
    with pytest.raises(edge.EdgeError):
        subject.capture()
    assert not subject.path.exists()


def test_inspect_mount_order_is_not_a_runtime_reconfiguration(inventory):
    deploy,release,subject,containers,networks,calls = inventory
    subject.capture()
    before = subject.path.read_bytes()
    worker = next(c for c in containers.values() if c['Config']['Labels'][LABEL+'role']=='worker')
    assert len(worker['Mounts'])==2
    for _ in range(6):
        worker['Mounts'].reverse()
        assert subject.verify() and subject.capture()
        assert subject.path.read_bytes()==before
    # Canonicalization cannot discard duplicate or modified mount evidence.
    worker['Mounts'].append(dict(worker['Mounts'][0]))
    with pytest.raises(edge.EdgeError,match='mount destinations'):
        subject.verify()
    assert subject.path.read_bytes()==before


@pytest.mark.parametrize('change', ['restart','replace','image','env','mount','foreign-member','namespace','missing'])
def test_restart_replacement_or_reconfiguration_never_overwrites_prior_evidence(inventory,change):
    deploy,release,subject,containers,networks,calls = inventory
    subject.capture()
    before = subject.path.read_bytes()
    identity = next(iter(containers))
    if change=='restart':
        containers[identity]['RestartCount'] += 1
        containers[identity]['State']['StartedAt'] = '2026-09-10T00:01:01Z'
    elif change=='replace':
        replacement = containers.pop(identity)
        replacement['Id'] = 'a'*64
        containers['a'*64] = replacement
    elif change=='image':
        containers[identity]['Image'] = 'sha256:'+'a'*64
    elif change=='env':
        containers[identity]['Config']['Env'].append('OTHER_SECRET=changed')
    elif change=='mount':
        containers[identity]['Mounts'].append({'Type':'bind','Source':'/other','Destination':'/other','RW':True})
    elif change=='foreign-member':
        networks['webcompiler-blue-api-plane']['Containers']['a'*64] = {}
    elif change=='namespace':
        controller = next(c for c in containers.values() if c['Config']['Labels'][LABEL+'role']=='proxy-controller')
        controller['HostConfig']['PidMode'] = 'container:'+identity
    else:
        containers.pop(identity)
    with pytest.raises(edge.EdgeError):
        subject.verify()
    with pytest.raises(edge.EdgeError):
        subject.capture()
    assert subject.path.read_bytes()==before


@pytest.mark.parametrize('change', ['labels','wrong-env','duplicate-env','replica','incomplete',
    'extra-role','short-id','paused','initializer','control-volume','missing-rw'])
def test_unbound_incomplete_or_unstable_color_is_not_captured(inventory,change):
    deploy,release,subject,containers,networks,calls = inventory
    identity = next(iter(containers))
    first = containers[identity]
    if change=='labels':
        first['Config']['Labels'].pop(LABEL+'id')
    elif change=='wrong-env':
        first['Config']['Env'] = [v.replace(release.runtime_id,'b'*32) for v in first['Config']['Env']]
    elif change=='duplicate-env':
        first['Config']['Env'].append('RUNTIME_INSTANCE_ID='+release.runtime_id)
    elif change=='replica':
        containers[list(containers)[1]]['Config']['Labels']['com.docker.compose.container-number']='1'
    elif change=='incomplete':
        containers.pop(identity)
    elif change=='extra-role':
        first['Config']['Labels']['com.docker.compose.service']='postgres'
    elif change=='short-id':
        containers[identity[:12]] = containers.pop(identity)
    elif change=='paused':
        first['State']['Paused']=True
    elif change=='initializer':
        next(c for c in containers.values() if c['Config']['Labels'][LABEL+'role']=='initialize')['State']['ExitCode']=1
    else:
        proxy = next(c for c in containers.values() if c['Config']['Labels'][LABEL+'role']=='api-proxy')
        if change=='control-volume':
            proxy['Mounts'][0]['Name']='foreign'
        else:
            proxy['Mounts'][0].pop('RW')
    with pytest.raises(edge.EdgeError):
        subject.capture()
    assert not subject.path.exists()


def test_member_change_between_observations_never_creates_snapshot(inventory):
    deploy,release,subject,containers,networks,calls = inventory
    original = subject.observe
    def observe():
        result = original()
        containers[next(iter(containers))]['RestartCount'] += 1
        return result
    subject.observe = observe
    with pytest.raises(edge.EdgeError,match='changed during capture'):
        subject.capture()
    assert not subject.path.exists()


def test_edge_switch_requires_capture_before_activation_and_verify_before_commit(inventory,monkeypatch):
    deploy,release,subject,containers,networks,calls = inventory
    monkeypatch.setattr(deploy,'capture_inventory',lambda _:subject.capture())
    monkeypatch.setattr(deploy,'verify_inventory',lambda _:subject.verify())
    monkeypatch.setattr(deploy,'preflight',lambda:None)
    monkeypatch.setattr(deploy,'gate',lambda _:True)
    monkeypatch.setattr(deploy,'verify',lambda *a,**kw:True)
    def activate(target):
        if target is not None:
            assert subject.path.exists()
            containers[next(iter(containers))]['RestartCount'] += 1
        return True
    deploy.transaction.activate = activate
    with pytest.raises(edge.EdgeError,match='committed route restored'):
        deploy.switch('blue','a'*40)
    assert deploy.store.committed() is None
    assert subject.path.exists()
    assert len(list((deploy.store.path/'state'/'drains').iterdir()))==1


def test_incomplete_inventory_fails_before_edge_changes(inventory,monkeypatch):
    deploy,release,subject,containers,networks,calls = inventory
    monkeypatch.setattr(deploy,'capture_inventory',lambda _:subject.capture())
    monkeypatch.setattr(deploy,'preflight',lambda:None)
    monkeypatch.setattr(deploy,'gate',lambda _:True)
    monkeypatch.setattr(deploy,'verify',lambda *a,**kw:True)
    deploy.transaction.activate = lambda _:pytest.fail('Incomplete candidate must not be activated')
    containers.pop(next(iter(containers)))
    with pytest.raises(edge.EdgeError):
        deploy.switch('blue','a'*40)
    assert deploy.store.committed() is None and deploy.store.pending() is None
    assert deploy.reserved()==release and not subject.path.exists()


@pytest.mark.parametrize('result',[[],['fixture-secret'],[{}],{'foreign':'fixture-secret'}])
def test_malformed_inspect_fails_without_leaking_payload(inventory,result):
    deploy,release,subject,containers,networks,calls = inventory
    original = subject.call
    subject.call = lambda args:json.dumps(result) if args[:2]==['container','inspect'] else original(args)
    with pytest.raises(edge.EdgeError) as failure:
        subject.capture()
    assert 'fixture-secret' not in str(failure.value)
    assert not subject.path.exists()


def test_network_observation_cannot_extend_expired_deadline(inventory):
    deploy,release,subject,containers,networks,calls = inventory
    now = [0]
    subject.clock = lambda:now[0]
    original = subject.call
    def call(args):
        if args[:2]==['network','inspect']:
            now[0] = 46
        return original(args)
    subject.call = call
    with pytest.raises(edge.EdgeError,match='timed out'):
        subject.capture()
    assert sum(call[:2]==['network','inspect'] for call in calls)==1
    assert not subject.path.exists()


@pytest.mark.parametrize('change',['public-ip','wrong-port','effective-port','backend-port',
    'privileged','host-pid','extra-network','host-network','extra-mount','writable-root',
    'cap-add','missing-cap-drop','no-new-privileges','dead','oom','endpoint','timestamp'])
def test_candidate_configuration_must_match_listener_and_isolation_policy(inventory,change):
    deploy,release,subject,containers,networks,calls = inventory
    first = next(iter(containers.values()))
    proxy = next(c for c in containers.values() if c['Config']['Labels'][LABEL+'role']=='api-proxy')
    if change in ('public-ip','wrong-port'):
        proxy['HostConfig']['PortBindings']['8080/tcp'][0][
            'HostIp' if change=='public-ip' else 'HostPort'] = '0.0.0.0' if change=='public-ip' else '19999'
    elif change=='effective-port':
        proxy['NetworkSettings']['Ports'] = {}
    elif change=='backend-port':
        first['HostConfig']['PortBindings'] = {'8000/tcp':[{'HostIp':'127.0.0.1','HostPort':'19000'}]}
    elif change=='privileged':
        first['HostConfig']['Privileged']=True
    elif change=='host-pid':
        first['HostConfig']['PidMode']='host'
    elif change=='extra-network':
        first['NetworkSettings']['Networks']['foreign']={'NetworkID':'f'*64}
    elif change=='host-network':
        first['HostConfig']['NetworkMode']='host'
    elif change=='extra-mount':
        proxy['Mounts'].append({'Type':'bind','Source':'/','Destination':'/host','RW':True})
    elif change=='writable-root':
        first['HostConfig']['ReadonlyRootfs']=False
    elif change=='cap-add':
        first['HostConfig']['CapAdd']=['CAP_SYS_ADMIN']
    elif change=='missing-cap-drop':
        first['HostConfig']['CapDrop']=[]
    elif change=='no-new-privileges':
        first['HostConfig']['SecurityOpt']=[]
    elif change in ('dead','oom'):
        first['State']['Dead' if change=='dead' else 'OOMKilled']=True
    elif change=='endpoint':
        first['NetworkSettings']['Networks']['webcompiler-blue-api-plane']['EndpointID']='short'
    else:
        first['State']['StartedAt']='2026-09-09T00:00:00Z'
    with pytest.raises(edge.EdgeError):
        subject.capture()
    assert not subject.path.exists()


@pytest.mark.parametrize('key,value',[('SecurityOpt',['no-new-privileges','seccomp=unconfined']),
    ('SecurityOpt',['no-new-privileges:true','apparmor=unconfined']),('Devices',[{'PathOnHost':'/dev/example'}]),
    ('DeviceRequests',[{'Count':-1,'Capabilities':[['gpu']]}]),('DeviceCgroupRules',['a *:* rwm']),
    ('IpcMode','host'),('UsernsMode','host'),('UTSMode','host'),('CgroupnsMode','host')])
def test_undeclared_security_device_and_host_namespace_overrides_are_refused(inventory,key,value):
    deploy,release,subject,containers,networks,calls = inventory
    next(iter(containers.values()))['HostConfig'][key] = value
    with pytest.raises(edge.EdgeError):
        subject.capture()
    assert not subject.path.exists()
