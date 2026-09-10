#!/usr/bin/env python3
"""Read-only gate for an explicitly selected, bounded local BuildKit builder.

Provisioning a builder is separate. Never bootstrap, select a default builder,
change its limits, or accept a remote daemon as a local resource-budget proof.
"""
from dataclasses import dataclass
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys


class BuilderError(RuntimeError):
    pass


@dataclass(frozen=True)
class Config:
    name: str
    memory_mb: int = 2048
    cpu_millis: int = 1000
    pids: int = 512
    container_id: str = ''

    def __post_init__(self):
        if not isinstance(self.name,str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,79}', self.name) or self.name == 'default':
            raise BuilderError('An explicit named build container is required')
        for value, low, high in ((self.memory_mb,256,32768),(self.cpu_millis,50,8000),(self.pids,64,4096)):
            if type(value) is not int or not low <= value <= high:
                raise BuilderError('Invalid build resource budget')
        if not isinstance(self.container_id,str) or (self.container_id and not re.fullmatch(r'[0-9a-f]{64}',self.container_id)):
            raise BuilderError('Invalid bound build container identity')

    @classmethod
    def from_environment(cls, env=None):
        env=os.environ if env is None else env
        try:
            return cls(env.get('WEBCOMPILER_BUILD_BUILDER',''),
                int(env.get('WEBCOMPILER_BUILD_MEMORY_MB','2048')),
                int(env.get('WEBCOMPILER_BUILD_CPU_MILLIS','1000')),
                int(env.get('WEBCOMPILER_BUILD_PIDS','512')),
                env.get('WEBCOMPILER_BUILD_CONTAINER_ID',''))
        except (TypeError,ValueError):
            raise BuilderError('Invalid build resource configuration') from None


def docker(arguments):
    result=subprocess.run(['docker',*arguments],capture_output=True,text=True,timeout=30)
    if result.returncode or len(result.stdout)>1024*1024:
        raise BuilderError('Unable to verify the configured build container')
    return result.stdout


def read_host_text(path):
    return Path(path).read_text()


def container_cgroup(text,identity):
    rows=[line.split(':',2)[2] for line in text.splitlines() if line.startswith('0::')]
    if len(rows)!=1 or not rows[0].startswith('/') or '..' in rows[0].split('/'):
        raise BuilderError('A host cgroup-v2 container identity is required')
    parts=PurePosixPath(rows[0]).parts
    indexes=[index for index,part in enumerate(parts)
             if part=='docker-'+identity+'.scope' or
             (part==identity and index>0 and parts[index-1]=='docker')]
    if len(indexes)!=1:
        raise BuilderError('Build process is outside its expected Docker cgroup')
    return str(PurePosixPath(*parts[:indexes[0]+1]))


def verify(config, call=docker):
    try:
        rows=[json.loads(line) for line in call(['buildx','ls','--format','{{json .}}']).splitlines() if line.strip()]
        selected=[row for row in rows if row.get('Name')==config.name]
        # Buildx 0.31 can render an identical builder row twice. Collapse only
        # byte-equivalent structured observations; conflicting rows still fail.
        selected=list({json.dumps(row,sort_keys=True):row for row in selected}.values())
        if len(selected)!=1 or selected[0].get('Driver')!='docker-container' or selected[0].get('Dynamic'):
            raise BuilderError('A single static docker-container builder is required')
        nodes=selected[0].get('Nodes',[])
        if len(nodes)!=1 or nodes[0].get('Status')!='running':
            raise BuilderError('The configured builder must already be running with one node')
        node=nodes[0]
        if node.get('Endpoint')!='unix:///var/run/docker.sock':
            raise BuilderError('The builder must use the explicit local Docker socket')
        name=node.get('Name','')
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,95}',name):
            raise BuilderError('Invalid builder node identity')
        container_name='buildx_buildkit_'+name
        def inspect(identity):
            data=json.loads(call(['--host','unix:///var/run/docker.sock','container','inspect',identity]))
            if not isinstance(data,list) or len(data)!=1:
                raise BuilderError('Build container inspection is ambiguous')
            return data[0]
        container=inspect(config.container_id or container_name)
        identity=container.get('Id','')
        if not re.fullmatch(r'[0-9a-f]{64}',identity) or (config.container_id and config.container_id!=identity):
            raise BuilderError('Build container identity changed')
        if container.get('Name')!='/'+container_name:
            raise BuilderError('Builder metadata and container identity disagree')
        state=container.get('State',{})
        if not state.get('Running') or state.get('Paused') or state.get('Restarting'):
            raise BuilderError('Build container is not stably running')
        host=container.get('HostConfig',{})
        memory=host.get('Memory',0)
        period=host.get('CpuPeriod',0)
        quota=host.get('CpuQuota',0)
        pids=host.get('PidsLimit',0)
        if not (type(memory) is int and 0<memory<=config.memory_mb*1024*1024 and host.get('MemorySwap')==memory):
            raise BuilderError('Builder memory must be capped without additional swap')
        if not (type(period) is int and type(quota) is int and 0<period<=1000000 and
                0<quota and quota*1000<=period*config.cpu_millis and host.get('NanoCpus',0)==0):
            raise BuilderError('Builder CPU quota exceeds the configured budget')
        if not (type(pids) is int and 0<pids<=config.pids):
            raise BuilderError('Builder process count must have a finite cap')
        if host.get('PidMode')=='host' or host.get('NetworkMode')=='host':
            raise BuilderError('Builder host PID/network namespaces are not supported')
        pid=state.get('Pid')
        if type(pid) is not int or pid<=1:
            raise BuilderError('Build container has no stable host process')
        parent=container_cgroup(read_host_text('/proc/'+str(pid)+'/cgroup'),identity)
        root='/sys/fs/cgroup'+parent
        expected={'memory.max':str(memory),'memory.swap.max':'0',
                  'cpu.max':str(quota)+' '+str(period),'pids.max':str(pids)}
        for filename,value in expected.items():
            if read_host_text(root+'/'+filename).strip()!=value:
                raise BuilderError('Host cgroup limits disagree with the configured build container')
        # Bind the name lookup to the inspected full ID too. A renamed/replaced
        # builder must not be silently adopted between build phases.
        final=inspect(container_name)
        if (final.get('Id')!=identity or final.get('HostConfig')!=host
                or final.get('State')!=state):
            raise BuilderError('Builder container name changed during verification')
        return identity
    except (KeyError,TypeError,ValueError,AttributeError):
        raise BuilderError('Invalid build container verification response') from None


def main():
    try:
        print(verify(Config.from_environment()))
    except (BuilderError,OSError,subprocess.SubprocessError) as error:
        # No daemon output, builder environment, source or credentials in errors.
        print('Build resource verification failed: '+str(error) if isinstance(error,BuilderError)
              else 'Build resource verification failed',file=sys.stderr)
        return 1
    return 0


if __name__=='__main__':
    raise SystemExit(main())
