"""Isolated v12 storage/admission tests; evidence below is SYNTHETIC."""
from copy import deepcopy
from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.main import app
from app.models import database as m
from app.initialize import initialize, LEARNING_SCHEMA_VERSION, RUNTIME_SCHEMA_VERSION
from app.services.judge_policy import UNREVIEWED, stored_policy, freeze_stored_submission
from app.services.judging import judge_code
from app.core.config import settings
from tests.test_contests import env, headers, payload, setup_contest
from tests.test_judge_policy import policy_fixture, SAMPLE, HIDDEN
from tests.test_durable_queue import replicas


def problem_body():
    return dict(title='Measured fixture', description='Synthetic test only', difficulty='ruby5',
                tags=['io'], testCases=SAMPLE, hiddenTestCases=HIDDEN, judgePolicy=policy_fixture())


@pytest.mark.asyncio
async def test_new_public_problem_requires_measured_policy_and_redacts_evidence(env):
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as c:
        body = problem_body()
        missing = {k: v for k, v in body.items() if k != 'judgePolicy'}
        assert (await c.post('/api/v1/problems/', json=missing, headers=headers(env.admin))).status_code == 409
        response = await c.post('/api/v1/problems/', json=body, headers=headers(env.admin))
        assert response.status_code == 200, response.text
        problem_id = response.json()['id']
        assert response.json()['publicationStatus'] == 'draft'
        # This test isolates policy projection. The publication gate itself is
        # exercised in test_problem_publication_gate.py.
        with env.factory() as db:
            db.get(m.Problem, problem_id).publication_approved_at = env.clock[0]
            db.commit()
        public = (await c.get('/api/v1/problems/' + problem_id)).json()
        assert public['judgePolicyLegacy'] is False
        assert public['judgeLimits']['languages']['python']['run']['cpuMs'] == 1000
        assert public['judgePolicy'] is None
        assert 'reportHash' not in str(public) and 'SECRET_INPUT' not in str(public)
        # Omitting the policy on update retains it; stale measurements cannot
        # authorize a modified test suite. No partial title/content write.
        changed = {**missing, 'title': 'Must rollback', 'testCases': [{'input':'changed', 'expectedOutput':'2'}]}
        assert (await c.put('/api/v1/problems/' + problem_id, json=changed, headers=headers(env.admin))).status_code == 409
        assert (await c.get('/api/v1/problems/' + problem_id, headers=headers(env.admin))).json()['title'] == body['title']


@pytest.mark.asyncio
async def test_contest_draft_not_legacy_and_publication_is_atomic(env):
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as c:
        body = payload(env)
        body['problems'][0]['newProblem'].pop('judgePolicy')
        body['published'] = False
        response = await c.post('/api/v1/contests', json=body, headers=headers(env.admin))
        assert response.status_code == 201, response.text
        contest = response.json()
        root = '/api/v1/contests/' + contest['id']
        problem = contest['problems'][0]
        detail = (await c.get(root + '/problems/' + problem['id'], headers=headers(env.admin))).json()
        assert detail['judgeLimits'] is None and detail['judgePolicyLegacy'] is False
        source = (await c.get('/api/v1/problems/' + problem['problemId'], headers=headers(env.admin))).json()
        assert source['judgePolicy'] is None and source['judgePolicyLegacy'] is False
        managed = (await c.get(root + '/manage', headers=headers(env.admin))).json()
        body['problems'] = managed['problems']
        body['published'] = True
        assert (await c.put(root, json=body, headers=headers(env.admin))).status_code == 409
        assert (await c.get(root)).status_code == 404
        with env.factory() as db:
            assert db.get(m.Contest, contest['id']).published is False
            assert db.get(m.Problem, problem['problemId']).judge_policy == UNREVIEWED


@pytest.mark.asyncio
async def test_practice_receipt_freezes_policy_and_retry_does_not_refresh_it(env):
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as c:
        created = await c.post('/api/v1/problems/', json=problem_body(), headers=headers(env.admin))
        assert created.status_code == 200, created.text
        problem_id = created.json()['id']
        with env.factory() as db:
            db.get(m.Problem, problem_id).publication_approved_at = env.clock[0]
            db.commit()
        url = '/api/v1/problems/' + problem_id + '/submit'
        auth = {**headers(env.alice), 'X-Request-ID': 'dddddddd-aaaa-4444-9999-123456789abc'}
        request = dict(language='python', code='print(2)')
        first = await c.post(url, headers=auth, json=request)
        assert first.status_code in (200,202), first.text
        with env.factory() as db:
            job = db.get(m.ExecutionJob, first.json()['executionId'])
            frozen = deepcopy(job.payload['judge_contract'])
            assert frozen['kind'] == 'measured-v1'
            assert frozen['profile']['run']['cpuMs'] == 1000
            assert 'evidence' not in frozen
            problem = db.get(m.Problem, problem_id)
            # Administrative change after receipt, including invalidating
            # current policy, cannot invalidate the idempotent receipt.
            problem.judge_policy = UNREVIEWED
            db.commit()
        retry = await c.post(url, headers=auth, json=request)
        assert retry.status_code == first.status_code, retry.text
        assert retry.json()['executionId'] == first.json()['executionId']
        with env.factory() as db:
            assert db.get(m.ExecutionJob, first.json()['executionId']).payload['judge_contract'] == frozen


def test_legacy_and_draft_are_never_conflated():
    assert stored_policy(None, creating=True) == UNREVIEWED
    assert stored_policy(None, previous=None) is None
    legacy = freeze_stored_submission(None, 'python', SAMPLE, HIDDEN, settings=settings)
    assert legacy['kind'] == 'legacy-v1' and 'cpuMs' not in legacy
    with pytest.raises(ValueError):
        freeze_stored_submission(UNREVIEWED, 'python', SAMPLE, HIDDEN, settings=settings)


@pytest.mark.asyncio
async def test_old_runner_must_not_silently_ignore_measured_contract():
    with pytest.raises(RuntimeError, match='supervisor'):
        await judge_code(object(), {'judge_contract': {'kind': 'measured-v1'}})


def test_v12_additive_migration_preserves_v11_marker_and_legacy_data(replicas, monkeypatch):
    engine = replicas[0].kw['bind']
    with Session(engine) as db:
        db.add(m.User(id='admin-policy', username='admin-policy', hashed_password='', role='admin', total_score=321))
        db.flush()
        db.add(m.Problem(id='old-problem', creator_id='admin-policy', title='Keep exactly', difficulty='iron5',
                         tags=['io'], description='Legacy content', test_cases=SAMPLE, points=17))
        db.commit()
    with engine.begin() as c:
        c.execute(text('ALTER TABLE problems DROP COLUMN judge_policy'))
        c.execute(text('CREATE TABLE IF NOT EXISTS schema_migrations (version VARCHAR PRIMARY KEY)'))
        c.execute(text('INSERT INTO schema_migrations (version) VALUES (:v) ON CONFLICT (version) DO NOTHING'), {'v': LEARNING_SCHEMA_VERSION})
    def must_not_backfill(*_):
        pytest.fail('v12 must not rerun v11 progress backfill')
    monkeypatch.setattr('app.services.learning.backfill_progress', must_not_backfill)
    initialize(bind=engine, skip_bootstrap=True)
    initialize(bind=engine, skip_bootstrap=True)
    assert 'judge_policy' in {col['name'] for col in inspect(engine).get_columns('problems')}
    with engine.connect() as c:
        assert c.execute(text('SELECT COUNT(*) FROM schema_migrations WHERE version = :v'), {'v': RUNTIME_SCHEMA_VERSION}).scalar() == 1
    with Session(engine) as db:
        assert db.get(m.User, 'admin-policy').total_score == 321
        old = db.get(m.Problem, 'old-problem')
        assert (old.title, old.points, old.test_cases, old.judge_policy) == ('Keep exactly', 17, SAMPLE, None)


@pytest.mark.asyncio
async def test_contest_policy_snapshot_and_submission_use_original_limits(env):
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as c:
        body = payload(env)
        contest, problem = await setup_contest(c, env)
        root = '/api/v1/contests/' + contest['id']
        await c.post(root + '/join', headers=headers(env.alice))
        with env.factory() as db:
            source = db.get(m.Problem, problem['problemId'])
            source.judge_policy = UNREVIEWED
            db.commit()
        # Date edit before start retains the earlier policy even if its source
        # was changed independently. No evidence from today replaces old tests.
        body['problems'] = [{'problemId':problem['problemId'], 'points':500}]
        changed = await c.put(root, json=body, headers=headers(env.admin))
        assert changed.status_code == 200, changed.text
        problem = changed.json()['problems'][0]
        env.clock[0] += timedelta(seconds=10)
        url = root + '/problems/' + problem['id']
        detail = (await c.get(url, headers=headers(env.alice))).json()
        assert detail['judgeLimits']['languages']['python']['run']['cpuMs'] == 1000
        assert 'evidence' not in str(detail)
        response = await c.post(url + '/submit', headers=headers(env.alice), json=dict(code='print(42)', language='python', requestId='frozen'))
        assert response.status_code == 202, response.text
        with env.factory() as db:
            submission = db.get(m.ContestSubmission, response.json()['id'])
            job = db.get(m.ExecutionJob, submission.execution_job_id)
            assert job.payload['judge_contract']['profile']['run']['cpuMs'] == 1000
            assert job.payload['judge_contract']['revision'] == 1


def test_policy_version_cannot_be_rewritten_or_replaced_with_different_id():
    old = stored_policy(policy_fixture(), creating=True)
    same = stored_policy(policy_fixture(), previous=old)
    assert old == same
    for patch in ({'policyId':'replacement'}, {'preparationCleanupMs':2000}):
        with pytest.raises(ValueError, match='버전'):
            stored_policy({**policy_fixture(), **patch}, previous=old)
    assert stored_policy({**policy_fixture(), 'revision':2}, previous=old)['revision'] == 2


@pytest.mark.asyncio
async def test_legacy_receipt_settings_drift_cannot_be_silently_accepted(monkeypatch):
    contract = freeze_stored_submission(None, 'python', SAMPLE, HIDDEN, settings=settings)
    monkeypatch.setattr(settings, 'EXECUTION_TIMEOUT', settings.EXECUTION_TIMEOUT + 1)
    with pytest.raises(RuntimeError, match='exact measured'):
        await judge_code(object(), dict(judge_contract=contract, language='python', sample=SAMPLE, hidden=HIDDEN))


def test_v12_column_and_marker_roll_back_together(replicas, monkeypatch):
    engine = replicas[0].kw['bind']
    with engine.begin() as c:
        c.execute(text('ALTER TABLE problems DROP COLUMN judge_policy'))
    def failed_bootstrap(*_):
        raise RuntimeError('injected bootstrap failure')
    monkeypatch.setattr('app.initialize.bootstrap_application_data', failed_bootstrap)
    with pytest.raises(RuntimeError, match='injected'):
        initialize(bind=engine)
    assert 'judge_policy' not in {col['name'] for col in inspect(engine).get_columns('problems')}
