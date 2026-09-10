#!/usr/bin/env python3
"""Create/validate one private, persistent Redis independent of deploy colors.

No adoption of unlabelled resources, reset, removal, image pull or data migration.
An operator-provided external Redis URL bypasses this managed service in deploy.
"""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


class SharedRedisError(RuntimeError):
    pass


@dataclass(frozen=True)
class Config:
    root: str
    name: str = 'webcompiler-redis'
    volume: str = 'webcompiler-redis-data'
    network: str = 'webcompiler-shared'
    image: str = 'redis:7-alpine@sha256:ff02b58f971e7d7d156a1267e283fcbbeee91773b6aa36c49dac28ecfe28eadf'
    memory_mb: int = 320
    maxmemory_mb: int = 256
    cpu_millis: int = 500

    def __post_init__(self):
        root = Path(self.root)
        if not root.is_absolute() or len(root.parts) < 3 or root.resolve() == Path.home():
            raise ValueError('An explicit deployment directory is required')
        for value in (self.name, self.volume, self.network):
            if re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}', value) is None:
                raise ValueError('Invalid Docker resource name')
        if not self.image or self.image.startswith('-') or any(c.isspace() for c in self.image):
            raise ValueError('Invalid preinstalled Redis image')
        if not 64 <= self.memory_mb <= 2048 or not 16 <= self.maxmemory_mb < self.memory_mb:
            raise ValueError('Invalid Redis memory budget')
        if not 50 <= self.cpu_millis <= 2000:
            raise ValueError('Invalid Redis CPU budget')

    @property
    def labels(self):
        return {'io.webcompiler.shared.role':'redis', 'io.webcompiler.owner':
                hashlib.sha256(str(Path(self.root).resolve()).encode()).hexdigest()}

    @property
    def command(self):
        # Only an isolated bridge network; never publish Redis to a host port.
        return ['redis-server','--bind','0.0.0.0','--protected-mode','no',
                '--appendonly','yes','--appendfsync','everysec','--save','60','1000',
                '--maxmemory',str(self.maxmemory_mb)+'mb','--maxmemory-policy','noeviction']


def docker(args):
    result = subprocess.run(['docker', *args], capture_output=True, text=True, timeout=20)
    if result.returncode:
        # Never include inspect/env output or arbitrary CLI stderr in logs.
        raise SharedRedisError('Shared Redis Docker operation failed')
    return result.stdout


def ensure(config, *, call=docker):
    network = json.loads(call(['network','inspect',config.network]))[0]
    if network.get('Driver') != 'bridge' or network.get('Scope') != 'local':
        raise SharedRedisError('Shared Redis requires an existing private bridge network')
    call(['image','inspect',config.image])  # No implicit pull of a mutable image.
    volume_names = call(['volume','ls','--filter','name=^'+re.escape(config.volume)+'$', '--format','{{.Name}}']).splitlines()
    if config.volume not in volume_names:
        args = ['volume','create']
        for key, value in config.labels.items():
            args += ['--label', key+'='+value]
        call(args+[config.volume])
    volume = json.loads(call(['volume','inspect',config.volume]))[0]
    if (any((volume.get('Labels') or {}).get(k) != v for k,v in config.labels.items())
            or volume.get('Driver') != 'local' or volume.get('Options')):
        raise SharedRedisError('Refusing a Redis volume owned by another deployment')
    names = call(['container','ls','-a','--filter','name=^/'+re.escape(config.name)+'$', '--format','{{.Names}}']).splitlines()
    if config.name not in names:
        args = ['run','-d','--pull','never','--name',config.name,'--restart','unless-stopped',
                '--network',config.network,'--memory',str(config.memory_mb)+'m',
                '--memory-swap',str(config.memory_mb)+'m','--cpus',str(config.cpu_millis/1000),
                '--pids-limit','128','--read-only','--tmpfs','/tmp:rw,noexec,nosuid,size=16m',
                '--security-opt','no-new-privileges:true','--log-driver','json-file',
                '--log-opt','max-size=10m','--log-opt','max-file=3',
                '--mount','type=volume,source='+config.volume+',target=/data']
        for key,value in config.labels.items():
            args += ['--label',key+'='+value]
        call(args+[config.image,*config.command])
    container = json.loads(call(['container','inspect',config.name]))[0]
    actual, host = container['Config'], container['HostConfig']
    valid = (all((actual.get('Labels') or {}).get(k) == v for k,v in config.labels.items())
        and actual['Image'] == config.image and actual['Cmd'] == config.command
        and not host.get('PortBindings') and not host.get('PublishAllPorts')
        and not host.get('Privileged') and host.get('ReadonlyRootfs')
        and set(container['NetworkSettings']['Networks']) == {config.network}
        and host['Memory'] == host['MemorySwap'] == config.memory_mb*1024*1024
        and host['NanoCpus'] == config.cpu_millis*1_000_000 and host['PidsLimit'] == 128
        and any(option in ('no-new-privileges', 'no-new-privileges:true')
                for option in (host.get('SecurityOpt') or []))
        and host.get('LogConfig') == {'Type':'json-file', 'Config':{'max-size':'10m','max-file':'3'}}
        and host['RestartPolicy']['Name'] == 'unless-stopped')
    volumes = [m for m in container['Mounts'] if m['Type'] != 'tmpfs']
    valid = (valid and len(volumes) == 1 and volumes[0].get('Name') == config.volume
             and volumes[0]['Destination'] == '/data' and volumes[0].get('RW') is True)
    if not valid:
        raise SharedRedisError('Existing shared Redis differs from the approved configuration')
    if not container['State']['Running']:
        call(['start',config.name])
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            if call(['exec',config.name,'redis-cli','ping']).strip() == 'PONG':
                return
        except SharedRedisError:
            pass
        time.sleep(1)
    raise SharedRedisError('Shared Redis did not become ready')


def main():
    try:
        ensure(Config(root=os.environ['PROJECT_ROOT'],
            name=os.getenv('WEBCOMPILER_SHARED_REDIS_NAME','webcompiler-redis'),
            volume=os.getenv('WEBCOMPILER_SHARED_REDIS_VOLUME','webcompiler-redis-data'),
            network=os.getenv('WEBCOMPILER_SHARED_POSTGRES_NETWORK','webcompiler-shared'),
            image=os.getenv('WEBCOMPILER_SHARED_REDIS_IMAGE','redis:7-alpine@sha256:ff02b58f971e7d7d156a1267e283fcbbeee91773b6aa36c49dac28ecfe28eadf'),
            memory_mb=int(os.getenv('WEBCOMPILER_SHARED_REDIS_MEMORY_MB','320')),
            maxmemory_mb=int(os.getenv('WEBCOMPILER_SHARED_REDIS_MAXMEMORY_MB','256')),
            cpu_millis=int(os.getenv('WEBCOMPILER_SHARED_REDIS_CPU_MILLIS','500'))))
        print('Shared Redis is ready')
        return 0
    except (KeyError, ValueError, SharedRedisError, OSError, subprocess.SubprocessError):
        print('Shared Redis configuration/readiness check failed; existing data was not reset',file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
