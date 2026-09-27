"""Transactional correction tests with synthetic protected runner, never production."""
from copy import deepcopy
import hashlib
import pytest
from httpx import ASGITransport, AsyncClient
from app.main import app
from app.models import database as m
from app.models.contest_rejudge import RejudgeApply
from app.services import contest_rejudge as service, contest_rejudge_review, contests, execution_runtime, solve_evidence
from tests.test_contest_rejudge import env, seeded, create, worker, headers


async def ready(env, seeded, monkeypatch, *, tracked=True, other=False, attested=True):
    from tests.test_contest_package_authoring import package_body
    from app.models.contest_rejudge import RejudgeReview
    from app.services import contest_rejudge_review
    seeded = deepcopy(seeded)
    seeded['authoring'] = package_body(env)['entries'][0]['metadata']
    seeded['authoring']['sources'][0].update(reuseBasis='original', reuseEvidence='Invented unit test metadata only')
    reference_digest = 'sha256:' + hashlib.sha256(b'print(43)').hexdigest()
    next(asset for asset in seeded['authoring']['assets']
         if asset['role'] == 'reference' and asset.get('language') == 'python')['digest'] = reference_digest
    if tracked:
        with env.factory() as db:
            solve_evidence.record(db, user_id='alice', problem_id='p', source_kind='contest',
                source_id='s0', points=120, solved_at=db.get(m.ContestSubmission,'s0').received_at)
            if other:
                solve_evidence.record(db, user_id='alice', problem_id='p', source_kind='practice',
                    source_id='already-pruned-practice', points=200, solved_at=env.clock[0])
            db.commit()
    batch = create(env, seeded)
    with env.factory() as db:
        target = contest_rejudge_review.read(db, 'c', batch['id'])
        for category in ('sources', 'statement', 'tests', 'resources'):
            contest_rejudge_review.append(db, 'c', batch['id'], RejudgeReview.model_validate(dict(
                requestId='approve-'+category, expectedRequestHash=target['requestHash'],
                expectedFingerprint=target['fingerprint'], category=category, decision='approved',
                note='Synthetic fixture approval, not real contest acceptance')), env.admin)
        if attested:
            from app.core.config import settings
            from app.services import problem_authoring
            from app.services.judge_policy import content_hash, freeze_stored_submission
            row = db.get(m.ContestRejudgeBatch, batch['id'])
            contest_problem = db.get(m.ContestProblem, row.contest_problem_id)
            digest = next(asset['digest'] for asset in row.snapshot['authoring']['assets']
                if asset['role'] == 'reference' and asset.get('language') == 'python')
            contract = freeze_stored_submission(row.snapshot['judgePolicy'], 'python',
                row.snapshot['sample'], row.snapshot['hidden'], settings=settings)
            db.add(m.ProblemValidationAttestation(job_id='synthetic-rejudge-proof-'+row.id,
                problem_id=contest_problem.problem_id, contest_id='c',
                contest_problem_id=contest_problem.id,
                problem_snapshot_hash=content_hash(row.snapshot),
                authoring_fingerprint=problem_authoring.fingerprint(row.snapshot), language='python',
                source_hash=digest, reference_asset_digest=digest,
                policy_hash=contract['policyHash'], test_suite_hash=contract['testSuiteHash']))
            db.commit()
    queue = execution_runtime.execution_queue()
    assert service.dispatch_pending(queue) == 2
    assert await worker(env, queue, monkeypatch).run_once()
    assert await worker(env, queue, monkeypatch).run_once()
    with env.factory() as db:
        row = db.get(m.ContestRejudgeBatch, batch['id'])
        assert row.status == 'ready'
        request = dict(expectedRequestHash=row.request_hash, expectedScoreboardRevision=row.before_scoreboard_revision,
            expectedPreviewHash=service.preview_candidate(db,'c',batch['id'])['previewHash'],
            publicNote='예제 정답 오류를 수정해 모든 제출을 다시 채점했습니다.')
    return batch['id'], request


@pytest.mark.asyncio
async def test_apply_requires_accepted_reference_run_for_exact_candidate(env, seeded, monkeypatch):
    batch_id, body = await ready(env, seeded, monkeypatch, attested=False)
    with env.factory() as db, pytest.raises(service.HTTPException) as error:
        service.apply_candidate(db, 'c', batch_id, RejudgeApply.model_validate(body), env.admin)
    assert error.value.status_code == 409
    assert 'python' in error.value.detail
    with env.factory() as db:
        assert db.get(m.ContestRejudgeBatch, batch_id).status == 'ready'
        assert db.query(m.ContestRejudgeApplication).count() == 0


@pytest.mark.asyncio
async def test_rejudge_reference_validation_endpoint_unlocks_exact_candidate(env, seeded, monkeypatch):
    batch_id, body = await ready(env, seeded, monkeypatch, attested=False)
    with env.factory() as db:
        review = contest_rejudge_review.read(db, 'c', batch_id)
        digest = next(asset['digest'] for asset in review['metadata']['assets']
                      if asset['role'] == 'reference' and asset.get('language') == 'python')
    path = f'/api/v1/contests/c/rejudges/{batch_id}/authoring-validations'
    validation = dict(code='print(43)', language='python', requestId='candidate-reference',
        expectedFingerprint=review['fingerprint'], referenceAssetDigest=digest)
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        assert (await client.post(path, json=validation)).status_code == 401
        assert (await client.post(path, headers=headers(env.alice), json=validation)).status_code == 403
        queued = await client.post(path, headers=headers(env.admin), json=validation)
        assert queued.status_code == 202, queued.text
        queue = execution_runtime.execution_queue()
        assert await worker(env, queue, monkeypatch).run_once()
        result = await client.get(f'{path}/{queued.json()["id"]}', headers=headers(env.admin))
        assert result.status_code == 200
        assert result.json()['result']['verdict'] == 'accepted'
        applied = await client.post(f'/api/v1/contests/c/rejudges/{batch_id}/apply',
            headers=headers(env.admin), json=body)
        assert applied.status_code == 200, applied.text
        with env.factory() as db:
            jobs_before = db.query(m.ExecutionJob).count()
        after_apply = await client.post(path, headers=headers(env.admin), json={
            **validation, 'requestId':'candidate-reference-after-apply'
        })
        assert after_apply.status_code == 409
        assert '검증할 수 없는 재채점 후보' in after_apply.text
        with env.factory() as db:
            assert db.query(m.ExecutionJob).count() == jobs_before


@pytest.mark.asyncio
@pytest.mark.parametrize('other', [False, True])
async def test_apply_atomic_awards_audit_public_notice_and_exact_retry(env, seeded, monkeypatch, other):
    batch_id, body = await ready(env, seeded, monkeypatch, other=other)
    with env.factory() as db:
        before_receipts = {s.id:s.received_at for s in db.query(m.ContestSubmission)}
        before_jobs = {s.id:s.execution_job_id for s in db.query(m.ContestSubmission)}
    path = '/api/v1/contests/c/rejudges/'+batch_id+'/apply'
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        assert (await client.post(path, json=body)).status_code == 401
        assert (await client.post(path, json=body, headers=headers(env.alice))).status_code == 403
        response = await client.post(path, json=body, headers=headers(env.admin))
        assert response.status_code == 200, response.text
        assert response.headers['Cache-Control'] == 'no-store'
        assert response.json()['status'] == 'applied'
        assert (await client.post(path, json=body, headers=headers(env.admin))).json() == response.json()
        changed = {**body, 'publicNote':'이전 요청과 다른 사유로 재시도하는 요청입니다.'}
        assert (await client.post(path, json=changed, headers=headers(env.admin))).status_code == 409
        public = await client.get('/api/v1/contests/c')
        assert public.json()['corrections']['items'][0]['note'] == body['publicNote']
        assert seeded['reason'] not in public.text and 'corrected-private-input' not in public.text
        audit_path = path.removesuffix('/apply')+'/audit?limit=1'
        assert (await client.get(audit_path,headers=headers(env.alice))).status_code==403
        audit_response = await client.get(audit_path,headers=headers(env.admin))
        assert audit_response.status_code==200 and audit_response.headers['Cache-Control']=='no-store'
        assert audit_response.json()['total']==2 and len(audit_response.json()['rows'])==1
        assert all(secret not in audit_response.text for secret in ('private-input','print(42)','resourceReport'))
    with env.factory() as db:
        assert db.query(m.ContestRejudgeApplication).count() == 1
        audit = db.get(m.ContestRejudgeApplication, batch_id)
        assert audit.before_board['rows'][0]['userId'] == 'alice'
        assert audit.after_board['rows'][0]['userId'] == 'bob'
        assert audit.after_revision == audit.before_revision+1
        assert audit.before_snapshot['sample'][0]['expectedOutput'] == '42'
        assert next(s for s in audit.before_submissions if s['id']=='s0')['verdict'] == 'accepted'
        assert db.get(m.ContestProblem,'cp').snapshot['sample'][0]['expectedOutput'] == '43'
        assert db.get(m.User,'alice').total_score == (120 if other else 0)
        assert db.get(m.User,'bob').total_score == 120
        assert db.query(m.UserProblemScore).count() == (2 if other else 1)
        assert {s.id:s.received_at for s in db.query(m.ContestSubmission)} == before_receipts
        assert {s.id:s.execution_job_id for s in db.query(m.ContestSubmission)} == before_jobs
        assert db.query(m.SolveEvidence).filter_by(source_kind='contest',source_id='s0').one().active is False
    contests.finalize_contests()
    with env.factory() as db:
        assert db.get(m.User,'bob').total_score == 120


@pytest.mark.asyncio
async def test_multishard_campaign_has_one_atomic_application_and_revision(env, seeded, monkeypatch):
    monkeypatch.setattr(service, 'MAX_SUBMISSIONS', 1)
    batch_id, body = await ready(env, seeded, monkeypatch)
    with env.factory() as db:
        assert db.query(m.ContestRejudgeShard).filter_by(batch_id=batch_id).count() == 2
        before_revision = db.get(m.Contest, 'c').scoreboard_revision
        result = service.apply_candidate(
            db, 'c', batch_id, RejudgeApply.model_validate(body), env.admin)
        assert result['status'] == 'applied'
    with env.factory() as db:
        assert db.query(m.ContestRejudgeApplication).filter_by(batch_id=batch_id).count() == 1
        assert db.get(m.Contest, 'c').scoreboard_revision == before_revision + 1
        assert db.get(m.User, 'alice').total_score == 0
        assert db.get(m.User, 'bob').total_score == 120


@pytest.mark.asyncio
@pytest.mark.parametrize('drift', ['legacy', 'snapshot', 'submission', 'membership', 'revision', 'failed', 'missing_report'])
async def test_apply_rejects_conflict_without_partial_changes(env, seeded, monkeypatch, drift):
    batch_id, body = await ready(env, seeded, monkeypatch, tracked=drift!='legacy')
    with env.factory() as db:
        if drift == 'snapshot':
            snap=deepcopy(db.get(m.ContestProblem,'cp').snapshot); snap['title']='Changed'
            db.get(m.ContestProblem,'cp').snapshot=snap
        elif drift == 'submission': db.get(m.ContestSubmission,'s0').code='different'
        elif drift == 'membership': db.delete(db.get(m.ContestSubmission,'s1'))
        elif drift == 'revision': db.get(m.Contest,'c').scoreboard_revision += 1
        elif drift == 'failed': db.get(m.ContestRejudgeBatch,batch_id).status='failed'
        elif drift == 'missing_report': db.query(m.ContestRejudgeItem).filter_by(submission_id='s0').one().resource_report=None
        db.commit()
    with env.factory() as db:
        before = {s.id:service.submission_fingerprint(s) for s in db.query(m.ContestSubmission)}
    with env.factory() as db, pytest.raises(service.HTTPException) as error:
        service.apply_candidate(db,'c',batch_id,RejudgeApply.model_validate(body),env.admin)
    assert error.value.status_code == 409
    with env.factory() as db:
        assert {s.id:service.submission_fingerprint(s) for s in db.query(m.ContestSubmission)} == before
        assert db.query(m.ContestRejudgeApplication).count() == 0
        assert db.get(m.User,'alice').total_score == 120 and db.get(m.User,'bob').total_score == 0


@pytest.mark.asyncio
async def test_transaction_failure_rolls_back_claims_scores_snapshot_and_audit(env, seeded, monkeypatch):
    batch_id, body = await ready(env, seeded, monkeypatch)
    original=contests._scoreboard_projection
    calls=[]
    def fail_after(*args, **kwargs):
        calls.append(1)
        if len(calls)==4: raise RuntimeError('injected post-score audit failure')
        return original(*args, **kwargs)
    monkeypatch.setattr(contests,'_scoreboard_projection',fail_after)
    with env.factory() as db, pytest.raises(RuntimeError):
        service.apply_candidate(db,'c',batch_id,RejudgeApply.model_validate(body),env.admin)
    with env.factory() as db:
        assert db.get(m.User,'alice').total_score == 120 and db.get(m.User,'bob').total_score == 0
        assert db.get(m.ContestProblem,'cp').snapshot['sample'][0]['expectedOutput']=='42'
        assert db.get(m.ContestSubmission,'s0').verdict=='accepted'
        assert db.get(m.ContestRejudgeBatch,batch_id).status=='ready'
        assert db.query(m.ContestRejudgeApplication).count()==0
        assert db.query(m.SolveEvidence).filter_by(source_id='s0').one().active
    monkeypatch.setattr(contests,'_scoreboard_projection',original)
    with env.factory() as db:
        assert service.apply_candidate(db,'c',batch_id,RejudgeApply.model_validate(body),env.admin)['status']=='applied'


@pytest.mark.asyncio
async def test_two_independent_sqlite_sessions_apply_exactly_once(env, seeded, monkeypatch):
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    batch_id, body = await ready(env, seeded, monkeypatch)
    gate = Barrier(2)
    def apply():
        gate.wait(timeout=10)
        with env.factory() as db:
            return service.apply_candidate(db,'c',batch_id,RejudgeApply.model_validate(body),env.admin)
    with ThreadPoolExecutor(max_workers=2) as pool:
        loop = asyncio.get_running_loop()
        responses = await asyncio.gather(*(loop.run_in_executor(pool,apply) for _ in range(2)))
    assert all(r['status']=='applied' for r in responses)
    with env.factory() as db:
        assert db.query(m.ContestRejudgeApplication).count()==1
        assert db.get(m.User,'alice').total_score==0 and db.get(m.User,'bob').total_score==120
        assert db.get(m.Contest,'c').scoreboard_revision == body['expectedScoreboardRevision']+1


@pytest.mark.asyncio
async def test_apply_report_preflight_rejects_oversized_audit(env, seeded, monkeypatch):
    batch_id, body = await ready(env, seeded, monkeypatch)
    with env.factory() as db:
        db.query(m.ContestRejudgeItem).filter_by(submission_id='s0').one().resource_report={'synthetic':'x'*(2*1024**2+1)}
        db.commit()
    with env.factory() as db, pytest.raises(service.HTTPException) as error:
        service.apply_candidate(db,'c',batch_id,RejudgeApply.model_validate(body),env.admin)
    assert error.value.status_code == 413


def test_practice_provenance_survives_history_pruning_and_duplicate_solve(env, seeded, monkeypatch):
    from app.services.execution_results import publish_result
    from app.services.durable_queue import execution_payload_hash
    from app.api.routes.problems import _prune_old_submissions
    from app.core.config import settings
    from tests.test_judge_metrics import full_report
    from tests.test_measured_judge import payload_fixture
    monkeypatch.setattr(settings,'SUBMISSION_RETENTION_PER_USER',1)
    with env.factory() as db:
        for index in range(3):
            payload = payload_fixture()
            payload.update(practice_points=120, problem_id='p')
            job = m.ExecutionJob(id='practice-job-'+str(index), owner_key='account:bob', quota_key='account:bob',
                request_id='practice-'+str(index), kind='practice', status='completed',
                payload=payload, payload_hash=execution_payload_hash('practice',payload)[0], received_at=env.clock[0])
            db.add(job); db.flush()
            db.add(m.Submission(id='practice-sub-'+str(index),execution_job_id=job.id,user_id='bob',problem_id='p',
                language='python',code='print(42)',status='queued',created_at=env.clock[0]))
            db.flush()
            publish_result(db,job.id,{'verdict':'accepted','value':{
                '_resource_report':full_report(payload)}})
            db.commit()
        _prune_old_submissions(db,'bob'); db.commit()
        assert db.query(m.Submission).filter_by(user_id='bob').count()==1
        assert db.query(m.SolveEvidence).filter_by(user_id='bob',source_kind='practice').count()==3
        assert db.query(m.User.total_score).filter_by(id='bob').scalar()==120
        assert db.query(m.UserProblemScore).filter_by(user_id='bob').count()==1


@pytest.mark.asyncio
async def test_manual_award_has_persistent_source_and_no_duplicate_points(env, seeded):
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        data={'username':'bob','challenge_id':'p','points':77}
        first=await client.post('/api/v1/problems/leaderboard/score',json=data,headers=headers(env.admin))
        assert first.status_code==200,first.text
        second=await client.post('/api/v1/problems/leaderboard/score',json=data,headers=headers(env.admin))
        assert second.status_code==200,second.text
    with env.factory() as db:
        assert db.query(m.SolveEvidence).filter_by(user_id='bob',source_kind='manual').count()==1
        assert db.get(m.User,'bob').total_score==77


@pytest.mark.asyncio
async def test_additive_v18_initializer_preserves_applied_audit_and_claims(env, seeded, monkeypatch):
    from app.initialize import initialize, RUNTIME_SCHEMA_VERSION
    from sqlalchemy import text
    batch_id, body = await ready(env, seeded, monkeypatch)
    with env.factory() as db:
        service.apply_candidate(db,'c',batch_id,RejudgeApply.model_validate(body),env.admin)
    engine=env.db.get_bind()
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE IF NOT EXISTS schema_migrations (version VARCHAR PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'))
        conn.execute(text("INSERT INTO schema_migrations(version) VALUES ('20260926_contest_rejudge_v17')"))
    initialize(bind=engine,skip_bootstrap=True)
    initialize(bind=engine,skip_bootstrap=True)
    with env.factory() as db:
        assert db.get(m.ContestRejudgeApplication,batch_id).after_board['rows'][0]['userId']=='bob'
        assert db.query(m.SolveEvidence).count()==2
        assert db.get(m.User,'alice').total_score==0 and db.get(m.User,'bob').total_score==120
        versions=list(db.execute(text('SELECT version FROM schema_migrations')).scalars())
        assert versions.count(RUNTIME_SCHEMA_VERSION)==1
        assert versions.count('20260926_contest_rejudge_v17')==0
        assert db.execute(text('SELECT 1 FROM runtime_schema_history WHERE version=:v'),
                          {'v':'20260926_contest_rejudge_v17'}).first()
