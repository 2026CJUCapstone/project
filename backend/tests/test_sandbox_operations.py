"""Durable Docker mutation boundaries across independent SQLite/PG sessions."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Event
from types import SimpleNamespace

import pytest
from docker.errors import DockerException
from sqlalchemy import event

from app.models.database import ExecutionJob
from app.services.durable_queue import DurableQueue, SandboxOperationPending
from tests.test_durable_queue import replicas, add


AT=datetime(2026,9,10)
CONTAINER='a'*64


def prepared(replicas):
    queue=DurableQueue(replicas[0],concurrency=1)
    identity=add(queue,at=AT)
    claim=queue.claim(at=AT)
    assert claim.id==identity
    return queue,claim


def pending(sessions,job):
    with sessions() as db:
        return db.get(ExecutionJob,job).sandbox_operation


@pytest.mark.parametrize('kind',['create','start'])
def test_intent_visible_before_effect_blocks_finish_reap_and_new_claim(replicas,kind):
    queue,claim=prepared(replicas)
    reaped=[]
    peer=DurableQueue(replicas[1],concurrency=1,reap_expired=lambda *args:reaped.append(args))
    add(peer,'other',at=AT)
    def action(operation):
        assert pending(replicas[1],claim.id)==operation
        assert operation['kind']==kind and operation['lease_token']==claim.token
        assert len(operation['id'])==32
        assert peer.finish(claim.id,claim.token,{'verdict':'system_error'},at=AT) is False
        assert peer.claim(at=AT+timedelta(hours=1)) is None
        assert reaped==[]
        assert peer.start(claim.id,claim.token,lambda:pytest.fail('second start'),at=AT) is False
        return SimpleNamespace(id=CONTAINER) if kind=='create' else None
    queue.sandbox_operation(claim.id,claim.token,kind,action,at=AT,
        **({'container_id':CONTAINER} if kind=='start' else {}))
    assert pending(replicas[1],claim.id) is None
    assert peer.finish(claim.id,claim.token,{'verdict':'accepted'},at=AT)


@pytest.mark.parametrize('kind',['create','start'])
@pytest.mark.parametrize('exception',[DockerException,RuntimeError,SystemExit])
def test_errors_and_process_exit_do_not_erase_intent_or_allow_expired_reuse(replicas,kind,exception):
    queue,claim=prepared(replicas)
    def action(operation): raise exception('private daemon failure')
    with pytest.raises(exception):
        queue.sandbox_operation(claim.id,claim.token,kind,action,at=AT,
            **({'container_id':CONTAINER} if kind=='start' else {}))
    original=pending(replicas[1],claim.id)
    assert original and 'private daemon failure' not in str(original)
    restarted=DurableQueue(replicas[1],concurrency=1,reap_expired=lambda *args:pytest.fail('unproven reap'))
    assert restarted.finish(claim.id,claim.token,{'verdict':'accepted'},at=AT) is False
    assert restarted.claim(at=AT+timedelta(days=30)) is None
    with pytest.raises(SandboxOperationPending):
        restarted.sandbox_operation(claim.id,claim.token,'create',lambda _:pytest.fail('duplicate mutation'),at=AT)
    assert pending(replicas[0],claim.id)==original


def test_late_positive_response_allows_cleanup_not_lease_renewal(replicas):
    queue,claim=prepared(replicas)
    entered,release=Event(),Event()
    def action(operation):
        entered.set()
        assert release.wait(5)
        return SimpleNamespace(id=CONTAINER)
    peer=DurableQueue(replicas[1],concurrency=1,reap_expired=lambda *args:None)
    with ThreadPoolExecutor(max_workers=1) as executor:
        task=executor.submit(queue.sandbox_operation,claim.id,claim.token,'create',action,at=AT)
        try:
            assert entered.wait(3)
            assert peer.claim(at=AT+timedelta(seconds=121)) is None
        finally: release.set()
        assert task.result(5).id==CONTAINER
    next_claim=peer.claim(at=AT+timedelta(seconds=121))
    assert next_claim.id==claim.id and next_claim.token!=claim.token
    assert queue.finish(claim.id,claim.token,{'verdict':'accepted'},at=AT) is False
    assert queue.start(claim.id,claim.token,lambda:pytest.fail('stale start'),at=AT) is False


@pytest.mark.parametrize('phase',['intent','acknowledgment'])
def test_failed_commit_never_sends_unjournaled_request_or_loses_pending_outcome(replicas,phase):
    queue,claim=prepared(replicas)
    factory=replicas[0]
    calls=[]
    def fail_commit(session):
        for item in session.dirty:
            if isinstance(item,ExecutionJob):
                should_fail=(item.sandbox_operation is not None)==(phase=='intent')
                if should_fail: raise RuntimeError('injected commit failure')
    def action(operation):
        calls.append(operation)
        return SimpleNamespace(id=CONTAINER)
    event.listen(factory,'before_commit',fail_commit)
    try:
        with pytest.raises(RuntimeError,match='injected commit failure'):
            queue.sandbox_operation(claim.id,claim.token,'create',action,at=AT)
    finally: event.remove(factory,'before_commit',fail_commit)
    if phase=='intent':
        assert calls==[] and pending(replicas[1],claim.id) is None
    else:
        assert len(calls)==1 and pending(replicas[1],claim.id)==calls[0]


@pytest.mark.parametrize('container_id',[None,'a'*63,'A'*64,True])
def test_invalid_start_target_refused_before_intent_or_effect(replicas,container_id):
    queue,claim=prepared(replicas)
    with pytest.raises(ValueError):
        queue.sandbox_operation(claim.id,claim.token,'start',lambda _:pytest.fail('invalid effect'),
            container_id=container_id,at=AT)
    assert pending(replicas[1],claim.id) is None


def test_incomplete_allocation_response_keeps_original_intent(replicas):
    queue,claim=prepared(replicas)
    with pytest.raises(SandboxOperationPending,match='incomplete'):
        queue.sandbox_operation(claim.id,claim.token,'create',lambda _:SimpleNamespace(id='short'),at=AT)
    assert pending(replicas[1],claim.id)['kind']=='create'


def test_private_pending_metadata_is_not_exposed_in_owner_receipt(replicas):
    queue,claim=prepared(replicas)
    with pytest.raises(DockerException):
        queue.sandbox_operation(claim.id,claim.token,'create',
            lambda _:(_ for _ in ()).throw(DockerException()),at=AT)
    receipt=queue.read(claim.id,owner_key='owner')
    assert receipt['status']=='running'
    assert not {'sandbox_operation','lease_token','payload'} & set(receipt)


def test_runtime_retirement_evidence_keeps_uncertain_operation_as_active_work(replicas):
    from tests.test_runtime_evidence import setup
    from app.services.runtime_evidence import RuntimeEvidence
    owner,api,worker,identity,request,claim=setup(replicas[0])
    queue=DurableQueue(replicas[0])
    with pytest.raises(DockerException):
        queue.sandbox_operation(claim.id,claim.token,'create',
            lambda _:(_ for _ in ()).throw(DockerException()),at=datetime(2020,1,1))
    assert queue.finish(claim.id,claim.token,{'verdict':'system_error'},at=datetime(2020,1,1)) is False
    report=RuntimeEvidence(replicas[1],owner).snapshot()
    assert report['active_claims']==1
    assert report['lanes'][0]['active_claims']==1
    assert pending(replicas[1],claim.id) is not None
    assert claim.token not in str(report)
