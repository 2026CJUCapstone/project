"""Owned combined Nginx edge lifecycle. Does not adopt/remove legacy edges.

Import-safe adapter for edge_transaction. Deployment-lock ownership and target
application pre/postflight remain the caller's responsibility.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import sys
import time

from edge_transaction import EdgeError, acknowledgment


# Docker restarts only after the previous container processes have exited.
# The private directory is reused, so a SIGKILL can leave this socket pathname.
# Never remove a regular file, symlink, foreign-UID socket or any other path.
EDGE_START = """set -eu
socket=/status/control.sock
if [ -e "$socket" ] || [ -L "$socket" ]; then
    [ ! -L "$socket" ] && [ -S "$socket" ] || exit 2
    [ "$(stat -c %u "$socket")" = "$(id -u)" ] || exit 2
    rm -- "$socket"
fi
exec nginx -c /control/nginx.conf -g 'daemon off;'
"""


def docker(args):
    result=subprocess.run(['docker',*args],capture_output=True,text=True,timeout=20)
    if result.returncode:
        raise EdgeError('Managed edge Docker operation failed')
    return result.stdout


def wait_postflight(check,*,timeout=15,stable_seconds=2,clock=time.monotonic,sleep=time.sleep):
    """Verify fresh requests on all public listeners beyond worker handoff.

The caller checks exact API release/readiness AND the static frontend target.
Existing requests may still drain on the old worker; this never replays them.
"""
    if not 1<=stable_seconds<=10 or not stable_seconds+2<=timeout<=60:
        raise ValueError('Bounded edge verification window required')
    deadline=clock()+timeout
    since=None
    while clock()<deadline:
        try:
            healthy=check() is True
        except (OSError,ValueError,EdgeError):
            healthy=False
        now=clock()
        if not healthy:
            since=None
        elif since is None:
            since=now
        elif now<deadline and now-since>=stable_seconds:
            return True
        sleep(min(.2,max(0,deadline-clock())))
    return False


class Runtime:
    def __init__(self,store,*,name='webcompiler-edge-v2',image='nginx:1.30.4-alpine-slim@sha256:77da26c31397bf6694b4bf93275f5b40b0b120ba1b8f114264b603e592c561d6',call=docker):
        if not re.fullmatch('[a-z0-9][a-z0-9_.-]{0,99}',name):
            raise ValueError('Explicit edge resource name required')
        if not image or image.startswith('-') or any(c.isspace() for c in image):
            raise ValueError('Preinstalled edge image required')
        self.store,self.name,self.image,self.call=store,name,image,call
        self.labels={'io.webcompiler.edge.role':'transactional-router',
                     'io.webcompiler.owner':hashlib.sha256(str(store.path).encode()).hexdigest()}

    def inspect(self):
        names=self.call(['container','ls','-a','--filter','name=^/'+re.escape(self.name)+'$', '--format','{{.Names}}']).splitlines()
        if self.name not in names:
            return None
        return json.loads(self.call(['container','inspect',self.name]))[0]

    def validate(self,container,image_id):
        host,actual=container['HostConfig'],container['Config']
        expected_user=f'{os.getuid()}:{os.getgid()}'
        mounts={item['Destination']:item for item in container['Mounts'] if item['Type']!='tmpfs'}
        valid=(container['Image']==image_id and actual.get('User')==expected_user
            and all((actual.get('Labels') or {}).get(k)==v for k,v in self.labels.items())
            and actual.get('Entrypoint')==['/bin/sh']
            and actual.get('Cmd')==['-c',EDGE_START]
            and host.get('NetworkMode')=='host' and host.get('ReadonlyRootfs') is True
            and not host.get('Privileged') and host.get('CapDrop')==['ALL'] and not host.get('CapAdd')
            and not host.get('PidMode') and host.get('IpcMode')=='private'
            and not host.get('Devices') and not host.get('DeviceRequests')
            and not host.get('PortBindings') and not host.get('PublishAllPorts')
            and host.get('Memory')==host.get('MemorySwap')==96*1024*1024
            and host.get('NanoCpus')==250_000_000 and host.get('PidsLimit')==64
            and host.get('RestartPolicy',{}).get('Name')=='unless-stopped'
            and host.get('LogConfig')=={'Type':'json-file','Config':{'max-size':'10m','max-file':'3'}}
            and (host.get('SecurityOpt') or []) in (['no-new-privileges'],['no-new-privileges:true'])
            and host.get('Tmpfs')=={'/tmp':'rw,noexec,nosuid,size=32m,mode=1777'}
            and set(mounts)=={'/control','/status'})
        for destination,source,writable in (('/control','config',False),('/status','status',True)):
            mount=mounts.get(destination,{})
            valid=valid and mount.get('Type')=='bind' and mount.get('Source')==str(self.store.path/source) and mount.get('RW') is writable
        if not valid:
            raise EdgeError('Refusing unowned or mismatched edge container')

    def preflight(self):
        """Read-only identity/port checks; does not create state or containers."""
        if sys.platform!='linux' or os.getuid()==0:
            raise EdgeError('Managed edge requires an unprivileged Linux deployment account')
        image_id=json.loads(self.call(['image','inspect',self.image]))[0]['Id']
        owners=self.call(['container','ls','-a','--filter',
                         'label=io.webcompiler.owner='+self.labels['io.webcompiler.owner'],
                         '--format','{{.Names}}']).splitlines()
        if any(name!=self.name for name in owners):
            raise EdgeError('Another container owns this edge directory; refusing shared control socket')
        container=self.inspect()
        if container is not None:
            self.validate(container,image_id)
            if container['State']['Running']:
                return container
        probes=[]
        try:
            for port in (self.store.layout.api_port,self.store.layout.frontend_port):
                probe=socket.socket()
                probes.append(probe)
                probe.bind(('127.0.0.1',port))
        finally:
            for probe in probes:
                probe.close()
        return container

    def _ensure(self):
        container=self.preflight()
        image_id=json.loads(self.call(['image','inspect',self.image]))[0]['Id']
        if container is None:
            # Do not rm/stop/reconfigure other listeners to make these ports
            # available. A port conflict is an explicit migration blocker.
            for port in (self.store.layout.api_port,self.store.layout.frontend_port):
                with socket.socket() as probe:
                    probe.bind(('127.0.0.1',port))
            args=['create','--name',self.name,'--network','host','--pull','never',
                '--user',f'{os.getuid()}:{os.getgid()}','--read-only','--cap-drop','ALL',
                '--security-opt','no-new-privileges:true','--restart','unless-stopped',
                '--memory','96m','--memory-swap','96m','--cpus','0.25','--pids-limit','64',
                '--tmpfs','/tmp:rw,noexec,nosuid,size=32m,mode=1777',
                '--log-driver','json-file','--log-opt','max-size=10m','--log-opt','max-file=3',
                '--mount','type=bind,source='+str(self.store.path/'config')+',target=/control,readonly',
                '--mount','type=bind,source='+str(self.store.path/'status')+',target=/status',
                '--entrypoint','/bin/sh']
            for key,value in self.labels.items():
                args+=['--label',key+'='+value]
            self.call(args+[image_id,'-c',EDGE_START])
            container=self.inspect()
        self.validate(container,image_id)
        if not container['State']['Running']:
            self.call(['start',container['Id']])
        return container['Id']

    def launch_committed(self):
        """Explicit cold/stopped start from committed bytes, never a candidate."""
        with self.store.locked():
            release=self.store.committed()
            self.store.intent(release,'restore')
            self.store.install(release)
            self._ensure()
            if not self.wait_ack(release):
                raise EdgeError('Started edge did not acknowledge committed configuration')

    def observe(self):
        # Linux sockaddr_un paths are short. The deployment checkout can be
        # deeply nested: connect through an owned directory fd, not its full
        # host pathname (the container itself binds the short /status path).
        directory=os.open(self.store.path/'status',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:
            info=os.stat('control.sock',dir_fd=directory,follow_symlinks=False)
            if not stat.S_ISSOCK(info.st_mode) or info.st_uid!=os.getuid():
                raise EdgeError('Private edge status socket required')
            return self._read_socket(f'/proc/self/fd/{directory}/control.sock')
        finally:
            os.close(directory)

    @staticmethod
    def _read_socket(path):
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
            deadline=time.monotonic()+2
            client.settimeout(1)
            client.connect(path)
            client.sendall(b'GET /configuration HTTP/1.1\r\nHost: edge.local\r\nConnection: close\r\n\r\n')
            data=b''
            def receive(size):
                remaining=deadline-time.monotonic()
                if remaining<=0:
                    raise TimeoutError('Edge acknowledgment deadline exceeded')
                client.settimeout(min(1,remaining))
                return client.recv(size)
            while b'\r\n\r\n' not in data:
                block=receive(1024)
                if not block or len(data)+len(block)>8192:
                    raise EdgeError('Invalid edge response headers')
                data+=block
            header,body=data.split(b'\r\n\r\n',1)
            lines=header.decode('ascii').split('\r\n')
            if lines[0].split()[:2]!=['HTTP/1.1','200']:
                raise EdgeError('Edge acknowledgment unavailable')
            headers={}
            for line in lines[1:]:
                key,value=line.split(':',1)
                if key.lower() in headers:
                    raise EdgeError('Ambiguous edge acknowledgment')
                headers[key.lower()]=value.strip()
            size=headers.get('content-length','')
            if not size.isascii() or not size.isdecimal() or not 0<int(size)<=4096 or 'transfer-encoding' in headers:
                raise EdgeError('Unbounded edge acknowledgment')
            while len(body)<int(size):
                block=receive(min(4096,int(size)-len(body)))
                if not block:
                    raise EdgeError('Truncated edge acknowledgment')
                body+=block
            return json.loads(body[:int(size)])

    def activate(self,release):
        image_id=json.loads(self.call(['image','inspect',self.image]))[0]['Id']
        container=self.inspect()
        if container is None or not container['State']['Running']:
            raise EdgeError('Cold/stopped edge must be explicitly launched from committed configuration')
        self.validate(container,image_id)
        container_id=container['Id']
        # Test before HUP, but still require the new workers' UDS response:
        # syntax validation or successful signal delivery alone proves nothing.
        self.call(['exec',container_id,'nginx','-t','-c','/control/nginx.conf'])
        # Docker's kill endpoint marks even HUP as manually stopped, which
        # suppresses a later unless-stopped crash restart. Signal via Nginx
        # inside the verified container instead of Docker's kill API.
        self.call(['exec',container_id,'nginx','-s','reload','-c','/control/nginx.conf'])
        return self.wait_ack(release)

    def wait_ack(self,release):
        expected=self.store.expected(release)
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            try:
                if self.observe()==expected:
                    return True
            except (OSError,EdgeError,ValueError):
                pass
            time.sleep(.1)
        return False
