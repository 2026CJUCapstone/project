"""Real ExecutionWorker subprocess crash/restart on disposable PostgreSQL.

The runner and sandbox pool are deliberately synthetic. The two worker
instances, queue transactions, lease fence, and OS process death are real.
"""
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import re
import select
import subprocess
import sys
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.models.database import ExecutionJob, ExecutionWorkerRecord
from app.services.durable_queue import DurableQueue
from tests.test_durable_queue import replicas


CHILD = '''\
import asyncio, json, os, sys
from datetime import datetime
from types import SimpleNamespace
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.services import durable_queue
from app.services.durable_queue import DurableQueue, WorkerIdentity
from app.services.execution_worker import ExecutionWorker

mode, schema, time_value, worker_id, owner = sys.argv[1:]
clock = datetime.fromisoformat(time_value)
durable_queue.now_utc = lambda: clock
engine = create_engine(os.environ['TEST_POSTGRES_URL'],
    connect_args={'options': '-csearch_path=' + schema})
factory = sessionmaker(bind=engine)
queue = DurableQueue(factory, lease_seconds=2)
reaped = []
pool = SimpleNamespace(reap=lambda job, token: reaped.append([job, token]))

class Runner:
    def __init__(self, **kwargs):
        self.guard = kwargs['start_guard']
        self.job = kwargs['labels']['webcompiler.job']

    async def run(self, **kwargs):
        assert kwargs['source_code'] == 'print(42)'
        assert self.guard(lambda: None)  # Confirm start while lease is exclusive.
        if mode == 'crash':
            print(json.dumps({'stage': 'running', 'job': self.job}), flush=True)
            await asyncio.Event().wait()
        return {'stdout':'42', 'stderr':'', 'exit_code':0, 'execution_time':1}

identity = WorkerIdentity(id=worker_id, pool_id='audit', deployment_sha='',
    sandbox_pool_id='audit')
worker = ExecutionWorker(queue, pool=pool, runner_factory=Runner, identity=identity)
assert asyncio.run(worker.run_once())
if mode == 'recover':
    row = queue.read(owner, owner_key='fixture-owner')
    print(json.dumps({'stage':'finished', 'result':{'status':row['status'], 'result':row['result']},
        'reaped':reaped}), flush=True)
'''


@pytest.mark.skipif(os.name != 'posix', reason='Requires POSIX process termination')
def test_execution_worker_new_process_reaps_and_finishes_after_crash(replicas):
    engine = replicas[0].kw['bind']
    if engine.dialect.name != 'postgresql':
        pytest.skip('Explicit isolated PostgreSQL process test')
    with engine.connect() as db:
        schema = db.execute(text('SELECT current_schema()')).scalar_one()
    assert re.fullmatch(r'audit_queue_[a-f0-9]{32}', schema)
    assert os.getenv('TEST_POSTGRES_URL')

    when = datetime(2030, 1, 1)
    producer = DurableQueue(replicas[0], lease_seconds=2)
    job_id = producer.enqueue(owner_key='fixture-owner', request_id=uuid4().hex,
        kind='run', payload={'code':'print(42)', 'language':'python'}, at=when)
    backend_root = str(Path(__file__).resolve().parents[1])
    env = dict(os.environ, PYTHONUNBUFFERED='1')
    first_id, second_id = uuid4().hex, uuid4().hex
    first = subprocess.Popen(
        [sys.executable, '-c', CHILD, 'crash', schema, when.isoformat(), first_id, job_id],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        cwd=backend_root, env=env)
    try:
        ready, _, _ = select.select([first.stdout], [], [], 15)
        assert ready, 'Worker did not start the claimed job'
        line = first.stdout.readline()
        assert line, first.stderr.read(2048) if first.poll() is not None else 'No worker event'
        event = json.loads(line)
        assert event == {'stage':'running', 'job':job_id}
        assert first.poll() is None
        first.kill()  # Only this test's own worker subprocess.
        first.communicate(timeout=5)
        assert first.returncode != 0
    finally:
        if first.poll() is None:
            first.kill()
            first.communicate(timeout=5)

    with replicas[1]() as db:
        before = db.get(ExecutionJob, job_id)
        old_token = before.lease_token
        assert before.status == 'running' and before.worker_id == first_id
        assert before.result is None and before.attempts == 1
        assert before.sandbox_operation is None and before.sandbox_daemon_id is None
        assert db.get(ExecutionWorkerRecord, first_id) is not None

    # No real sandbox exists: Runner's only guarded start action was a no-op.
    second = subprocess.run(
        [sys.executable, '-c', CHILD, 'recover', schema,
         (when + timedelta(seconds=2)).isoformat(), second_id, job_id],
        capture_output=True, text=True, cwd=backend_root, env=env, timeout=15)
    assert second.returncode == 0, second.stderr[:2048]
    result = json.loads(second.stdout)
    assert result['stage'] == 'finished'
    assert result['result']['status'] == 'completed'
    assert result['result']['result']['value']['stdout'] == '42'
    assert result['reaped'][0] == [job_id, old_token]
    assert len(result['reaped']) == 2 and result['reaped'][1][0] == job_id
    assert not producer.finish(job_id, old_token, {'verdict':'accepted'},
        at=when + timedelta(seconds=2))
    assert producer.read(job_id, owner_key='other-owner') is None
    with replicas[0]() as db:
        final = db.get(ExecutionJob, job_id)
        assert final.status == 'completed' and final.attempts == 2
        assert final.worker_id == second_id and final.lease_token is None
        assert db.get(ExecutionWorkerRecord, second_id) is not None
