"""Admin draft validation is durable, private and has no participant effects."""
from copy import deepcopy
from datetime import timedelta
import hashlib
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.core.config import settings
from app.models import database as m
from app.services import execution_runtime
from app.services.execution_results import publish_result
from app.services.execution_retention import expire_execution_content
from app.services.execution_worker import ExecutionWorker
from app.services import problem_authoring as review
from app.services.judge_policy import content_hash, freeze_stored_submission
from tests.test_contest_package_authoring import package_body
from tests.test_contests import env, headers, payload
from tests.test_judge_metrics import full_report


def _counts(db):
    return {
        model.__tablename__: db.query(model).count()
        for model in (
            m.Submission,
            m.ContestSubmission,
            m.UserProblemScore,
            m.SolveEvidence,
            m.CompileQueueRecord,
        )
    }


async def _saved_draft(client, fixture, *, measured=True):
    source = 'print(42)'
    digest = 'sha256:' + hashlib.sha256(source.encode('utf-8')).hexdigest()
    body = package_body(fixture)
    body['packageId'] = 'validation-' + ('measured' if measured else 'unreviewed')
    body['entries'][0]['metadata']['assets'][0]['digest'] = digest
    if not measured:
        body['entries'][0]['problem'].pop('judgePolicy')
    response = await client.post('/api/v1/contests/packages/import', headers=headers(fixture.admin), json=body)
    assert response.status_code == 200, response.text
    receipt = response.json()
    problem = receipt['problems'][0]
    authoring = await client.get(
        f"/api/v1/problems/{problem['problemId']}/authoring",
        headers=headers(fixture.admin),
    )
    assert authoring.status_code == 200
    return (
        {'id': receipt['contestId']},
        {'id': problem['contestProblemId'], 'problemId': problem['problemId']},
        source,
        digest,
        authoring.json()['fingerprint'],
    )


async def _approve_current(client, fixture, contest_id, problem_id):
    url = f'/api/v1/problems/{problem_id}/authoring'
    auth = headers(fixture.admin)
    current = (await client.get(url, headers=auth)).json()
    metadata = deepcopy(current['metadata'])
    metadata['sources'][0].update(
        reuseBasis='permission',
        reuseEvidence='Synthetic permission fixture only',
    )
    current = (await client.put(url, headers=auth, json={
        'expectedFingerprint': current['fingerprint'],
        'metadata': metadata,
    })).json()
    # Contest validation is deliberately bound to its saved snapshot. Refresh
    # that snapshot after changing authoring metadata, before approving it.
    manage = (await client.get(
        f'/api/v1/contests/{contest_id}/manage', headers=auth
    )).json()
    draft = payload(fixture)
    draft.update(problems=manage['problems'], published=False)
    saved = await client.put(f'/api/v1/contests/{contest_id}', headers=auth, json=draft)
    assert saved.status_code == 200, saved.text
    refreshed = (await client.get(
        f'/api/v1/contests/{contest_id}/manage', headers=auth
    )).json()
    contest_problem_id = next(
        item['contestProblemId'] for item in refreshed['problems'] if item['problemId'] == problem_id
    )
    current = (await client.get(url, headers=auth)).json()
    for category in review.CATEGORIES:
        response = await client.post(url + '/reviews', headers=auth, json={
            'requestId': f'validation-gate-{category}-{current["fingerprint"][-8:]}',
            'expectedFingerprint': current['fingerprint'],
            'category': category,
            'decision': 'approved',
            'note': f'Synthetic {category} approval',
        })
        assert response.status_code == 200, response.text
    return current['fingerprint'], contest_problem_id


@pytest.mark.asyncio
async def test_authoring_validation_requires_admin_saved_draft_and_measured_policy(env):
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        contest, problem, source, digest, fingerprint = await _saved_draft(client, env, measured=False)
        url = f"/api/v1/contests/{contest['id']}/problems/{problem['id']}/authoring-validations"
        body = {'code': source, 'language': 'python', 'requestId': 'policy-required',
                'expectedFingerprint': fingerprint, 'referenceAssetDigest': digest}
        assert (await client.post(url, json=body)).status_code == 401
        assert (await client.post(url, headers=headers(env.alice), json=body)).status_code == 403
        rejected = await client.post(url, headers=headers(env.admin), json=body)
        assert rejected.status_code == 409
        assert '채점 제한' in rejected.text
        with env.factory() as db:
            assert db.query(m.ExecutionJob).count() == 0


@pytest.mark.asyncio
async def test_manage_and_validation_stay_bound_to_saved_snapshot_after_source_metadata_changes(env):
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        contest, problem, source, digest, fingerprint = await _saved_draft(client, env)
        with env.factory() as db:
            record = db.get(m.ProblemAuthoring, problem['problemId'])
            changed = deepcopy(record.metadata_json)
            changed['adaptationNotes'] = 'changed after the contest snapshot was saved'
            record.metadata_json = changed
            db.commit()

        manage = await client.get(
            f"/api/v1/contests/{contest['id']}/manage",
            headers=headers(env.admin),
        )
        assert manage.status_code == 200
        saved = manage.json()['authoring'][problem['problemId']]
        assert saved['fingerprint'] == fingerprint
        assert saved['metadata']['adaptationNotes'] != 'changed after the contest snapshot was saved'

        response = await client.post(
            f"/api/v1/contests/{contest['id']}/problems/{problem['id']}/authoring-validations",
            headers=headers(env.admin),
            json={'code': source, 'language': 'python', 'requestId': 'saved-snapshot',
                  'expectedFingerprint': saved['fingerprint'], 'referenceAssetDigest': digest},
        )
        assert response.status_code == 202, response.text


@pytest.mark.asyncio
async def test_authoring_validation_is_frozen_idempotent_redacted_and_scoreless(env, monkeypatch):
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        contest, problem, source, digest, fingerprint = await _saved_draft(client, env)
        url = f"/api/v1/contests/{contest['id']}/problems/{problem['id']}/authoring-validations"
        body = {'code': source, 'language': 'python', 'requestId': 'reference-python-v1',
                'expectedFingerprint': fingerprint, 'referenceAssetDigest': digest}
        with env.factory() as db:
            before = _counts(db)
            user_totals = {row.id: row.total_score for row in db.query(m.User).all()}
            scoreboard_revision = db.get(m.Contest, contest['id']).scoreboard_revision

        accepted = await client.post(url, headers=headers(env.admin), json=body)
        assert accepted.status_code == 202, accepted.text
        receipt = accepted.json()
        assert receipt['status'] == 'queued' and receipt['result'] is None
        assert receipt['sourceHash'].startswith('sha256:')
        assert receipt['sourceHash'] == digest
        assert receipt['authoringFingerprint'] == fingerprint
        assert receipt['referenceAssetDigest'] == digest
        assert receipt['problemSnapshotHash'].startswith('sha256:')
        assert receipt['policyHash'].startswith('sha256:')
        assert receipt['testSuiteHash'].startswith('sha256:')
        assert accepted.headers['cache-control'] == 'no-store'

        stale = await client.post(url, headers=headers(env.admin), json={
            **body, 'requestId': 'stale-fingerprint', 'expectedFingerprint': 'sha256:' + '9' * 64,
        })
        assert stale.status_code == 409
        wrong_asset = await client.post(url, headers=headers(env.admin), json={
            **body, 'requestId': 'wrong-asset', 'referenceAssetDigest': 'sha256:' + '8' * 64,
        })
        assert wrong_asset.status_code == 409
        wrong_source = await client.post(url, headers=headers(env.admin), json={
            **body, 'requestId': 'wrong-source', 'code': 'print(0)',
        })
        assert wrong_source.status_code == 409
        with env.factory() as db:
            assert db.query(m.ExecutionJob).count() == 1

        with env.factory() as db:
            row = db.get(m.ContestProblem, problem['id'])
            changed = deepcopy(row.snapshot)
            changed['description'] = 'Edited after durable admission'
            row.snapshot = changed
            db.commit()
        replay = await client.post(url, headers=headers(env.admin), json=body)
        assert replay.status_code == 202 and replay.json()['id'] == receipt['id']
        collision = await client.post(url, headers=headers(env.admin), json={**body, 'code': 'print(0)'})
        assert collision.status_code == 409

        with env.factory() as db:
            job = db.get(m.ExecutionJob, receipt['id'])
            assert job.kind == 'authoring-validation-v1'
            assert job.payload['code'] == body['code']
            assert job.payload['hidden'][0]['input'] == 'secret-input'
            assert job.payload['judge_contract']['kind'] == 'measured-v1'
            assert db.query(m.CompileQueueRecord).filter_by(id=job.id).first() is None
            assert _counts(db) == before
            assert db.get(m.Contest, contest['id']).scoreboard_revision == scoreboard_revision

        async def private_judge(_runner, frozen, *, contest=False, load_case=None):
            assert contest is True
            assert frozen['code'] == body['code']
            assert frozen['hidden'][0]['input'] == 'secret-input'
            return {
                'verdict': 'accepted',
                'status': 'Accepted',
                'details': [{'input': 'secret-input', 'expected': 'secret-expected'}],
                '_resource_report': full_report(frozen),
            }

        monkeypatch.setattr('app.services.execution_worker.judge_code', private_judge)
        monkeypatch.setattr(
            ExecutionWorker,
            '_replay_eligibility',
            staticmethod(lambda *_args, **_kwargs: lambda _kind, _payload, _job_id=None: True),
        )
        worker = ExecutionWorker(
            execution_runtime.execution_queue(),
            pool=SimpleNamespace(reap=lambda *_args: None),
            runner_factory=lambda **_kwargs: object(),
        )
        assert await worker.run_once()

        finished = await client.get(f'{url}/{receipt["id"]}', headers=headers(env.admin))
        assert finished.status_code == 200
        data = finished.json()
        assert data['status'] == 'completed'
        assert data['result']['verdict'] == 'accepted'
        assert data['result']['resourceUsage']['compile']['cpuMs'] == 1.2
        assert data['result']['resourceUsage']['run']['peakMemoryBytes'] == 2048
        assert finished.headers['cache-control'] == 'no-store'
        assert 'secret-input' not in finished.text
        assert 'secret-expected' not in finished.text
        assert body['code'] not in finished.text

        assert (await client.get(f'{url}/{receipt["id"]}')).status_code == 401
        assert (await client.get(f'{url}/{receipt["id"]}', headers=headers(env.alice))).status_code == 403
        other_admin = m.User(id='other-admin', username='other_admin', hashed_password='unused', role='admin')
        with env.factory() as db:
            db.add(other_admin)
            db.commit()
            other_admin_headers = headers(db.get(m.User, 'other-admin'))
        assert (await client.get(f'{url}/{receipt["id"]}', headers=other_admin_headers)).status_code == 404
        assert (await client.get(f'/api/v1/executions/{receipt["id"]}', headers=headers(env.admin))).status_code == 404
        wrong_problem = await client.get(
            f"/api/v1/contests/{contest['id']}/problems/not-this-problem/authoring-validations/{receipt['id']}",
            headers=headers(env.admin),
        )
        assert wrong_problem.status_code == 404

        with env.factory() as db:
            saved = db.get(m.ExecutionJob, receipt['id'])
            attestation = db.get(m.ProblemValidationAttestation, receipt['id'])
            assert attestation is not None
            assert attestation.problem_id == problem['problemId']
            assert attestation.contest_id == contest['id']
            assert attestation.contest_problem_id == problem['id']
            assert attestation.language == 'python'
            assert attestation.source_hash == digest == attestation.reference_asset_digest
            assert attestation.authoring_fingerprint == fingerprint
            assert attestation.problem_snapshot_hash == saved.payload['problem_snapshot_hash']
            assert attestation.policy_hash == saved.payload['judge_contract']['policyHash']
            assert attestation.test_suite_hash == saved.payload['judge_contract']['testSuiteHash']
            assert source not in str(attestation.__dict__)
            assert 'secret-input' not in str(attestation.__dict__)
            assert '_resource_report' not in str(saved.result)
            assert 'secret-input' not in str(saved.result)
            assert body['code'] not in str(saved.result)
            assert _counts(db) == before
            assert {identifier: db.get(m.User, identifier).total_score
                    for identifier in user_totals} == user_totals
            assert db.get(m.Contest, contest['id']).scoreboard_revision == scoreboard_revision


@pytest.mark.asyncio
async def test_expired_authoring_validation_keeps_receipt_and_never_replays_private_content(env):
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        contest, problem, source, digest, fingerprint = await _saved_draft(client, env)
        url = f"/api/v1/contests/{contest['id']}/problems/{problem['id']}/authoring-validations"
        body = {
            'code': source,
            'language': 'python',
            'requestId': 'expiring-reference-python',
            'expectedFingerprint': fingerprint,
            'referenceAssetDigest': digest,
        }
        created = await client.post(url, headers=headers(env.admin), json=body)
        assert created.status_code == 202, created.text
        receipt_id = created.json()['id']

        other_admin = m.User(
            id='retention-admin', username='retention_admin', hashed_password='unused', role='admin'
        )
        with env.factory() as db:
            db.add(other_admin)
            db.flush()
            other_admin_headers = headers(other_admin)
            job = db.get(m.ExecutionJob, receipt_id)
            job.status = 'completed'
            job.finished_at = env.clock[0]
            result = {'verdict': 'accepted', 'value': {
                '_resource_report': full_report(job.payload),
                'details': [{'input': 'secret-input', 'expected': 'secret-expected'}],
            }}
            publish_result(db, receipt_id, result)
            job.result = result
            db.commit()
            identity = (job.request_id, job.payload_hash, job.status)
            before = _counts(db)
            user_totals = {row.id: row.total_score for row in db.query(m.User).all()}
            scoreboard_revision = db.get(m.Contest, contest['id']).scoreboard_revision

        expired_at = env.clock[0] + timedelta(days=8)
        with env.factory() as db:
            assert expire_execution_content(db, retention_days=7, at=expired_at) == 1
            db.commit()
            job = db.get(m.ExecutionJob, receipt_id)
            assert job.payload == {}
            assert job.result is None
            assert job.content_expired_at == expired_at
            assert (job.request_id, job.payload_hash, job.status) == identity
            assert _counts(db) == before
            assert {identifier: db.get(m.User, identifier).total_score
                    for identifier in user_totals} == user_totals
            assert db.get(m.Contest, contest['id']).scoreboard_revision == scoreboard_revision
            attestation = db.get(m.ProblemValidationAttestation, receipt_id)
            assert attestation is not None
            attestation_identity = {
                column.name: getattr(attestation, column.name)
                for column in m.ProblemValidationAttestation.__table__.columns
            }
            for secret in (source, 'secret-input', 'secret-expected'):
                assert secret not in str(attestation_identity)

        expired = await client.get(f'{url}/{receipt_id}', headers=headers(env.admin))
        assert expired.status_code == 410
        assert expired.headers['cache-control'] == 'no-store'
        for secret in (source, 'secret-input', 'secret-expected'):
            assert secret not in expired.text

        for replay_body in (body, {**body, 'code': 'print(0)'}):
            replay = await client.post(url, headers=headers(env.admin), json=replay_body)
            assert replay.status_code == 410
            assert replay.headers['cache-control'] == 'no-store'
            for secret in (source, 'secret-input', 'secret-expected'):
                assert secret not in replay.text

        hidden_from_other_admin = await client.get(
            f'{url}/{receipt_id}', headers=other_admin_headers
        )
        assert hidden_from_other_admin.status_code == 404
        with env.factory() as db:
            assert db.query(m.ExecutionJob).count() == 1
            assert db.query(m.ProblemValidationAttestation).count() == 1
            persisted = db.get(m.ProblemValidationAttestation, receipt_id)
            assert {
                column.name: getattr(persisted, column.name)
                for column in m.ProblemValidationAttestation.__table__.columns
            } == attestation_identity
            assert _counts(db) == before
            assert db.get(m.Contest, contest['id']).scoreboard_revision == scoreboard_revision


@pytest.mark.asyncio
async def test_authoring_validation_rejects_started_published_contest(env):
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        body = payload(env)
        body['published'] = False
        created = await client.post('/api/v1/contests', headers=headers(env.admin), json=body)
        assert created.status_code == 201
        contest = created.json()
        problem = contest['problems'][0]
        env.clock[0] += timedelta(seconds=10)
        with env.factory() as db:
            row = db.get(m.Contest, contest['id'])
            row.published = True
            db.commit()
        response = await client.post(
            f"/api/v1/contests/{contest['id']}/problems/{problem['id']}/authoring-validations",
            headers=headers(env.admin),
            json={'code': 'print(42)', 'language': 'python', 'requestId': 'too-late',
                  'expectedFingerprint': 'sha256:' + '1' * 64,
                  'referenceAssetDigest': 'sha256:' + '2' * 64},
        )
        assert response.status_code == 409
        with env.factory() as db:
            assert db.query(m.ExecutionJob).count() == 0


@pytest.mark.asyncio
async def test_current_accepted_reference_validation_is_required_for_publication(env, monkeypatch):
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        contest, problem, source, digest, _ = await _saved_draft(client, env)
        fingerprint, problem['id'] = await _approve_current(
            client, env, contest['id'], problem['problemId']
        )
        manage = await client.get(
            f'/api/v1/contests/{contest["id"]}/manage', headers=headers(env.admin)
        )
        assert manage.status_code == 200
        publish_body = payload(env)
        publish_body['problems'] = manage.json()['problems']
        publish_body['published'] = True

        blocked = await client.put(
            f'/api/v1/contests/{contest["id"]}', headers=headers(env.admin), json=publish_body
        )
        assert blocked.status_code == 409
        assert '전체 테스트 통과 검증' in blocked.text

        validation_url = (
            f'/api/v1/contests/{contest["id"]}/problems/{problem["id"]}'
            '/authoring-validations'
        )
        queued = await client.post(validation_url, headers=headers(env.admin), json={
            'code': source,
            'language': 'python',
            'requestId': 'publication-gate-reference',
            'expectedFingerprint': fingerprint,
            'referenceAssetDigest': digest,
        })
        assert queued.status_code == 202, queued.text
        job_id = queued.json()['id']

        async def accepted_reference(_runner, frozen, *, contest=False, load_case=None):
            assert contest is True
            return {
                'verdict': 'accepted',
                'status': 'Accepted',
                'details': [],
                '_resource_report': full_report(frozen),
            }

        monkeypatch.setattr('app.services.execution_worker.judge_code', accepted_reference)
        monkeypatch.setattr(
            ExecutionWorker,
            '_replay_eligibility',
            staticmethod(lambda *_args, **_kwargs: lambda _kind, _payload, _job_id=None: True),
        )
        worker = ExecutionWorker(
            execution_runtime.execution_queue(),
            pool=SimpleNamespace(reap=lambda *_args: None),
            runner_factory=lambda **_kwargs: object(),
        )
        assert await worker.run_once()

        published = await client.put(
            f'/api/v1/contests/{contest["id"]}', headers=headers(env.admin), json=publish_body
        )
        assert published.status_code == 200, published.text
        assert published.json()['published'] is True
        # Saving unchanged problem content replaces internal mapping rows. The
        # exact proof remains valid within the same contest for schedule/point
        # edits because those fields are outside the reviewed snapshot.
        refreshed = (await client.get(
            f'/api/v1/contests/{contest["id"]}/manage', headers=headers(env.admin)
        )).json()
        unchanged = payload(env)
        unchanged.update(problems=refreshed['problems'], published=True)
        unchanged['description'] = 'Schedule and points may change without rerunning identical code'
        resaved = await client.put(
            f'/api/v1/contests/{contest["id"]}', headers=headers(env.admin), json=unchanged
        )
        assert resaved.status_code == 200, resaved.text
        with env.factory() as db:
            proof = db.get(m.ProblemValidationAttestation, job_id)
            assert proof is not None
            assert db.get(m.Contest, contest['id']).published is True
            assert _counts(db) == {
                m.Submission.__tablename__: 0,
                m.ContestSubmission.__tablename__: 0,
                m.UserProblemScore.__tablename__: 0,
                m.SolveEvidence.__tablename__: 0,
                m.CompileQueueRecord.__tablename__: 0,
            }


@pytest.mark.asyncio
async def test_failed_or_stale_reference_validation_cannot_publish(env, monkeypatch):
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        contest, problem, source, digest, _ = await _saved_draft(client, env)
        fingerprint, problem['id'] = await _approve_current(
            client, env, contest['id'], problem['problemId']
        )
        validation_url = (
            f'/api/v1/contests/{contest["id"]}/problems/{problem["id"]}'
            '/authoring-validations'
        )
        queued = await client.post(validation_url, headers=headers(env.admin), json={
            'code': source,
            'language': 'python',
            'requestId': 'failed-reference',
            'expectedFingerprint': fingerprint,
            'referenceAssetDigest': digest,
        })
        assert queued.status_code == 202, queued.text

        async def wrong_reference(_runner, frozen, *, contest=False, load_case=None):
            return {
                'verdict': 'wrong_answer',
                'status': 'Rejected',
                'details': [],
                '_resource_report': full_report(frozen),
            }

        monkeypatch.setattr('app.services.execution_worker.judge_code', wrong_reference)
        monkeypatch.setattr(
            ExecutionWorker,
            '_replay_eligibility',
            staticmethod(lambda *_args, **_kwargs: lambda _kind, _payload, _job_id=None: True),
        )
        worker = ExecutionWorker(
            execution_runtime.execution_queue(),
            pool=SimpleNamespace(reap=lambda *_args: None),
            runner_factory=lambda **_kwargs: object(),
        )
        assert await worker.run_once()
        with env.factory() as db:
            assert db.query(m.ProblemValidationAttestation).count() == 0

        manage = (await client.get(
            f'/api/v1/contests/{contest["id"]}/manage', headers=headers(env.admin)
        )).json()
        publish_body = payload(env)
        publish_body.update(problems=manage['problems'], published=True)
        blocked = await client.put(
            f'/api/v1/contests/{contest["id"]}', headers=headers(env.admin), json=publish_body
        )
        assert blocked.status_code == 409
        assert '전체 테스트 통과 검증' in blocked.text


@pytest.mark.asyncio
async def test_every_declared_reference_language_needs_its_own_current_proof(env):
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        contest, problem, _source, _digest, _ = await _saved_draft(client, env)
        with env.factory() as db:
            record = db.get(m.ProblemAuthoring, problem['problemId'])
            metadata = deepcopy(record.metadata_json)
            metadata['requiredLanguages'].append('javascript')
            metadata['assets'].append({
                'role': 'reference',
                'name': 'reference.js',
                'digest': 'sha256:' + '2' * 64,
                'language': 'javascript',
            })
            record.metadata_json = metadata
            db.commit()
        fingerprint, problem['id'] = await _approve_current(
            client, env, contest['id'], problem['problemId']
        )
        with env.factory() as db:
            saved = db.get(m.ContestProblem, problem['id'])
            snapshot = saved.snapshot
            python_digest = next(
                asset['digest'] for asset in snapshot['authoring']['assets']
                if asset['role'] == 'reference' and asset.get('language') == 'python'
            )
            contract = freeze_stored_submission(
                snapshot['judgePolicy'], 'python', snapshot['sample'], snapshot['hidden'], settings=settings
            )
            db.add(m.ProblemValidationAttestation(
                job_id='python-only-current-proof',
                problem_id=problem['problemId'],
                contest_id=contest['id'],
                contest_problem_id=saved.id,
                problem_snapshot_hash=content_hash(snapshot),
                authoring_fingerprint=fingerprint,
                language='python',
                source_hash=python_digest,
                reference_asset_digest=python_digest,
                policy_hash=contract['policyHash'],
                test_suite_hash=contract['testSuiteHash'],
            ))
            db.commit()

        manage = (await client.get(
            f'/api/v1/contests/{contest["id"]}/manage', headers=headers(env.admin)
        )).json()
        publish_body = payload(env)
        publish_body.update(problems=manage['problems'], published=True)
        blocked = await client.put(
            f'/api/v1/contests/{contest["id"]}', headers=headers(env.admin), json=publish_body
        )
        assert blocked.status_code == 409
        assert 'javascript' in blocked.text


@pytest.mark.asyncio
async def test_accepted_reference_proof_becomes_stale_after_problem_content_changes(env, monkeypatch):
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        contest, problem, source, digest, _ = await _saved_draft(client, env)
        fingerprint, problem['id'] = await _approve_current(
            client, env, contest['id'], problem['problemId']
        )
        validation_url = (
            f'/api/v1/contests/{contest["id"]}/problems/{problem["id"]}'
            '/authoring-validations'
        )
        queued = await client.post(validation_url, headers=headers(env.admin), json={
            'code': source,
            'language': 'python',
            'requestId': 'proof-before-content-change',
            'expectedFingerprint': fingerprint,
            'referenceAssetDigest': digest,
        })
        assert queued.status_code == 202, queued.text

        async def accepted_reference(_runner, frozen, *, contest=False, load_case=None):
            return {
                'verdict': 'accepted',
                'status': 'Accepted',
                'details': [],
                '_resource_report': full_report(frozen),
            }

        monkeypatch.setattr('app.services.execution_worker.judge_code', accepted_reference)
        monkeypatch.setattr(
            ExecutionWorker,
            '_replay_eligibility',
            staticmethod(lambda *_args, **_kwargs: lambda _kind, _payload, _job_id=None: True),
        )
        worker = ExecutionWorker(
            execution_runtime.execution_queue(),
            pool=SimpleNamespace(reap=lambda *_args: None),
            runner_factory=lambda **_kwargs: object(),
        )
        assert await worker.run_once()

        manage = (await client.get(
            f'/api/v1/contests/{contest["id"]}/manage', headers=headers(env.admin)
        )).json()
        draft = payload(env)
        draft.update(problems=manage['problems'], published=False)
        draft['problems'][0]['newProblem']['description'] = 'Changed after accepted validation'
        changed = await client.put(
            f'/api/v1/contests/{contest["id"]}', headers=headers(env.admin), json=draft
        )
        assert changed.status_code == 200, changed.text
        current = (await client.get(
            f'/api/v1/problems/{problem["problemId"]}/authoring', headers=headers(env.admin)
        )).json()
        assert current['fingerprint'] != fingerprint
        for category in review.CATEGORIES:
            approved = await client.post(
                f'/api/v1/problems/{problem["problemId"]}/authoring/reviews',
                headers=headers(env.admin),
                json={
                    'requestId': f'changed-content-{category}',
                    'expectedFingerprint': current['fingerprint'],
                    'category': category,
                    'decision': 'approved',
                    'note': f'Approve changed {category}',
                },
            )
            assert approved.status_code == 200, approved.text

        manage = (await client.get(
            f'/api/v1/contests/{contest["id"]}/manage', headers=headers(env.admin)
        )).json()
        publish_body = payload(env)
        publish_body.update(problems=manage['problems'], published=True)
        blocked = await client.put(
            f'/api/v1/contests/{contest["id"]}', headers=headers(env.admin), json=publish_body
        )
        assert blocked.status_code == 409
        assert '전체 테스트 통과 검증' in blocked.text
        with env.factory() as db:
            assert db.query(m.ProblemValidationAttestation).count() == 1
            assert db.get(m.Contest, contest['id']).published is False
