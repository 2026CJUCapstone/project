"""Real app.worker process/Redis/PG lifecycle with a synthetic execution lane.

This test must run only against disposable PostgreSQL and Redis instances. It
does not grant the worker a Docker socket or claim to verify sandbox behavior.
"""
import json
import os
from pathlib import Path
import re
import select
import socket
import subprocess
import sys
import time
from uuid import uuid4

import pytest
import httpx
from sqlalchemy import text

from app.core import database
from app.initialize import RUNTIME_SCHEMA_VERSION
from app.models.database import ExecutionJob, ExecutionWorkerRecord, WorkerProcessRecord
from app.services.durable_queue import DurableQueue
from app.services.runtime_health import WORKER_HEALTH_SECONDS
from tests.test_durable_queue import replicas


CHILD = '''\
import asyncio, json, os, sys
from uuid import uuid4
from app import worker
from app.core.database import SessionLocal
from app.services.durable_queue import DurableQueue, WorkerIdentity
from app.services.runtime_health import (ensure_worker_process_registered,
    report_worker_ready, worker_process_identity)

mode, job_id = sys.argv[1:]

class SyntheticWorker:
    def __init__(self):
        self.identity = WorkerIdentity(uuid4().hex, os.environ['RUNTIME_POOL_ID'],
            os.environ['DEPLOYMENT_SHA'], os.environ['SANDBOX_POOL_ID'],
            os.environ['RUNTIME_INSTANCE_ID'], worker_process_identity().epoch)
        self.queue = DurableQueue(SessionLocal, lease_seconds=2,
            reap_expired=lambda job, token: None)

    def begin_drain(self):
        self.queue.begin_worker_drain(self.identity)

    async def run(self, stop):
        while not stop.is_set():
            claim = await asyncio.to_thread(self.queue.claim, worker=self.identity,
                stop_requested=stop.is_set)
            if claim is None:
                await asyncio.sleep(.05)
                continue
            assert claim.id == job_id
            if mode == 'crash':
                assert await asyncio.to_thread(self.queue.start, claim.id, claim.token, lambda: None)
                print(json.dumps({'stage':'claimed', 'job':job_id, 'token':claim.token,
                    'epoch':self.identity.process_id}), flush=True)
                await asyncio.Event().wait()
            else:
                assert self.queue.finish(claim.id, claim.token,
                    {'value':{'stdout':'42'}, 'verdict':'accepted'})
                print(json.dumps({'stage':'finished', 'job':job_id,
                    'epoch':self.identity.process_id}), flush=True)
                await stop.wait()
        self.begin_drain()

async def synthetic_health(stop):
    await asyncio.to_thread(ensure_worker_process_registered)
    await asyncio.to_thread(report_worker_ready)
    print(json.dumps({'stage':'ready', 'epoch':worker_process_identity().epoch}), flush=True)
    await stop.wait()

worker.build_worker = SyntheticWorker
worker.health_loop = synthetic_health
worker.contest_maintenance = lambda: asyncio.Event().wait()
worker.retention_maintenance = lambda: asyncio.Event().wait()
asyncio.run(worker.serve())
'''


def _events_until(process, wanted, *, timeout=15):
    deadline = time.monotonic() + timeout
    events = []
    pending = b''
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(f'Worker exited {process.returncode}: {process.stderr.read(2048)}; events={events}')
        ready, _, _ = select.select([process.stdout], [], [], min(.2, max(.01, deadline-time.monotonic())))
        if ready:
            pending += os.read(process.stdout.fileno(), 4096)
            while b'\n' in pending:
                line, pending = pending.split(b'\n', 1)
                event = json.loads(line.decode())
                events.append(event)
                if wanted <= {item['stage'] for item in events}:
                    return {item['stage']: item for item in events}
    raise AssertionError(f'Worker never emitted {sorted(wanted)}: {events}')


@pytest.mark.skipif(os.name != 'posix' or not os.getenv('TEST_REDIS_URL'),
    reason='Requires disposable POSIX PostgreSQL and Redis sockets')
def test_managed_worker_process_restarts_with_new_redis_owner(replicas, tmp_path):
    import redis

    engine = replicas[0].kw['bind']
    if engine.dialect.name != 'postgresql':
        pytest.skip('Explicit isolated PostgreSQL process test')
    with engine.begin() as db:
        schema = db.execute(text('SELECT current_schema()')).scalar_one()
        assert re.fullmatch(r'audit_queue_[a-f0-9]{32}', schema)
        database.init_db(db)
        db.execute(text('INSERT INTO schema_migrations (version) VALUES (:v)'),
            {'v': RUNTIME_SCHEMA_VERSION})

    job_id = DurableQueue(replicas[0]).enqueue(owner_key='fixture-owner',
        request_id=uuid4().hex, kind='run', payload={'code':'print(42)', 'language':'python'})
    runtime_id, prefix = uuid4().hex, 'audit-' + uuid4().hex
    state_dir = tmp_path/'worker-state'
    state_dir.mkdir(mode=0o700)
    env = dict(os.environ, PYTHONUNBUFFERED='1', ENVIRONMENT='production',
        AUTO_INITIALIZE_DB='false', EMBEDDED_EXECUTION_WORKER='false',
        DATABASE_URL=os.environ['TEST_POSTGRES_URL'], PGOPTIONS='-csearch_path=' + schema,
        REDIS_URL=os.environ['TEST_REDIS_URL'], REDIS_KEY_PREFIX=prefix,
        RUNTIME_POOL_ID=prefix, SANDBOX_POOL_ID=prefix,
        RUNTIME_INSTANCE_ID=runtime_id, DEPLOYMENT_SHA='a'*40,
        WORKER_STATE_DIRECTORY=str(state_dir), COMPILER_QUEUE_CONCURRENCY='1',
        SECRET_KEY='isolated-managed-worker-secret-key-20260927',
        ADMIN_PASSWORD='isolated-managed-worker-password-20260927')
    backend_root = str(Path(__file__).resolve().parents[1])
    client = redis.Redis.from_url(env['REDIS_URL'], decode_responses=True)
    health_key = f'{prefix}:health:workers-v2:{prefix}:{"a"*40}:{runtime_id}'
    owner_key = health_key + ':owners'
    children = []

    def start(mode):
        child = subprocess.Popen([sys.executable, '-c', CHILD, mode, job_id],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            cwd=backend_root, env=env)
        children.append(child)
        return child

    try:
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            api_port = listener.getsockname()[1]
        api = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app',
            '--host', '127.0.0.1', '--port', str(api_port), '--no-proxy-headers',
            '--log-level', 'error'], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=backend_root, env=dict(env, DOCKER_HOST='tcp://127.0.0.1:1'))
        children.append(api)
        url = f'http://127.0.0.1:{api_port}'
        http = httpx.Client(timeout=2)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            assert api.poll() is None, api.stderr.read(2048).decode() if api.poll() is not None else ''
            try:
                if http.get(url + '/health').status_code == 200:
                    break
            except httpx.TransportError:
                pass
            time.sleep(.05)
        else:
            raise AssertionError('Isolated API did not start')
        assert http.get(url + '/ready').status_code == 503

        first = start('crash')
        first_events = _events_until(first, {'claimed', 'ready'})
        claimed, ready = first_events['claimed'], first_events['ready']
        assert claimed['epoch'] == ready['epoch']
        assert client.zrange(health_key, 0, -1)
        assert claimed['epoch'] in client.hvals(owner_key)
        assert http.get(url + '/ready').status_code == 200
        with replicas[0]() as db:
            row = db.get(WorkerProcessRecord, claimed['epoch'])
            assert row.pid == first.pid and row.stopped_at is None
            job = db.get(ExecutionJob, job_id)
            assert job.status == 'running' and job.attempts == 1
            old_token = job.lease_token
            lane = db.get(ExecutionWorkerRecord, job.worker_id)
            assert lane.process_id == claimed['epoch']

        first.kill()  # This test's own child only; crash leaves stale Redis evidence.
        first.communicate(timeout=5)
        assert first.returncode != 0
        # Diagnostic current behavior: only the worker-local CLI can reject
        # the dead PID immediately. The remote API sees the unexpired lease.
        assert http.get(url + '/ready').status_code == 200
        expiry_deadline = time.monotonic() + WORKER_HEALTH_SECONDS + 5
        while time.monotonic() < expiry_deadline:
            if http.get(url + '/ready').status_code == 503:
                break
            time.sleep(.2)
        else:
            raise AssertionError('Dead worker still marked API ready after heartbeat expiry')
        second = start('recover')
        second_events = _events_until(second, {'ready', 'finished'})
        ready2, finished = second_events['ready'], second_events['finished']
        assert ready2['epoch'] == finished['epoch'] != claimed['epoch']
        assert all(claimed['epoch'] not in member for member in client.zrange(health_key, 0, -1))
        assert ready2['epoch'] in client.hvals(owner_key)
        assert http.get(url + '/ready').status_code == 200
        assert not DurableQueue(replicas[0]).finish(job_id, old_token, {'verdict':'accepted'})
        with replicas[0]() as db:
            job = db.get(ExecutionJob, job_id)
            assert job.status == 'completed' and job.attempts == 2
            assert job.result['value']['stdout'] == '42'
            assert db.get(WorkerProcessRecord, claimed['epoch']).stopped_at is None
            assert db.get(WorkerProcessRecord, ready2['epoch']).stopped_at is None

        second.terminate()  # Graceful SIGTERM should revoke readiness and drain.
        second.communicate(timeout=15)
        assert second.returncode == 0
        assert not client.zrange(health_key, 0, -1)
        assert all(value != ready2['epoch'] for value in client.hvals(owner_key))
        assert http.get(url + '/ready').status_code == 503
        with replicas[0]() as db:
            owner = db.get(WorkerProcessRecord, ready2['epoch'])
            assert owner.draining_at is not None and owner.stopped_at is not None
    finally:
        if 'http' in locals():
            http.close()
        for child in children:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=5)
        client.close()
