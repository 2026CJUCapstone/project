import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.services.durable_queue import DurableQueue
from app.services.execution_worker import ExecutionWorker, SandboxPool


@pytest.fixture
def queue(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'worker.db').as_posix()}", connect_args={'check_same_thread':False})
    Base.metadata.create_all(engine)
    yield DurableQueue(sessionmaker(bind=engine), lease_seconds=1)
    engine.dispose()


def submit(queue):
    return queue.enqueue(owner_key='test', request_id='request', kind='run', payload={'code':'print(42)', 'language':'python'})


@pytest.mark.asyncio
async def test_unavailable_daemon_still_registers_lane_without_claiming(queue):
    from app.models.database import ExecutionJob
    job_id = submit(queue)
    def unavailable():
        raise RuntimeError('isolated unavailable daemon')
    worker = ExecutionWorker(queue, pool=SandboxPool(client_factory=unavailable))
    with pytest.raises(RuntimeError, match='unavailable daemon'):
        await worker.run_once()
    assert queue.worker_status(worker.identity) == {
        'id': worker.identity.id, 'draining': False, 'active_claims': 0}
    with queue.sessions() as db:
        job = db.get(ExecutionJob, job_id)
        assert job.status == 'queued' and job.attempts == 0 and job.lease_token is None
    worker.begin_drain()
    assert queue.worker_status(worker.identity)['draining'] is True
    # Repeated registration after drain cannot reach even the unavailable probe.
    assert await worker.run_once() is False


@pytest.mark.asyncio
async def test_stop_before_real_pool_probe_records_fence_and_accepts_nothing(queue):
    job_id = submit(queue)
    probe = Mock(side_effect=AssertionError('must not probe after stop'))
    worker = ExecutionWorker(queue, pool=SandboxPool(client_factory=probe))
    stop = asyncio.Event()
    stop.set()
    assert await worker.run_once(stop=stop) is False
    assert queue.worker_status(worker.identity)['draining'] is True
    assert queue.read(job_id, owner_key='test')['status'] == 'queued'
    probe.assert_not_called()


@pytest.mark.asyncio
async def test_restarted_worker_executes_persisted_code_and_reaps_before_completion(queue):
    job_id = submit(queue)
    events = []
    pool = SimpleNamespace(labels=lambda *args: {}, reap=lambda *args: events.append('reap'))

    class Runner:
        def __init__(self, **kwargs): self.guard = kwargs['start_guard']
        async def run(self, **kwargs):
            assert kwargs['source_code'] == 'print(42)'
            assert self.guard(lambda: events.append('start'))
            return {'stdout':'42','stderr':'','exit_code':0,'execution_time':1}

    worker = ExecutionWorker(DurableQueue(queue.sessions), pool=pool, runner_factory=Runner)
    assert await worker.run_once()
    assert events == ['start','reap']
    result = queue.read(job_id, owner_key='test')
    assert result['status'] == 'completed'
    assert result['result']['value']['stdout'] == '42'
    assert not await worker.run_once()


@pytest.mark.asyncio
async def test_failed_heartbeat_cancels_execution_and_never_commits_result(queue, monkeypatch):
    job_id = submit(queue)
    canceled = asyncio.Event()
    reaped = []
    pool = SimpleNamespace(labels=lambda *args: {}, reap=lambda *args: reaped.append(args))

    class Runner:
        def __init__(self, **kwargs): pass
        async def run(self, **kwargs):
            try:
                await asyncio.Event().wait()
            finally:
                canceled.set()

    monkeypatch.setattr(queue, 'renew', lambda *args: False)
    assert await ExecutionWorker(queue, pool=pool, runner_factory=Runner).run_once()
    assert canceled.is_set() and len(reaped) == 1
    assert queue.read(job_id, owner_key='test')['result'] is None


@pytest.mark.asyncio
async def test_unconfirmed_cleanup_does_not_release_capacity(queue):
    job_id = submit(queue)
    pool = SimpleNamespace(labels=lambda *args: {}, reap=Mock(side_effect=RuntimeError('unreachable')))

    class Runner:
        def __init__(self, **kwargs): pass
        async def run(self, **kwargs): return {'stdout':'','stderr':'','exit_code':0,'execution_time':1}

    with pytest.raises(RuntimeError, match='unreachable'):
        await ExecutionWorker(queue, pool=pool, runner_factory=Runner).run_once()
    assert queue.read(job_id, owner_key='test')['status'] == 'running'


def test_reaper_refuses_a_mismatched_container_even_if_docker_filter_returns_it():
    container = Mock(labels={'webcompiler.pool':'unrelated-production'})
    client = SimpleNamespace(containers=Mock())
    client.containers.list.return_value = [container]
    with pytest.raises(RuntimeError, match='ownership mismatch'):
        SandboxPool(lambda:client).reap('a'*32, 'b'*32)
    container.remove.assert_not_called()


def test_reaper_cleans_only_its_claim_directories_after_confirmed_stop(tmp_path, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, 'SANDBOX_WORKDIR_ROOT', str(tmp_path))
    own = tmp_path / ('job-' + 'a'*32 + '-' + 'b'*32 + '-scratch')
    unrelated = tmp_path / 'job-unrelated'
    own.mkdir()
    unrelated.mkdir()
    (own / 'source.py').write_text('test')
    client = SimpleNamespace(containers=Mock())
    client.containers.list.return_value = []
    SandboxPool(lambda:client).reap('a'*32, 'b'*32)
    assert not own.exists()
    assert unrelated.is_dir()


@pytest.mark.asyncio
async def test_total_job_deadline_bounds_many_individually_short_cases(queue, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, 'EXECUTION_JOB_TIMEOUT_SECONDS', 0.05)
    job_id = submit(queue)
    canceled = asyncio.Event()
    pool = SimpleNamespace(labels=lambda *args: {}, reap=lambda *args: None)

    class Runner:
        def __init__(self, **kwargs): pass
        async def run(self, **kwargs):
            try:
                await asyncio.Event().wait()
            finally:
                canceled.set()

    await ExecutionWorker(queue, pool=pool, runner_factory=Runner).run_once()
    assert canceled.is_set()
    result = queue.read(job_id, owner_key='test')
    assert result['status'] == 'completed'
    assert result['result']['verdict'] == 'time_limit_exceeded'
