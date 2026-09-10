"""Real PID lifetime and Docker PID-namespace separation, never production data."""
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.services.process_observation import local_process_state
from app.services.worker_process import ProcessIdentity, configured_scope, local_namespace_token, process_start_token
from app.models.database import ActiveApiRequest, ApiProcessRecord, WorkerProcessRecord, ExecutionJob
from app.services.durable_queue import DurableQueue
from app.services.api_lifecycle import RuntimeRequests
from app.services.runtime_identity import RuntimeIdentity
from app.services.runtime_registry import RuntimeRegistry
from app.services.worker_lifecycle import WorkerLifecycle
from tests.test_durable_queue import replicas
from tests.test_runtime_registry import lane


@pytest.mark.skipif(sys.platform != 'linux', reason='Kernel absence observation currently supports Linux only')
def test_real_child_is_alive_then_absent_with_same_stored_identity():
    child = subprocess.Popen([sys.executable,'-c',
        'import os,sys; print(os.getpid(),flush=True); sys.stdin.readline()'],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert int(child.stdout.readline()) == child.pid
        identity = ProcessIdentity(uuid4().hex,child.pid,process_start_token(child.pid),
            socket.gethostname(),configured_scope())
        assert local_process_state(identity) == 'alive'
        child.communicate('\n',timeout=5)
        assert child.returncode == 0
        assert local_process_state(identity) == 'absent'
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux kernel observation required')
@pytest.mark.parametrize('role', ['api','worker'])
def test_real_cli_db_and_child_lifetime_keep_unknown_scope_and_unresolved_rows(replicas, monkeypatch, role):
    owner = RuntimeIdentity(uuid4().hex,'audit-observer-cli','a'*40,'audit-observer-cli')
    values = {'REDIS_KEY_PREFIX':'audit-observer-'+uuid4().hex,'RUNTIME_POOL_ID':owner.pool_id,
        'DEPLOYMENT_SHA':owner.deployment_sha,'RUNTIME_INSTANCE_ID':owner.id,
        'SANDBOX_POOL_ID':owner.sandbox_pool_id,'SANDBOX_IMAGE':'compiler-sandbox','WORKER_STATE_DIRECTORY':''}
    for key,value in values.items():
        monkeypatch.setattr(settings,key,value)
    engine = replicas[0].kw['bind']
    env = dict(os.environ, **values, ENVIRONMENT='development', REDIS_URL='')
    if engine.dialect.name == 'postgresql':
        with engine.connect() as db:
            schema = db.execute(text('SELECT current_schema()')).scalar_one()
        assert schema.startswith('audit_queue_')
        env.update(DATABASE_URL=os.environ['TEST_POSTGRES_URL'], PGOPTIONS='-csearch_path='+schema)
    else:
        env['DATABASE_URL'] = str(engine.url)
    assert RuntimeRegistry(replicas[0]).register(owner)
    child = subprocess.Popen([sys.executable,'-c','import sys; sys.stdin.readline()'],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
    try:
        process = ProcessIdentity(uuid4().hex,child.pid,process_start_token(child.pid),
            socket.gethostname(),configured_scope())
        model = ApiProcessRecord if role == 'api' else WorkerProcessRecord
        lifecycle = RuntimeRequests if role == 'api' else WorkerLifecycle
        service = lifecycle(replicas[0],owner,process)
        assert service.register()
        request = service.begin('websocket') if role == 'api' else None
        claim_before = None
        if role=='worker':
            queue = DurableQueue(replicas[0])
            job_id = queue.enqueue(owner_key='observer-fixture',request_id=uuid4().hex,
                kind='run',payload={'code':'print(1)'})
            assert queue.claim(worker=replace(lane(owner),process_id=process.epoch)).id==job_id
            with replicas[0]() as db:
                row = db.get(ExecutionJob,job_id)
                claim_before = (row.status,row.lease_token,row.lease_until,row.worker_id)
        stale = replace(process,epoch=uuid4().hex,scope='b'*64)
        assert lifecycle(replicas[0],owner,stale).register()

        def observe(identity, expected, exit_code):
            result = subprocess.run([sys.executable,'-m','app.process_observe',
                '--role',role,'--epoch',identity.epoch,'--runtime',owner.id,
                '--pool',owner.pool_id,'--release',owner.deployment_sha,
                '--sandbox-pool',owner.sandbox_pool_id], env=env,
                cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,timeout=12)
            assert result.returncode == exit_code
            assert json.loads(result.stdout) == {'runtime_id':owner.id,'role':role,
                'epoch':identity.epoch,'state':expected}

        observe(process,'alive',0)
        observe(stale,'unknown',1)
        child.communicate('\n',timeout=5)
        assert child.returncode == 0
        observe(process,'absent',0)
        observe(stale,'unknown',1)
        with replicas[0]() as db:
            assert db.get(model,process.epoch).stopped_at is None
            assert db.get(model,stale.epoch).stopped_at is None
            if request is not None:
                assert db.get(ActiveApiRequest,request) is not None
            if claim_before is not None:
                row = db.get(ExecutionJob,job_id)
                assert (row.status,row.lease_token,row.lease_until,row.worker_id)==claim_before
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)


@pytest.mark.skipif(sys.platform != 'linux' or os.getenv('RUN_SANDBOX_INTEGRATION') != '1',
    reason='Explicit isolated Docker namespace test required')
def test_same_hostname_and_configuration_in_other_container_is_unknown(monkeypatch):
    import docker
    root = Path(os.environ['AUDIT_ROOT']).resolve()
    assert root.name.startswith('webcompiler-audit-')
    nonce = uuid4().hex
    values = {'REDIS_KEY_PREFIX':'audit-observer-'+nonce,'RUNTIME_POOL_ID':'audit-observer',
        'DEPLOYMENT_SHA':'a'*40,'RUNTIME_INSTANCE_ID':uuid4().hex,'SANDBOX_POOL_ID':'audit-observer',
        'SANDBOX_IMAGE':'compiler-sandbox','WORKER_STATE_DIRECTORY':''}
    for key,value in values.items():
        monkeypatch.setattr(settings,key,value)
    identity = ProcessIdentity(uuid4().hex,os.getpid(),process_start_token(os.getpid()),
        socket.gethostname(),configured_scope())
    assert local_process_state(identity) == 'alive'
    script = ('import json,sys,socket; from app.services.worker_process import ProcessIdentity,local_namespace_token; '
        'from app.services.process_observation import local_process_state; '
        'p=ProcessIdentity(**json.loads(sys.argv[1])); '
        'print(json.dumps(dict(hostname=socket.gethostname(),namespace=local_namespace_token(),state=local_process_state(p))))')
    client = docker.from_env(timeout=5)
    child = None
    try:
        runner = client.containers.get(socket.gethostname())
        assert runner.labels.get('com.docker.compose.service') == 'test-runner'
        assert runner.labels.get('com.docker.compose.project','').startswith('webcompiler-audit-')
        child = client.containers.run(runner.image.id,
            command=['python','-c',script,json.dumps(asdict(identity))], detach=True,
            hostname=socket.gethostname(), environment={**values,'ENVIRONMENT':'development','REDIS_URL':''},
            volumes={str(root/'backend'):{'bind':'/app','mode':'ro'}}, working_dir='/app',
            user=str(os.geteuid()), network_disabled=True, read_only=True, cap_drop=['ALL'],
            security_opt=['no-new-privileges'], pids_limit=32, mem_limit='128m', memswap_limit='128m',
            nano_cpus=125000000, labels={'io.webcompiler.audit.process-observer':nonce})
        assert child.wait(timeout=20)['StatusCode'] == 0
        output = child.logs(stdout=True,stderr=False)
        assert len(output) < 4096
        result = json.loads(output)
        assert result['hostname'] == identity.hostname
        assert result['namespace'] != local_namespace_token()
        assert result['state'] == 'unknown'
        assert local_process_state(identity) == 'alive'
    finally:
        if child is not None:
            child.reload()
            assert child.labels.get('io.webcompiler.audit.process-observer') == nonce
            child.remove(force=True)  # Only this exact test-created child.
        client.close()
