"""Real isolated PG + three Docker namespaces + private evidence CLI.

The inventory adapter here intentionally covers only the three test processes,
not the eight-role production topology (covered separately by inventory tests).
No stop authorization, sandbox retirement or cold rollout claim is made.
"""
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest

from tests.test_edge_deploy import edge
from runtime_binding import Binding


pytestmark = pytest.mark.skipif(os.getenv('RUN_SANDBOX_INTEGRATION') != '1',
    reason='Explicit isolated Docker and PostgreSQL binding test required')


PROCESS = '''
import os, socket, time
from pathlib import Path
from uuid import uuid4
from app.core.database import SessionLocal
from app.services.runtime_identity import RuntimeIdentity
from app.services.runtime_registry import RuntimeRegistry
from app.services.worker_process import ProcessIdentity, configured_scope, process_start_token
from app.services.api_lifecycle import RuntimeRequests
from app.services.worker_lifecycle import WorkerLifecycle
from app.services.durable_queue import DurableQueue, WorkerIdentity
owner = RuntimeIdentity.configured()
assert RuntimeRegistry(SessionLocal).register(owner)
process = ProcessIdentity(uuid4().hex, os.getpid(), process_start_token(os.getpid()),
    socket.gethostname(), configured_scope())
role = os.environ['AUDIT_PROCESS_ROLE']
service = (RuntimeRequests if role == 'api' else WorkerLifecycle)(SessionLocal, owner, process)
assert service.register()
if role == 'api':
    assert service.begin('websocket')
else:
    queue = DurableQueue(SessionLocal)
    job = queue.enqueue(owner_key='audit-only', request_id=uuid4().hex,
        kind='run', payload={'code':'fixture-source-not-in-evidence'})
    claim = queue.claim(worker=WorkerIdentity(uuid4().hex, owner.pool_id,
        owner.deployment_sha, owner.sandbox_pool_id, owner.id, process.epoch))
    assert claim.id == job
Path('/tmp/audit-ready').touch()
time.sleep(300)
'''

INITIALIZE = '''
import json, sys, traceback
try:
    from app.initialize import initialize
    initialize()
except Exception as error:
    original = getattr(error, 'orig', None)
    print(json.dumps({'type':type(error).__name__, 'original':type(original).__name__,
        'sqlstate':getattr(original, 'pgcode', None),
        'frames':[frame.name for frame in traceback.extract_tb(error.__traceback__)]}), flush=True)
    sys.exit(1)
'''


def test_all_db_epochs_bind_to_real_container_namespaces_and_drift_refuses(tmp_path):
    import docker
    audit = Path(os.environ['AUDIT_ROOT']).resolve()
    assert audit.name.startswith('webcompiler-audit-')
    nonce = uuid4().hex
    labels = {'webcompiler.audit.binding': nonce}
    client = docker.from_env(timeout=10)
    own = []
    network = None
    image = client.images.get(os.getenv('AUDIT_TEST_IMAGE', 'webcompiler-audit-tests:t82h')).id
    pg_image = client.images.get('postgres:16-alpine@sha256:cf78e76683b9ca8c5733cbbdce6c9262b45b6767934dd0a95e671f9a0fc20685').id
    runtime = {'id': uuid4().hex, 'pool_id': 'audit-binding-'+nonce,
        'deployment_sha': 'a'*40, 'sandbox_pool_id': 'audit-binding-'+nonce}
    env = {'ENVIRONMENT': 'development', 'REDIS_URL': '',
        'SECRET_KEY': 'audit-only-binding-secret-01234567890123456789',
        'ADMIN_PASSWORD': 'audit-only-binding-password', 'PYTHONDONTWRITEBYTECODE': '1',
        'DATABASE_URL': 'postgresql://audit_binding:audit_binding_only@audit-pg:5432/audit_binding',
        'RUNTIME_INSTANCE_ID': runtime['id'], 'RUNTIME_POOL_ID': runtime['pool_id'],
        'DEPLOYMENT_SHA': runtime['deployment_sha'], 'SANDBOX_POOL_ID': runtime['sandbox_pool_id'],
        'REDIS_KEY_PREFIX': 'audit-binding-'+nonce, 'WORKER_STATE_DIRECTORY': ''}
    def app(command, extra=None, *, diagnostic=False):
        child = client.containers.create(image=image, entrypoint=['python'], command=command,
            working_dir='/app', environment={**env, **(extra or {})}, network=network.name,
            volumes={str(audit/'backend'):{'bind':'/app','mode':'ro'}},
            user='10001:10001', read_only=True, cap_drop=['ALL'],
            security_opt=['no-new-privileges'], tmpfs={'/tmp':'size=16m,mode=1777,noexec,nosuid'},
            # A held app process plus a separate DB/kernel CLI coexist here.
            mem_limit='192m', memswap_limit='192m', nano_cpus=125000000, pids_limit=24,
            labels=labels, log_config=docker.types.LogConfig(type='json-file',
                config={'max-size':'32k','max-file':'1'}) if diagnostic else docker.types.LogConfig(type='none'))
        own.append(child)
        child.start()
        return child
    def execute(child, args):
        assert child in own and child.labels.get('webcompiler.audit.binding') == nonce
        result = child.exec_run(args)
        assert result.exit_code == 0, 'Owned diagnostic CLI failed (output withheld)'
        assert len(result.output) <= 262144
        return result.output.decode()
    try:
        network = client.networks.create('audit-binding-'+nonce, internal=True, labels=labels)
        pg = client.containers.create(image=pg_image, environment={
            'POSTGRES_USER':'audit_binding', 'POSTGRES_PASSWORD':'audit_binding_only',
            'POSTGRES_DB':'audit_binding'}, network=network.name,
            networking_config={network.name:client.api.create_endpoint_config(aliases=['audit-pg'])},
            mem_limit='128m', memswap_limit='128m', nano_cpus=125000000, pids_limit=64,
            labels=labels, log_config=docker.types.LogConfig(type='none'))
        own.append(pg)
        pg.start()
        pg.reload()
        assert 'audit-pg' in pg.attrs['NetworkSettings']['Networks'][network.name]['Aliases']
        deadline = time.monotonic()+30
        # The image's temporary bootstrap server accepts Unix sockets before
        # the final TCP listener exists. Other containers need TCP readiness.
        while pg.exec_run(['pg_isready','-h','127.0.0.1','-U','audit_binding','-d','audit_binding']).exit_code:
            assert time.monotonic() < deadline, 'Owned PostgreSQL startup timed out'
            time.sleep(.2)
        initializer = app(['-c',INITIALIZE], diagnostic=True)
        status = initializer.wait(timeout=30)['StatusCode']
        assert status == 0, initializer.logs(tail=1).decode()[:4096]
        processes = [(app(['-c', PROCESS], {'AUDIT_PROCESS_ROLE': role}), role)
                     for role in ('api', 'api', 'worker')]
        for child, _ in processes:
            deadline = time.monotonic()+30
            while child.exec_run(['test','-f','/tmp/audit-ready']).exit_code:
                child.reload()
                assert child.status == 'running', 'Owned process exited during registration'
                assert time.monotonic() < deadline, 'Owned process registration timed out'
                time.sleep(.2)
        execute(processes[0][0], ['python','-c',
            'from app.core.database import SessionLocal; '
            'from app.services.runtime_identity import RuntimeIdentity; '
            'from app.services.runtime_registry import RuntimeRegistry; '
            'RuntimeRegistry(SessionLocal).begin_drain(RuntimeIdentity.configured())'])
        def inventory_rows():
            rows = []
            for child, role in processes:
                child.reload()
                assert child.labels.get('webcompiler.audit.binding') == nonce
                rows.append({'id': child.id, 'role': 'backend' if role == 'api' else role,
                    'hostname': child.attrs['Config']['Hostname'], 'state': child.attrs['State'],
                    'restart': child.attrs['RestartCount']})
            return rows
        frozen = inventory_rows()
        store = edge.Store(tmp_path/'binding', edge.Layout(18000,15173))
        store.initialize()
        path = store.path/'state'/'fixture-inventory.json'
        store.write(path, {'containers':frozen})
        def verify():
            if inventory_rows() != frozen:
                raise edge.EdgeError('Actual fixture container incarnation changed')
            return True
        inventory = SimpleNamespace(release=SimpleNamespace(runtime_id=runtime['id'],sha=runtime['deployment_sha']),
            project=runtime['pool_id'], sandbox_pool=runtime['sandbox_pool_id'],
            store=store, path=path, verify=verify)
        def read(identity, requested, role):
            assert requested == runtime
            child = next(c for c, _ in processes if c.id == identity)
            args = ['python','-m','app.runtime_inspect','--runtime',runtime['id'],
                '--pool',runtime['pool_id'],'--release',runtime['deployment_sha'],
                '--sandbox-pool',runtime['sandbox_pool_id']]
            return execute(child, args+(['--local-role',role] if role else []))
        subject = Binding(inventory, read=read)
        result = subject.observe()
        assert len(result['bindings']) == 3
        assert {p['container_id'] for p in result['bindings'].values()} == {c.id for c, _ in processes}
        assert all(p['state'] == 'alive' for p in result['bindings'].values())
        assert result['snapshot']['active_websockets'] == 2 and result['snapshot']['active_claims'] == 1
        assert 'fixture-source' not in json.dumps(result)
        # Same-role reports from a different namespace must not bind by role alone.
        def swapped(identity, requested, role):
            if role == 'api':
                identity = processes[1][0].id if identity == processes[0][0].id else processes[0][0].id
            return read(identity, requested, role)
        with pytest.raises(edge.EdgeError, match='identity mismatch'):
            Binding(inventory, read=swapped).observe()
        assert subject.observe()['snapshot'] == result['snapshot']
        # Only this owned fixture process is stopped; no DB record is reconciled.
        processes[0][0].stop(timeout=1)
        with pytest.raises(edge.EdgeError, match='incarnation changed'): subject.observe()
        raw = read(processes[1][0].id, runtime, None)
        assert json.loads(raw) == result['snapshot']
    finally:
        for child in reversed(own):
            child.reload()
            assert child.labels.get('webcompiler.audit.binding') == nonce
            child.remove(force=True, v=True)
        if network is not None:
            network.reload()
            assert network.attrs['Labels'].get('webcompiler.audit.binding') == nonce
            network.remove()
        client.close()
