"""Consistent private DB evidence under concurrent completion, on SQLite/PG."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime
import json
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import event, text

from app.models.database import (
    ActiveApiRequest, ApiProcessRecord, ExecutionJob, ExecutionQueueLock,
    ExecutionWorkerRecord, WorkerProcessRecord,
)
from app.services import runtime_evidence as module
from app.services.api_lifecycle import RuntimeRequests
from app.services.durable_queue import DurableQueue
from app.services.runtime_evidence import RuntimeEvidence
from app.services.runtime_registry import RuntimeRegistry, execution_lock
from app.services.worker_lifecycle import WorkerLifecycle
from app.services.worker_process import ProcessIdentity
from tests.test_durable_queue import replicas, add
from tests.test_runtime_registry import runtime, lane


def setup(sessions):
    owner = runtime()
    registry = RuntimeRegistry(sessions)
    assert registry.register(owner)
    api = ProcessIdentity(uuid4().hex,123,'linux:boot:456','fixture','a'*64)
    worker = replace(api,epoch=uuid4().hex,pid=124,start_token='linux:boot:457')
    requests = RuntimeRequests(sessions,owner,api)
    assert requests.register()
    assert WorkerLifecycle(sessions,owner,worker).register()
    request = requests.begin('websocket')
    queue = DurableQueue(sessions)
    job = queue.enqueue(owner_key='private-owner',request_id=uuid4().hex,kind='run',
        payload={'code':'SECRET_SOURCE_DO_NOT_SELECT'},at=datetime(2020,1,1))
    identity = replace(lane(owner),process_id=worker.epoch)
    claim = queue.claim(worker=identity,at=datetime(2020,1,1))
    assert claim.id==job
    registry.begin_drain(owner)
    return owner,api,worker,identity,request,claim


def test_readonly_projection_preserves_expired_claims_requests_and_process_lifetime(replicas):
    owner,api,worker,identity,request,claim = setup(replicas[0])
    statements = []
    engine = replicas[1].kw['bind']
    with replicas[0]() as db:
        revision = db.get(ExecutionQueueLock,'execution').revision
        job = db.get(ExecutionJob,claim.id)
        before = (job.status,job.worker_id,job.lease_token,job.lease_until)
    def record(connection,cursor,statement,parameters,context,many):
        statements.append(statement.lower())
    event.listen(engine,'before_cursor_execute',record)
    try:
        subject = RuntimeEvidence(replicas[1],owner)
        observed = subject.snapshot()
        assert subject.snapshot()==observed
    finally:
        event.remove(engine,'before_cursor_execute',record)
    assert observed['active_claims']==1 and observed['active_websockets']==1 and observed['active_http']==0
    assert observed['lanes']==[{'id':identity.id,'epoch':worker.epoch,'draining':False,'active_claims':1}]
    assert {p['epoch'] for p in observed['processes']}=={api.epoch,worker.epoch}
    assert not any(p['stopped'] for p in observed['processes'])
    serialized = json.dumps(observed)
    assert 'SECRET_SOURCE' not in serialized and 'private-owner' not in serialized and claim.token not in serialized
    assert not any(s.lstrip().startswith(('insert ','update ','delete ')) for s in statements)
    assert not any('execution_jobs.payload' in s or 'execution_jobs.result' in s for s in statements)
    with replicas[0]() as db:
        job = db.get(ExecutionJob,claim.id)
        assert (job.status,job.worker_id,job.lease_token,job.lease_until)==before
        assert db.get(ExecutionQueueLock,'execution').revision==revision
        assert db.get(ActiveApiRequest,request) is not None
        assert db.get(ApiProcessRecord,api.epoch).stopped_at is None
        assert db.get(WorkerProcessRecord,worker.epoch).stopped_at is None


def test_one_snapshot_cannot_mix_process_and_claim_state_from_concurrent_completion(replicas):
    engine = replicas[0].kw['bind']
    if engine.dialect.name=='sqlite':
        # Allow a second connection to commit while the reader keeps its
        # snapshot. This is a fixture-only journal mode, not a product change.
        with engine.connect() as db:
            assert db.exec_driver_sql('PRAGMA journal_mode=WAL').scalar()=='wal'
    owner,api,worker,identity,request,claim = setup(replicas[0])
    snapshot_started,release = Event(),Event()
    def hold(connection,cursor,statement,parameters,context,many):
        if statement.lstrip().upper().startswith('SELECT') and 'FROM execution_runtimes' in statement:
            snapshot_started.set()
            assert release.wait(10)
    event.listen(engine,'after_cursor_execute',hold)
    try:
        with ThreadPoolExecutor(1) as executor:
            future = executor.submit(RuntimeEvidence(replicas[0],owner).snapshot)
            try:
                assert snapshot_started.wait(5)
                with replicas[1]() as db:
                    execution_lock(db)
                    db.get(ExecutionJob,claim.id).status='completed'
                    db.get(ApiProcessRecord,api.epoch).stopped_at=datetime(2030,1,1)
                    db.delete(db.get(ActiveApiRequest,request))
                    db.commit()
            finally:
                release.set()
            observed = future.result(timeout=10)
    finally:
        event.remove(engine,'after_cursor_execute',hold)
    assert observed['active_claims']==1 and observed['active_websockets']==1
    assert not next(p for p in observed['processes'] if p['role']=='api')['stopped']
    latest = RuntimeEvidence(replicas[0],owner).snapshot()
    assert latest['active_claims']==0 and latest['active_websockets']==0
    assert next(p for p in latest['processes'] if p['role']=='api')['stopped']
    if engine.dialect.name=='postgresql':
        with engine.connect() as db:
            assert db.get_isolation_level()=='READ COMMITTED'
            assert db.exec_driver_sql('SHOW transaction_read_only').scalar()=='off'
            assert db.exec_driver_sql('SHOW statement_timeout').scalar()!='5s'


@pytest.mark.parametrize('state',['missing','accepting','wrong-metadata'])
def test_unregistered_unfenced_or_conflicting_runtime_never_yields_retirement_evidence(replicas,state):
    owner = runtime()
    if state!='missing':
        assert RuntimeRegistry(replicas[0]).register(owner)
    if state=='wrong-metadata':
        RuntimeRegistry(replicas[0]).begin_drain(owner)
        owner=replace(owner,deployment_sha='b'*40)
    with pytest.raises(ValueError):
        RuntimeEvidence(replicas[1],owner).snapshot()


@pytest.mark.parametrize('field,value',[('process_id',None),('runtime_id','f'*32),
    ('pool_id','foreign'),('deployment_sha','b'*40),('sandbox_pool_id','foreign')])
def test_conflicting_or_unbound_lane_cannot_disappear_from_evidence(replicas,field,value):
    owner,api,worker,identity,request,claim = setup(replicas[0])
    with replicas[0]() as db:
        setattr(db.get(ExecutionWorkerRecord,identity.id),field,value)
        db.commit()
    with pytest.raises(ValueError,match='Unbound or conflicting'):
        RuntimeEvidence(replicas[1],owner).snapshot()
    with replicas[0]() as db:
        assert db.get(ExecutionJob,claim.id).status=='running'
        assert db.get(ExecutionWorkerRecord,identity.id).__dict__[field]==value


def test_same_sha_pool_other_runtime_is_not_included(replicas):
    owner,*_ = setup(replicas[0])
    other,*_ = setup(replicas[0])
    assert owner.id!=other.id and owner.pool_id==other.pool_id
    observed = RuntimeEvidence(replicas[1],owner).snapshot()
    assert observed['active_claims']==1 and observed['active_websockets']==1
    assert len(observed['processes'])==2 and len(observed['lanes'])==1


def test_unknown_active_request_kind_is_not_silently_omitted(replicas):
    owner,api,worker,identity,request,claim = setup(replicas[0])
    with replicas[0]() as db:
        db.get(ActiveApiRequest,request).kind='future-kind'
        db.commit()
    with pytest.raises(ValueError,match='Unknown active request kind'):
        RuntimeEvidence(replicas[1],owner).snapshot()


def test_unbounded_distinct_kinds_are_rejected_before_group_materialization(replicas):
    owner,api,worker,identity,request,claim = setup(replicas[0])
    with replicas[0]() as db:
        db.add_all(ActiveApiRequest(id=uuid4().hex,process_id=api.epoch,kind=f'unknown-{index}')
            for index in range(100))
        db.commit()
    queries=[]
    engine=replicas[1].kw['bind']
    def record(connection,cursor,statement,parameters,context,many):
        if 'FROM active_api_requests' in statement:
            queries.append(statement)
    event.listen(engine,'before_cursor_execute',record)
    try:
        with pytest.raises(ValueError,match='Unknown active request kind'):
            RuntimeEvidence(replicas[1],owner).snapshot()
    finally:
        event.remove(engine,'before_cursor_execute',record)
    assert len(queries)==1 and 'LIMIT' in queries[0] and 'GROUP BY' not in queries[0]


def test_process_and_lane_caps_refuse_partial_lists_and_release_the_read_transaction(replicas):
    owner,api,worker,identity,request,claim = setup(replicas[0])
    with pytest.raises(ValueError,match='process evidence exceeds'):
        RuntimeEvidence(replicas[1],owner,max_processes=1).snapshot()
    with replicas[0]() as db:
        db.add(ExecutionWorkerRecord(id=uuid4().hex,runtime_id=owner.id,process_id=worker.epoch,
            pool_id=owner.pool_id,deployment_sha=owner.deployment_sha,sandbox_pool_id=owner.sandbox_pool_id))
        db.commit()
    with pytest.raises(ValueError,match='lane evidence exceeds'):
        RuntimeEvidence(replicas[1],owner,max_lanes=1).snapshot()
    assert RuntimeRequests(replicas[0],owner,api).finish(request)
    assert DurableQueue(replicas[0]).finish(claim.id,claim.token,{'ok':True},at=datetime(2020,1,1,0,0,1))


def test_local_evidence_never_attributes_another_namespace_or_role(replicas,monkeypatch):
    owner,api,worker,identity,request,claim = setup(replicas[0])
    monkeypatch.setattr(module,'local_namespace_token',lambda:'exact-kernel-namespace')
    monkeypatch.setattr(module.socket,'gethostname',lambda:api.hostname)
    monkeypatch.setattr(module,'configured_scope',lambda:api.scope)
    seen=[]
    def observe(process):
        seen.append(process)
        return 'absent'
    monkeypatch.setattr(module,'local_process_state',observe)
    subject=RuntimeEvidence(replicas[1],owner)
    assert subject.local('api')['processes']==[{'epoch':api.epoch,'state':'absent'}]
    assert seen==[api]
    seen.clear()
    monkeypatch.setattr(module,'configured_scope',lambda:'b'*64)
    assert subject.local('api')['processes']==[] and seen==[]
    monkeypatch.setattr(module,'local_namespace_token',lambda:None)
    with pytest.raises(ValueError,match='namespace observation unavailable'):
        subject.local('worker')
    assert RuntimeEvidence(replicas[1],owner).snapshot()['active_websockets']==1
