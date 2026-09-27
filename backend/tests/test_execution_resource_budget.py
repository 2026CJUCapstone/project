"""Resource accounting races, not real cgroup/runtime measurements."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta
from threading import Barrier

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.orm.attributes import flag_modified

from app.initialize import initialize, RUNTIME_SCHEMA_VERSION
from app.models.database import ExecutionJob, ExecutionResourceBudget
from app.services.durable_queue import DurableQueue
from app.services.execution_resources import ResourceBudget
from app.core.config import settings
from app.models.judge_policy import JudgePolicy
from app.services.judge_policy import freeze_stored_submission, resource_fingerprint
from tests.test_durable_queue import replicas
from tests.test_judge_policy import policy_fixture, SAMPLE, HIDDEN

MIB = 1024**2
AT = datetime(2030, 1, 1)


def budget(memory=300, cpu=4000, overhead=16, worker_class='test-cpu'):
    return ResourceBudget(memory*MIB, cpu, 64*MIB, 1000, overhead*MIB, worker_class)


def queue(factory, **kwargs):
    return DurableQueue(factory, concurrency=10, per_owner=30,
        resource_budget=kwargs.pop('resource_budget', budget()), **kwargs)


def contract(memory=128, worker_class='test-cpu'):
    profile = deepcopy(policy_fixture()['profiles']['python'])
    profile['workerClass'] = worker_class
    profile['run']['memoryBytes'] = memory*MIB
    profile['compile']['memoryBytes'] = memory*MIB
    return {'kind':'measured-v1', 'profile':profile, 'reservationBytes':memory*MIB}


def add(q, request, *, limits=None, at=AT):
    return q.enqueue(owner_key='owner', request_id=request, kind='judge', at=at,
        payload={'code':'print(1)', **({'judge_contract':limits} if limits else {})})


def active(factory):
    with factory() as db:
        return [deepcopy(job.resource_reservation) for job in db.query(ExecutionJob).filter_by(status='running')]


@pytest.mark.parametrize('memory,cpu,expected', [(300,4000,2), (1000,2000,2), (1000,4000,4)])
def test_atomic_memory_and_cpu_budget_across_workers(replicas, memory, cpu, expected):
    qs = [queue(factory, resource_budget=budget(memory,cpu)) for factory in replicas]
    for i in range(8):
        add(qs[0], str(i), limits=contract())
    barrier = Barrier(8)
    def claim(i):
        barrier.wait()
        return qs[i%2].claim(at=AT, daemon_id='host-a')
    with ThreadPoolExecutor(8) as pool:
        claims = [c for c in pool.map(claim, range(8)) if c]
    assert len(claims) == len({c.id for c in claims}) == expected
    reservations = active(replicas[0])
    assert sum(r['memoryBytes'] for r in reservations) <= memory*MIB
    assert sum(r['cpuMillis'] for r in reservations) <= cpu


def test_compile_peak_and_outside_overhead_reserved_once():
    receipt = contract(64)
    receipt['profile']['compile']['memoryBytes'] = 128*MIB
    receipt['reservationBytes'] = 128*MIB
    reserved = budget().reservation({'judge_contract':receipt}, 'daemon:a')
    assert reserved['memoryBytes'] == 144*MIB  # max stage + overhead, not sum or tmpfs twice
    assert reserved['cpuMillis'] == 1000
    receipt['reservationBytes'] = 64*MIB
    with pytest.raises(ValueError, match='stage limits'):
        budget().reservation({'judge_contract':receipt}, 'daemon:a')


def test_legacy_receipt_uses_frozen_quota_not_current_defaults():
    reserved = budget().reservation({'judge_contract':{
        'kind':'legacy-v1', 'memoryBytes':90*MIB, 'cpuQuota':0.501}}, 'legacy-global')
    assert reserved == dict(version=1, scope='legacy-global', memoryBytes=106*MIB, cpuMillis=501, workerClass=None)


def test_admission_memory_uses_host_budget_minus_overhead(monkeypatch,tmp_path):
    from tests.test_judge_policy import install_synthetic_registry
    install_synthetic_registry(tmp_path,monkeypatch)
    monkeypatch.setattr(settings,'EXECUTION_MEMORY_BUDGET_MB',544)
    monkeypatch.setattr(settings,'EXECUTION_JOB_OVERHEAD_MB',32)
    monkeypatch.setattr(settings,'SANDBOX_MEMORY_MB',64)
    raw = policy_fixture()
    raw['profiles']['python']['run']['memoryBytes'] = 512*MIB
    parsed = JudgePolicy.model_validate(raw)
    raw['evidence']['python']['resourceFingerprint'] = resource_fingerprint(parsed,'python')
    receipt = freeze_stored_submission(raw,'python',SAMPLE,HIDDEN,settings=settings)
    assert receipt['reservationBytes'] == 512*MIB
    monkeypatch.setattr(settings,'EXECUTION_MEMORY_BUDGET_MB',543)
    with pytest.raises(ValueError,match='memory reservation'):
        freeze_stored_submission(raw,'python',SAMPLE,HIDDEN,settings=settings)
    # Legacy problems keep their old absolute per-container limit.
    assert freeze_stored_submission(None,'python',SAMPLE,HIDDEN,settings=settings)['memoryBytes'] == 64*MIB


def test_measured_admission_rejects_insufficient_cpu_allocation(monkeypatch):
    monkeypatch.setattr(settings,'EXECUTION_CPU_BUDGET_MILLIS',999)
    with pytest.raises(ValueError,match='measured execution lane'):
        freeze_stored_submission(policy_fixture(),'python',SAMPLE,HIDDEN,settings=settings)


@pytest.mark.parametrize('limits', [
    {'kind':'unknown'}, {'kind':'legacy-v1','memoryBytes':True,'cpuQuota':1},
    {'kind':'legacy-v1','memoryBytes':64*MIB,'cpuQuota':True},
    {'kind':'legacy-v1','memoryBytes':64*MIB,'cpuQuota':float('inf')},
])
def test_invalid_receipt_does_not_create_reservation(limits):
    with pytest.raises(ValueError):
        budget().reservation({'judge_contract':limits}, 'legacy-global')


def test_strict_fifo_prevents_small_job_starving_large_job(replicas):
    q = queue(replicas[0], resource_budget=budget(240))
    first = add(q,'first',limits=contract(128))
    assert q.claim(at=AT,daemon_id='host-a').id == first
    large = add(q,'large',limits=contract(128),at=AT+timedelta(seconds=1))
    add(q,'small',limits=contract(32),at=AT+timedelta(seconds=2))
    assert q.claim(at=AT,daemon_id='host-a') is None
    with replicas[0]() as db:
        token = db.get(ExecutionJob,first).lease_token
    assert q.finish(first,token,{'verdict':'accepted'},at=AT)
    assert q.claim(at=AT,daemon_id='host-a').id == large


def test_ineligible_class_skipped_without_assigning_it(replicas):
    q = queue(replicas[0])
    foreign = add(q,'foreign',limits=contract(worker_class='another-host-class'))
    eligible = add(q,'eligible',at=AT+timedelta(seconds=1))
    assert q.claim(at=AT,daemon_id='host-a').id == eligible
    with replicas[0]() as db:
        job = db.get(ExecutionJob,foreign)
        assert job.status == 'queued' and job.resource_reservation is None


def test_unavailable_replay_receipt_is_skipped_without_claim_or_reservation(replicas):
    q=queue(replicas[0])
    historical=add(q,'historical',limits=contract())
    later=add(q,'later',limits=contract(),at=AT+timedelta(seconds=1))
    marker=object()
    def eligible(kind,payload,job_id):
        return False if payload.get('code')=='print(1)' and payload.get('history') else marker
    # Keep the history marker outside the frozen resource contract itself.
    with replicas[0]() as db:
        job=db.get(ExecutionJob,historical)
        job.payload={**job.payload,'history':True}
        db.commit()
    claim=q.claim(at=AT,daemon_id='host-a',eligible=eligible)
    assert claim.id==later and claim.runtime_snapshot is marker
    with replicas[0]() as db:
        old=db.get(ExecutionJob,historical)
        assert old.status=='queued' and old.attempts==0 and old.resource_reservation is None


def test_expired_and_unsettled_claim_remains_charged(replicas):
    q = queue(replicas[0],resource_budget=budget(160),lease_seconds=1)
    first = add(q,'first',limits=contract())
    c = q.claim(at=AT,daemon_id='host-a')
    add(q,'second',limits=contract())
    with replicas[0]() as db:
        db.get(ExecutionJob,first).sandbox_operation = {'id':'unsettled'}
        db.commit()
    assert not q.finish(first,c.token,{'verdict':'accepted'},at=AT)
    assert q.claim(at=AT+timedelta(days=1),daemon_id='host-a') is None
    assert active(replicas[0])[0]['memoryBytes'] == 144*MIB


def test_restart_keeps_reservations_and_expiry_alone_does_not_release(replicas):
    q = queue(replicas[0],resource_budget=budget(160),lease_seconds=1)
    add(q,'first',limits=contract())
    c = q.claim(at=AT,daemon_id='host-a')
    add(q,'second',limits=contract())
    restart = queue(replicas[1],resource_budget=budget(160))
    assert restart.claim(at=AT+timedelta(seconds=2),daemon_id='host-a') is None
    assert not restart.finish(c.id,c.token,{'verdict':'accepted'},at=AT+timedelta(seconds=2))
    assert len(active(replicas[0])) == 1


def test_proven_legacy_cleanup_reclaims_only_one_reservation(replicas):
    q = queue(replicas[0],resource_budget=budget(160),lease_seconds=1)
    add(q,'first',limits=contract())
    first = q.claim(at=AT)
    add(q,'next',limits=contract(),at=AT+timedelta(microseconds=1))
    assert q.claim(at=AT+timedelta(seconds=1)) is None
    cleanup = []
    q.reap_expired = lambda *args: cleanup.append(args)
    new = q.claim(at=AT+timedelta(seconds=1))
    assert new.id == first.id and new.token != first.token
    assert cleanup == [(first.id,first.token)]
    assert len(active(replicas[0])) == 1
    assert not q.finish(first.id,first.token,{},at=AT+timedelta(seconds=1))


def test_daemons_have_independent_budgets_but_global_concurrency_still_applies(replicas):
    q = queue(replicas[0],resource_budget=budget(160))
    q.concurrency = 2
    for i in range(3):
        add(q,str(i),limits=contract())
    assert q.claim(at=AT,daemon_id='host-a')
    assert q.claim(at=AT,daemon_id='host-a') is None
    assert q.claim(at=AT,daemon_id='host-b')
    assert q.claim(at=AT,daemon_id='host-b') is None
    assert q.claim(at=AT,daemon_id='host-c') is None
    assert q.claim(at=AT) is None  # unbound worker accounts every active daemon


def test_unbound_claim_charged_to_every_daemon(replicas):
    q = queue(replicas[0],resource_budget=budget(160))
    add(q,'first',limits=contract())
    assert q.claim(at=AT)
    add(q,'second',limits=contract())
    assert q.claim(at=AT,daemon_id='host-b') is None


def test_unknown_pre_migration_reservation_blocks_without_guessing(replicas):
    old = DurableQueue(replicas[0],concurrency=10)
    add(old,'old')
    claim = old.claim(at=AT,daemon_id='elsewhere')
    q = queue(replicas[1])
    add(q,'new')
    assert q.claim(at=AT,daemon_id='host-a') is None
    assert old.finish(claim.id,claim.token,{},at=AT)
    assert q.claim(at=AT,daemon_id='host-a')


@pytest.mark.parametrize('field,value', [('scope','daemon:wrong'),('scope',None),
    ('memoryBytes',True),('cpuMillis',0),('version',True),('version',2)])
def test_malformed_active_reservation_fails_closed(replicas,field,value):
    q = queue(replicas[0])
    job_id = add(q,'first')
    q.claim(at=AT,daemon_id='host-a')
    add(q,'second')
    with replicas[0]() as db:
        job = db.get(ExecutionJob,job_id)
        job.resource_reservation = {**job.resource_reservation,field:value}
        # Python dict equality considers True == 1; force this corruption
        # fixture to write the distinct JSON boolean into storage.
        flag_modified(job, 'resource_reservation')
        db.commit()
    with pytest.raises(ValueError,match='Invalid active'):
        q.claim(at=AT,daemon_id='host-b')


def test_budget_changes_do_not_silently_increase_capacity(replicas):
    original = queue(replicas[0])
    assert original.claim(at=AT,daemon_id='host-a') is None
    changed = queue(replicas[1],resource_budget=budget(1000))
    with pytest.raises(ValueError,match='configuration mismatch'):
        changed.claim(at=AT,daemon_id='host-a')
    with replicas[0]() as db:
        assert db.get(ExecutionResourceBudget,'daemon:host-a').memory_bytes == 300*MIB


def test_failed_claim_transaction_does_not_leak_reservation(replicas):
    def fail_transition(*_):
        raise RuntimeError('injected claim failure')
    q = queue(replicas[0],on_transition=fail_transition)
    job_id = add(q,'first',limits=contract())
    with pytest.raises(RuntimeError,match='injected'):
        q.claim(at=AT,daemon_id='host-a')
    with replicas[0]() as db:
        job = db.get(ExecutionJob,job_id)
        assert job.status == 'queued' and job.resource_reservation is None
        assert db.get(ExecutionResourceBudget,'daemon:host-a') is None
    q.on_transition = None
    assert q.claim(at=AT,daemon_id='host-a').id == job_id


def test_failed_result_publication_keeps_reservation(replicas):
    def fail_publish(*_):
        raise RuntimeError('injected publication failure')
    q = queue(replicas[0],resource_budget=budget(160),on_terminal=fail_publish)
    job_id = add(q,'first',limits=contract())
    c = q.claim(at=AT,daemon_id='host-a')
    add(q,'next',limits=contract())
    with pytest.raises(RuntimeError,match='injected'):
        q.finish(job_id,c.token,{'verdict':'accepted'},at=AT)
    assert q.claim(at=AT,daemon_id='host-a') is None
    assert len(active(replicas[0])) == 1
    q.on_terminal = None
    assert q.finish(job_id,c.token,{'verdict':'accepted'},at=AT)
    assert not q.finish(job_id,c.token,{'verdict':'accepted'},at=AT)
    assert q.claim(at=AT,daemon_id='host-a')


def test_oversize_job_fails_without_claim_or_resource_leak(replicas):
    q = queue(replicas[0],resource_budget=budget(160))
    job_id = add(q,'large',limits=contract(256))
    with pytest.raises(ValueError,match='cannot fit'):
        q.claim(at=AT,daemon_id='host-a')
    with replicas[0]() as db:
        job = db.get(ExecutionJob,job_id)
        assert job.status == 'queued' and job.attempts == 0 and job.resource_reservation is None
        assert db.get(ExecutionResourceBudget,'daemon:host-a') is None


def test_v13_migration_is_additive_and_preserves_v12_marker(replicas):
    engine = replicas[0].kw['bind']
    initialize(bind=engine)
    q = queue(replicas[0])
    job_id = add(q,'old')
    with engine.begin() as db:
        db.execute(text('ALTER TABLE execution_jobs DROP COLUMN resource_reservation'))
        db.execute(text('DROP TABLE execution_resource_budgets'))
        db.execute(text('DELETE FROM schema_migrations WHERE version=:v'), {'v':RUNTIME_SCHEMA_VERSION})
        db.execute(text('INSERT INTO schema_migrations (version) VALUES (:v)'),{'v':'20260926_judge_policy_v12'})
    initialize(bind=engine)
    assert 'resource_reservation' in {c['name'] for c in inspect(engine).get_columns('execution_jobs')}
    with replicas[0]() as db:
        job = db.get(ExecutionJob,job_id)
        assert job.payload == {'code':'print(1)'} and job.resource_reservation is None
        assert set(db.execute(text('SELECT version FROM schema_migrations WHERE version LIKE :v'),
                              {'v':'%_v%'}).scalars()) == {RUNTIME_SCHEMA_VERSION}
        assert db.execute(text('SELECT 1 FROM runtime_schema_history WHERE version=:v'),
                          {'v':'20260926_judge_policy_v12'}).first()
    c = q.claim(at=AT,daemon_id='host-a')
    before = active(replicas[0])
    initialize(bind=engine)
    assert active(replicas[1]) == before
    assert q.finish(c.id,c.token,{},at=AT)
