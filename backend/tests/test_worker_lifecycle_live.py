"""Real managed worker: process-bound lanes, SIGTERM drain, then fresh epoch."""
import asyncio
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.models.database import ExecutionJob, ExecutionWorkerRecord, WorkerProcessRecord
from app.services.compiler import DockerCompilerRunner
from app.services.durable_queue import DurableQueue
from app.services.execution_worker import SandboxPool
from tests.test_durable_queue import replicas
from tests.test_execution_http_live import stop
from tests.test_sandbox_live import isolated_resource_budget

pytestmark = pytest.mark.skipif(os.getenv('RUN_SANDBOX_INTEGRATION') != '1' or not os.getenv('TEST_REDIS_URL'),
    reason='Explicit isolated Docker/Redis managed-worker test host required')


@pytest.mark.asyncio
async def test_managed_process_fences_all_lanes_finishes_claim_and_restarts_with_new_owner(
        replicas, isolated_resource_budget, monkeypatch):
    prefix = 'audit-worker-life-'+uuid4().hex
    runtime_id = uuid4().hex
    monkeypatch.setattr(settings, 'SANDBOX_POOL_ID', prefix)
    engine = replicas[0].kw['bind']
    env = dict(os.environ, ENVIRONMENT='production', AUTO_INITIALIZE_DB='false',
        EMBEDDED_EXECUTION_WORKER='false', REDIS_URL=os.environ['TEST_REDIS_URL'],
        REDIS_KEY_PREFIX=prefix, RUNTIME_POOL_ID=prefix, SANDBOX_POOL_ID=prefix,
        RUNTIME_INSTANCE_ID=runtime_id, DEPLOYMENT_SHA='a'*40, COMPILER_QUEUE_CONCURRENCY='2')
    if engine.dialect.name == 'postgresql':
        with engine.connect() as db:
            schema = db.execute(text('SELECT current_schema()')).scalar_one()
        assert schema.startswith('audit_queue_')
        env.update(DATABASE_URL=os.environ['TEST_POSTGRES_URL'], PGOPTIONS='-csearch_path='+schema)
    else:
        env['DATABASE_URL'] = str(engine.url)
    root = Path(__file__).resolve().parents[1]
    queue = DurableQueue(replicas[0], concurrency=2)
    first = queue.enqueue(owner_key='fixture', request_id='first', kind='run',
        payload={'code':'import time; time.sleep(6); print(41)', 'language':'python'})
    client = DockerCompilerRunner()._get_client()
    pool = SandboxPool(lambda:client)
    processes = []
    with tempfile.TemporaryFile() as log:
        def start():
            process = subprocess.Popen([sys.executable,'-m','app.worker'], cwd=root, env=env, stdout=log, stderr=log)
            processes.append(process)
            return process
        try:
            initialized = await asyncio.to_thread(subprocess.run, [sys.executable,'-m','app.initialize'],
                cwd=root, env=env, stdout=log, stderr=log, timeout=30)
            assert initialized.returncode == 0
            process = start()
            async with asyncio.timeout(25):
                while True:
                    assert process.poll() is None
                    with replicas[0]() as db:
                        lanes = db.query(ExecutionWorkerRecord).filter_by(runtime_id=runtime_id).all()
                        current = db.get(ExecutionJob, first)
                        if len(lanes) == 2 and current.status == 'running':
                            epochs = {lane.process_id for lane in lanes}
                            assert len(epochs) == 1 and None not in epochs
                            epoch = next(iter(epochs))
                            owner = db.get(WorkerProcessRecord, epoch)
                            assert owner.pid == process.pid and owner.runtime_id == runtime_id
                            assert owner.draining_at is None and owner.stopped_at is None
                            containers = await asyncio.to_thread(client.containers.list,
                                filters={'label':[f'webcompiler.pool={prefix}', f'webcompiler.job={first}']})
                            if containers:
                                break
                    await asyncio.sleep(.05)
            process.terminate()  # Only this test's child process.
            async with asyncio.timeout(5):
                while True:
                    with replicas[0]() as db:
                        owner = db.get(WorkerProcessRecord, epoch)
                        if owner.draining_at is not None:
                            assert owner.stopped_at is None
                            break
                    await asyncio.sleep(.02)
            second = queue.enqueue(owner_key='fixture', request_id='second', kind='run',
                payload={'code':'print(42)', 'language':'python'})
            assert await asyncio.to_thread(process.wait, timeout=15) == 0
            assert queue.read(first, owner_key='fixture')['result']['value']['stdout'].strip() == '41'
            assert queue.read(second, owner_key='fixture')['status'] == 'queued'
            with replicas[0]() as db:
                assert db.get(WorkerProcessRecord, epoch).stopped_at is not None
                assert all(lane.draining_at is not None for lane in db.query(ExecutionWorkerRecord).filter_by(process_id=epoch))
            replacement = start()
            async with asyncio.timeout(20):
                while queue.read(second, owner_key='fixture')['status'] != 'completed':
                    assert replacement.poll() is None
                    await asyncio.sleep(.1)
            assert queue.read(second, owner_key='fixture')['result']['value']['stdout'].strip() == '42'
            replacement.terminate()
            assert await asyncio.to_thread(replacement.wait, timeout=15) == 0
            with replicas[0]() as db:
                rows = db.query(WorkerProcessRecord).filter_by(runtime_id=runtime_id).all()
                assert len(rows) == 2 and all(row.stopped_at is not None for row in rows)
                second_lane = db.get(ExecutionWorkerRecord, db.get(ExecutionJob, second).worker_id)
                assert second_lane.process_id != epoch and second_lane.process_id in {row.id for row in rows}
            assert not await asyncio.to_thread(client.containers.list, all=True, filters={'label':f'webcompiler.pool={prefix}'})
        finally:
            for process in processes:
                await asyncio.to_thread(stop, process)
            for container in client.containers.list(all=True, filters={'label':f'webcompiler.pool={prefix}'}):
                assert container.labels['webcompiler.pool'] == prefix
                pool.reap(container.labels['webcompiler.job'], container.labels['webcompiler.lease'])
            client.close()
