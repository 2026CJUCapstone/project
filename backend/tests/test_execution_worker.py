import asyncio
from copy import deepcopy
import hashlib
import json
import math
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from docker.errors import ImageNotFound, NotFound
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.services.durable_queue import DurableQueue
from app.services.execution_worker import ExecutionWorker, SandboxPool


@pytest.mark.asyncio
async def test_missing_historical_toolchain_skips_old_receipt_but_runs_current(tmp_path,queue,monkeypatch):
    from app.core.config import settings
    from app.models.database import ExecutionJob
    from tests.test_measured_judge import payload_fixture, registry_fixture

    current=payload_fixture()
    historical=deepcopy(current)
    historical['judge_contract']['profile']['toolchainProfile']='cpython-removed-v0'
    current_entry=registry_fixture(current)['runtimes'][0] | {'admitNew':True}
    old_entry=current_entry | {'toolchainProfile':'cpython-removed-v0','admitNew':False}
    registry_file=tmp_path/'runtime-registry.json'
    registry_file.write_text(json.dumps({'version':2,'runtimes':[old_entry,current_entry]}),encoding='utf-8')
    monkeypatch.setattr(settings,'JUDGE_RUNTIME_REGISTRY',str(registry_file))
    monkeypatch.setattr(settings,'JUDGE_WORKER_CLASS','unit')
    old_id=queue.enqueue(owner_key='test',request_id='old',kind='practice',payload=historical)
    new_id=queue.enqueue(owner_key='test',request_id='new',kind='practice',payload=current)
    observed=[]
    async def fake_judge(runner,received,**kwargs):
        observed.append(runner.measured_submission(received).toolchain.profile)
        return {'verdict':'accepted'}
    monkeypatch.setattr('app.services.execution_worker.judge_code',fake_judge)
    pool=SimpleNamespace(labels=lambda *args:{},reap=lambda *args:None)
    assert await ExecutionWorker(queue,pool=pool).run_once()
    with queue.sessions() as db:
        old=db.get(ExecutionJob,old_id)
        assert old.status=='queued' and old.attempts==0 and old.lease_token is None
        assert db.get(ExecutionJob,new_id).status=='completed'
    assert observed==[current_entry['toolchainProfile']]


def test_image_preflight_accepts_only_exact_local_id_and_same_daemon():
    present='sha256:'+'1'*64
    wrong='sha256:'+'2'*64
    missing='sha256:'+'3'*64
    seen=[]
    closed=[]
    daemon=['fixture-engine']
    def get(digest):
        seen.append(digest)
        if digest==missing:
            raise NotFound('not installed')
        return SimpleNamespace(id=present)
    client=SimpleNamespace(info=lambda:{'ID':daemon[0]},images=SimpleNamespace(get=get),
        close=lambda:closed.append(True))
    pool=SandboxPool(lambda:client,pool_id='fixture')
    assert pool.available_images([present,wrong,missing],daemon_id='fixture-engine')=={present}
    assert seen==[present,wrong,missing] and closed==[True]
    daemon[0]='different-engine'
    with pytest.raises(RuntimeError,match='daemon changed'):
        pool.available_images([present],daemon_id='fixture-engine')
    assert closed==[True,True]


def test_image_preflight_aborts_on_daemon_flip_or_api_error():
    digest='sha256:'+'1'*64
    closed=[]
    calls=[]
    def info():
        calls.append(True)
        return {'ID':'fixture-engine' if len(calls)==1 else 'other-engine'}
    client=SimpleNamespace(info=info,images=SimpleNamespace(get=lambda _:SimpleNamespace(id=digest)),
        close=lambda:closed.append(True))
    with pytest.raises(RuntimeError,match='during image inspection'):
        SandboxPool(lambda:client,pool_id='fixture').available_images([digest],daemon_id='fixture-engine')
    assert closed==[True]
    failed=SimpleNamespace(info=lambda:{'ID':'fixture-engine'},
        images=SimpleNamespace(get=Mock(side_effect=RuntimeError('image API unavailable'))),
        close=lambda:closed.append(True))
    with pytest.raises(RuntimeError,match='image API unavailable'):
        SandboxPool(lambda:failed,pool_id='fixture').available_images([digest],daemon_id='fixture-engine')
    assert closed==[True,True]


def test_worker_rejects_measured_class_budget_mismatch(queue,monkeypatch):
    from app.core.config import settings
    from app.services.execution_resources import ResourceBudget
    monkeypatch.setattr(settings,'JUDGE_WORKER_CLASS','measured-unit')
    budget=ResourceBudget(256*1024**2,2000,64*1024**2,1000,worker_class='other-lane')
    with pytest.raises(ValueError,match='Worker class'):
        ExecutionWorker(DurableQueue(queue.sessions,resource_budget=budget),
            pool=SimpleNamespace(labels=lambda *args:{},reap=lambda *args:None))


@pytest.mark.asyncio
async def test_missing_registered_image_remains_queued_before_claim(tmp_path, queue, monkeypatch):
    from app.core.config import settings
    from app.models.database import ExecutionJob
    from app.services.compiler import DockerCompilerRunner
    from tests.test_measured_judge import payload_fixture, registry_fixture

    payload=payload_fixture()
    registry_file=tmp_path/'runtime-registry.json'
    registry_file.write_text(json.dumps(registry_fixture(payload)),encoding='utf-8')
    monkeypatch.setattr(settings,'JUDGE_RUNTIME_REGISTRY',str(registry_file))
    monkeypatch.setattr(settings,'JUDGE_WORKER_CLASS','unit')
    old_id=queue.enqueue(owner_key='test',request_id='measured',kind='practice',payload=payload)
    new_id=queue.enqueue(owner_key='test',request_id='ordinary',kind='run',
        payload={'code':'print(1)','language':'python'})
    available=set()
    probes=[]
    class ProbePool(SandboxPool):
        def __init__(self): super().__init__(lambda:None,pool_id=settings.SANDBOX_POOL_ID)
        def daemon_identity(self): return 'fixture-engine'
        def available_images(self,digests,*,daemon_id):
            assert daemon_id=='fixture-engine'
            probes.append(set(digests))
            return available & set(digests)
        def reap_claim(self,*args,**kwargs): pass
        def confirm_claim_absent(self,*args,**kwargs): pass
    class OrdinaryRunner:
        def __init__(self,**kwargs): pass
        async def run(self,**kwargs):
            return {'stdout':'1','stderr':'','exit_code':0,'execution_time':1}
    pool=ProbePool()
    assert await ExecutionWorker(queue,pool=pool,runner_factory=OrdinaryRunner).run_once()
    with queue.sessions() as db:
        old=db.get(ExecutionJob,old_id)
        assert old.status=='queued' and old.attempts==0 and old.lease_token is None
        assert db.get(ExecutionJob,new_id).status=='completed'
    assert probes==[{payload['judge_contract']['profile']['imageDigest']}]

    available.add(payload['judge_contract']['profile']['imageDigest'])
    observed=[]
    async def fake_judge(runner,received,**kwargs):
        assert isinstance(runner,DockerCompilerRunner)
        session=runner.measured_submission(received)
        observed.append(session.entry.image_digest)
        return {'verdict':'accepted'}
    monkeypatch.setattr('app.services.execution_worker.judge_code',fake_judge)
    worker=ExecutionWorker(queue,pool=pool)
    monkeypatch.setattr(settings,'JUDGE_WORKER_CLASS','changed-after-worker-start')
    assert await worker.run_once()
    with queue.sessions() as db:
        old=db.get(ExecutionJob,old_id)
        assert old.status=='completed' and old.attempts==1
    assert observed==[payload['judge_contract']['profile']['imageDigest']]


@pytest.mark.asyncio
async def test_unavailable_historical_launcher_stays_queued_then_replays(tmp_path, queue, monkeypatch):
    from app.core.config import settings
    from app.models.database import ExecutionJob
    from app.services import judge_runtime_registry as runtime_registry
    from app.services.compiler import DockerCompilerRunner
    from app.services.measured_judge import MeasuredSubmission
    from tests.test_measured_judge import payload_fixture, registry_fixture

    payload=payload_fixture()
    old_source=runtime_registry.LAUNCHER_PATH.read_bytes()
    old_digest='sha256:'+hashlib.sha256(old_source).hexdigest()
    assert payload['judge_contract']['profile']['launcherDigest']==old_digest
    record=registry_fixture(payload)['runtimes'][0] | {'admitNew':False}
    registry_file=tmp_path/'runtime-registry.json'
    registry_file.write_text(json.dumps({'version':2,'runtimes':[record]}),encoding='utf-8')
    active=tmp_path/'new-launcher.py';active.write_bytes(b"print('new supervisor')\n")
    archive=tmp_path/'archive'
    monkeypatch.setattr(runtime_registry,'LAUNCHER_PATH',active)
    monkeypatch.setattr(runtime_registry,'LAUNCHER_ARCHIVE_DIR',archive)
    monkeypatch.setattr(settings,'JUDGE_RUNTIME_REGISTRY',str(registry_file))
    monkeypatch.setattr(settings,'JUDGE_WORKER_CLASS','unit')
    old_id=queue.enqueue(owner_key='test',request_id='old',kind='practice',payload=payload)
    new_id=queue.enqueue(owner_key='test',request_id='new',kind='run',
        payload={'code':'print(1)','language':'python'})
    pool=SimpleNamespace(labels=lambda *args:{},reap=lambda *args:None)
    class OrdinaryRunner:
        def __init__(self,**kwargs): pass
        async def run(self,**kwargs):
            return {'stdout':'1','stderr':'','exit_code':0,'execution_time':1}
    assert await ExecutionWorker(queue,pool=pool,runner_factory=OrdinaryRunner).run_once()
    with queue.sessions() as db:
        old=db.get(ExecutionJob,old_id)
        assert old.status=='queued' and old.attempts==0 and old.lease_token is None
        assert db.get(ExecutionJob,new_id).status=='completed'

    archive.mkdir()
    (archive/('sha256-'+old_digest[7:]+'.py')).write_bytes(old_source)
    observed=[]
    async def fake_judge(runner,received,**kwargs):
        assert isinstance(runner,DockerCompilerRunner)
        session=MeasuredSubmission(runner,received,None,'unit',snapshot=runner.measured_snapshot)
        observed.append(session.launcher_script)
        return {'verdict':'accepted'}
    monkeypatch.setattr('app.services.execution_worker.judge_code',fake_judge)
    assert await ExecutionWorker(queue,pool=pool).run_once()
    with queue.sessions() as db:
        old=db.get(ExecutionJob,old_id)
        assert old.status=='completed' and old.attempts==1
    assert observed==[old_source.decode('utf-8')]


@pytest.fixture
def queue(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'worker.db').as_posix()}", connect_args={'check_same_thread':False})
    Base.metadata.create_all(engine)
    yield DurableQueue(sessionmaker(bind=engine), lease_seconds=1)
    engine.dispose()


def submit(queue):
    return queue.enqueue(owner_key='test', request_id='request', kind='run', payload={'code':'print(42)', 'language':'python'})


def install_measured_fixture_registry(tmp_path, monkeypatch, payload):
    from app.core.config import settings
    from tests.test_measured_judge import registry_fixture
    path=tmp_path/'measured-fixture-registry.json'
    path.write_text(json.dumps(registry_fixture(payload)),encoding='utf-8')
    monkeypatch.setattr(settings,'JUDGE_RUNTIME_REGISTRY',str(path))
    monkeypatch.setattr(settings,'JUDGE_WORKER_CLASS','unit')


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
async def test_definitive_missing_image_settles_create_and_removes_workdir(queue,tmp_path,monkeypatch):
    from app.core.config import settings
    from app.models.database import ExecutionJob

    sandbox=tmp_path/'missing-image-sandbox'
    sandbox.mkdir()
    monkeypatch.setattr(settings,'SANDBOX_WORKDIR_ROOT',str(sandbox))
    monkeypatch.setattr(settings,'SANDBOX_IMAGE','sha256:'+'f'*64)
    monkeypatch.setattr(settings,'SANDBOX_POOL_ID','missing-image-test')
    queue.max_attempts=1
    job_id=submit(queue)

    class Containers:
        @staticmethod
        def create(**_kwargs):
            raise ImageNotFound('authoritative fixture response')

        @staticmethod
        def list(*_args,**_kwargs):
            return []

    class Client:
        containers=Containers()

        @staticmethod
        def info():
            return {'ID':'fixture-daemon'}

        @staticmethod
        def close():
            pass

    client=Client()
    pool=SandboxPool(lambda:client,pool_id='missing-image-test')
    worker=ExecutionWorker(queue,pool=pool)
    assert await worker.run_once()
    with queue.sessions() as db:
        job=db.get(ExecutionJob,job_id)
        assert job.status=='completed' and job.result['verdict']=='system_error'
        assert job.sandbox_operation is None
    assert list(sandbox.iterdir())==[]


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
async def test_durable_worker_releases_resources_across_tle_mle_and_acceptance(queue):
    from app.core.config import settings
    from app.models.database import ExecutionJob
    from app.services.execution_resources import ResourceBudget

    mib = 1024**2
    legacy_memory = settings.SANDBOX_MEMORY_MB * mib
    legacy_cpu = math.ceil(settings.SANDBOX_CPU_LIMIT * 1000)
    overhead = 16*mib
    one_job = ResourceBudget(
        memory_bytes=legacy_memory + overhead,
        cpu_millis=legacy_cpu,
        legacy_memory_bytes=legacy_memory,
        legacy_cpu_millis=legacy_cpu,
        overhead_bytes=overhead,
        worker_class=settings.JUDGE_WORKER_CLASS,
    )
    durable = DurableQueue(queue.sessions, concurrency=1, resource_budget=one_job)
    jobs = {}
    for code in ('tle', 'mle', 'accepted'):
        jobs[code] = durable.enqueue(
            owner_key='test',
            request_id=f'v19-{code}',
            kind='run',
            payload={
                'code': code,
                'language': 'python',
            },
        )

    events = []

    class Pool:
        def labels(self, *_args):
            return {}

        def reap(self, job_id, token):
            with durable.sessions() as db:
                job = db.get(ExecutionJob, job_id)
                assert job.status == 'running'
                assert job.lease_token == token
                assert job.resource_reservation is not None
            events.append(('reap', job_id))

    class Runner:
        def __init__(self, **_kwargs):
            pass

        async def _execute(self, **_kwargs):
            return {'success': True, 'exit_code': 0, 'execution_phase': 'compile'}

        async def run(self, *, source_code, **_kwargs):
            result = {
                'stdout': '42',
                'stderr': '',
                'exit_code': 0,
                'execution_phase': 'run',
            }
            if source_code == 'tle':
                result.update(exit_code=1, failure_reason='time_limit_exceeded')
            elif source_code == 'mle':
                result.update(exit_code=137, failure_reason='memory_limit_exceeded')
            events.append(('run', jobs[source_code]))
            return result

    claim = durable.claim
    def track_claim(*args, **kwargs):
        result = claim(*args, **kwargs)
        if result is not None:
            events.append(('claim', result.id))
        return result
    durable.claim = track_claim

    finish = durable.finish
    def track_finish(job_id, token, result, **kwargs):
        completed = finish(job_id, token, result, **kwargs)
        if completed:
            events.append(('finish', job_id))
        return completed
    durable.finish = track_finish

    worker = ExecutionWorker(durable, pool=Pool(), runner_factory=Runner)
    for code, verdict in (
        ('tle', 'time_limit_exceeded'),
        ('mle', 'memory_limit_exceeded'),
        ('accepted', 'finished'),
    ):
        assert await worker.run_once()
        result = durable.read(jobs[code], owner_key='test')
        assert result['status'] == 'completed'
        assert result['result']['verdict'] == verdict
        with durable.sessions() as db:
            completed = db.get(ExecutionJob, jobs[code])
            assert completed.resource_reservation['memoryBytes'] == legacy_memory + overhead
            assert db.query(ExecutionJob).filter_by(status='running').count() == 0

    expected_events = []
    for code in ('tle', 'mle', 'accepted'):
        job_id = jobs[code]
        expected_events.extend((
            ('claim', job_id),
            ('run', job_id),
            ('reap', job_id),
            ('finish', job_id),
        ))
    assert events == expected_events
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


@pytest.mark.asyncio
async def test_measured_job_uses_frozen_deadline_but_watchdog_is_not_participant_tle(queue,tmp_path,monkeypatch):
    from unittest.mock import AsyncMock
    from tests.test_measured_judge import payload_fixture
    payload=payload_fixture()
    install_measured_fixture_registry(tmp_path,monkeypatch,payload)
    queue.max_attempts=1  # Inspect the terminal system error, not the retry state.
    job_id=queue.enqueue(owner_key='test',request_id='measured',kind='practice',payload=payload)
    pool=SimpleNamespace(labels=lambda *args:{},reap=lambda *args:None)
    worker=ExecutionWorker(queue,pool=pool)
    worker._execute=AsyncMock(side_effect=TimeoutError('RPC did not return'))
    actual_wait=asyncio.wait_for;deadlines=[]
    async def wait(awaitable,timeout):
        deadlines.append(timeout)
        return await actual_wait(awaitable,timeout)
    monkeypatch.setattr(asyncio,'wait_for',wait)
    assert await worker.run_once()
    assert deadlines==[7]
    assert queue.read(job_id,owner_key='test')['result']['verdict']=='system_error'


@pytest.mark.asyncio
async def test_invalid_measured_deadline_does_not_execute_or_fall_back(queue,tmp_path,monkeypatch):
    from unittest.mock import AsyncMock
    from tests.test_measured_judge import payload_fixture
    queue.max_attempts=1
    payload=payload_fixture();payload['judge_contract']['jobDeadlineMs']=True
    install_measured_fixture_registry(tmp_path,monkeypatch,payload)
    job_id=queue.enqueue(owner_key='test',request_id='invalid-measured',kind='practice',payload=payload)
    worker=ExecutionWorker(queue,pool=SimpleNamespace(labels=lambda *args:{},reap=lambda *args:None))
    worker._execute=AsyncMock()
    assert await worker.run_once()
    worker._execute.assert_not_called()
    assert queue.read(job_id,owner_key='test')['result']['verdict']=='system_error'


@pytest.mark.asyncio
async def test_measured_retry_uses_receipt_deadline_after_live_ceiling_decreases(queue,tmp_path,monkeypatch):
    from unittest.mock import AsyncMock
    from app.core.config import settings
    from tests.test_measured_judge import payload_fixture
    payload=payload_fixture()  # Receipt was frozen with a 7-second deadline.
    install_measured_fixture_registry(tmp_path,monkeypatch,payload)
    queue.max_attempts=1
    job_id=queue.enqueue(owner_key='test',request_id='frozen-after-config-change',kind='practice',payload=payload)
    monkeypatch.setattr(settings,'EXECUTION_JOB_TIMEOUT_SECONDS',6)
    worker=ExecutionWorker(queue,pool=SimpleNamespace(labels=lambda *args:{},reap=lambda *args:None))
    worker._execute=AsyncMock(side_effect=TimeoutError('test RPC failure after admission'))
    actual_wait=asyncio.wait_for;deadlines=[]
    async def wait(awaitable,timeout):
        deadlines.append(timeout)
        return await actual_wait(awaitable,timeout)
    monkeypatch.setattr(asyncio,'wait_for',wait)
    assert await worker.run_once()
    worker._execute.assert_awaited_once()
    assert deadlines==[7]
    assert queue.read(job_id,owner_key='test')['result']['verdict']=='system_error'


@pytest.mark.asyncio
async def test_unexpected_failure_logs_only_bounded_exception_types(queue,caplog):
    secret='participant-source-or-hidden-input-must-not-be-logged'
    queue.max_attempts=1
    cause=PermissionError(secret)
    failure=RuntimeError(secret)
    failure.__cause__=cause
    job_id=submit(queue)
    pool=SimpleNamespace(labels=lambda *args:{},reap=lambda *args:None)
    worker=ExecutionWorker(queue,pool=pool)

    async def fail(_claim):
        raise failure

    worker._execute=fail
    with caplog.at_level('WARNING',logger='app.services.execution_worker'):
        assert await worker.run_once()
    assert queue.read(job_id,owner_key='test')['result']['verdict']=='system_error'
    assert 'RuntimeError <- PermissionError' in caplog.text
    assert secret not in caplog.text
