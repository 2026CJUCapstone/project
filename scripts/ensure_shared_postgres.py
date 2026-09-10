#!/usr/bin/env python3
"""Provision an owned, color-independent PostgreSQL without adopting or resetting data.

Existing unlabelled deployments require an explicitly approved offline migration.
The caller must serialize deployment operations and supply the real credential.
"""
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


class SharedPostgresError(RuntimeError):
    pass


@dataclass(frozen=True)
class Config:
    root: str
    password: str = field(repr=False)
    name: str = 'webcompiler-postgres'
    volume: str = 'webcompiler-postgres-data'
    network: str = 'webcompiler-shared'
    image: str = 'postgres:16-alpine@sha256:cf78e76683b9ca8c5733cbbdce6c9262b45b6767934dd0a95e671f9a0fc20685'
    user: str = 'compiler'
    database: str = 'compiler'
    memory_mb: int = 512
    cpu_millis: int = 500

    def __post_init__(self):
        root = Path(self.root)
        if not root.is_absolute() or len(root.resolve().parts) < 3 or root.resolve() == Path.home():
            raise ValueError('An explicit deployment directory is required')
        for value in (self.name, self.volume, self.network):
            if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,79}', value):
                raise ValueError('Invalid Docker resource name')
        for value in (self.user, self.database):
            if not re.fullmatch(r'[a-z][a-z0-9_]{0,62}', value):
                raise ValueError('Explicit simple PostgreSQL identifiers required')
        # URLs in the managed Compose configuration interpolate this verbatim.
        if not re.fullmatch(r'[A-Za-z0-9_-]{24,128}', self.password):
            raise ValueError('An explicit URL-safe PostgreSQL credential is required')
        if not self.image or self.image.startswith('-') or any(c.isspace() for c in self.image):
            raise ValueError('Invalid preinstalled PostgreSQL image')
        if not 256 <= self.memory_mb <= 8192 or not 50 <= self.cpu_millis <= 4000:
            raise ValueError('Invalid PostgreSQL resource budget')

    @property
    def owner(self):
        return hashlib.sha256(str(Path(self.root).resolve()).encode()).hexdigest()

    @property
    def labels(self):
        return {'io.webcompiler.owner': self.owner, 'io.webcompiler.shared.role': 'postgres'}

    @property
    def network_labels(self):
        return {'io.webcompiler.owner': self.owner, 'io.webcompiler.network.role': 'shared-state'}

    @property
    def command(self):
        return ['postgres', '-c', 'max_connections=100', '-c', 'shared_buffers=64MB']

    @property
    def environment(self):
        return {'POSTGRES_USER': self.user, 'POSTGRES_DB': self.database,
                'POSTGRES_PASSWORD': self.password, 'POSTGRES_INITDB_ARGS': '--auth-host=scram-sha-256'}


def docker(args, *, env=None):
    # Password values travel in the process environment, never command arguments.
    result = subprocess.run(['docker', *args], env={**os.environ, **(env or {})},
                            capture_output=True, text=True, timeout=20)
    if result.returncode:
        raise SharedPostgresError('Shared PostgreSQL Docker operation failed')
    return result.stdout


def record(call, args):
    value = json.loads(call(args))
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise SharedPostgresError('Invalid Docker resource evidence')
    return value[0]


def labels_match(actual, expected):
    return all((actual or {}).get(k) == v for k, v in expected.items())


def validate_network(value, config):
    if (value.get('Name') != config.network or value.get('Driver') != 'bridge'
            or value.get('Scope') != 'local' or value.get('Internal') is not True
            or value.get('EnableIPv6') or value.get('Ingress') or value.get('Options')
            or not labels_match(value.get('Labels'), config.network_labels)):
        raise SharedPostgresError('Refusing foreign or non-private shared network')


def validate_volume(value, config):
    if (value.get('Name') != config.volume or value.get('Driver') != 'local'
            or value.get('Options') or not labels_match(value.get('Labels'), config.labels)):
        raise SharedPostgresError('Refusing foreign PostgreSQL data volume')


def validate_container(value, config, image_id, environment, network_id):
    actual, host = value.get('Config') or {}, value.get('HostConfig') or {}
    env_items = actual.get('Env') or []
    env = dict(item.split('=', 1) for item in env_items if '=' in item)
    if len(env_items) != len(env) or env != environment:
        raise SharedPostgresError('PostgreSQL environment differs from the approved image and configuration')
    networks = (value.get('NetworkSettings') or {}).get('Networks') or {}
    endpoint = networks.get(config.network) or networks.get(network_id) or {}
    state = value.get('State') or {}
    # Docker allocates the endpoint at start, not at create. Pinning NetworkMode
    # to the immutable ID prevents a replacement of the same name from winning.
    inactive_endpoint = (state.get('Running') is False and state.get('Status') in ('created', 'exited')
        and not endpoint.get('NetworkID') and not endpoint.get('EndpointID')
        and not endpoint.get('IPAddress') and not endpoint.get('GlobalIPv6Address'))
    if (set(networks) not in ({config.network}, {network_id})
            or (endpoint.get('NetworkID') != network_id and not inactive_endpoint)):
        raise SharedPostgresError('PostgreSQL endpoint does not match the owned network identity')
    mounts = [m for m in (value.get('Mounts') or []) if m.get('Type') != 'tmpfs']
    container_id = value.get('Id', '')
    if not (re.fullmatch('[0-9a-f]{64}', container_id)
            and value.get('Name') == '/' + config.name and value.get('Image') == image_id
            and actual.get('Image') == image_id and actual.get('Cmd') == config.command
            and actual.get('Entrypoint') == ['docker-entrypoint.sh']
            and actual.get('User', '') == '' and not actual.get('Healthcheck')
            and labels_match(actual.get('Labels'), config.labels)
            and len(env_items) == len(env) and env == environment
            and not host.get('PortBindings') and not host.get('PublishAllPorts')
            and not host.get('Privileged') and host.get('ReadonlyRootfs') is True
            and not host.get('CapAdd') and not host.get('Devices')
            and not host.get('DeviceRequests') and not host.get('DeviceCgroupRules')
            and not host.get('PidMode') and not host.get('UsernsMode')
            and host.get('IpcMode') == 'private' and host.get('NetworkMode') == network_id
            and host.get('Memory') == host.get('MemorySwap') == config.memory_mb * 1024 * 1024
            and host.get('NanoCpus') == config.cpu_millis * 1_000_000
            and host.get('PidsLimit') == 256 and host.get('ShmSize') == 64 * 1024 * 1024
            and host.get('RestartPolicy') == {'Name': 'unless-stopped', 'MaximumRetryCount': 0}
            and set(host.get('SecurityOpt') or []) in ({'no-new-privileges:true'}, {'no-new-privileges'})
            and host.get('LogConfig') == {'Type': 'json-file', 'Config': {'max-size': '10m', 'max-file': '3'}}
            and host.get('Tmpfs') == {'/tmp': 'rw,noexec,nosuid,size=16m',
                                      '/var/run/postgresql': 'rw,noexec,nosuid,size=16m'}
            and len(mounts) == 1 and mounts[0].get('Type') == 'volume'
            and mounts[0].get('Name') == config.volume
            and mounts[0].get('Destination') == '/var/lib/postgresql/data' and mounts[0].get('RW') is True
            and not (value.get('State') or {}).get('Paused')
            and not (value.get('State') or {}).get('Restarting')
            and not (value.get('State') or {}).get('Dead')):
        raise SharedPostgresError('Existing PostgreSQL differs from the approved configuration')
    return container_id


APP_TABLE_COUNT_SQL = ("select count(*) from information_schema.tables where table_schema = 'public' "
                       "and table_name in ('problems', 'users', 'user_problem_scores')")


def ensure(config, *, call=docker, clock=time.monotonic, sleep=time.sleep, check_tables=False):
    image = record(call, ['image', 'inspect', config.image])
    image_id = image.get('Id', '')
    if not re.fullmatch('sha256:[0-9a-f]{64}', image_id):
        raise SharedPostgresError('Preinstalled PostgreSQL image identity required')
    image_env = dict(item.split('=', 1) for item in (image.get('Config') or {}).get('Env', []) if '=' in item)
    if image_env.get('PG_MAJOR') != '16' or image_env.get('PGDATA') != '/var/lib/postgresql/data':
        raise SharedPostgresError('Explicit PostgreSQL 16 data-layout compatibility required')
    environment = {**image_env, **config.environment}
    resources = {}
    def validate(value, c):
        network_id = (resources.get('network') or {}).get('Id')
        if not network_id or not re.fullmatch('[0-9a-f]{64}', network_id):
            raise SharedPostgresError('Owned network identity required')
        return validate_container(value, c, image_id, environment, network_id)
    # Inspect every pre-existing target before creating or starting anything.
    for kind, name, validator in (
            ('network', config.network, validate_network), ('volume', config.volume, validate_volume),
            ('container', config.name, validate)):
        args = [kind, 'ls'] + (['-a'] if kind == 'container' else [])
        names = call(args + ['--format', '{{.Names}}' if kind == 'container' else '{{.Name}}']).splitlines()
        resources[kind] = record(call, [kind, 'inspect', name]) if name in names else None
        if resources[kind] is not None:
            validator(resources[kind], config)
    if resources['container'] and (not resources['network'] or not resources['volume']):
        raise SharedPostgresError('Existing PostgreSQL has incomplete resource ownership')
    for kind, name, labels, options, validator in (
            ('network', config.network, config.network_labels, ['--driver', 'bridge', '--internal'], validate_network),
            ('volume', config.volume, config.labels, [], validate_volume)):
        created_id = None
        if resources[kind] is None:
            args = [kind, 'create', *options]
            for key, value in labels.items():
                args += ['--label', key + '=' + value]
            created_id = call(args + [name]).strip()
            if (kind == 'network' and not re.fullmatch('[0-9a-f]{64}', created_id)
                    or kind == 'volume' and created_id != name):
                raise SharedPostgresError('Created resource identity was not confirmed')
        current = record(call, [kind, 'inspect', name])
        validator(current, config)
        if kind == 'network' and created_id is not None and current.get('Id') != created_id:
            raise SharedPostgresError('New shared network was replaced before inspection')
        if kind == 'network' and resources[kind] and resources[kind]['Id'] != current.get('Id'):
            raise SharedPostgresError('Shared network was replaced during validation')
        resources[kind] = current
    created_container_id = None
    if resources['container'] is None:
        args = ['create', '--pull', 'never', '--name', config.name, '--restart', 'unless-stopped',
                '--network', resources['network']['Id'], '--memory', str(config.memory_mb) + 'm',
                '--memory-swap', str(config.memory_mb) + 'm', '--cpus', str(config.cpu_millis / 1000),
                '--pids-limit', '256', '--shm-size', '64m', '--ipc', 'private', '--read-only',
                '--tmpfs', '/tmp:rw,noexec,nosuid,size=16m',
                '--tmpfs', '/var/run/postgresql:rw,noexec,nosuid,size=16m',
                '--security-opt', 'no-new-privileges:true', '--log-driver', 'json-file',
                '--log-opt', 'max-size=10m', '--log-opt', 'max-file=3',
                '--mount', 'type=volume,source=' + config.volume + ',target=/var/lib/postgresql/data']
        for key, value in config.labels.items():
            args += ['--label', key + '=' + value]
        for key in config.environment:
            args += ['--env', key]
        # Never allocate a tag which can change between image inspection and create.
        created_container_id = call(args + [image_id, *config.command], env=config.environment).strip()
        if not re.fullmatch('[0-9a-f]{64}', created_container_id):
            raise SharedPostgresError('Created PostgreSQL identity was not confirmed')
    value = record(call, ['container', 'inspect', config.name])
    container_id = validate(value, config)
    if created_container_id is not None and created_container_id != container_id:
        raise SharedPostgresError('New PostgreSQL was replaced before inspection')
    if resources['container'] and resources['container']['Id'] != container_id:
        raise SharedPostgresError('PostgreSQL was replaced during validation')
    if not value['State']['Running']:
        call(['start', container_id])
    deadline = clock() + 60
    while clock() < deadline:
        try:
            result = call(['exec', '--env', 'PGPASSWORD', container_id, 'psql', '-X', '-w',
                           '-h', '127.0.0.1', '-U', config.user, '-d', config.database,
                           '-v', 'ON_ERROR_STOP=1', '-tAc', APP_TABLE_COUNT_SQL if check_tables else 'select 1'],
                          env={'PGPASSWORD': config.password})
            result = result.strip()
            if result in (('0', '1', '2', '3') if check_tables else ('1',)):
                final = record(call, ['container', 'inspect', config.name])
                network = record(call, ['network', 'inspect', config.network])
                validate_network(network, config)
                if (validate(final, config) != container_id or not final['State']['Running']
                        or network.get('Id') != resources['network']['Id']):
                    raise SharedPostgresError('PostgreSQL identity changed during readiness')
                return int(result) if check_tables else container_id
        except SharedPostgresError:
            pass
        sleep(1)
    raise SharedPostgresError('Authenticated PostgreSQL readiness did not pass')


def main():
    try:
        if sys.argv[1:] not in ([], ['--has-app-tables']):
            raise ValueError('Unsupported PostgreSQL helper operation')
        check_tables = sys.argv[1:] == ['--has-app-tables']
        name = os.getenv('WEBCOMPILER_SHARED_POSTGRES_NAME', 'webcompiler-postgres')
        if (os.getenv('WEBCOMPILER_POSTGRES_HOST', name) != name
                or os.getenv('WEBCOMPILER_POSTGRES_PORT', '5432') != '5432'):
            raise ValueError('Managed PostgreSQL endpoint must match its owned service')
        result = ensure(Config(root=os.environ['PROJECT_ROOT'], password=os.environ['WEBCOMPILER_POSTGRES_PASSWORD'],
            name=name,
            volume=os.getenv('WEBCOMPILER_SHARED_POSTGRES_VOLUME', 'webcompiler-postgres-data'),
            network=os.getenv('WEBCOMPILER_SHARED_POSTGRES_NETWORK', 'webcompiler-shared'),
            image=os.getenv('WEBCOMPILER_SHARED_POSTGRES_IMAGE', 'postgres:16-alpine@sha256:cf78e76683b9ca8c5733cbbdce6c9262b45b6767934dd0a95e671f9a0fc20685'),
            user=os.getenv('WEBCOMPILER_POSTGRES_USER', 'compiler'), database=os.getenv('WEBCOMPILER_POSTGRES_DB', 'compiler'),
            memory_mb=int(os.getenv('WEBCOMPILER_SHARED_POSTGRES_MEMORY_MB', '512')),
            cpu_millis=int(os.getenv('WEBCOMPILER_SHARED_POSTGRES_CPU_MILLIS', '500'))), check_tables=check_tables)
        print(('yes' if result else 'no') if check_tables else 'Owned shared PostgreSQL is ready')
        return 0
    except (KeyError, TypeError, ValueError, SharedPostgresError, OSError, subprocess.SubprocessError):
        print('Shared PostgreSQL ownership/configuration/readiness failed; no data reset or adoption performed', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
