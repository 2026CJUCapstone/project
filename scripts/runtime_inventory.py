"""Read-only Docker ownership evidence, persisted before a color is promoted.

Snapshots bind exact container incarnations. They are neither stop authorization
nor proof that processes, requests, claims or sandboxes have finished.
"""
from collections import Counter
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
import re
import subprocess
import threading
import time
from urllib.parse import urlsplit

from edge_transaction import EdgeError


ROLES = frozenset(('backend','worker','frontend','pgbouncer','initialize',
                  'api-proxy','proxy-controller','proxy-control-init'))
INITIALIZERS = frozenset(('initialize','proxy-control-init'))
APP_IMAGE_ROLES = frozenset(('backend','worker','initialize','proxy-controller','proxy-control-init'))
LABEL = 'io.webcompiler.runtime.'
MAX_CONTAINERS = 64
MAX_RECORD_BYTES = 262144
MAX_RAW_BYTES = 1048576
HOSTNAME_PATTERN = r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,252}'
PROCESS_ROLES = frozenset(('backend','worker'))
MAX_DATABASE_URL_BYTES = 4096


def bounded_docker(args,*,timeout=20):
    """Read-only CLI output cap, before JSON parsing or secret-bearing capture."""
    if args[:2] not in (['container','ls'],['container','inspect'],['network','inspect']):
        raise EdgeError('Read-only inventory operation required')
    if isinstance(timeout,bool) or not isinstance(timeout,(int,float)) or not .1<=timeout<=20:
        raise ValueError('Bounded Docker observation timeout required')
    process = subprocess.Popen(['docker',*args],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
    output = []
    def read():
        try:
            output.append(process.stdout.read(MAX_RAW_BYTES+1))
        except (OSError,ValueError):
            pass
    reader = threading.Thread(target=read,daemon=True)
    deadline = time.monotonic()+timeout
    try:
        reader.start()
        reader.join(max(0,deadline-time.monotonic()))
        if reader.is_alive() or not output or len(output[0])>MAX_RAW_BYTES:
            raise EdgeError('Inventory Docker output exceeded time or size limit')
        if process.wait(timeout=max(.001,deadline-time.monotonic())):
            raise EdgeError('Runtime inventory Docker query failed')
        return output[0].decode('utf-8')
    finally:
        if process.poll() is None:
            process.kill()  # Only this reader's own Docker CLI process.
        process.wait(timeout=5)
        reader.join(5)
        process.stdout.close()


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def exact_id(value):
    if not isinstance(value,str) or not re.fullmatch('[a-f0-9]{64}',value):
        raise EdgeError('Full immutable Docker identity required')
    return value


def identity_labels(project,release,sandbox_pool):
    return {LABEL+'version':'1',LABEL+'id':release.runtime_id,LABEL+'pool':project,
            LABEL+'release':release.sha,LABEL+'sandbox-pool':sandbox_pool}


def preserved_stateful_record(data,identity,project,*,shared_network='webcompiler-shared'):
    """Only explicitly selected immutable legacy IDs; not adoption authority."""
    try:
        return _preserved_stateful_record(data,identity,project,shared_network)
    except (ValueError,TypeError,KeyError,AttributeError,RecursionError):
        raise EdgeError('Malformed preserved stateful observation') from None


def _preserved_stateful_record(data,identity,project,shared_network):
    exact_id(identity)
    config,host = data['Config'],data['HostConfig']
    labels = config.get('Labels') or {}
    role = labels.get('com.docker.compose.service')
    projects={project}
    if project.endswith(('-blue','-green')):
        prefix=project.rsplit('-',1)[0]
        projects.update((prefix+'-blue',prefix+'-green'))
    forbidden={shared_network,'host'}|{p+suffix for p in projects
        for suffix in ('-api-plane','_frontend_plane','_edge_ingress')}
    networks=data.get('NetworkSettings',{}).get('Networks') or {}
    if (data.get('Id')!=identity or role not in ('postgres','redis')
            or labels.get('com.docker.compose.project')!=project
            or any(key.startswith('io.webcompiler.') for key in labels)
            or host.get('NetworkMode') in forbidden
            or str(host.get('NetworkMode','')).startswith('container:')
            or set(networks)&forbidden):
        raise EdgeError('Approved preserved ID is not an isolated legacy stateful container')
    mounts = data.get('Mounts') or []
    if (not isinstance(mounts,list) or len(mounts)>32
            or any(not isinstance(m,dict) or not isinstance(m.get('Destination'),str) for m in mounts)
            or len({m['Destination'] for m in mounts})!=len(mounts)):
        raise EdgeError('Bounded distinct preserved stateful mounts required')
    return {'id':identity,'role':role,'preserved':True,
            'configuration_sha256':digest({'config':config,'host':host,
                'mounts':sorted(mounts,key=lambda m:m['Destination']),
                # Reconnect, aliases and DNS identity are configuration too.
                # A container restart may require explicit re-verification;
                # it must never silently enroll a changed network endpoint.
                'networks':networks})}


def preservation_path(store,project):
    if not isinstance(project,str) or not re.fullmatch('[a-z0-9][a-z0-9_-]{0,79}',project):
        raise EdgeError('Exact preserved project required')
    return store.path/'state'/'preserved-stateful.json'


def preservation_value(project,records):
    return {'version':1,'projects':{project:sorted(records,key=lambda r:r['id'])}}


def verify_preservation(store,project,records,*,allow_unbound=False):
    """One durable baseline across releases; inventory capture never enrolls."""
    try:
        previous=store.read_json(preservation_path(store,project))
    except FileNotFoundError:
        if records and not allow_unbound:
            raise EdgeError('Explicit preservation configuration must be bound before capture') from None
        return False
    if (not isinstance(previous,dict) or set(previous)!={'version','projects'}
            or type(previous['version']) is not int or previous['version']!=1
            or not isinstance(previous['projects'],dict) or not 1<=len(previous['projects'])<=2
            or previous['projects'].get(project)!=preservation_value(project,records)['projects'][project]):
        raise EdgeError('Preserved stateful preservation configuration changed; explicit reconciliation required')
    return True


def managed_database_url(environment):
    """Validate a process DB target without retaining its credential-bearing text."""
    value = environment.get('DATABASE_URL')
    try:
        if (not isinstance(value,str) or not value or len(value.encode())>MAX_DATABASE_URL_BYTES
                or any(character.isspace() or ord(character)<32 for character in value)):
            raise ValueError
        parsed = urlsplit(value)
        if (parsed.scheme not in ('postgresql','postgresql+psycopg2') or not parsed.hostname
                or parsed.path in ('','/') or parsed.fragment):
            raise ValueError
    except (TypeError, ValueError, UnicodeError):
        raise EdgeError('Bounded managed PostgreSQL target required') from None
    # The managed Compose topology declares DATABASE_URL only.  A libpq PG*
    # override could select a different host/service/options context despite a
    # matching URL, so accept none until it is explicitly modeled and bound.
    if any(key.startswith('PG') for key in environment):
        raise EdgeError('Unsupported libpq runtime override')
    return value


class Inventory:
    def __init__(self,store,root,project,release,sandbox_pool,call,*,shared_network='webcompiler-shared',clock=time.monotonic,
                 preserved_stateful=()):
        if (not release.runtime_id or not re.fullmatch('[a-z0-9][a-z0-9_-]{0,79}',project)
                or not isinstance(sandbox_pool,str)
                or not re.fullmatch('[a-z0-9][a-z0-9_-]{0,79}',sandbox_pool)):
            raise EdgeError('Exact runtime inventory scope required')
        if not isinstance(shared_network,str) or not re.fullmatch('[a-z0-9][a-z0-9_-]{0,79}',shared_network):
            raise EdgeError('Exact shared network name required')
        self.store,self.root,self.project,self.release = store,root,project,release
        self.sandbox_pool,self.call,self.clock = sandbox_pool,call,clock
        self.shared_network = shared_network
        if (not isinstance(preserved_stateful,tuple) or len(preserved_stateful)>4
                or len(set(preserved_stateful))!=len(preserved_stateful)):
            raise EdgeError('At most four distinct approved stateful container IDs required')
        self.preserved_stateful = tuple(exact_id(value) for value in preserved_stateful)
        self.path = store.path/'state'/('inventory-'+release.runtime_id+'.json')

    def _read(self,args):
        if self.clock()>=self._deadline:
            raise EdgeError('Runtime inventory observation timed out')
        result = self.call(args)
        if not isinstance(result,str) or len(result)>MAX_RAW_BYTES:
            raise EdgeError('Runtime inventory response exceeds bounded capacity')
        if self.clock()>=self._deadline:
            raise EdgeError('Runtime inventory observation timed out')
        return result

    def _ids(self):
        value = self._read(['container','ls','--all','--no-trunc','--filter',
            'label=com.docker.compose.project='+self.project,'--format','{{.ID}}'])
        if len(value)>MAX_CONTAINERS*65:
            raise EdgeError('Runtime inventory exceeds bounded capacity')
        ids = value.splitlines()
        if not 1<=len(ids)<=MAX_CONTAINERS or len(set(ids))!=len(ids):
            raise EdgeError('Ambiguous or empty runtime inventory')
        return sorted(exact_id(value) for value in ids)

    def _container(self,identity,process_urls=None,*,allow_stopped=False,allow_preserved=False):
        value = json.loads(self._read(['container','inspect',identity]))
        if not isinstance(value,list) or len(value)!=1 or value[0].get('Id')!=identity:
            raise EdgeError('Container inspection identity mismatch')
        data = value[0]
        config,state,host = data['Config'],data['State'],data['HostConfig']
        hostname = config.get('Hostname')
        # This is the exact value the API/worker records report through
        # socket.gethostname().  Keep it bounded and syntax-compatible with
        # the process identity contract before persisting it as evidence.
        if not isinstance(hostname,str) or not re.fullmatch(HOSTNAME_PATTERN,hostname):
            raise EdgeError('Bounded exact container hostname required')
        labels = config.get('Labels') or {}
        role = labels.get('com.docker.compose.service')
        if allow_preserved and identity in self.preserved_stateful:
            # An explicit full ID is a preservation exception, never ownership
            # or authority to stop/adopt a legacy DB. Unknown roles/managed IDs
            # and legacy access to the new private planes remain forbidden.
            return preserved_stateful_record(data,identity,self.project,shared_network=self.shared_network)
        if (role not in ROLES or labels.get('com.docker.compose.project')!=self.project
                or labels.get(LABEL+'role')!=role
                or any(labels.get(k)!=v for k,v in identity_labels(self.project,self.release,self.sandbox_pool).items())):
            raise EdgeError('Foreign or unbound runtime container refused')
        replica = labels.get('com.docker.compose.container-number','')
        config_hash = labels.get('com.docker.compose.config-hash','')
        if not re.fullmatch('[1-9][0-9]{0,2}',replica) or not re.fullmatch('[a-f0-9]{64}',config_hash):
            raise EdgeError('Exact Compose service incarnation required')
        env = {}
        for entry in config.get('Env') or []:
            key,separator,value = entry.partition('=')
            if not separator or key in env:
                raise EdgeError('Ambiguous container environment refused')
            env[key] = value
        required = {}
        if role in ('backend','worker','initialize'):
            required = {'RUNTIME_INSTANCE_ID':self.release.runtime_id,'DEPLOYMENT_SHA':self.release.sha,
                        'SANDBOX_POOL_ID':self.sandbox_pool}
            if role!='initialize':
                required['RUNTIME_POOL_ID'] = self.project
        elif role in ('proxy-controller','proxy-control-init'):
            required = {'RUNTIME_INSTANCE_ID':self.release.runtime_id,'DEPLOYMENT_SHA':self.release.sha,
                        'PROXY_POOL_ID':self.project}
        if any(env.get(k)!=v for k,v in required.items()):
            raise EdgeError('Runtime environment differs from ownership labels')
        if role in PROCESS_ROLES:
            database_url = managed_database_url(env)
            if process_urls is not None:
                process_urls[identity] = database_url
        if state.get('Restarting') is not False or state.get('Paused') is not False:
            raise EdgeError('Unstable runtime process state')
        stopped = allow_stopped and role not in INITIALIZERS and state.get('Status')=='exited'
        expected_ports = ({'8080/tcp':[{'HostIp':'127.0.0.1','HostPort':str(self.release.api_port)}]}
            if role=='api-proxy' else {'8080/tcp':[{'HostIp':'127.0.0.1','HostPort':str(self.release.frontend_port)}]}
            if role=='frontend' else {})
        for bindings,expected in ((host.get('PortBindings') or {},expected_ports),
                (data.get('NetworkSettings',{}).get('Ports') or {},{} if stopped else expected_ports)):
            if not isinstance(bindings,dict) or {key:value for key,value in bindings.items() if value}!=expected:
                raise EdgeError('Exact owned loopback listener bindings required ('+role+')')
        if (host.get('Privileged') or host.get('PublishAllPorts')
                or (role!='proxy-controller' and host.get('PidMode') not in ('',None))):
            raise EdgeError('Privileged or foreign PID namespace refused')
        if state.get('Dead') or state.get('OOMKilled') or state.get('Error'):
            raise EdgeError('Unhealthy container lifetime state')
        policy = host.get('RestartPolicy')
        expected_restart = 'no' if role in INITIALIZERS else 'unless-stopped'
        if (not isinstance(policy,dict) or set(policy)!={'Name','MaximumRetryCount'}
                or policy['Name']!=expected_restart
                or type(policy['MaximumRetryCount']) is not int or policy['MaximumRetryCount']!=0):
            # `always` may revive a manually stopped old runtime after daemon
            # restart. Hashing that unsafe policy would only preserve the bug.
            raise EdgeError('Exact retirement-safe restart policy required')
        allowed_caps = {'CHOWN','DAC_OVERRIDE'} if role=='proxy-control-init' else set()
        if {value.removeprefix('CAP_') for value in host.get('CapAdd') or []}-allowed_caps:
            raise EdgeError('Unexpected runtime capability additions')
        options = set(host.get('SecurityOpt') or [])
        if options-{'no-new-privileges','no-new-privileges:true'}:
            raise EdgeError('Unexpected runtime security override')
        if any(host.get(key) for key in ('Devices','DeviceRequests','DeviceCgroupRules')):
            raise EdgeError('Unexpected runtime device access')
        if any(host.get(key) not in (None,'','private') for key in ('IpcMode','UsernsMode','UTSMode','CgroupnsMode')):
            raise EdgeError('Unexpected host namespace exposure')
        if role in APP_IMAGE_ROLES|{'api-proxy','frontend'}:
            if (host.get('ReadonlyRootfs') is not True or 'ALL' not in (host.get('CapDrop') or [])
                    or not set(host.get('SecurityOpt') or []) & {'no-new-privileges','no-new-privileges:true'}):
                raise EdgeError('Restricted application container configuration required')
        if role in ('backend','frontend','api-proxy','proxy-controller') and config.get('User')!='10001:10001':
            raise EdgeError('Exact unprivileged runtime user required')
        if role in INITIALIZERS:
            if state.get('Running') is not False or state.get('Status')!='exited' or state.get('ExitCode')!=0 or state.get('Pid')!=0:
                raise EdgeError('Completed initializer ownership required')
        elif stopped:
            if (state.get('Running') is not False or type(state.get('Pid')) is not int or state['Pid']!=0
                    or type(state.get('ExitCode')) is not int or state['ExitCode'] not in (0,143)):
                raise EdgeError('Confirmed graceful process termination required')
        elif (state.get('Running') is not True or state.get('Status')!='running'
                or type(state.get('Pid')) is not int or state['Pid']<=0):
            raise EdgeError('Live runtime container required for capture')
        image = data.get('Image','')
        if not re.fullmatch('sha256:[a-f0-9]{64}',image):
            raise EdgeError('Immutable image ID required')
        timestamps = {key:data.get(key) if key=='Created' else state.get(key)
                      for key in ('Created','StartedAt','FinishedAt')}
        for value in timestamps.values():
            if not isinstance(value,str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,9})?Z',value):
                raise EdgeError('Exact Docker lifetime timestamps required')
        created,started,finished = (datetime.fromisoformat(timestamps[key]) for key in ('Created','StartedAt','FinishedAt'))
        if created.year==1 or not created<=started or ((role in INITIALIZERS or stopped) and finished<started):
            raise EdgeError('Invalid Docker lifetime ordering')
        restart = data.get('RestartCount')
        if type(restart) is not int or restart<0:
            raise EdgeError('Exact container restart count required')
        mounts = data.get('Mounts') or []
        if not isinstance(mounts,list) or len(mounts)>32:
            raise EdgeError('Bounded mount inventory required')
        destinations = [mount.get('Destination') for mount in mounts]
        if (any(not isinstance(path,str) or not path for path in destinations)
                or len(set(destinations))!=len(destinations)):
            raise EdgeError('Unique exact mount destinations required')
        # Docker inspect enumerates MountPoints in map order. Order alone is
        # not a new incarnation; retain every mount field, canonicalized by
        # its already-validated unique destination before hashing.
        mounts = sorted(mounts,key=lambda mount:mount['Destination'])
        controls = [mount for mount in mounts if mount.get('Destination')=='/control']
        if role in ('api-proxy','proxy-controller','proxy-control-init'):
            expected = self.project+'-proxy-'+self.release.sha+'-'+self.release.runtime_id
            if (len(controls)!=1 or controls[0].get('Type')!='volume'
                    or controls[0].get('Name')!=expected
                    or controls[0].get('RW') is not (role!='api-proxy')):
                raise EdgeError('Exact private proxy control volume required')
        ordinary_mounts = [m for m in mounts if not (m.get('Type')=='tmpfs' and m.get('Destination')=='/tmp')]
        if role=='worker':
            workdir = str(self.root/'.sandbox-work')
            expected_binds = {'/var/run/docker.sock':'/var/run/docker.sock',workdir:workdir}
            if (len(ordinary_mounts)!=2 or any(m.get('Type')!='bind' or m.get('RW') is not True
                    or expected_binds.get(m.get('Destination'))!=m.get('Source') for m in ordinary_mounts)
                    or {m.get('Destination') for m in ordinary_mounts}!=set(expected_binds)
                    or env.get('SANDBOX_WORKDIR_ROOT')!=workdir):
                raise EdgeError('Exact worker-only sandbox/socket mounts required')
        elif role in ('api-proxy','proxy-controller','proxy-control-init'):
            if ordinary_mounts!=controls:
                raise EdgeError('Unexpected proxy control mount')
        elif ordinary_mounts:
            raise EdgeError('Unexpected service host/volume mount')
        if set(host.get('Tmpfs') or {})-{'/tmp'}:
            raise EdgeError('Unexpected runtime tmpfs mount')
        networks = data.get('NetworkSettings',{}).get('Networks') or {}
        if not isinstance(networks,dict) or len(networks)>8:
            raise EdgeError('Bounded container networks required')
        api_name,front_name = self.project+'-api-plane',self.project+'_frontend_plane'
        ingress_name = self.project+'_edge_ingress'
        expected_networks = ({api_name,self.shared_network} if role=='backend'
            else {self.shared_network} if role in ('worker','initialize','pgbouncer')
            else {api_name,front_name,ingress_name} if role=='api-proxy'
            else {front_name,ingress_name} if role=='frontend'
            else {'none'} if role=='proxy-control-init' else set())
        if set(networks)!=expected_networks:
            raise EdgeError('Unexpected runtime network attachment ('+role+')')
        if role!='proxy-controller' and host.get('NetworkMode') not in (expected_networks or {'none'}):
            raise EdgeError('Unexpected runtime network mode')
        endpoints = {name:{key:value.get(key) for key in ('NetworkID','EndpointID','IPAddress','GlobalIPv6Address')}
                     for name,value in networks.items()}
        for endpoint in endpoints.values():
            if role=='proxy-control-init' or stopped:
                # Docker retains the disabled endpoint key after exit. There
                # must be no address or live endpoint on this network mode.
                if any(endpoint[key]!='' for key in ('EndpointID','IPAddress','GlobalIPv6Address')):
                    raise EdgeError('Disabled initializer network has a live endpoint')
            exact_id(endpoint['NetworkID'])
            if role not in INITIALIZERS and not stopped:
                exact_id(endpoint['EndpointID'])
        # Never store the raw Env, command line, arbitrary labels or secrets.
        # A private digest detects reconfiguration without exposing its values.
        return {'id':identity,'role':role,'replica':replica,'image':image,
            'hostname':hostname,
            'timestamps':timestamps,'pid':state['Pid'],'restart_count':restart,
            'status':state['Status'],'exit_code':state['ExitCode'],
            'compose_config_hash':config_hash,'configuration_sha256':digest({'config':config,'host':host,'mounts':mounts}),
            'pid_mode':host.get('PidMode',''),'network_mode':host.get('NetworkMode',''),
            'networks':endpoints}

    def _network(self,name,expected_members,*,kind):
        raw = json.loads(self._read(['network','inspect',name]))
        if not isinstance(raw,list) or len(raw)!=1:
            raise EdgeError('Exact private network required')
        value = raw[0]
        labels = value.get('Labels') or {}
        expected = ({'io.webcompiler.network.role':'api-plane','io.webcompiler.pool':self.project,
                     'io.webcompiler.owner':hashlib.sha256(str(self.root.resolve()).encode()).hexdigest()}
                    if kind=='api-plane' else {'com.docker.compose.project':self.project,'com.docker.compose.network':kind})
        if (value.get('Name')!=name or value.get('Driver')!='bridge' or value.get('Scope')!='local'
                or value.get('Internal') is not (kind!='edge_ingress')
                or any(labels.get(k)!=v for k,v in expected.items())
                or set(value.get('Containers') or {})!=set(expected_members)):
            raise EdgeError('Foreign or changed private network membership')
        return {'id':exact_id(value['Id']),'name':name,'members':sorted(expected_members)}

    def observe(self):
        self._deadline = self.clock()+45
        try:
            return self._observe()
        except (ValueError,TypeError,KeyError,AttributeError,RecursionError):
            raise EdgeError('Malformed runtime ownership observation') from None

    def _observe(self,stopping=frozenset()):
        ids = self._ids()
        if not set(self.preserved_stateful)<=set(ids):
            raise EdgeError('Approved preserved stateful container is missing or changed project')
        if not isinstance(stopping,(set,frozenset)) or not stopping<=set(ids):
            raise EdgeError('Exact requested stop identities required')
        process_urls = {}
        records, preserved = [], []
        for identity in ids:
            record = self._container(identity,process_urls,allow_stopped=identity in stopping,allow_preserved=True)
            (preserved if record.get('preserved') else records).append(record)
        if not stopping<={record['id'] for record in records}:
            raise EdgeError('Preserved stateful containers cannot be retirement targets')
        verify_preservation(self.store,self.project,preserved)
        counts = Counter(record['role'] for record in records)
        if (set(counts)!=ROLES or counts['backend']<2 or counts['worker']<1
                or any(counts[role]!=1 for role in ROLES-{'backend','worker'})
                or len({(r['role'],r['replica']) for r in records})!=len(records)):
            raise EdgeError('Complete unambiguous runtime service inventory required')
        # API/worker DB process rows identify their owning process container by
        # role plus this Docker hostname.  Do not leave two candidate process
        # containers for a single hostname.  The controller intentionally is
        # excluded: it shares the proxy PID/network namespace, but is not an
        # API/worker DB-process container and has no required hostname relation
        # to the proxy.
        process_hosts = [record['hostname'] for record in records
                         if record['role'] in ('backend','worker')]
        if len(set(process_hosts))!=len(process_hosts):
            raise EdgeError('Ambiguous duplicate process container hostname')
        # Do not persist a credential-bearing URL or its digest.  Equality is
        # checked only while this exact Docker observation is in memory, so
        # the source DB snapshot cannot silently represent another process
        # container's database.
        database_urls = [process_urls.get(record['id']) for record in records
                         if record['role'] in PROCESS_ROLES]
        if (len(database_urls)!=len(process_hosts) or any(value is None for value in database_urls)
                or len(set(database_urls))!=1):
            raise EdgeError('Process containers do not share one managed database target')
        if len({record['image'] for record in records if record['role'] in APP_IMAGE_ROLES})!=1:
            raise EdgeError('Application roles must share the exact release image')
        if len({record['networks'][self.shared_network]['NetworkID'] for record in records
                if self.shared_network in record['networks']})!=1:
            raise EdgeError('Shared runtime network identity mismatch')
        proxy = next(r for r in records if r['role']=='api-proxy')
        controller = next(r for r in records if r['role']=='proxy-controller')
        if (controller['pid_mode']!='container:'+proxy['id']
                or controller['network_mode']!='container:'+proxy['id']):
            raise EdgeError('Exact controller/proxy namespace binding required')
        networks = []
        for name,roles,kind in ((self.project+'-api-plane',{'backend','api-proxy'},'api-plane'),
                              (self.project+'_frontend_plane',{'frontend','api-proxy'},'frontend_plane'),
                              (self.project+'_edge_ingress',{'frontend','api-proxy'},'edge_ingress')):
            members = [r['id'] for r in records if r['role'] in roles and r['status']=='running']
            network = self._network(name,members,kind=kind)
            if any(r['networks'].get(name,{}).get('NetworkID')!=network['id']
                   for r in records if r['id'] in members):
                raise EdgeError('Container/network observation mismatch')
            networks.append(network)
        if self._ids()!=ids:
            raise EdgeError('Runtime membership changed during observation')
        result = {'version':1,'project':self.project,'release':asdict(self.release),
                  'sandbox_pool':self.sandbox_pool,'shared_network':self.shared_network,
                  'containers':records,'private_networks':networks}
        if preserved:
            result['preserved_stateful'] = preserved
        if len(json.dumps(result).encode())>MAX_RECORD_BYTES:
            raise EdgeError('Runtime ownership record exceeds bounded capacity')
        return result

    def capture(self):
        observed = self.observe()
        if self.observe()!=observed:
            raise EdgeError('Runtime incarnation changed during capture')
        try:
            previous = self.store.read_json(self.path,max_bytes=MAX_RECORD_BYTES)
        except FileNotFoundError:
            self.store.write(self.path,observed)
        else:
            if previous!=observed:
                raise EdgeError('Existing runtime ownership evidence differs; reconcile explicitly')
        return True

    def verify(self):
        previous = self.store.read_json(self.path,max_bytes=MAX_RECORD_BYTES)
        if previous!=self.observe():
            raise EdgeError('Runtime incarnation changed after capture')
        return True

    def verify_retiring(self,requested):
        """Allow only recorded graceful stops, never restart/replacement drift.

Returns actual stopped IDs. A request or a timeout alone proves nothing.
Original promotion evidence remains immutable throughout partial shutdown.
"""
        previous = self.store.read_json(self.path,max_bytes=MAX_RECORD_BYTES)
        self._deadline = self.clock()+45
        try:
            observed = self._observe(requested)
            original = {row['id']:row for row in previous['containers']}
            stopped = set()
            for row in observed['containers']:
                before = original[row['id']]
                if row['status']=='exited' and before['status']=='running':
                    if row['id'] not in requested:
                        raise EdgeError('Unrequested container termination')
                    stopped.add(row['id'])
                    # These fields alone may change on an authorized graceful
                    # stop. Creation/start time, restart count, image/config,
                    # network IDs, labels and all other identity stay exact.
                    for key in ('status','pid','exit_code'):
                        row[key] = before[key]
                    row['timestamps']['FinishedAt'] = before['timestamps']['FinishedAt']
                    for name,endpoint in row['networks'].items():
                        for key in ('EndpointID','IPAddress','GlobalIPv6Address'):
                            endpoint[key] = before['networks'][name][key]
            for network in observed['private_networks']:
                original_network = next(n for n in previous['private_networks'] if n['name']==network['name'])
                network['members'] = sorted(set(network['members']) | (set(original_network['members']) & stopped))
            if observed != previous:
                raise EdgeError('Runtime identity changed during retirement')
            return stopped
        except (ValueError,TypeError,KeyError,AttributeError,StopIteration,RecursionError):
            raise EdgeError('Malformed retirement inventory') from None
