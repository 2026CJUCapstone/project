"""Deployment adapter for the durable edge, guarded by the parent deploy lock.

No implicit legacy handoff, container retirement, DB migration or image pull.
The committed snapshot is authoritative; active-color is only a projection.
"""
import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import time
from uuid import uuid4

from edge_transaction import EdgeError, Layout, Release, Store, Transaction
from edge_runtime import Runtime, docker, wait_postflight
from runtime_inventory import (Inventory, bounded_docker, exact_id, preserved_stateful_record,
                               preservation_path, preservation_value, verify_preservation)
from runtime_binding import Binding
from runtime_retirement import Retirement


@dataclass(frozen=True)
class Config:
    root: Path
    layout: Layout
    blue: tuple
    green: tuple
    edge_name: str = 'webcompiler-edge-v2'
    project_prefix: str = 'webcompiler'
    legacy_names: tuple = ('webcompiler-edge-backend','webcompiler-edge-frontend')
    sandbox_pool: str = 'webcompiler'
    shared_network: str = 'webcompiler-shared'
    preserved_blue: tuple = ()
    preserved_green: tuple = ()

    def __post_init__(self):
        if (not self.root.is_absolute() or self.root.resolve()!=self.root
                or len(self.root.parts)<3 or (self.root/'.deploy').is_symlink()):
            raise ValueError('Explicit non-symlink deployment root required')
        for pair in (self.blue,self.green):
            if not isinstance(pair,tuple) or len(pair)!=2:
                raise ValueError('Two color ports required')
            Layout(*pair)
        if len({self.layout.api_port,self.layout.frontend_port,*self.blue,*self.green})!=6:
            raise ValueError('All edge/color ports must be distinct')
        for name in (self.edge_name,self.project_prefix,*self.legacy_names):
            if not isinstance(name,str) or not re.fullmatch('[a-z0-9][a-z0-9_-]{0,79}',name):
                raise ValueError('Explicit deployment resource names required')
        if len(self.project_prefix)>66:
            raise ValueError('Deployment prefix must leave room for derived resource names')
        if not isinstance(self.sandbox_pool,str) or not re.fullmatch('[a-z0-9][a-z0-9_-]{0,79}',self.sandbox_pool):
            raise ValueError('Explicit sandbox pool identity required')
        if not isinstance(self.shared_network,str) or not re.fullmatch('[a-z0-9][a-z0-9_-]{0,79}',self.shared_network):
            raise ValueError('Explicit shared network name required')
        for identities in (self.preserved_blue,self.preserved_green):
            if not isinstance(identities,tuple) or len(identities)>4 or len(set(identities))!=len(identities):
                raise ValueError('At most four distinct preserved stateful IDs per color required')
            for identity in identities:
                exact_id(identity)
        if set(self.preserved_blue)&set(self.preserved_green):
            raise ValueError('A preserved stateful container cannot belong to both colors')

    @classmethod
    def from_environment(cls):
        prefix=os.environ.get('WEBCOMPILER_PROJECT_PREFIX','webcompiler')
        if not isinstance(prefix,str) or not re.fullmatch('[a-z0-9][a-z0-9_-]{0,65}',prefix):
            raise ValueError('Explicit deployment resource names required')
        def preserved(color):
            value=os.environ.get('WEBCOMPILER_'+color+'_PRESERVED_STATEFUL_IDS','')
            return tuple(value.split(',')) if value else ()
        def port(name,default):
            if prefix!='webcompiler' and 'WEBCOMPILER_'+name not in os.environ:
                raise ValueError('Custom deployment prefix requires six explicit edge/color ports')
            raw=os.environ.get('WEBCOMPILER_'+name,str(default))
            if not re.fullmatch('[0-9]{4,5}',raw):
                raise ValueError('Invalid deployment port')
            return int(raw)
        root=Path(os.environ['PROJECT_ROOT'])
        legacy=os.environ.get('WEBCOMPILER_LEGACY_PROJECT_NAME',prefix)
        expected=root/'.deploy'/'active-color'
        if os.environ.get('WEBCOMPILER_ACTIVE_COLOR_FILE',str(expected))!=str(expected):
            raise ValueError('Managed deployment requires the canonical active-color projection')
        return cls(root,Layout(port('EDGE_BACKEND_PORT',18000),port('EDGE_FRONTEND_PORT',15173),
                              os.environ.get('WEBCOMPILER_EDGE_TRUSTED_INGRESS_CIDRS','')),
                   (port('BLUE_BACKEND_PORT',18001),port('BLUE_FRONTEND_PORT',15174)),
                   (port('GREEN_BACKEND_PORT',18002),port('GREEN_FRONTEND_PORT',15175)),
                   edge_name=os.environ.get('WEBCOMPILER_EDGE_NAME',prefix+'-edge-v2'),
                   project_prefix=prefix,
                   legacy_names=(os.environ.get('WEBCOMPILER_BACKEND_EDGE_NAME',prefix+'-edge-backend'),
                                 os.environ.get('WEBCOMPILER_FRONTEND_EDGE_NAME',prefix+'-edge-frontend'),
                                 legacy+'-backend-1',legacy+'-frontend-1'),
                   sandbox_pool=os.environ.get('SANDBOX_POOL_ID',prefix),
                   shared_network=os.environ.get('WEBCOMPILER_SHARED_POSTGRES_NETWORK',prefix+'-shared'),
                   preserved_blue=preserved('BLUE'),preserved_green=preserved('GREEN'))

    def release(self,color,sha):
        if color not in ('blue','green'):
            raise ValueError('Invalid color')
        return Release(color,sha,*(self.blue if color=='blue' else self.green),uuid4().hex,uuid4().hex)


def require_deploy_lock(root):
    """The shell holds fd9 from source selection until this child exits."""
    import fcntl
    expected=root/'.deploy'/'deploy.lock'
    if expected.is_symlink() or Path('/proc/self/fd/9').resolve()!=expected:
        raise EdgeError('Verified parent deployment lock required')
    info=os.fstat(9)
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid():
        raise EdgeError('Invalid deployment lock owner')
    # An open fd is not evidence of a lock held throughout source selection.
    # A separate open description must conflict; then fd9 itself must retain
    # the lock (not merely point at a file locked by some unrelated process).
    probe=os.open(expected,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        other=os.fstat(probe)
        if (other.st_dev,other.st_ino)!=(info.st_dev,info.st_ino):
            raise EdgeError('Deployment lock identity changed')
        try:
            fcntl.flock(probe,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            pass
        else:
            raise EdgeError('Deployment lock was not held by parent')
    finally:
        os.close(probe)
    fcntl.flock(9,fcntl.LOCK_EX|fcntl.LOCK_NB)


def loopback_json(port,path):
    """No redirects/proxies/chunking; 2s total IO, 8KiB headers, 4KiB body."""
    if path not in ('/health','/ready','/webcompiler/.well-known/webcompiler-release.json'):
        raise ValueError('Unknown release probe path')
    deadline=time.monotonic()+2
    with socket.create_connection(('127.0.0.1',port),timeout=2) as client:
        def receive(size):
            remaining=deadline-time.monotonic()
            if remaining<=0:
                raise TimeoutError('Release probe deadline exceeded')
            client.settimeout(remaining)
            return client.recv(size)
        remaining=deadline-time.monotonic()
        if remaining<=0:
            raise TimeoutError('Release probe deadline exceeded')
        client.settimeout(remaining)
        client.sendall(f'GET {path} HTTP/1.1\r\nHost: edge.local\r\nConnection: close\r\n\r\n'.encode('ascii'))
        data=b''
        while b'\r\n\r\n' not in data:
            block=receive(1024)
            if not block or len(data)+len(block)>8192:
                raise EdgeError('Invalid release probe headers')
            data+=block
        head,body=data.split(b'\r\n\r\n',1)
        lines=head.decode('ascii').split('\r\n')
        status=lines[0].split()
        if len(status)<2 or status[0]!='HTTP/1.1' or not re.fullmatch('[1-5][0-9]{2}',status[1]):
            raise EdgeError('Invalid release probe status')
        headers={}
        for line in lines[1:]:
            key,value=line.split(':',1)
            if key.lower() in headers:
                raise EdgeError('Ambiguous release probe headers')
            headers[key.lower()]=value.strip()
        length=headers.get('content-length','')
        if 'transfer-encoding' in headers or not re.fullmatch('[0-9]{1,4}',length) or not 0<int(length)<=4096:
            raise EdgeError('Unbounded release probe body')
        while len(body)<int(length):
            block=receive(int(length)-len(body))
            if not block:
                raise EdgeError('Truncated release probe body')
            body+=block
        code=int(status[1])
        if code!=200:
            return code,None
        if not headers.get('content-type','').split(';',1)[0].strip()=='application/json':
            raise EdgeError('Release probe did not return JSON')
        return code,json.loads(body[:int(length)])


class Deployment:
    def __init__(self,config,*,call=docker,probe=loopback_json):
        self.config,self.call,self.probe=config,call,probe
        self.store=Store(config.root/'.deploy'/'edge-v2',config.layout)
        self.runtime=Runtime(self.store,name=config.edge_name,call=call)
        self.transaction=Transaction(self.store,self.runtime.activate,
                                     lambda release:self.verify(release,edge=True),observe=self.runtime.observe)
        self._preserved_preflight=None

    @property
    def projection(self):
        return self.config.root/'.deploy'/'active-color'

    def read_projection(self):
        try:
            fd=os.open(self.projection,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
        except FileNotFoundError:
            return None
        with os.fdopen(fd,'r',encoding='ascii') as source:
            info=os.fstat(source.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_size>16
                    or (os.name=='posix' and info.st_uid!=os.getuid())):
                raise EdgeError('Invalid active-color projection')
            value=source.read()
        if value not in ('','\n','blue\n','green\n'):
            raise EdgeError('Invalid active-color projection')
        return value.strip()

    def project(self):
        # Never use or mutate an arbitrary caller-provided path.
        self.read_projection()
        release=self.store.committed()
        self.store.write(self.projection,(release.color if release else '')+'\n')
        return release.color if release else ''

    def observe_preserved(self):
        observations={}
        for color,identities in (('blue',self.config.preserved_blue),('green',self.config.preserved_green)):
            project=self.config.project_prefix+'-'+color
            records=[]
            for identity in sorted(identities):
                read=bounded_docker if self.call is docker else self.call
                raw=json.loads(read(['container','inspect',identity]))
                if not isinstance(raw,list) or len(raw)!=1:
                    raise EdgeError('Exact preserved stateful inspection required')
                records.append(preserved_stateful_record(raw[0],identity,project,
                    shared_network=self.config.shared_network))
            verify_preservation(self.store,project,records,allow_unbound=True)
            observations[project]=records
        return observations

    def bind_preserved(self,expected=None):
        # Called by prepare under the parent deployment lock. Bind the first
        # explicit exception before runtime launch; never overwrite an existing
        # baseline, and never let per-release inventory capture enroll one.
        observed=self.observe_preserved()
        if expected is None:
            expected=observed
            observed=self.observe_preserved()
        if observed!=expected:
            raise EdgeError('Preservation configuration changed after preflight')
        # Both colors, including explicit empty selections, are one atomic
        # record. A crash cannot leave the other color open to new enrollment.
        value={'version':1,'projects':{project:preservation_value(project,records)['projects'][project]
            for project,records in observed.items()}}
        path=preservation_path(self.store,self.config.project_prefix+'-blue')
        try:
            previous=self.store.read_json(path)
        except FileNotFoundError:
            self.store.write(path,value)
        else:
            if previous!=value:
                raise EdgeError('Preserved stateful preservation configuration changed; explicit reconciliation required')

    def preflight(self):
        existing=self.store.inspect_existing()
        # No name-only adoption or new baseline on a later release. Omitting
        # an already-bound exception is also a configuration change.
        self._preserved_preflight=self.observe_preserved()
        projection=self.read_projection()
        if projection and (not existing or self.store.committed() is None):
            raise EdgeError('Legacy active-color requires explicit verified handoff')
        names=self.call(['container','ls','-a','--format','{{.Names}}']).splitlines()
        legacy=set(self.config.legacy_names)|{
            self.config.project_prefix+'-backend-1',self.config.project_prefix+'-frontend-1'}
        if set(names)&legacy:
            raise EdgeError('Legacy runtime requires explicit verified handoff; nothing stopped')
        container=self.runtime.preflight()
        if container and not existing:
            raise EdgeError('Existing edge has no owned state; explicit repair required')
        return container

    def prepare(self):
        container=self.preflight()
        self.store.initialize()
        self.bind_preserved(self._preserved_preflight)
        if container is None or not container['State']['Running']:
            self.runtime.launch_committed()
        self.transaction.recover()
        return self.project()

    def verify(self,release,*,edge=False):
        def check():
            if release is None:
                return all(self.probe(port,'/health')[0]==503 for port in
                           (self.config.layout.api_port,self.config.layout.frontend_port))
            api_ports=(self.config.layout.api_port,self.config.layout.frontend_port) if edge else (release.api_port,)
            frontend=self.config.layout.frontend_port if edge else release.frontend_port
            for port in api_ports:
                code,health=self.probe(port,'/health')
                if (code!=200 or not isinstance(health,dict) or health.get('status')!='ok'
                        or health.get('deploymentSha')!=release.sha
                        or not release.runtime_id or health.get('runtimeInstanceId')!=release.runtime_id):
                    return False
                if self.probe(port,'/ready')!=(200,{'status':'ready'}):
                    return False
            return self.probe(frontend,'/webcompiler/.well-known/webcompiler-release.json')==(200,{'deployment_sha':release.sha})
        return wait_postflight(check,timeout=20)

    def gate(self,release):
        project=self.config.project_prefix+'-'+release.color
        ids=self.call(['container','ls','--filter','label=com.docker.compose.project='+project,
                       '--filter','label=com.docker.compose.service=proxy-controller','--format','{{.ID}}']).splitlines()
        if len(ids)!=1 or not re.fullmatch('[0-9a-f]{12,64}',ids[0]):
            raise EdgeError('Exactly one running color controller is required')
        container=json.loads(self.call(['container','inspect',ids[0]]))[0]
        environment=container['Config'].get('Env') or []
        if (not container['State']['Running'] or 'DEPLOYMENT_SHA='+release.sha not in environment
                or 'PROXY_POOL_ID='+project not in environment or not release.runtime_id
                or 'RUNTIME_INSTANCE_ID='+release.runtime_id not in environment):
            raise EdgeError('Color controller release/pool mismatch')
        # The CLI enforces a 60s internal deadline. Do not print container env,
        # command output, credentials or dependency errors on failed promotion.
        result=subprocess.run(['docker','exec',container['Id'],'python','-m','app.proxy_promotion',
                               '--release',release.sha,'--pool',project,'--runtime',release.runtime_id],capture_output=True,timeout=70)
        if result.returncode:
            raise EdgeError('Two-peer color promotion gate failed')
        return True

    def check_build(self,color):
        previous=self.store.committed()
        if previous and previous.color==color:
            raise EdgeError('Refusing to rebuild the committed color in place')
        if self.store.pending() is not None:
            raise EdgeError('Recover pending edge operation before building')
        if any((self.store.path/'state'/'drains').iterdir()):
            raise EdgeError('Previous runtime drain/retirement must be verified before another build')

    def reserved(self):
        try:
            value=self.store.read_json(self.store.path/'state'/'candidate.json')
        except FileNotFoundError:
            return None
        if not isinstance(value,dict) or set(value)!={'version','release'} or value['version']!=1:
            raise EdgeError('Invalid reserved candidate; explicit reconciliation required')
        try:
            release=Release(**value['release'])
        except (TypeError,ValueError):
            raise EdgeError('Invalid reserved candidate identity') from None
        ports=self.config.blue if release.color=='blue' else self.config.green
        if not release.runtime_id or (release.api_port,release.frontend_port)!=ports:
            raise EdgeError('Reserved candidate differs from deployment layout')
        return release

    def candidate(self,color,sha):
        # Parent deployment lock covers source selection/build; the edge lock
        # also serializes this durable reservation with routing recovery.
        requested=self.config.release(color,sha)
        with self.store.locked():
            self.check_build(color)
            reserved=self.reserved()
            if reserved is not None and reserved!=self.store.committed():
                if (reserved.color,reserved.sha)!=(color,sha):
                    raise EdgeError('Unfinished candidate differs; explicit reconciliation required')
                return reserved
            self.store.write(self.store.path/'state'/'candidate.json',
                             {'version':1,'release':asdict(requested)})
            return requested

    def inventory(self,release):
        return Inventory(self.store,self.config.root,self.config.project_prefix+'-'+release.color,
                         release,self.config.sandbox_pool,bounded_docker if self.call is docker else self.call,
                         shared_network=self.config.shared_network,
                         preserved_stateful=self.config.preserved_blue if release.color=='blue' else self.config.preserved_green)

    def capture_inventory(self,release):
        return self.inventory(release).capture()

    def verify_inventory(self,release):
        return self.inventory(release).verify()

    def inspect_runtime(self,release):
        # Evidence only: never fences, stops containers, closes DB rows or
        # removes drain markers. Serialize against local routing mutations.
        with self.store.locked():
            return Binding(self.inventory(release)).observe()

    def retire_pending(self):
        with self.store.locked():
            if self.store.pending() is not None:
                raise EdgeError('Recover routing before retiring a runtime')
            paths=list((self.store.path/'state'/'drains').iterdir())
            if not paths:
                return {'phase':'retired','remaining':0}
            if len(paths)>64:
                raise EdgeError('Drain registry exceeds capacity')
            value=self.store.read_json(sorted(paths)[0])
            release=Release(**value['retire'][0]['release'])
            ports=self.config.blue if release.color=='blue' else self.config.green
            if not release.runtime_id or (release.api_port,release.frontend_port)!=ports:
                raise EdgeError('Drain target differs from configured color ports')
            return Retirement(self,release).step()

    def switch(self,color,sha):
        self.preflight()
        self.check_build(color)
        release=self.reserved()
        if release is None or (release.color,release.sha)!=(color,sha):
            raise EdgeError('Exact reserved candidate required before switching')
        def before(target):
            return self.gate(target) and self.verify(target) and self.capture_inventory(target)
        def after(target):
            return self.verify(target,edge=True) and self.gate(target) and self.verify_inventory(target)
        self.transaction.switch(release,preflight=before,postflight=after)
        return self.project()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=('preflight','prepare','candidate','switch','retire'))
    parser.add_argument('--color',choices=('blue','green'))
    args=parser.parse_args()
    try:
        config=Config.from_environment()
        require_deploy_lock(config.root)
        deploy=Deployment(config)
        if args.operation=='preflight':
            deploy.preflight()
        elif args.operation=='prepare':
            print(deploy.prepare())
        elif args.operation=='retire':
            print(json.dumps(deploy.retire_pending(),sort_keys=True))
        else:
            if args.color is None:
                raise ValueError('Color is required')
            sha=os.environ['DEPLOY_SHA']
            if args.operation=='candidate':
                print(deploy.candidate(args.color,sha).runtime_id)
            else:
                print(deploy.switch(args.color,sha))
    except EdgeError as error:
        parser.exit(1,str(error)+'\n')
    except (ValueError,KeyError,OSError,subprocess.SubprocessError):
        parser.exit(1,'Managed edge operation failed; existing state retained for inspection\n')


if __name__=='__main__':
    main()
