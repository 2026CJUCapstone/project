"""Ownership, immutable-target and secret-handling contracts; actual lifecycle is separate."""
from copy import deepcopy
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('audit_owned_postgres', ROOT/'scripts/ensure_shared_postgres.py')
shared = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = shared
spec.loader.exec_module(shared)
IMAGE = 'sha256:' + '1' * 64
CID = '2' * 64


def records(c):
    return {
        'network': {'Name': c.network, 'Id': '3'*64, 'Driver': 'bridge', 'Scope': 'local',
                    'Internal': True, 'Labels': c.network_labels},
        'volume': {'Name': c.volume, 'Driver': 'local', 'Options': {}, 'Labels': c.labels},
        'container': {
            'Id': CID, 'Name': '/' + c.name, 'Image': IMAGE,
            'Config': {'Image': IMAGE, 'Entrypoint': ['docker-entrypoint.sh'], 'Cmd': c.command,
                       'Labels': c.labels, 'Env': [k+'='+v for k, v in c.environment.items()]
                       + ['PGDATA=/var/lib/postgresql/data', 'PG_MAJOR=16']},
            'HostConfig': {'Memory': c.memory_mb*1024*1024, 'MemorySwap': c.memory_mb*1024*1024,
                'NanoCpus': c.cpu_millis*1_000_000, 'PidsLimit': 256, 'ShmSize': 64*1024*1024,
                'ReadonlyRootfs': True, 'IpcMode': 'private', 'NetworkMode': '3'*64,
                'RestartPolicy': {'Name': 'unless-stopped', 'MaximumRetryCount': 0},
                'SecurityOpt': ['no-new-privileges:true'],
                'LogConfig': {'Type': 'json-file', 'Config': {'max-size': '10m', 'max-file': '3'}},
                'Tmpfs': {'/tmp': 'rw,noexec,nosuid,size=16m', '/var/run/postgresql': 'rw,noexec,nosuid,size=16m'}},
            'Mounts': [{'Type': 'volume', 'Name': c.volume, 'Destination': '/var/lib/postgresql/data', 'RW': True}],
            'NetworkSettings': {'Networks': {c.network: {'NetworkID': '3'*64}}},
            'State': {'Running': False, 'Status': 'created'}}
    }


class Docker:
    def __init__(self, c, existing=False):
        self.c, self.templates = c, records(c)
        self.state = deepcopy(self.templates) if existing else {}
        self.calls = []
        self.auth_ok = True

    def __call__(self, args, *, env=None):
        self.calls.append((args, env))
        if args[:2] == ['image', 'inspect']:
            return json.dumps([{'Id': IMAGE, 'Config': {'Env': ['PGDATA=/var/lib/postgresql/data', 'PG_MAJOR=16']}}])
        if len(args) > 1 and args[1] == 'ls':
            return {'network': self.c.network, 'volume': self.c.volume, 'container': self.c.name}[args[0]] if args[0] in self.state else ''
        if len(args) > 1 and args[1] == 'inspect':
            return json.dumps([self.state[args[0]]])
        if args[0] in ('network', 'volume') and args[1] == 'create':
            self.state[args[0]] = deepcopy(self.templates[args[0]])
            return '3'*64 if args[0] == 'network' else args[-1]
        if args[0] == 'create':
            self.state['container'] = deepcopy(self.templates['container'])
            return CID
        if args[0] == 'start':
            assert args == ['start', CID]
            self.state['container']['State']['Running'] = True
            return CID
        if args[0] == 'exec':
            assert CID in args and self.c.password not in args
            assert env == {'PGPASSWORD': self.c.password}
            if not self.auth_ok:
                raise shared.SharedPostgresError('opaque fixture auth failure')
            return '1\n'
        raise AssertionError(args)

    @property
    def mutations(self):
        return [args for args, _ in self.calls if args[0] in ('start', 'create') or args[1:2] == ['create']]


@pytest.fixture
def config(tmp_path):
    return shared.Config(root=str(tmp_path/'deployment'), password='test-only-postgres-credential-12345')


def test_create_is_bounded_pinned_private_and_secret_not_in_argv(config):
    call = Docker(config)
    assert shared.ensure(config, call=call) == CID
    create, env = next((args, env) for args, env in call.calls if args[0] == 'create')
    assert create[-len(config.command)-1:] == [IMAGE, *config.command]
    assert '--pull' in create and 'never' in create
    assert create[create.index('--network')+1] == '3'*64
    assert env == config.environment
    assert all(config.password not in ' '.join(args) for args, _ in call.calls)
    assert config.password not in repr(config)
    assert call.mutations[-1] == ['start', CID]
    call.calls.clear()
    assert shared.ensure(config, call=call) == CID
    assert call.mutations == []


@pytest.mark.parametrize('kind,path,value', [
    ('network', ('Labels',), {}), ('network', ('Internal',), False),
    ('volume', ('Labels',), {}), ('volume', ('Options',), {'device': '/host'}),
    ('container', ('Config', 'Labels'), {}), ('container', ('Image',), 'sha256:'+'9'*64),
    ('container', ('Config', 'Image'), 'postgres:16-alpine'),
    ('container', ('Config', 'Entrypoint'), ['sh']),
    ('container', ('Config', 'Env'), ['POSTGRES_PASSWORD=wrong']),
    ('container', ('HostConfig', 'PortBindings'), {'5432/tcp': [{'HostPort': '5432'}]}),
    ('container', ('HostConfig', 'Privileged'), True),
    ('container', ('HostConfig', 'ReadonlyRootfs'), False),
    ('container', ('HostConfig', 'MemorySwap'), -1),
    ('container', ('HostConfig', 'CapAdd'), ['SYS_ADMIN']),
    ('container', ('HostConfig', 'DeviceRequests'), [{'Driver': 'nvidia', 'Count': -1, 'Capabilities': [['gpu']]}]),
    ('container', ('HostConfig', 'DeviceCgroupRules'), ['c 1:3 rwm']),
    ('container', ('HostConfig', 'Tmpfs'), {}),
    ('container', ('HostConfig', 'PidMode'), 'host'),
    ('container', ('Mounts',), [{'Type': 'bind', 'Source': '/host', 'Destination': '/var/lib/postgresql/data', 'RW': True}]),
    ('container', ('State', 'Restarting'), True),
    ('container', ('NetworkSettings', 'Networks'), {'public': {}}),
])
def test_foreign_or_different_existing_targets_refused_before_any_mutation(config, kind, path, value):
    call = Docker(config, existing=True)
    target = call.state[kind]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    before = deepcopy(call.state)
    with pytest.raises(shared.SharedPostgresError):
        shared.ensure(config, call=call)
    assert call.mutations == [] and call.state == before


def test_foreign_container_rejected_before_missing_network_or_volume_created(config):
    call = Docker(config, existing=True)
    del call.state['network']
    del call.state['volume']
    call.state['container']['Config']['Labels'] = {}
    with pytest.raises(shared.SharedPostgresError):
        shared.ensure(config, call=call)
    assert call.mutations == []


def test_name_replacement_never_starts_different_id(config):
    fake = Docker(config, existing=True)
    reads = 0
    def call(args, **kwargs):
        nonlocal reads
        if args[:2] == ['container', 'inspect']:
            reads += 1
            if reads == 2:
                fake.state['container']['Id'] = '8'*64
        return fake(args, **kwargs)
    with pytest.raises(shared.SharedPostgresError, match='replaced'):
        shared.ensure(config, call=call)
    assert fake.mutations == []


@pytest.mark.parametrize('kind', ['network', 'container'])
def test_new_resource_id_is_pinned_before_first_inspection(config, kind):
    fake = Docker(config)
    def call(args, **kwargs):
        value = fake(args, **kwargs)
        if (kind == 'container' and args[0] == 'create'
                or kind == 'network' and args[:2] == ['network', 'create']):
            fake.state[kind]['Id'] = '8'*64
        return value
    with pytest.raises(shared.SharedPostgresError, match='replaced before inspection'):
        shared.ensure(config, call=call)
    assert not any(args[0] in ('start', 'exec') for args, _ in fake.calls)


def test_table_count_and_provisioning_are_one_deployment_identity_check():
    source = (ROOT/'scripts/deploy_server.sh').read_text()
    assert source.count('scripts/ensure_shared_postgres.py') == 1
    assert 'SHARED_DATABASE_HAS_APP_TABLES="$(python3' in source
    assert '--has-app-tables)' in source


def test_auth_failure_never_recreates_or_resets_existing_database(config):
    call = Docker(config, existing=True)
    call.state['container']['State']['Running'] = True
    call.auth_ok = False
    ticks = iter((0, 1, 61))
    with pytest.raises(shared.SharedPostgresError, match='Authenticated'):
        shared.ensure(config, call=call, clock=lambda: next(ticks), sleep=lambda _: None)
    assert call.mutations == []


@pytest.mark.parametrize('options', [
    {'password': ''}, {'password': 'compiler'}, {'password': 'x'*24+'@'},
    {'password': 'x'*24+'$'}, {'password': 'x'*129}, {'name': '-bad'},
    {'database': 'db;drop'}, {'user': 'user@host'}, {'memory_mb': 255},
    {'cpu_millis': 49}, {'root': '/'}, {'root': 'relative'}, {'image': '-bad'},
])
def test_invalid_config_is_rejected(config, options):
    with pytest.raises(ValueError):
        replace(config, **options)


def test_main_refuses_endpoint_override_before_docker(monkeypatch, config, capsys):
    monkeypatch.setattr(sys, 'argv', ['ensure_shared_postgres.py'])
    monkeypatch.setenv('WEBCOMPILER_POSTGRES_HOST', 'unrelated-db')
    monkeypatch.setattr(shared, 'ensure', lambda *args, **kwargs: pytest.fail('must not call Docker'))
    assert shared.main() == 1
    assert 'ownership/configuration/readiness failed' in capsys.readouterr().err


@pytest.mark.parametrize('extra', ['PGOPTIONS=-c fsync=off', 'POSTGRES_INITDB_WALDIR=/tmp/wal',
                                  'POSTGRES_PASSWORD=test-only-postgres-credential-12345'])
def test_unexpected_or_duplicate_environment_refused_before_start(config, extra):
    call = Docker(config, existing=True)
    call.state['container']['Config']['Env'].append(extra)
    with pytest.raises(shared.SharedPostgresError):
        shared.ensure(config, call=call)
    assert call.mutations == []


def test_same_network_name_with_different_id_is_refused(config):
    call = Docker(config, existing=True)
    call.state['container']['NetworkSettings']['Networks'][config.network]['NetworkID'] = '7'*64
    with pytest.raises(shared.SharedPostgresError):
        shared.ensure(config, call=call)
    assert call.mutations == []


def test_created_endpoint_may_be_unassigned_only_with_immutable_network_mode(config):
    call = Docker(config, existing=True)
    call.state['container']['NetworkSettings']['Networks'] = {'3'*64: {'NetworkID': '', 'EndpointID': '', 'IPAddress': ''}}
    def observed(args, **kwargs):
        value = call(args, **kwargs)
        if args[0] == 'start':
            call.state['container']['NetworkSettings']['Networks'] = deepcopy(call.templates['container']['NetworkSettings']['Networks'])
            call.state['container']['State']['Status'] = 'running'
        return value
    assert shared.ensure(config, call=observed) == CID
    assert call.mutations == [['start', CID]]


@pytest.mark.parametrize('running,mode', [(True, '3'*64), (False, 'webcompiler-shared')])
def test_missing_endpoint_never_proves_running_or_name_bound_service(config, running, mode):
    call = Docker(config, existing=True)
    call.state['container']['NetworkSettings']['Networks'] = {config.network: {'NetworkID': ''}}
    call.state['container']['State']['Running'] = running
    call.state['container']['HostConfig']['NetworkMode'] = mode
    with pytest.raises(shared.SharedPostgresError):
        shared.ensure(config, call=call)
    assert call.mutations == []


def test_app_table_check_uses_same_pinned_id_and_authenticated_tcp(config):
    call = Docker(config, existing=True)
    assert shared.ensure(config, call=call, check_tables=True) == 1
    command, env = next((args, env) for args, env in call.calls if args[0] == 'exec')
    assert CID in command and config.name not in command
    assert command[-1] == shared.APP_TABLE_COUNT_SQL
    assert command[command.index('-h')+1] == '127.0.0.1'
    assert env == {'PGPASSWORD': config.password}


def test_deploy_wires_owned_helper_and_removes_name_only_adoption():
    source = (ROOT/'scripts/deploy_server.sh').read_text()
    assert 'python3 "$SOURCE_ROOT/scripts/ensure_shared_postgres.py"' in source
    assert 'WEBCOMPILER_POSTGRES_PASSWORD:-compiler' not in source
    for old in ('docker network connect', 'docker start "$SHARED_POSTGRES_NAME"', 'pg_isready'):
        assert old not in source
