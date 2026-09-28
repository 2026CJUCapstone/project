"""Fail-closed recovery for graded receipts created before judge contracts."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import app
from app.models import database as m
from app.models.legacy_execution import LegacyExecutionResolutionWrite
from app.services.durable_queue import DurableQueue, execution_payload_hash
from app.services.execution_worker import ExecutionWorker
from app.services.execution_results import publish_result
from app.services.judge_policy import content_hash, freeze_stored_submission
from app.services import legacy_execution_resolution as resolution
from tests.test_contests import env, headers
from tests.test_judge_metrics import full_report
from tests.test_measured_judge import payload_fixture, registry_fixture


def install_registry(tmp_path, monkeypatch, payload):
    path = tmp_path / 'legacy-execution-registry.json'
    path.write_text(json.dumps(registry_fixture(payload)), encoding='utf-8')
    monkeypatch.setattr(settings, 'JUDGE_RUNTIME_REGISTRY', str(path))
    monkeypatch.setattr(settings, 'JUDGE_WORKER_CLASS', 'unit')
    return path


def enqueue_contractless(env, *, request_id='legacy-job', kind='practice'):
    complete = payload_fixture()
    contract = complete.pop('judge_contract')
    queue = DurableQueue(env.factory)
    job_id = queue.enqueue(owner_key='legacy-owner', request_id=request_id,
        kind=kind, payload=complete)
    return queue, job_id, complete, contract


def write_body(job, contract, *, request_id='resolve-1', note='Verified archive receipt evidence'):
    return {
        'requestId': request_id,
        'expectedPayloadHash': job.payload_hash,
        'judgeContract': contract,
        'verdictSchemaVersion': 'measured-v1',
        'note': note,
    }


@pytest.mark.asyncio
async def test_admin_resolution_is_exact_idempotent_and_redacted(env, tmp_path, monkeypatch):
    _queue, job_id, payload, contract = enqueue_contractless(env)
    install_registry(tmp_path, monkeypatch, {**payload, 'judge_contract': contract})
    with env.factory() as db:
        job = db.get(m.ExecutionJob, job_id)
        body = write_body(job, contract)

    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        unauthenticated = await client.post(
            f'/api/v1/admin/execution-jobs/{job_id}/legacy-resolution', json=body)
        assert unauthenticated.status_code == 401
        forbidden = await client.post(
            f'/api/v1/admin/execution-jobs/{job_id}/legacy-resolution',
            headers=headers(env.alice), json=body)
        assert forbidden.status_code == 403

        created = await client.post(
            f'/api/v1/admin/execution-jobs/{job_id}/legacy-resolution',
            headers=headers(env.admin), json=body)
        assert created.status_code == 200, created.text
        assert created.headers['cache-control'] == 'no-store'
        projection = created.json()
        assert projection['executionJobId'] == job_id
        assert projection['payloadHash'] == body['expectedPayloadHash']
        assert projection['judgeContractHash'] == content_hash(contract)
        assert projection['verdictSchemaVersion'] == 'measured-v1'
        assert 'judgeContract' not in projection and 'code' not in created.text
        assert payload['code'] not in created.text

        duplicate = await client.post(
            f'/api/v1/admin/execution-jobs/{job_id}/legacy-resolution',
            headers=headers(env.admin), json=body)
        assert duplicate.status_code == 200
        assert duplicate.json() == projection

        conflict = await client.post(
            f'/api/v1/admin/execution-jobs/{job_id}/legacy-resolution',
            headers=headers(env.admin), json={**body, 'note': 'Different verified evidence note'})
        assert conflict.status_code == 409

        fetched = await client.get(
            f'/api/v1/admin/execution-jobs/{job_id}/legacy-resolution',
            headers=headers(env.admin))
        assert fetched.status_code == 200 and fetched.json() == projection
        assert fetched.headers['cache-control'] == 'no-store'

    with env.factory() as db:
        assert db.query(m.LegacyExecutionResolution).count() == 1
        job = db.get(m.ExecutionJob, job_id)
        assert job.payload == payload and 'judge_contract' not in job.payload


@pytest.mark.asyncio
async def test_resolution_rejects_guesses_mutated_jobs_and_blank_notes(env, tmp_path, monkeypatch):
    _queue, job_id, payload, contract = enqueue_contractless(env)
    install_registry(tmp_path, monkeypatch, {**payload, 'judge_contract': contract})
    with env.factory() as db:
        body = write_body(db.get(m.ExecutionJob, job_id), contract)

    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        url = f'/api/v1/admin/execution-jobs/{job_id}/legacy-resolution'
        wrong_hash = await client.post(url, headers=headers(env.admin),
            json={**body, 'requestId': 'wrong-hash', 'expectedPayloadHash': '0' * 64})
        assert wrong_hash.status_code == 409

        blank_note = await client.post(url, headers=headers(env.admin),
            json={**body, 'requestId': 'blank-note', 'note': '            '})
        assert blank_note.status_code == 422

        bad_contract = deepcopy(contract)
        bad_contract['testSuiteHash'] = 'sha256:' + '9' * 64
        mismatch = await client.post(url, headers=headers(env.admin),
            json={**body, 'requestId': 'bad-contract', 'judgeContract': bad_contract})
        assert mismatch.status_code == 409

    with env.factory() as db:
        assert db.query(m.LegacyExecutionResolution).count() == 0
        job = db.get(m.ExecutionJob, job_id)
        job.attempts = 1
        db.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        attempted = await client.post(
            f'/api/v1/admin/execution-jobs/{job_id}/legacy-resolution',
            headers=headers(env.admin), json={**body, 'requestId': 'attempted'})
        assert attempted.status_code == 409


@pytest.mark.asyncio
async def test_unresolved_legacy_job_is_skipped_without_attempt(env, tmp_path, monkeypatch):
    queue, old_id, _payload, _contract = enqueue_contractless(env)
    new_id = queue.enqueue(owner_key='new-owner', request_id='ordinary-run', kind='run',
        payload={'code': 'print(1)', 'language': 'python'})
    calls = []

    class Runner:
        def __init__(self, **_kwargs):
            pass

        async def run(self, **_kwargs):
            calls.append('run')
            return {'stdout': '1', 'stderr': '', 'exit_code': 0, 'execution_time': 1}

    pool = SimpleNamespace(labels=lambda *_args: {}, reap=lambda *_args: None)
    assert await ExecutionWorker(queue, pool=pool, runner_factory=Runner).run_once()
    with env.factory() as db:
        old = db.get(m.ExecutionJob, old_id)
        assert old.status == 'queued' and old.attempts == 0 and old.started_at is None
        assert old.lease_token is None and old.resource_reservation is None
        assert db.get(m.ExecutionJob, new_id).status == 'completed'
    assert calls == ['run']


@pytest.mark.asyncio
async def test_exact_resolution_replays_without_mutating_durable_payload(env, tmp_path, monkeypatch):
    _queue, job_id, payload, contract = enqueue_contractless(env)
    queue = DurableQueue(env.factory, on_terminal=publish_result)
    install_registry(tmp_path, monkeypatch, {**payload, 'judge_contract': contract})
    with env.factory() as db:
        job = db.get(m.ExecutionJob, job_id)
        original_hash = job.payload_hash
        resolution.append(db, job_id, LegacyExecutionResolutionWrite(
            requestId='replay-1', expectedPayloadHash=original_hash,
            judgeContract=contract, verdictSchemaVersion='measured-v1',
            note='Verified exact historical archive receipt'), env.admin)

    observed = []

    async def fake_judge(runner, received, **_kwargs):
        assert received['judge_contract'] == contract
        assert runner.measured_snapshot.registration.image_digest == \
            contract['profile']['imageDigest']
        with env.factory() as db:
            durable = db.get(m.ExecutionJob, job_id)
            assert durable.payload == payload
            assert durable.payload_hash == original_hash
        observed.append(True)
        return {'verdict': 'accepted', 'status': 'Accepted',
            'sample_total_cases': 1, 'sample_passed_cases': 1,
            'grading_completed': True, 'grading_passed': True, 'details': [],
            '_resource_report': full_report(received)}

    monkeypatch.setattr('app.services.execution_worker.judge_code', fake_judge)
    pool = SimpleNamespace(labels=lambda *_args: {}, reap=lambda *_args: None)
    assert await ExecutionWorker(queue, pool=pool).run_once()
    with env.factory() as db:
        job = db.get(m.ExecutionJob, job_id)
        assert job.status == 'completed' and job.attempts == 1
        assert job.payload == payload and job.payload_hash == original_hash
        assert job.result['verdict'] == 'accepted'
        assert job.result['value']['resource_usage']['measurement'] == 'cgroup-v2-whole-phase'
    assert observed == [True]


@pytest.mark.asyncio
async def test_tampered_resolution_or_unavailable_runtime_never_claims(env, tmp_path, monkeypatch):
    queue, first_id, payload, contract = enqueue_contractless(env, request_id='legacy-first')
    registry_path = install_registry(tmp_path, monkeypatch, {**payload, 'judge_contract': contract})
    with env.factory() as db:
        first = db.get(m.ExecutionJob, first_id)
        resolution.append(db, first_id, LegacyExecutionResolutionWrite(
            requestId='resolve-first', expectedPayloadHash=first.payload_hash,
            judgeContract=contract, verdictSchemaVersion='measured-v1',
            note='Verified exact historical archive receipt'), env.admin)
        row = db.query(m.LegacyExecutionResolution).filter_by(execution_job_id=first_id).one()
        row.judge_contract_hash = 'sha256:' + '0' * 64
        db.commit()

    assert not await ExecutionWorker(queue,
        pool=SimpleNamespace(labels=lambda *_args: {}, reap=lambda *_args: None)).run_once()
    with env.factory() as db:
        first = db.get(m.ExecutionJob, first_id)
        assert first.status == 'queued' and first.attempts == 0

    _queue, second_id, second_payload, second_contract = enqueue_contractless(
        env, request_id='legacy-second')
    with env.factory() as db:
        second = db.get(m.ExecutionJob, second_id)
        resolution.append(db, second_id, LegacyExecutionResolutionWrite(
            requestId='resolve-second', expectedPayloadHash=second.payload_hash,
            judgeContract=second_contract, verdictSchemaVersion='measured-v1',
            note='Verified second historical archive receipt'), env.admin)
    raw = registry_fixture({**second_payload, 'judge_contract': second_contract})
    raw['runtimes'][0]['runtimeVersion'] = 'different-runtime'
    registry_path.write_text(json.dumps(raw), encoding='utf-8')
    assert not await ExecutionWorker(queue,
        pool=SimpleNamespace(labels=lambda *_args: {}, reap=lambda *_args: None)).run_once()
    with env.factory() as db:
        second = db.get(m.ExecutionJob, second_id)
        assert second.status == 'queued' and second.attempts == 0


@pytest.mark.asyncio
async def test_direct_judging_rejects_contractless_graded_payload():
    from app.services.judging import judge_code

    payload = payload_fixture()
    payload.pop('judge_contract')
    with pytest.raises(RuntimeError, match='exact measured judge contract'):
        await judge_code(SimpleNamespace(), payload)

    sample = payload['sample']
    hidden = payload['hidden']
    payload['judge_contract'] = freeze_stored_submission(
        None, payload['language'], sample, hidden, settings=settings)
    with pytest.raises(RuntimeError, match='exact measured judge contract'):
        await judge_code(SimpleNamespace(), payload)


@pytest.mark.asyncio
async def test_legacy_v1_job_also_requires_exact_resolution(env, tmp_path, monkeypatch):
    measured = payload_fixture()
    contract = measured.pop('judge_contract')
    measured['judge_contract'] = freeze_stored_submission(
        None, measured['language'], measured['sample'], measured['hidden'], settings=settings)
    queue = DurableQueue(env.factory, on_terminal=publish_result)
    job_id = queue.enqueue(owner_key='legacy-v1-owner', request_id='legacy-v1-job',
        kind='practice', payload=measured)
    install_registry(tmp_path, monkeypatch, {**measured, 'judge_contract': contract})

    pool = SimpleNamespace(labels=lambda *_args: {}, reap=lambda *_args: None)
    assert not await ExecutionWorker(queue, pool=pool).run_once()
    with env.factory() as db:
        job = db.get(m.ExecutionJob, job_id)
        assert job.status == 'queued' and job.attempts == 0
        resolution.append(db, job_id, LegacyExecutionResolutionWrite(
            requestId='legacy-v1-resolution', expectedPayloadHash=job.payload_hash,
            judgeContract=contract, verdictSchemaVersion='measured-v1',
            note='Verified exact historical archive receipt'), env.admin)

    async def accepted(_runner, received, **_kwargs):
        assert received['judge_contract'] == contract
        return {'verdict': 'accepted', 'status': 'Accepted',
            'sample_total_cases': 1, 'sample_passed_cases': 1,
            'grading_completed': True, 'grading_passed': True, 'details': [],
            '_resource_report': full_report(received)}

    monkeypatch.setattr('app.services.execution_worker.judge_code', accepted)
    assert await ExecutionWorker(queue, pool=pool).run_once()
    with env.factory() as db:
        job = db.get(m.ExecutionJob, job_id)
        assert job.status == 'completed' and job.attempts == 1
        assert job.payload['judge_contract']['kind'] == 'legacy-v1'
        assert job.result['value']['resource_usage']['measurement'] == 'cgroup-v2-whole-phase'


@pytest.mark.asyncio
async def test_reportless_resolved_acceptance_cannot_publish(env, tmp_path, monkeypatch):
    _queue, job_id, payload, contract = enqueue_contractless(env, request_id='reportless')
    queue = DurableQueue(env.factory, on_terminal=publish_result)
    install_registry(tmp_path, monkeypatch, {**payload, 'judge_contract': contract})
    with env.factory() as db:
        job = db.get(m.ExecutionJob, job_id)
        resolution.append(db, job_id, LegacyExecutionResolutionWrite(
            requestId='reportless-resolution', expectedPayloadHash=job.payload_hash,
            judgeContract=contract, verdictSchemaVersion='measured-v1',
            note='Verified exact historical archive receipt'), env.admin)

    async def accepted_without_report(_runner, _received, **_kwargs):
        return {'verdict': 'accepted'}

    monkeypatch.setattr('app.services.execution_worker.judge_code', accepted_without_report)
    with pytest.raises(ValueError, match='protected resource report'):
        await ExecutionWorker(queue,
            pool=SimpleNamespace(labels=lambda *_args: {}, reap=lambda *_args: None)).run_once()
    with env.factory() as db:
        job = db.get(m.ExecutionJob, job_id)
        assert job.status == 'running' and job.attempts == 1
        assert job.result is None and job.finished_at is None
        assert job.payload == payload and job.payload_hash == execution_payload_hash('practice', payload)[0]


def test_prepare_binding_checks_job_payload_and_contract_hash(env, tmp_path, monkeypatch):
    _queue, job_id, payload, contract = enqueue_contractless(env)
    install_registry(tmp_path, monkeypatch, {**payload, 'judge_contract': contract})
    with env.factory() as db:
        job = db.get(m.ExecutionJob, job_id)
        resolution.append(db, job_id, LegacyExecutionResolutionWrite(
            requestId='prepare-1', expectedPayloadHash=job.payload_hash,
            judgeContract=contract, verdictSchemaVersion='measured-v1',
            note='Verified exact historical archive receipt'), env.admin)
        binding = resolution.load_bindings(db)[job_id]
    from app.services.judge_runtime_registry import RuntimeRegistry
    snapshots = RuntimeRegistry.load(settings.JUDGE_RUNTIME_REGISTRY).replay_snapshots('unit')
    assert resolution.prepare_binding(binding, job_id=job_id, kind='practice',
        payload=payload, snapshots=snapshots, worker_class='unit') is not None
    assert resolution.prepare_binding(binding, job_id='different-job', kind='practice',
        payload=payload, snapshots=snapshots, worker_class='unit') is None
    mutated = {**payload, 'code': 'print(999)'}
    assert execution_payload_hash('practice', mutated)[0] != binding.payload_hash
    assert resolution.prepare_binding(binding, job_id=job_id, kind='practice',
        payload=mutated, snapshots=snapshots, worker_class='unit') is None
    bad_binding = SimpleNamespace(**{
        **binding.__dict__, 'judge_contract_hash': 'sha256:' + 'f' * 64})
    assert resolution.prepare_binding(bad_binding, job_id=job_id, kind='practice',
        payload=payload, snapshots=snapshots, worker_class='unit') is None
