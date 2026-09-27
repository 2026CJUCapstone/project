"""A killed claimant and its replacement use the same durable PostgreSQL rows.

The child performs no sandbox operation. This checks process death, lease
fencing, and result idempotency; it does not stand in for a managed judge.
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
from app.services.durable_queue import DurableQueue, WorkerIdentity
from tests.test_durable_queue import replicas


CHILD = '''\
import json, os, sys, time
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.services.durable_queue import DurableQueue, WorkerIdentity

mode, schema, at, worker_id, old_token = sys.argv[1:]
engine = create_engine(os.environ['TEST_POSTGRES_URL'],
    connect_args={'options': '-csearch_path=' + schema})
reaped = []
queue = DurableQueue(sessionmaker(bind=engine), lease_seconds=2,
    reap_expired=lambda job_id, token: reaped.append([job_id, token]))
worker = WorkerIdentity(id=worker_id, pool_id='audit', deployment_sha='',
    sandbox_pool_id='audit')
claim = queue.claim(at=datetime.fromisoformat(at), worker=worker)
result = {'id': claim.id, 'token': claim.token,
    'payload': claim.payload, 'attempts': claim.attempts, 'reaped': reaped}
if mode == 'first':
    print(json.dumps(result), flush=True)
    time.sleep(60)
elif mode == 'recover':
    result['staleFinish'] = queue.finish(claim.id, old_token,
        {'verdict': 'accepted'}, at=datetime.fromisoformat(at))
    result['freshFinish'] = queue.finish(claim.id, claim.token,
        {'verdict': 'accepted'}, at=datetime.fromisoformat(at))
    result['duplicateFinish'] = queue.finish(claim.id, claim.token,
        {'verdict': 'accepted'}, at=datetime.fromisoformat(at))
    print(json.dumps(result), flush=True)
else:
    raise ValueError('Unknown child role')
'''


@pytest.mark.skipif(os.name != 'posix', reason='This test terminates a POSIX child process')
def test_killed_claimant_is_fenced_and_fresh_process_recovers_once(replicas):
    engine = replicas[0].kw['bind']
    if engine.dialect.name != 'postgresql':
        pytest.skip('Explicit isolated PostgreSQL process test')
    with engine.connect() as db:
        schema = db.execute(text('SELECT current_schema()')).scalar_one()
    assert re.fullmatch(r'audit_queue_[a-f0-9]{32}', schema)
    assert os.getenv('TEST_POSTGRES_URL')

    received = datetime(2030, 1, 1)
    producer = DurableQueue(replicas[0], lease_seconds=2)
    request_id = uuid4().hex
    job_id = producer.enqueue(owner_key='fixture-owner', request_id=request_id,
        kind='run', payload={'code': 'print(42)'}, at=received)
    first_worker_id = uuid4().hex
    backend_root = str(Path(__file__).resolve().parents[1])
    child = subprocess.Popen(
        [sys.executable, '-c', CHILD, 'first', schema, received.isoformat(), first_worker_id, 'none'],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        cwd=backend_root, env=dict(os.environ, PYTHONUNBUFFERED='1'))
    try:
        ready, _, _ = select.select([child.stdout], [], [], 15)
        assert ready, 'Separate claimant did not reach its committed claim'
        line = child.stdout.readline()
        assert line, child.stderr.read(2048) if child.poll() is not None else 'No claim record'
        original = json.loads(line)
        assert original['id'] == job_id
        assert original['payload'] == {'code': 'print(42)'}
        assert original['attempts'] == 1
        assert child.poll() is None
        child.kill()  # Only the subprocess created above.
        child.communicate(timeout=5)
        assert child.returncode != 0
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=5)

    with replicas[1]() as db:
        job = db.get(ExecutionJob, job_id)
        assert job.status == 'running' and job.lease_token == original['token']
        assert job.worker_id == first_worker_id and job.attempts == 1
        assert db.get(ExecutionWorkerRecord, first_worker_id) is not None
    # No sandbox was started by the first child: its only action was claim().
    # A different OS process can therefore positively reap this lease.
    recovery_time = received + timedelta(seconds=2)
    next_worker_id = uuid4().hex
    recovered = subprocess.run(
        [sys.executable, '-c', CHILD, 'recover', schema, recovery_time.isoformat(),
         next_worker_id, original['token']],
        capture_output=True, text=True, cwd=backend_root,
        env=dict(os.environ, PYTHONUNBUFFERED='1'), timeout=15)
    assert recovered.returncode == 0, recovered.stderr[:2048]
    claim = json.loads(recovered.stdout)
    assert claim['reaped'] == [[job_id, original['token']]]
    assert claim['id'] == job_id and claim['token'] != original['token']
    assert claim['attempts'] == 2 and claim['payload'] == original['payload']
    assert claim['staleFinish'] is False
    assert claim['freshFinish'] is True
    assert claim['duplicateFinish'] is False
    assert producer.read(job_id, owner_key='fixture-owner')['result'] == {'verdict': 'accepted'}
    assert producer.read(job_id, owner_key='other-owner') is None
    with replicas[0]() as db:
        assert db.query(ExecutionJob).filter_by(owner_key='fixture-owner', request_id=request_id).count() == 1
        assert db.get(ExecutionJob, job_id).attempts == 2
        assert db.get(ExecutionJob, job_id).worker_id == next_worker_id
