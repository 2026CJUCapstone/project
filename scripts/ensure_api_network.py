#!/usr/bin/env python3
"""Provision only an owned, per-color internal API discovery bridge.

The Docker-enabled deploy process derives allowed CIDRs here. The controller
never gets a Docker socket or permission to discover arbitrary host networks.
No adoption, network reconnect, deletion, or subnet guessing on failure.
"""
from dataclasses import dataclass
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import sys


class NetworkError(RuntimeError):
    pass


@dataclass(frozen=True)
class Config:
    root: str
    project: str

    def __post_init__(self):
        root = Path(self.root)
        if not root.is_absolute() or len(root.parts) < 3 or root.resolve() == Path.home():
            raise ValueError('An explicit deployment directory is required')
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,79}', self.project):
            raise ValueError('Explicit color project required')

    @property
    def name(self):
        return self.project + '-api-plane'

    @property
    def labels(self):
        return {'io.webcompiler.network.role': 'api-plane', 'io.webcompiler.pool': self.project,
                'io.webcompiler.owner': hashlib.sha256(str(Path(self.root).resolve()).encode()).hexdigest()}


def docker(args):
    result = subprocess.run(['docker', *args], capture_output=True, text=True, timeout=20)
    if result.returncode:
        raise NetworkError('API network Docker operation failed')
    return result.stdout


def ensure(config, *, call=docker):
    names = call(['network', 'ls', '--filter', 'name=^'+re.escape(config.name)+'$',
                  '--format', '{{.Name}}']).splitlines()
    if config.name not in names:
        args = ['network', 'create', '--driver', 'bridge', '--internal']
        for key, value in config.labels.items():
            args += ['--label', key+'='+value]
        call(args + [config.name])
    network = json.loads(call(['network', 'inspect', config.name]))[0]
    if (network.get('Name') != config.name or network.get('Driver') != 'bridge'
            or network.get('Scope') != 'local' or network.get('Internal') is not True
            or network.get('EnableIPv6') or network.get('Ingress') or network.get('Options')
            or network.get('IPAM', {}).get('Driver') != 'default'
            or network.get('IPAM', {}).get('Options')
            or any((network.get('Labels') or {}).get(k) != v for k, v in config.labels.items())):
        raise NetworkError('Refusing foreign or non-private API network')
    subnets = network.get('IPAM', {}).get('Config') or []
    if not 1 <= len(subnets) <= 4:
        raise NetworkError('Bounded explicit API subnets required')
    allowed = tuple(ipaddress.ip_network(n) for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))
    cidrs = []
    for item in subnets:
        subnet = ipaddress.ip_network(item.get('Subnet', ''), strict=True)
        if (subnet.version != 4 or subnet.prefixlen < 16
                or not any(subnet.subnet_of(private) for private in allowed)):
            raise NetworkError('API subnet is not a bounded RFC1918 network')
        cidrs.append(str(subnet))
    # Reuse must not silently bless a network populated by another role/color.
    for container_id in (network.get('Containers') or {}):
        container = json.loads(call(['container', 'inspect', container_id]))[0]
        labels = container.get('Config', {}).get('Labels') or {}
        if (labels.get('com.docker.compose.project') != config.project
                or labels.get('com.docker.compose.service') not in ('backend', 'api-proxy')):
            raise NetworkError('API network contains an unexpected service')
    return ','.join(sorted(set(cidrs)))


def main():
    try:
        config = Config(root=os.environ['PROJECT_ROOT'], project=os.environ['COMPOSE_PROJECT_NAME'])
        print(ensure(config))
    except (KeyError, ValueError, NetworkError, OSError, subprocess.SubprocessError):
        print('API network validation failed; existing resources were not changed', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
