"""Same release and pool are insufficient evidence of the current incarnation."""
import json
from uuid import uuid4

import pytest
from sqlalchemy import Column, DateTime, MetaData, String, Table, inspect, text

from app.core import database
from app.core.config import settings
from app.models.database import ExecutionWorkerRecord
from app.proxy_membership import Config, ready_peer
from app.proxy_promotion import candidate
from app.services import runtime_health
from app.services.auth import validate_runtime_security
from app.services.durable_queue import DurableQueue, WorkerIdentity
from tests.test_durable_queue import replicas, add
from tests.test_worker_schema_migration import legacy_execution_engine


def test_runtime_health_keys_do_not_reuse_same_release_same_pool_heartbeat(monkeypatch):
    monkeypatch.setattr(settings,'RUNTIME_POOL_ID','same-pool')
    monkeypatch.setattr(settings,'DEPLOYMENT_SHA','a'*40)
    keys=set()
    for runtime_id in ('','b'*32,'c'*32):
        monkeypatch.setattr(settings,'RUNTIME_INSTANCE_ID',runtime_id)
        keys.add(runtime_health.worker_health_key())
    assert len(keys)==3


def test_production_requires_explicit_runtime_incarnation(monkeypatch):
    monkeypatch.setattr(settings,'ENVIRONMENT','production')
    monkeypatch.setattr(settings,'SECRET_KEY','s'*40)
    monkeypatch.setattr(settings,'ADMIN_PASSWORD','p'*32)
    monkeypatch.setattr(settings,'RUNTIME_INSTANCE_ID','')
    with pytest.raises(ValueError,match='runtime instance'):
        validate_runtime_security()
    monkeypatch.setattr(settings,'RUNTIME_INSTANCE_ID','b'*32)
    validate_runtime_security()


@pytest.mark.asyncio
@pytest.mark.parametrize('actual',[None,'','c'*32,'b'*32])
async def test_membership_rejects_stale_ready_peer_even_when_release_and_pool_match(monkeypatch,actual):
    async def probe(host,port,path):
        return json.dumps({'status':'ready'} if path=='/ready' else
            {'status':'ok','deploymentSha':'a'*40,'runtimeInstanceId':actual}).encode()
    monkeypatch.setattr('app.proxy_membership.http_get',probe)
    config=Config('backend',8000,'a'*40,('127.0.0.0/24',),runtime_id='b'*32)
    assert await ready_peer(config,'127.0.0.2') is (actual=='b'*32)
    status={'deploymentSha':'a'*40,'poolId':'pool','available':True,'deploymentReady':True,
            'draining':False,'readyPeers':2,'generation':'d'*32,'runtimeInstanceId':actual}
    assert (candidate(status,'a'*40,'pool','b'*32) is not None) is (actual=='b'*32)


def test_runtime_is_associated_without_merging_worker_lanes_or_queue_budget(replicas):
    queue=DurableQueue(replicas[0],concurrency=1)
    old=WorkerIdentity(uuid4().hex,'pool','a'*40,'sandbox','b'*32)
    sibling=WorkerIdentity(uuid4().hex,'pool','a'*40,'sandbox','b'*32)
    new=WorkerIdentity(uuid4().hex,'pool','a'*40,'sandbox','c'*32)
    first=add(queue)
    add(queue,request='second')
    owned=queue.claim(worker=old)
    assert owned.id==first
    queue.begin_worker_drain(old)
    assert queue.claim(worker=sibling) is None
    assert queue.claim(worker=new) is None
    assert not queue.worker_status(sibling)['draining']
    assert queue.worker_status(old)['active_claims']==1
    mismatch=WorkerIdentity(old.id,old.pool_id,old.deployment_sha,old.sandbox_pool_id,new.runtime_id)
    with pytest.raises(ValueError,match='identity mismatch'):
        queue.claim(worker=mismatch)
    assert queue.finish(first,owned.token,{'verdict':'accepted'})
    assert queue.claim(worker=new) is not None
    with replicas[0]() as db:
        assert db.get(ExecutionWorkerRecord,old.id).runtime_id=='b'*32
        assert db.get(ExecutionWorkerRecord,new.id).runtime_id=='c'*32


def test_legacy_worker_rows_keep_unknown_runtime_without_resurrecting_fence(legacy_execution_engine):
    engine=legacy_execution_engine
    metadata=MetaData()
    table=Table('execution_workers',metadata,
        Column('id',String,primary_key=True),Column('pool_id',String,nullable=False),
        Column('deployment_sha',String,nullable=False),Column('sandbox_pool_id',String,nullable=False),
        Column('started_at',DateTime,nullable=False),Column('draining_at',DateTime))
    metadata.create_all(engine)
    from datetime import datetime
    at=datetime(2030,1,1)
    with engine.begin() as connection:
        connection.execute(table.insert(),{'id':'a'*32,'pool_id':'old-pool','deployment_sha':'b'*40,
            'sandbox_pool_id':'shared','started_at':at,'draining_at':at})
    for _ in range(2):
        database.init_db(engine)
        with engine.connect() as connection:
            record=connection.execute(text('SELECT * FROM execution_workers')).mappings().one()
            assert record['runtime_id']=='' and record['pool_id']=='old-pool'
            assert record['draining_at'] is not None and record['started_at']==record['draining_at']
        assert any(index['column_names']==['runtime_id'] for index in inspect(engine).get_indexes('execution_workers'))
