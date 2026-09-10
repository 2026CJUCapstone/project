"""Durable, compensating edge switch. No Docker or deployment side effects on import.

The commit record is authoritative; the config may be a provisional candidate.
After an interrupted switch, restore the committed config before another switch.
Callbacks must prove Nginx generation adoption and application readiness.
"""
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import json
import hashlib
import os
from pathlib import Path
import re
import stat
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.services.trusted_ingress import nginx_ingress, trusted_networks


class EdgeError(RuntimeError):
    pass


@dataclass(frozen=True)
class Release:
    color: str
    sha: str
    api_port: int
    frontend_port: int
    generation: str
    # Empty only for legacy snapshots: never infer ownership of old runtimes.
    runtime_id: str = ''

    def __post_init__(self):
        if self.runtime_id and (not isinstance(self.runtime_id,str) or
                not re.fullmatch('[0-9a-f]{32}',self.runtime_id) or self.runtime_id=='0'*32):
            raise ValueError('Exact runtime incarnation required')
        if not isinstance(self.runtime_id,str):
            raise ValueError('Exact runtime incarnation required')
        if self.color not in ('blue','green') or not isinstance(self.sha,str) or not re.fullmatch('[0-9a-f]{40}',self.sha):
            raise ValueError('Exact release and color required')
        if not isinstance(self.generation,str) or not re.fullmatch('[0-9a-f]{32}',self.generation) or self.generation=='0'*32:
            raise ValueError('Fresh edge generation required')
        for port in (self.api_port,self.frontend_port):
            if type(port) is not int or not 1024 <= port <= 65535:
                raise ValueError('Unprivileged loopback upstream port required')
        if self.api_port==self.frontend_port:
            raise ValueError('Distinct upstream ports required')


@dataclass(frozen=True)
class Layout:
    api_port: int
    frontend_port: int
    trusted_ingress: str = ''

    def __post_init__(self):
        object.__setattr__(self, 'trusted_ingress', ','.join(str(n) for n in trusted_networks(self.trusted_ingress)))
        for port in (self.api_port,self.frontend_port):
            if type(port) is not int or not 1024 <= port <= 65535:
                raise ValueError('Unprivileged loopback listener required')
        if self.api_port==self.frontend_port:
            raise ValueError('Distinct listener ports required')


def _template(layout, release):
    if release and set((layout.api_port,layout.frontend_port)) & {release.api_port,release.frontend_port}:
        raise ValueError('Edge cannot proxy back into its own listeners')
    generation = release.generation if release else '0'*32
    preamble = '''worker_processes 1;
worker_shutdown_timeout 150s;
pid /tmp/nginx.pid;
error_log /dev/stderr warn;
events { worker_connections 512; }
http {
    access_log off;
    client_body_temp_path /tmp/client_body;
    proxy_temp_path /tmp/proxy_temp;
    fastcgi_temp_path /tmp/fastcgi;
    uwsgi_temp_path /tmp/uwsgi;
    scgi_temp_path /tmp/scgi;
    map $http_upgrade $connection_upgrade { default upgrade; '' ''; }
    client_max_body_size 512k;
    client_header_timeout 10s;
    client_body_timeout 10s;
    keepalive_timeout 15s;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
    proxy_connect_timeout 2s;
    proxy_read_timeout 60s;
    proxy_send_timeout 15s;
    proxy_next_upstream off;
'''
    ingress, client_scheme = nginx_ingress(layout.trusted_ingress)
    preamble = preamble.replace('http {', 'http {\n'+ingress, 1).replace(
        'proxy_set_header X-Forwarded-Proto $scheme;',
        'proxy_set_header X-Forwarded-Proto '+client_scheme+';\n'
        '    proxy_set_header Forwarded "";\n    proxy_set_header X-Real-IP "";')
    # Local TLS termination also arrives from loopback. A public HTTP path
    # guarded by allow127 would expose diagnostics; only the private UDS has it.
    preamble += f'''    server {{
        listen unix:/status/control.sock;
        location = /generation {{ return 200 '{generation}'; }}
        location = /configuration {{ return 200 '__EDGE_ACK__'; }}
        location / {{ return 404; }}
    }}
'''
    if not release:
        return preamble + ''.join(f'    server {{ listen 127.0.0.1:{port}; return 503; }}\n'
                                 for port in (layout.api_port,layout.frontend_port))+'}\n'
    preamble += f'''    upstream color_api {{ server 127.0.0.1:{release.api_port}; keepalive 16; }}
    upstream color_frontend {{ server 127.0.0.1:{release.frontend_port}; keepalive 16; }}
'''
    servers = []
    for port, fallback in ((layout.api_port,'color_api'),(layout.frontend_port,'color_frontend')):
        locations = '''
        location /webcompiler/api/ { proxy_pass http://color_api/api/; }
        location /api/ { proxy_pass http://color_api; }
        location /webcompiler/ws/terminal { proxy_pass http://color_api/ws/terminal; proxy_read_timeout 3600s; }
        location /ws/terminal { proxy_pass http://color_api; proxy_read_timeout 3600s; }
        location = /webcompiler/health { proxy_pass http://color_api/health; }
        location = /health { proxy_pass http://color_api/health; }
        location = /webcompiler/ready { proxy_pass http://color_api/ready; }
        location = /ready { proxy_pass http://color_api/ready; }
        location = /generation { return 404; }
        location = /configuration { return 404; }
        location = /_edge_generation { return 404; }
'''
        servers.append(f'    server {{\n        listen 127.0.0.1:{port};\n'+locations+
                       f'        location / {{ proxy_pass http://{fallback}; }}\n    }}\n')
    return preamble+''.join(servers)+'}\n'


def acknowledgment(layout,release):
    return {'generation':release.generation if release else '0'*32,
            'release':asdict(release) if release else None,'layout':asdict(layout),
            'templateSha256':hashlib.sha256(_template(layout,release).encode()).hexdigest()}


def render(layout,release):
    return _template(layout,release).replace('__EDGE_ACK__',json.dumps(acknowledgment(layout,release),sort_keys=True))


def fsync_directory(path):
    if os.name=='posix':
        descriptor = os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


class Store:
    def __init__(self,path,layout):
        self.path, self.layout = Path(path), layout
        if not self.path.is_absolute() or self.path.resolve()!=self.path or len(self.path.parts)<3:
            raise ValueError('Explicit non-symlink edge directory required')

    def initialize(self):
        if not self.path.exists():
            self.path.mkdir(mode=0o700)
            fsync_directory(self.path.parent)
        self.check_directory(self.path)
        marker = {'version':1,'layout':asdict(self.layout)}
        owner = self.path/'owner.json'
        if owner.exists():
            if self.read_json(owner)!=marker:
                raise EdgeError('Existing edge directory belongs to another layout')
        elif any(self.path.iterdir()):
            raise EdgeError('Refusing an unowned nonempty edge directory')
        else:
            self.write(owner,marker)
        for name in ('config','status','state'):
            folder = self.path/name
            folder.mkdir(mode=0o700,exist_ok=True)
            self.check_directory(folder)
        (self.path/'state'/'drains').mkdir(mode=0o700,exist_ok=True)
        self.check_directory(self.path/'state'/'drains')
        fsync_directory(self.path)

    def inspect_existing(self):
        """Read-only ownership/schema check before any deployment effects."""
        if not self.path.exists():
            return False
        self.check_directory(self.path)
        if self.read_json(self.path/'owner.json')!={'version':1,'layout':asdict(self.layout)}:
            raise EdgeError('Existing edge directory belongs to another layout')
        for relative in ('config','status','state','state/drains'):
            self.check_directory(self.path/relative)
        self.record()
        self.pending()
        return True

    @staticmethod
    def check_directory(path):
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or (os.name=='posix' and
                (info.st_uid!=os.getuid() or info.st_mode & 0o077)):
            raise EdgeError('Private owner-only directory required')

    @contextmanager
    def locked(self):
        if os.name!='posix':
            raise EdgeError('Edge process locking requires POSIX')
        import fcntl
        descriptor = os.open(self.path/'state'/'lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        try:
            info=os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode & 0o077:
                raise EdgeError('Private owner-only lock required')
            fcntl.flock(descriptor,fcntl.LOCK_EX|fcntl.LOCK_NB)
            yield
        finally:
            os.close(descriptor)

    def write(self,path,value):
        payload = value if isinstance(value,str) else json.dumps(value,sort_keys=True)
        temporary = path.parent/('.write-'+uuid4().hex)
        try:
            fd=os.open(temporary,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as output:
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            temporary.replace(path)
            fsync_directory(path.parent)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def read_json(path,*,max_bytes=16384):
        fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
        with os.fdopen(fd,'r',encoding='utf-8') as source:
            info=os.fstat(source.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_size>max_bytes or
                    (os.name=='posix' and (info.st_uid!=os.getuid() or info.st_mode & 0o077))):
                raise EdgeError('Invalid edge record')
            return json.load(source)

    def record(self):
        try:
            data=self.read_json(self.path/'state'/'committed.json')
        except FileNotFoundError:
            return None
        if not isinstance(data,dict) or set(data)!={'version','release','config','configSha256','ack'} or data['version']!=1:
            raise EdgeError('Invalid committed edge state')
        release=Release(**data['release'])
        if (not isinstance(data['config'],str) or hashlib.sha256(data['config'].encode()).hexdigest()!=data['configSha256']
                or not isinstance(data['ack'],dict) or data['ack'].get('release')!=asdict(release)
                or data['ack'].get('generation')!=release.generation or data['ack'].get('layout')!=asdict(self.layout)
                or not re.fullmatch('[0-9a-f]{64}',str(data['ack'].get('templateSha256','')))):
            raise EdgeError('Committed edge snapshot does not match its identity/digest')
        return data

    def committed(self):
        record=self.record()
        return Release(**record['release']) if record else None

    def expected(self,release):
        record=self.record()
        if record and release==Release(**record['release']):
            return record['ack']
        return acknowledgment(self.layout,release)

    def configuration(self,release):
        record=self.record()
        if record and release==Release(**record['release']):
            return record['config']
        return render(self.layout,release)

    def commit(self,release):
        config=render(self.layout,release)
        self.write(self.path/'state'/'committed.json',{'version':1,'release':asdict(release),
            'config':config,'configSha256':hashlib.sha256(config.encode()).hexdigest(),
            'ack':acknowledgment(self.layout,release)})

    def intent(self,target,phase):
        if phase not in ('switch','restore'):
            raise ValueError('Unknown edge transition phase')
        previous=self.pending()
        if phase=='restore' and previous:
            # Preserve the provisional target: it may already have accepted
            # requests that must drain even after routing rolls back elsewhere.
            value={**previous,'phase':'restore','restore':self.expected(target)}
        else:
            value={'version':1,'operationId':uuid4().hex,'phase':phase,
                   'committed':self.expected(self.committed()),'target':self.expected(target)}
        self.write(self.path/'state'/'pending.json',value)

    def pending(self):
        try:
            value=self.read_json(self.path/'state'/'pending.json')
        except FileNotFoundError:
            return None
        if (not isinstance(value,dict) or value.get('version')!=1
                or not re.fullmatch('[0-9a-f]{32}',str(value.get('operationId','')))
                or value.get('phase') not in ('switch','restore')
                or set(value)-{'version','operationId','phase','committed','target','restore'}):
            raise EdgeError('Invalid edge recovery intent; manual investigation required')
        for key in ('committed','target')+ (('restore',) if 'restore' in value else ()):
            item=value.get(key)
            if not isinstance(item,dict) or set(item)!={'generation','release','layout','templateSha256'} or item['layout']!=asdict(self.layout):
                raise EdgeError('Recovery intent does not match the edge layout')
            release=Release(**item['release']) if item['release'] is not None else None
            if (item['generation']!=(release.generation if release else '0'*32)
                    or not re.fullmatch('[0-9a-f]{64}',str(item['templateSha256']))):
                raise EdgeError('Recovery intent identity/digest mismatch')
        return value

    def install(self,release):
        self.write(self.path/'config'/'nginx.conf',self.configuration(release))

    def clear_intent(self):
        value=self.pending()
        current=self.expected(self.committed())
        retired=[]
        if value:
            for identity in (value['committed'],value['target']):
                if identity['release'] is not None and identity!=current and identity not in retired:
                    retired.append(identity)
        if retired:
            # Routing recovery does not prove HTTP/WS retirement. Retain both
            # identities for the caller's explicit drain/retirement procedure.
            self.write(self.path/'state'/'drains'/(value['operationId']+'.json'),
                       {**value,'retained':current,'retire':retired})
        (self.path/'state'/'pending.json').unlink(missing_ok=True)
        fsync_directory(self.path/'state')


class Transaction:
    def __init__(self,store,activate,verify_committed,*,observe=None):
        self.store,self.activate,self.verify_committed,self.observe=store,activate,verify_committed,observe

    def restore(self):
        committed=self.store.committed()
        self.store.intent(committed,'restore')
        self.store.install(committed)
        if self.activate(committed) is not True:
            raise EdgeError('Committed edge configuration was not acknowledged; intent retained')
        if self.verify_committed(committed) is not True:
            raise EdgeError('Committed application postflight failed; intent retained')
        self.store.clear_intent()
        return committed

    def recover(self):
        with self.store.locked():
            if (self.store.path/'state'/'pending.json').exists():
                return self.restore()
            committed=self.store.committed()
            if (self.observe is None or self.observe()!=self.store.expected(committed)
                    or self.verify_committed(committed) is not True):
                raise EdgeError('Unjournaled edge state differs; explicit repair required')
            return committed

    def repair(self):
        """Explicit cold bootstrap/repair, never a silent no-journal reload."""
        with self.store.locked():
            return self.restore()

    def switch(self,target,*,preflight,postflight):
        # Callbacks run under the local edge lock. The caller must additionally
        # hold the deployment lock spanning source selection and runtime build.
        with self.store.locked():
            if (self.store.path/'state'/'pending.json').exists():
                self.restore()
            # Storage/admission bound only, never a reason to block recovery.
            # This does not authorize retiring any recorded runtime.
            if len(list((self.store.path/'state'/'drains').iterdir()))>=64:
                raise EdgeError('Prior edge operations require verified drain reconciliation')
            previous=self.store.committed()
            if previous and target.generation==previous.generation:
                raise EdgeError('Cannot reuse a committed generation')
            render(self.store.layout,target)  # reject bad ports before intent
            if preflight(target) is not True:
                raise EdgeError('Candidate preflight failed; no edge switch performed')
            self.store.intent(target,'switch')
            try:
                self.store.install(target)
                if self.activate(target) is not True:
                    raise EdgeError('Candidate Nginx generation not acknowledged')
                if postflight(target) is not True:
                    raise EdgeError('Candidate application postflight failed')
                # This atomic record is the commit point. If interruption occurs
                # after replace but before intent deletion, recovery keeps new.
                self.store.commit(target)
                self.store.clear_intent()
            except Exception as original:
                try:
                    self.restore()
                except Exception as rollback:
                    raise EdgeError('Edge switch failed and rollback is unconfirmed; recovery required') from rollback
                raise EdgeError('Edge switch failed; committed route restored') from original
            return target
