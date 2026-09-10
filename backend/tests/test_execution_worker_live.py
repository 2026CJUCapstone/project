"""Opt-in, bounded SIGTERM recovery using only this test's process and sandboxes."""
import asyncio
import multiprocessing
import os
import time
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.database import ExecutionJob, ExecutionWorkerRecord
from app.services.compiler import DockerCompilerRunner
from app.services.durable_queue import DurableQueue, WorkerIdentity
from app.services.execution_worker import ExecutionWorker, SandboxPool
from tests.test_durable_queue import replicas
from tests.test_sandbox_live import isolated_resource_budget

pytestmark = pytest.mark.skipif(os.getenv('RUN_SANDBOX_INTEGRATION') != '1', reason='Explicit isolated Docker tests required')


def child_worker(url, schema, pool_id):
    settings.SANDBOX_POOL_ID = pool_id
    settings.RUNTIME_POOL_ID = pool_id+'-blue'
    args = {'options':f'-csearch_path={schema}'} if schema else {'check_same_thread':False}
    engine = create_engine(url, connect_args=args)
    queue = DurableQueue(sessionmaker(bind=engine), concurrency=1, lease_seconds=2, max_attempts=1)
    asyncio.run(ExecutionWorker(queue).run_once())


def test_process_death_reaps_real_sandbox_before_reusing_shared_capacity(replicas, isolated_resource_budget, monkeypatch):
    pool_id = f'audit-worker-{uuid.uuid4().hex}'
    monkeypatch.setattr(settings, 'SANDBOX_POOL_ID', pool_id)
    factory = replicas[0]
    engine = factory.kw['bind']
    with engine.connect() as db:
        schema = db.execute(text('select current_schema()')).scalar() if engine.dialect.name == 'postgresql' else None
    queue = DurableQueue(factory, concurrency=1, lease_seconds=2, max_attempts=1)
    first = queue.enqueue(owner_key='crash', request_id='first', kind='run',
                          payload={'code':'import time; time.sleep(20)', 'language':'python'})
    second = queue.enqueue(owner_key='crash', request_id='second', kind='run',
                           payload={'code':'print(42)', 'language':'python'})
    process = multiprocessing.get_context('spawn').Process(target=child_worker,
        args=(engine.url.render_as_string(hide_password=False), schema, pool_id))
    client = DockerCompilerRunner()._get_client()
    pool = SandboxPool(lambda:client)
    first_token, old_identity = None, None
    try:
        process.start()
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            with factory() as db:
                record = db.get(ExecutionJob, first)
                first_token = record.lease_token
                if record.worker_id:
                    owner = db.get(ExecutionWorkerRecord,record.worker_id)
                    old_identity = WorkerIdentity(owner.id,owner.pool_id,owner.deployment_sha,owner.sandbox_pool_id,owner.runtime_id)
            if first_token:
                containers = client.containers.list(filters={'label':[f'webcompiler.pool={pool_id}', f'webcompiler.job={first}']})
                if containers:
                    break
            assert process.is_alive(), 'Worker exited before sandbox started'
            time.sleep(0.1)
        else:
            pytest.fail('Sandbox did not start within the bounded deadline')
        # This PID was created by the test, inside its disposable runner container.
        process.terminate()
        process.join(5)
        assert not process.is_alive()
        # Crash deliberately bypasses finally; prove it actually left a sandbox.
        assert client.containers.list(filters={'label':[f'webcompiler.pool={pool_id}', f'webcompiler.job={first}']})
        assert old_identity is not None and old_identity.pool_id == pool_id+'-blue'
        with factory() as db:
            assert db.get(ExecutionJob, first).sandbox_daemon_id == client.info()['ID']
        queue.begin_worker_drain(old_identity)
        assert queue.worker_status(old_identity)['active_claims'] == 1
        monkeypatch.setattr(settings,'RUNTIME_POOL_ID',pool_id+'-green')
        worker = ExecutionWorker(queue, pool=pool)
        assert queue.reap_expired is None  # Real workers cannot use legacy locked cleanup.
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if asyncio.run(worker.run_once()):
                break
            time.sleep(0.1)
        assert queue.read(first, owner_key='crash')['status'] == 'failed'
        completed = queue.read(second, owner_key='crash')
        assert completed['status'] == 'completed'
        assert completed['result']['value']['stdout'].strip() == '42'
        assert queue.worker_status(old_identity) == {'id':old_identity.id,'draining':True,'active_claims':0}
        with factory() as db:
            assert db.get(ExecutionJob,first).worker_id == old_identity.id
            assert db.get(ExecutionJob,second).worker_id == worker.identity.id
            assert worker.identity.id != old_identity.id
        assert not queue.finish(first,first_token,{'verdict':'accepted'})
        assert not client.containers.list(all=True, filters={'label':f'webcompiler.pool={pool_id}'})
        assert not list(Path(settings.SANDBOX_WORKDIR_ROOT).glob(f'job-{first}-*'))
    finally:
        if process.is_alive():
            process.terminate()
            process.join(5)
        # Exact random pool label, never the production pool or broad prune.
        for container in client.containers.list(all=True, filters={'label':f'webcompiler.pool={pool_id}'}):
            labels = container.labels
            assert labels.get('webcompiler.pool') == pool_id
            pool.reap(labels['webcompiler.job'], labels['webcompiler.lease'])
        client.close()
