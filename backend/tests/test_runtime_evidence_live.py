"""Real kernel/CLI observation plus preserved DB work, isolated SQLite/PG."""
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
from app.models.database import ActiveApiRequest, ApiProcessRecord, ExecutionJob, WorkerProcessRecord
from app.services.api_lifecycle import RuntimeRequests
from app.services.durable_queue import DurableQueue
from app.services.runtime_registry import RuntimeRegistry
from app.services.worker_lifecycle import WorkerLifecycle
from app.services.worker_process import ProcessIdentity, configured_scope, process_start_token
from tests.test_durable_queue import replicas, add
from tests.test_runtime_registry import runtime, lane


pytestmark=pytest.mark.skipif(sys.platform!='linux',reason='Actual Linux namespace/CLI evidence required')


@pytest.mark.parametrize('role',['api','worker'])
def test_cli_reconciles_exact_local_epoch_without_discarding_unresolved_work(replicas,monkeypatch,role):
    owner=runtime()
    values={'REDIS_KEY_PREFIX':'evidence-'+uuid4().hex,'RUNTIME_POOL_ID':owner.pool_id,
        'RUNTIME_INSTANCE_ID':owner.id,'DEPLOYMENT_SHA':owner.deployment_sha,
        'SANDBOX_POOL_ID':owner.sandbox_pool_id,'SANDBOX_IMAGE':'compiler-sandbox','WORKER_STATE_DIRECTORY':''}
    for key,value in values.items():
        monkeypatch.setattr(settings,key,value)
    engine=replicas[0].kw['bind']
    env=dict(os.environ,**values,ENVIRONMENT='development',REDIS_URL='')
    if engine.dialect.name=='postgresql':
        with engine.connect() as db:
            schema=db.execute(text('SELECT current_schema()')).scalar_one()
        assert schema.startswith('audit_queue_')
        env.update(DATABASE_URL=os.environ['TEST_POSTGRES_URL'],PGOPTIONS='-csearch_path='+schema)
    else:
        env['DATABASE_URL']=str(engine.url)
    registry=RuntimeRegistry(replicas[0])
    assert registry.register(owner)
    child=subprocess.Popen([sys.executable,'-c','import sys; sys.stdin.readline()'],
        stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,text=True)
    try:
        process=ProcessIdentity(uuid4().hex,child.pid,process_start_token(child.pid),
            socket.gethostname(),configured_scope())
        cls=RuntimeRequests if role=='api' else WorkerLifecycle
        service=cls(replicas[0],owner,process)
        assert service.register()
        foreign=replace(process,epoch=uuid4().hex,scope='b'*64)
        assert cls(replicas[0],owner,foreign).register()
        request=service.begin('websocket') if role=='api' else None
        claim=None
        if role=='worker':
            queue=DurableQueue(replicas[0])
            job=add(queue)
            claim=queue.claim(worker=replace(lane(owner),process_id=process.epoch))
            assert claim.id==job
        args=[sys.executable,'-m','app.runtime_inspect','--runtime',owner.id,'--pool',owner.pool_id,
            '--release',owner.deployment_sha,'--sandbox-pool',owner.sandbox_pool_id]
        def inspect(local=False):
            return subprocess.run(args+(['--local-role',role] if local else []),env=env,
                cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,timeout=15)
        assert inspect().returncode==1  # A live unfenced runtime is not a retirement candidate.
        registry.begin_drain(owner)
        result=inspect()
        assert result.returncode==0, result.stderr
        before=json.loads(result.stdout)
        assert before['runtime']==asdict(owner) and len(before['processes'])==2
        assert before['active_websockets' if role=='api' else 'active_claims']==1
        local=inspect(True)
        assert local.returncode==0,local.stderr
        observed=json.loads(local.stdout)
        assert observed['hostname']==process.hostname and observed['scope']==process.scope
        assert observed['processes']==[{'epoch':process.epoch,'state':'alive'}]
        child.communicate('\n',timeout=5)
        assert child.returncode==0
        local=inspect(True)
        assert local.returncode==0
        assert json.loads(local.stdout)['processes']==[{'epoch':process.epoch,'state':'absent'}]
        # An absent process does not erase active work or close its record.
        result=inspect()
        assert result.returncode==0 and json.loads(result.stdout)==before
        with replicas[0]() as db:
            model=ApiProcessRecord if role=='api' else WorkerProcessRecord
            assert db.get(model,process.epoch).stopped_at is None
            assert db.get(model,foreign.epoch).stopped_at is None
            if request:
                assert db.get(ActiveApiRequest,request) is not None
            if claim:
                job=db.get(ExecutionJob,claim.id)
                assert job.status=='running' and job.lease_token==claim.token
    finally:
        if child.poll() is None:
            child.kill()  # Only this fixture's own child, never an observed PID.
            child.wait(timeout=5)
