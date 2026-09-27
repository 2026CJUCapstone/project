import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.core.database import Base, get_db
from app.models import database as m
from app.api.routes import contests as routes
from app.services import contests as service, contest_access as access
from app.services.auth import create_access_token
from app.services import execution_runtime, durable_queue, compiler as compiler_service
from app.services.execution_worker import ExecutionWorker
from tests.execution_helpers import finish_receipt
from tests.test_judge_policy import policy_fixture
from app.models.judge_policy import SUPPORTED_LANGUAGES
from app.models.judge_test_manifest import MAX_TEST_DATA_BYTES
from app.core.config import settings
from app.services.judge_policy import content_hash, freeze_stored_submission
from app.services import problem_authoring


@pytest.fixture
def env(tmp_path, monkeypatch, contest_engine):
    engine = contest_engine
    from tests.test_judge_policy import install_synthetic_registry
    install_synthetic_registry(tmp_path,monkeypatch)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    db = factory()
    admin = m.User(id="admin", username="contest_admin", hashed_password="unused", role="admin")
    alice = m.User(id="alice", username="alice", hashed_password="unused", role="user")
    bob = m.User(id="bob", username="bob", hashed_password="unused", role="user")
    db.add_all([admin, alice, bob]); db.commit()
    clock = [datetime(2030, 1, 1, 0, 0)]
    for module in (routes, service, access, durable_queue):
        monkeypatch.setattr(module, "now_utc", lambda: clock[0])
    monkeypatch.setattr(service, "SessionLocal", factory)
    monkeypatch.setattr(execution_runtime, 'SessionLocal', factory)
    monkeypatch.setattr(execution_runtime.settings, 'JUDGE_WORKER_CLASS', 'test-cpu')
    monkeypatch.setattr(service, "invalidate_rating_cache", lambda *args: None)

    async def compile_ok(**kwargs):
        return {"exit_code": 0, "stdout": "", "stderr": "", "execution_time": 1}
    async def run_ok(**kwargs):
        return {"exit_code": 0, "stdout": "42", "stderr": "", "execution_time": 1}
    monkeypatch.setattr(compiler_service.compiler_instance, "_execute", compile_ok)
    monkeypatch.setattr(compiler_service.compiler_instance, "run", run_ok)
    # These tests verify contest transactions/ranking, not cgroup enforcement.
    # Keep their existing fake compiler explicit. The real dispatcher must
    # refuse measured jobs until a capable supervisor is installed (separate test).
    from app.services.judging import _judge_cases
    from app.services.judge_metrics import JudgeMetrics
    from tests.test_judge_metrics import phase_result
    async def mock_resource_judge(runner, payload, *, contest=False):
        class MeteredRunner:
            async def _execute(self, **kwargs):
                value = await runner._execute(**kwargs)
                protected = phase_result('compile', exitCode=value.get('exit_code', 0),
                    failureReason=value.get('failure_reason'))
                return {**value, 'execution_phase':'compile',
                    'resource_usage':protected['resource_usage']}

            async def run(self, **kwargs):
                value = await runner.run(**kwargs)
                protected = phase_result('run', exitCode=value.get('exit_code', 0),
                    failureReason=value.get('failure_reason'))
                return {**value, 'execution_phase':'run',
                    'resource_usage':protected['resource_usage']}

        metrics = JudgeMetrics(payload)
        result = await _judge_cases(MeteredRunner(), payload, contest=contest, metrics=metrics)
        result['_resource_report'] = metrics.finish()
        return result
    monkeypatch.setattr('app.services.execution_worker.judge_code', mock_resource_judge)
    def worker():
        return ExecutionWorker(execution_runtime.execution_queue(),
            pool=SimpleNamespace(labels=lambda *args:{}, reap=lambda *args:None),
            runner_factory=lambda **kwargs:compiler_service.compiler_instance)
    import app.main as main
    monkeypatch.setattr(main, 'build_worker', worker)
    def session_override():
        with factory() as session:
            yield session
    app.dependency_overrides[get_db] = session_override
    try:
        yield SimpleNamespace(db=db, factory=factory, clock=clock, admin=admin, alice=alice, bob=bob, worker=worker)
    finally:
        app.dependency_overrides.clear()
        db.close()


def headers(user):
    return {"Authorization": f"Bearer {create_access_token({'sub': user.username})}"}


def payload(env):
    result = {"title": "Test contest", "description": "Rules", "published": True,
            "startsAt": access.iso(env.clock[0] + timedelta(seconds=10)), "endsAt": access.iso(env.clock[0] + timedelta(seconds=100)),
            "problems": [{"points": 500, "newProblem": {"title": "Secret problem", "description": "Print 42", "difficulty": "iron5",
                "tags": ["io"], "points": 120, "testCases": [{"input": "", "expectedOutput": "42"}],
                "hiddenTestCases": [{"input": "secret-input", "expectedOutput": "42"}]}}]}
    problem = result['problems'][0]['newProblem']
    problem['judgePolicy'] = policy_fixture(problem['testCases'], problem['hiddenTestCases'], SUPPORTED_LANGUAGES)
    return result


async def authorize_private_contest(client, env, contest, *, publish=True):
    """Install synthetic review/runner evidence for unrelated contest tests."""
    with env.factory() as db:
        row = db.query(m.ContestProblem).filter_by(contest_id=contest['id']).one()
        digest = 'sha256:' + 'a' * 64
        metadata = {
            'sources': [{'url':'https://example.invalid/synthetic','title':'Synthetic fixture',
                'author':'','event':'','reuseBasis':'original','reuseEvidence':'Unit-test fixture only',
                'externalTier':None,'tierCheckedAt':None}],
            'adaptationNotes':'Synthetic contest transaction fixture only',
            'requiredLanguages':['python'],
            'assets': [
                {'role':'reference','name':'reference.py','digest':digest,'language':'python'},
                {'role':'validator','name':'validator.py','digest':'sha256:'+'b'*64},
                {'role':'generator','name':'generator.py','digest':'sha256:'+'c'*64},
                {'role':'wrong_solution','name':'wrong.py','digest':'sha256:'+'d'*64},
            ],
        }
        db.add(m.ProblemAuthoring(problem_id=row.problem_id, metadata_json=metadata))
        db.flush()
        snap = problem_authoring.current_snapshot(db, db.get(m.Problem, row.problem_id))
        stamp = problem_authoring.fingerprint(snap)
        for sequence, category in enumerate(problem_authoring.CATEGORIES, 1):
            db.add(m.ProblemReviewEvent(problem_id=row.problem_id, actor_id=env.admin.id,
                request_id=f'{contest["id"]}-{category}', request_hash=f'fixture-{category}',
                fingerprint=stamp, category=category, decision='approved',
                note='Synthetic fixture approval only', sequence=sequence))
        contract = freeze_stored_submission(snap['judgePolicy'], 'python', snap['sample'], snap['hidden'], settings=settings)
        db.add(m.ProblemValidationAttestation(job_id='fixture-'+contest['id'],
            problem_id=row.problem_id, contest_id=contest['id'], contest_problem_id=row.id,
            problem_snapshot_hash=content_hash(snap), authoring_fingerprint=stamp,
            language='python', source_hash=digest, reference_asset_digest=digest,
            policy_hash=contract['policyHash'], test_suite_hash=contract['testSuiteHash']))
        db.commit()
    manage = (await client.get(f"/api/v1/contests/{contest['id']}/manage", headers=headers(env.admin))).json()
    if not publish:
        return manage
    publish = payload(env); publish['problems'] = manage['problems']; publish['published'] = True
    response = await client.put(f"/api/v1/contests/{contest['id']}", headers=headers(env.admin), json=publish)
    assert response.status_code == 200, response.text
    return response.json()


async def setup_contest(client, env, *, join=True):
    draft = payload(env); draft['published'] = False
    response = await client.post('/api/v1/contests', headers=headers(env.admin), json=draft)
    assert response.status_code == 201, response.text
    contest = await authorize_private_contest(client, env, response.json())
    if join:
        for user in (env.alice, env.bob):
            assert (await client.post(f"/api/v1/contests/{contest['id']}/join", headers=headers(user))).status_code == 200
    return contest, contest["problems"][0]


@pytest.mark.asyncio
@pytest.mark.parametrize('target', ['contest', 'practice'])
@pytest.mark.parametrize('field,value', [
    ('cpuMs', 300_000), ('wallMs', 300_000),
    ('memoryBytes', 8 * 1024**3), ('pids', 4096),
    ('judgePolicy', {'run': {'cpuMs': 300_000}}),
])
async def test_submit_http_rejects_client_resource_overrides_before_enqueue(env, target, field, value):
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        contest, problem = await setup_contest(client, env)
        if target == 'contest':
            env.clock[0] += timedelta(seconds=10)
            url = f"/api/v1/contests/{contest['id']}/problems/{problem['id']}/submit"
            valid = {'code': 'print(42)', 'language': 'python', 'requestId': 'override-check'}
        else:
            env.clock[0] += timedelta(seconds=101)
            service.finalize_contests()
            url = f"/api/v1/problems/{problem['problemId']}/submit"
            valid = {'code': 'print(42)', 'language': 'python'}
        before = tuple(env.db.query(model).count() for model in
                       (m.ExecutionJob, m.ContestSubmission, m.Submission))
        rejected = await client.post(url, headers=headers(env.alice), json={**valid, field: value})
        assert rejected.status_code == 422, rejected.text
        env.db.expire_all()
        assert tuple(env.db.query(model).count() for model in
                     (m.ExecutionJob, m.ContestSubmission, m.Submission)) == before
        admitted = await client.post(url, headers=headers(env.alice), json=valid)
        assert admitted.status_code == 202, admitted.text
        env.db.expire_all()
        job_id = admitted.json()['id' if target == 'contest' else 'executionId']
        if target == 'contest':
            job_id = env.db.get(m.ContestSubmission, job_id).execution_job_id
        job = env.db.get(m.ExecutionJob, job_id)
        assert job is not None and job.payload['judge_contract']['profile']['run']['cpuMs'] < 300_000


@pytest.mark.asyncio
async def test_visibility_permissions_and_publication(env):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.post('/api/v1/contests', headers=headers(env.alice), json=payload(env))).status_code == 403
        assert (await c.post('/api/v1/contests', headers=headers(env.admin), json=payload(env))).status_code == 409
        contest, p = await setup_contest(c, env)
        root = f"/api/v1/contests/{contest['id']}"
        assert (await c.get(root)).json()["problems"] == []
        assert (await c.get(f"{root}/problems/{p['id']}", headers=headers(env.alice))).status_code == 403
        assert (await c.get(f"/api/v1/problems/{p['problemId']}")).status_code == 404
        assert (await c.get('/api/v1/problems/')).json() == []
        assert (await c.get('/api/v1/community/posts', params={"problemId": p['problemId']})).status_code == 404
        assert (await c.post('/api/v1/compiler/compile', json={"language":"python", "code":"print(42)", "problemId":p['problemId']})).status_code == 404
        env.clock[0] += timedelta(seconds=10)
        detail = await c.get(f"{root}/problems/{p['id']}", headers=headers(env.alice))
        assert detail.status_code == 200
        assert 'secret-input' not in detail.text
        assert (await c.get(f"{root}/problems/{p['id']}")).status_code == 403
        assert (await c.post(f"/api/v1/problems/{p['problemId']}/submit", json={"language":"python", "code":"print(42)"})).status_code == 404
        env.clock[0] += timedelta(seconds=90)
        assert (await c.get(f"/api/v1/problems/{p['problemId']}")).status_code == 200
        assert 'secret-input' not in (await c.get(f"/api/v1/problems/{p['problemId']}")).text
        assert len((await c.get('/api/v1/problems/')).json()) == 1
        assert (await c.delete(f"/api/v1/problems/{p['problemId']}", headers=headers(env.admin))).status_code == 409


@pytest.mark.asyncio
async def test_deadline_idempotency_and_late_judging(env):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        contest, p = await setup_contest(c, env)
        root = f"/api/v1/contests/{contest['id']}"
        url = f"{root}/problems/{p['id']}/submit"
        body = {"code":"print(42)", "language":"python", "requestId":"attempt"}
        assert (await c.post(url, headers=headers(env.alice), json=body)).status_code == 403
        env.clock[0] += timedelta(seconds=99, microseconds=999999)
        response = await c.post(url, headers=headers(env.alice), json=body)
        assert response.status_code == 202
        assert response.json()['status'] == 'queued'
        env.clock[0] += timedelta(microseconds=1)
        assert (await c.post(url, headers=headers(env.alice), json={**body,"requestId":"late"})).status_code == 403
        assert (await c.post(url, headers=headers(env.alice), json=body)).json()['id'] == response.json()['id']
        assert (await c.post(url, headers=headers(env.alice), json={**body,"code":"different"})).status_code == 409
        service.finalize_contests()
        assert (await c.get(root)).json()['state'] == 'finalizing'
        assert await env.worker().run_once()
        service.finalize_contests(); service.finalize_contests()
        assert (await c.get(root)).json()['state'] == 'finished'
        env.db.expire_all()
        assert env.db.get(m.User, 'alice').total_score == 120
        assert env.db.query(m.UserProblemScore).count() == 1
        submission_url = f"{root}/submissions/{response.json()['id']}"
        owner_submission = await c.get(submission_url, headers=headers(env.alice))
        assert owner_submission.status_code == 200
        assert owner_submission.headers['cache-control'] == 'no-store'
        assert owner_submission.json()['code'] == body['code']
        assert (await c.get(submission_url, headers=headers(env.bob))).status_code == 404
        async with AsyncClient(transport=ASGITransport(app=app, root_path='/webcompiler'), base_url='http://test') as prefixed:
            prefixed_submission = await prefixed.get(submission_url, headers=headers(env.alice))
        assert prefixed_submission.status_code == 200
        assert prefixed_submission.headers['cache-control'] == 'no-store'
        assert prefixed_submission.json()['code'] == body['code']
        assert (await c.get(f"{root}/scoreboard")).json()['rows'][0]['totalPoints'] == 500


@pytest.mark.asyncio
async def test_snapshot_and_edit_lock(env):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        public = m.Problem(creator_id='admin', title='Original', description='old', difficulty='iron5', tags=[], points=50,
                           test_cases=[{"input":"", "expectedOutput":"42"}])
        env.db.add(public); env.db.commit()
        data = payload(env); data['problems'] = [{"problemId":public.id, "points":200}]
        response = await c.post('/api/v1/contests', headers=headers(env.admin), json=data)
        assert response.status_code == 201
        contest = response.json(); p = contest['problems'][0]
        public.title='Changed'; env.db.commit()
        assert (await c.get(f"/api/v1/contests/{contest['id']}/problems/{p['id']}",headers=headers(env.admin))).json()['title']=='Original'
        data['title'] = 'Changed schedule/title only'
        updated = await c.put(f"/api/v1/contests/{contest['id']}",headers=headers(env.admin),json=data)
        assert updated.status_code == 200
        assert updated.json()['problems'][0]['title'] == 'Original'
        env.clock[0] += timedelta(seconds=10)
        data['startsAt'] = access.iso(env.clock[0]+timedelta(seconds=100))
        data['endsAt'] = access.iso(env.clock[0]+timedelta(seconds=200))
        assert (await c.put(f"/api/v1/contests/{contest['id']}",headers=headers(env.admin),json=data)).status_code == 409


@pytest.mark.asyncio
async def test_existing_problem_cannot_bypass_contest_test_suite_bounds(env):
    # Existing public problems bypass ProblemCreate validation when selected by
    # ID. Publication must still check the frozen snapshot before committing.
    public = m.Problem(creator_id='admin', title='Legacy tests', description='old',
                       difficulty='iron5', tags=[], points=50,
                       test_cases=[{'input':'', 'expectedOutput':'42'}] * 201)
    env.db.add(public); env.db.commit()
    data = payload(env)
    data['problems'] = [{'problemId':public.id, 'points':200}]
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as c:
        excessive_count = await c.post('/api/v1/contests', headers=headers(env.admin), json=data)
        assert excessive_count.status_code == 400
        assert env.db.query(m.Contest).count() == 0

        public.test_cases = [{'input':'x' * (MAX_TEST_DATA_BYTES + 1), 'expectedOutput':'42'}]
        env.db.commit()
        excessive_data = await c.post('/api/v1/contests', headers=headers(env.admin), json=data)
        assert excessive_data.status_code == 400
        assert env.db.query(m.Contest).count() == 0

        public.test_cases = [{'input':'', 'expectedOutput':'42'}] * 200
        env.db.commit()
        at_limit = await c.post('/api/v1/contests', headers=headers(env.admin), json=data)
        assert at_limit.status_code == 201, at_limit.text


@pytest.mark.asyncio
async def test_invalid_draft_update_rolls_back_replacement_and_private_cleanup(env):
    draft_body = payload(env)
    draft_body['published'] = False
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as c:
        created = await c.post('/api/v1/contests', headers=headers(env.admin), json=draft_body)
        assert created.status_code == 201, created.text
        contest = created.json()
        root = f"/api/v1/contests/{contest['id']}"
        private_problem_id = contest['problems'][0]['problemId']

        with env.factory() as db:
            db.add(m.ProblemAuthoring(problem_id=private_problem_id, metadata_json={
                'sources': [{'url': 'https://example.invalid/source', 'title': 'Source',
                             'author': '', 'event': '', 'reuseBasis': 'pending',
                             'reuseEvidence': '', 'externalTier': None, 'tierCheckedAt': None}],
                'adaptationNotes': 'Preserve this private authoring record on rollback.',
                'assets': [],
                'requiredLanguages': ['python'],
            }))
            bad_public = m.Problem(
                creator_id=env.admin.id,
                title='Invalid legacy suite',
                description='Must fail during the transactional replacement.',
                difficulty='iron5',
                tags=[],
                points=50,
                test_cases=[{'input': str(index), 'expectedOutput': str(index)} for index in range(201)],
            )
            db.add(bad_public)
            db.commit()
            bad_public_id = bad_public.id

        manage = await c.get(root + '/manage', headers=headers(env.admin))
        assert manage.status_code == 200
        original_edit_problems = manage.json()['problems']
        with env.factory() as db:
            original_contest = db.get(m.Contest, contest['id'])
            original_fields = (
                original_contest.title,
                original_contest.description,
                original_contest.starts_at,
                original_contest.ends_at,
                original_contest.published,
                original_contest.scoreboard_revision,
            )
            original_rows = [
                (row.id, row.problem_id, row.position, row.points, row.is_new, deepcopy(row.snapshot))
                for row in service.problem_rows(db, contest['id'])
            ]
            original_authoring = deepcopy(db.get(m.ProblemAuthoring, private_problem_id).metadata_json)
            original_counts = {
                'problems': db.query(m.Problem).count(),
                'authoring': db.query(m.ProblemAuthoring).count(),
                'mappings': db.query(m.ContestProblem).count(),
            }

        invalid_update = {
            **draft_body,
            'title': 'This title must roll back',
            'description': 'This description must roll back',
            'startsAt': access.iso(env.clock[0] + timedelta(minutes=20)),
            'endsAt': access.iso(env.clock[0] + timedelta(hours=3)),
            'problems': [
                original_edit_problems[0],
                {'problemId': bad_public_id, 'points': 300},
            ],
        }
        rejected = await c.put(root, headers=headers(env.admin), json=invalid_update)
        assert rejected.status_code == 400, rejected.text

        # A new session is essential: the failed request deleted and flushed the
        # old mappings before it reached the invalid existing problem suite.
        with env.factory() as db:
            rolled_back_contest = db.get(m.Contest, contest['id'])
            assert (
                rolled_back_contest.title,
                rolled_back_contest.description,
                rolled_back_contest.starts_at,
                rolled_back_contest.ends_at,
                rolled_back_contest.published,
                rolled_back_contest.scoreboard_revision,
            ) == original_fields
            rolled_back_rows = [
                (row.id, row.problem_id, row.position, row.points, row.is_new, deepcopy(row.snapshot))
                for row in service.problem_rows(db, contest['id'])
            ]
            assert rolled_back_rows == original_rows
            assert db.get(m.Problem, private_problem_id) is not None
            assert db.get(m.ProblemAuthoring, private_problem_id).metadata_json == original_authoring
            assert {
                'problems': db.query(m.Problem).count(),
                'authoring': db.query(m.ProblemAuthoring).count(),
                'mappings': db.query(m.ContestProblem).count(),
            } == original_counts

        valid_update = {**draft_body, 'problems': original_edit_problems}
        saved = await c.put(root, headers=headers(env.admin), json=valid_update)
        assert saved.status_code == 200, saved.text


def test_scoring_first_accept_penalties_ties_and_no_duplicate_rewards(env):
    start = env.clock[0]
    contest = m.Contest(id='c',creator_id='admin',title='Contest',description='',starts_at=start,ends_at=start+timedelta(hours=2),published=True)
    env.db.add(contest)
    for i in range(2):
        env.db.add(m.Problem(id=f'p{i}', creator_id='admin', title='P', description='', difficulty='iron5', tags=[],points=100,test_cases=[]))
    env.db.flush()  # Persist parents before FK-only links; SQLite hid this ordering bug.
    for i in range(2):
        env.db.add(m.ContestProblem(id=f'cp{i}',contest_id='c',problem_id=f'p{i}',position=i,points=500,is_new=False,snapshot={'practicePoints':100}))
    for user in ('alice','bob'):
        env.db.add(m.ContestParticipant(contest_id='c',user_id=user))
    env.db.flush()
    def add(user, problem, minute, verdict):
        env.db.add(m.ContestSubmission(contest_id='c',contest_problem_id=problem,user_id=user,request_id=f'{user}{problem}{minute}',
            language='python',code='',received_at=start+timedelta(minutes=minute),status='completed',verdict=verdict))
    add('alice','cp0',30,'accepted')  # Insert out of order to exercise receipt-based scoring.
    add('alice','cp0',1,'compile_error'); add('alice','cp0',2,'system_error')
    add('alice','cp0',5,'wrong_answer'); add('alice','cp0',20,'accepted')
    add('alice','cp0',25,'wrong_answer'); add('alice','cp1',2,'wrong_answer')
    add('bob','cp0',25,'accepted')
    env.db.add(m.UserProblemScore(user_id='alice',challenge_id='p0',points_awarded=100))
    env.db.get(m.User,'alice').total_score = 100
    env.db.commit()
    board = service.scoreboard(env.db,contest)
    assert [r['rank'] for r in board['rows']] == [1,1]
    assert all(r['penaltySeconds']==1500 and r['totalPoints']==500 for r in board['rows'])
    env.clock[0] += timedelta(hours=2)
    service.finalize_contests(); service.finalize_contests(); env.db.expire_all()
    assert env.db.get(m.User,'alice').total_score==100
    assert env.db.get(m.User,'bob').total_score==100


def test_finalizer_exception_rolls_back_claim_awards_evidence_and_revision(env, monkeypatch):
    finished = env.clock[0] - timedelta(seconds=1)
    with env.factory() as db:
        db.add(m.Contest(
            id='atomic-finalize', creator_id=env.admin.id, title='Atomic finalize', description='',
            starts_at=finished - timedelta(hours=1), ends_at=finished, published=True,
        ))
        db.add(m.Problem(
            id='atomic-problem', creator_id=env.admin.id, title='Atomic problem', description='',
            difficulty='iron5', tags=[], points=100, test_cases=[],
        ))
        db.flush()
        db.add(m.ContestProblem(
            id='atomic-contest-problem', contest_id='atomic-finalize', problem_id='atomic-problem',
            position=0, points=500, is_new=False, snapshot={'practicePoints': 100},
        ))
        db.add(m.ContestParticipant(contest_id='atomic-finalize', user_id=env.alice.id))
        db.flush()
        db.add(m.ContestSubmission(
            id='atomic-accepted', contest_id='atomic-finalize',
            contest_problem_id='atomic-contest-problem', user_id=env.alice.id,
            request_id='atomic-finalize-request', language='python', code='print(42)',
            received_at=finished - timedelta(minutes=1), status='completed', verdict='accepted',
        ))
        db.commit()

    original_bump = service.bump_scoreboard_revision

    def fail_after_awards(_db, _contest_id):
        raise RuntimeError('injected finalizer failure before commit')

    monkeypatch.setattr(service, 'bump_scoreboard_revision', fail_after_awards)
    with pytest.raises(RuntimeError, match='injected finalizer failure'):
        service.finalize_contests()

    with env.factory() as db:
        contest = db.get(m.Contest, 'atomic-finalize')
        assert contest.finalized_at is None
        assert contest.scoreboard_revision == 0
        assert db.get(m.User, env.alice.id).total_score == 0
        assert db.query(m.UserProblemScore).filter_by(
            user_id=env.alice.id, challenge_id='atomic-problem'
        ).count() == 0
        assert db.query(m.SolveEvidence).filter_by(
            user_id=env.alice.id, problem_id='atomic-problem'
        ).count() == 0

    monkeypatch.setattr(service, 'bump_scoreboard_revision', original_bump)
    service.finalize_contests()
    service.finalize_contests()

    with env.factory() as db:
        contest = db.get(m.Contest, 'atomic-finalize')
        assert contest.finalized_at == env.clock[0]
        assert contest.scoreboard_revision == 1
        assert db.get(m.User, env.alice.id).total_score == 100
        score = db.query(m.UserProblemScore).filter_by(
            user_id=env.alice.id, challenge_id='atomic-problem'
        ).one()
        assert score.points_awarded == 100
        evidence = db.query(m.SolveEvidence).filter_by(
            user_id=env.alice.id, problem_id='atomic-problem'
        ).one()
        assert evidence.source_kind == 'contest'
        assert evidence.source_id == 'atomic-accepted'
        assert db.query(m.UserProblemScore).filter_by(
            user_id=env.alice.id, challenge_id='atomic-problem'
        ).count() == 1
        assert db.query(m.SolveEvidence).filter_by(
            user_id=env.alice.id, problem_id='atomic-problem'
        ).count() == 1


@pytest.mark.asyncio
async def test_expired_lease_recovery_and_compile_error(env, monkeypatch):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        contest,p=await setup_contest(c,env)
        env.clock[0] += timedelta(seconds=10)
        r=await c.post(f"/api/v1/contests/{contest['id']}/problems/{p['id']}/submit",headers=headers(env.alice),
                       json={'language':'java','code':'invalid','requestId':'a'})
        assert r.status_code==202
        queue = env.worker().queue
        original=queue.claim()
        assert queue.claim() is None
        env.clock[0] += timedelta(seconds=121)
        recovered=queue.claim()
        assert recovered.id==original.id and recovered.token!=original.token
        async def broken(**kwargs):
            return {'exit_code':1,'stderr':'syntax error','stdout':'','execution_time':1}
        monkeypatch.setattr(compiler_service.compiler_instance,'_execute',broken)
        assert not queue.finish(original.id, original.token, {'verdict':'accepted'})
        result = await env.worker()._execute(recovered)
        assert queue.finish(recovered.id, recovered.token, result)
        env.db.expire_all()
        record=env.db.get(m.ContestSubmission,r.json()['id'])
        assert record.status=='completed' and record.verdict=='compile_error'
        assert service.scoreboard(env.db,env.db.get(m.Contest,contest['id']))['rows'][0]['penaltySeconds']==0


@pytest.mark.asyncio
@pytest.mark.parametrize('language', ['bpp', 'c', 'cpp', 'python', 'java', 'javascript'])
async def test_exact_start_late_join_and_language_routing(env, monkeypatch, language):
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as c:
        contest, p = await setup_contest(c, env, join=False)
        root = f"/api/v1/contests/{contest['id']}"
        url = f"{root}/problems/{p['id']}/submit"
        body = {'code':'solution', 'language':language, 'requestId':'start'}
        env.clock[0] += timedelta(seconds=10)
        assert (await c.post(url, headers=headers(env.alice), json=body)).status_code == 403
        assert (await c.post(root+'/join', headers=headers(env.alice))).status_code == 200
        result = await c.post(url, headers=headers(env.alice), json=body)
        assert result.status_code == 202
        calls = []
        async def execute(**kwargs):
            calls.append(kwargs)
            return {'exit_code':0, 'stdout':'42', 'stderr':'', 'execution_time':1}
        monkeypatch.setattr(compiler_service.compiler_instance, '_execute', execute)
        monkeypatch.setattr(compiler_service.compiler_instance, 'run', execute)
        assert await env.worker().run_once()
        assert len(calls) == 3 and all(call['language'] == language for call in calls)
        board = (await c.get(root+'/scoreboard')).json()
        assert board['rows'][0]['penaltySeconds'] == 0
        assert board['rows'][0]['totalPoints'] == 500
        env.clock[0] += timedelta(seconds=1)
        assert (await c.post(root+'/join', headers=headers(env.bob))).status_code == 200
        assert (await c.get(root, headers=headers(env.bob))).json()['endsAt'] == contest['endsAt']


@pytest.mark.asyncio
async def test_system_retry_and_shutdown_recovery(env, monkeypatch):
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as c:
        contest, p = await setup_contest(c, env)
        env.clock[0] += timedelta(seconds=10)
        url = f"/api/v1/contests/{contest['id']}/problems/{p['id']}/submit"
        response = await c.post(url, headers=headers(env.alice), json={'code':'x','language':'python','requestId':'retry'})
        started = asyncio.Event()
        async def blocked(**kwargs):
            started.set()
            await asyncio.Event().wait()
        monkeypatch.setattr(compiler_service.compiler_instance, '_execute', blocked)
        task = asyncio.create_task(env.worker().run_once())
        await started.wait(); task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        env.db.expire_all()
        assert env.db.get(m.ContestSubmission, response.json()['id']).status == 'running'
        # Cancellation never releases capacity by assumption. The next worker
        # first reaps this expired claim, then retries the persisted receipt.
        env.clock[0] += timedelta(seconds=121)
        async def unavailable(**kwargs):
            raise RuntimeError('sandbox unavailable')
        monkeypatch.setattr(compiler_service.compiler_instance, '_execute', unavailable)
        assert await env.worker().run_once()
        env.db.expire_all()
        assert env.db.get(m.ContestSubmission, response.json()['id']).status == 'queued'
        assert await env.worker().run_once()
        env.db.expire_all()
        record = env.db.get(m.ContestSubmission, response.json()['id'])
        assert record.status == 'completed' and record.verdict == 'system_error'


@pytest.mark.asyncio
async def test_draft_edit_publish_and_no_hidden_metadata(env):
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as c:
        data = payload(env); data['published'] = False
        contest = (await c.post('/api/v1/contests', headers=headers(env.admin), json=data)).json()
        root = f"/api/v1/contests/{contest['id']}"
        assert (await c.get(root)).status_code == 404
        assert (await c.get('/api/v1/contests')).json() == []
        manage_response = await c.get(root+'/manage',headers=headers(env.admin))
        assert manage_response.status_code == 200
        assert manage_response.headers['cache-control'] == 'no-store'
        manage = manage_response.json()
        assert manage['problems'][0]['contestProblemId'] == contest['problems'][0]['id']
        assert manage['problems'][0]['newProblem']['hiddenTestCases'][0]['input'] == 'secret-input'
        async with AsyncClient(transport=ASGITransport(app=app, root_path='/webcompiler'), base_url='http://test') as prefixed:
            prefixed_manage = await prefixed.get(root+'/manage', headers=headers(env.admin))
        assert prefixed_manage.status_code == 200
        assert prefixed_manage.headers['cache-control'] == 'no-store'
        assert prefixed_manage.json()['problems'][0]['newProblem']['hiddenTestCases'][0]['input'] == 'secret-input'
        data['problems'] = manage['problems']
        data['problems'][0]['newProblem']['title'] = 'Revised secret'
        revised = await c.put(root,headers=headers(env.admin),json=data)
        assert revised.status_code == 200, revised.text
        authorized = await authorize_private_contest(c, env, revised.json(), publish=False)
        data['problems'] = authorized['problems']; data['published'] = True
        assert (await c.put(root,headers=headers(env.admin),json=data)).status_code == 200
        assert 'Revised secret' not in (await c.get(root)).text
        assert 'secret-input' not in (await c.get(root+'/scoreboard')).text
        assert (await c.get(root+'/manage',headers=headers(env.alice))).status_code == 403
        assert (await c.get('/api/v1/contests/library',headers=headers(env.admin))).json() == []
        env.clock[0] += timedelta(seconds=100)
        service.finalize_contests(); service.finalize_contests()
        assert (await c.get(root)).json()['state'] == 'finished'
        listed = (await c.get('/api/v1/problems/')).json()
        assert listed[0]['title'] == 'Revised secret' and 'secret-input' not in str(listed)


@pytest.mark.asyncio
async def test_practice_judging_racing_contest_award(env, monkeypatch):
    from app.api.routes import problems as practice
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as c:
        contest, p = await setup_contest(c, env)
        env.clock[0] += timedelta(seconds=10)
        await c.post(f"/api/v1/contests/{contest['id']}/problems/{p['id']}/submit",headers=headers(env.alice),
                     json={'code':'print(42)','language':'python','requestId':'a'})
        assert await env.worker().run_once()
        env.clock[0] += timedelta(seconds=90)
        async def practice_case(**kwargs):
            # Another DB session finalizes after practice checked already_solved.
            service.finalize_contests()
            return {'exit_code':0,'stdout':'42','stderr':'','execution_time':1}
        monkeypatch.setattr(compiler_service.compiler_instance, 'run', practice_case)
        response = await c.post(f"/api/v1/problems/{p['problemId']}/submit", headers=headers(env.alice),
                                json={'code':'print(42)','language':'python'})
        result = await finish_receipt(c, response, headers=headers(env.alice))
        assert result['value']['status'] == 'Accepted'
        env.db.expire_all()
        assert env.db.get(m.User,'alice').total_score == 120
        assert env.db.query(m.UserProblemScore).count() == 1


@pytest.mark.asyncio
async def test_lifespan_recovers_queue_and_repeated_finalization(env):
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as c:
        contest, p = await setup_contest(c, env)
        env.clock[0] += timedelta(seconds=10)
        url = f"/api/v1/contests/{contest['id']}/problems/{p['id']}/submit"
        body = {'code':'print(42)','language':'python','requestId':'same-request'}
        results = await asyncio.gather(*(c.post(url, headers=headers(env.alice), json=body) for _ in range(2)))
        assert all(r.status_code == 202 for r in results)
        assert results[0].json()['id'] == results[1].json()['id']
        env.clock[0] += timedelta(seconds=90)
        # Persisted queued submissions exist before application startup.
        async with app.router.lifespan_context(app):
            async with asyncio.timeout(8):
                while (await c.get(f"/api/v1/contests/{contest['id']}")).json()['state'] != 'finished':
                    await asyncio.sleep(.05)
        async with app.router.lifespan_context(app):
            await asyncio.sleep(.1)
        env.db.expire_all()
        assert env.db.query(m.ContestSubmission).count() == 1
        assert env.db.query(m.UserProblemScore).count() == 1
        assert env.db.get(m.User,'alice').total_score == 120


@pytest.mark.asyncio
async def test_predeadline_receipt_waiting_on_finalizer(env, monkeypatch):
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as c:
        contest, p = await setup_contest(c, env)
        receipt = env.clock[0] + timedelta(seconds=99, microseconds=999999)
        env.clock[0] += timedelta(seconds=100)
        service.finalize_contests()
        assert (await c.get(f"/api/v1/contests/{contest['id']}")).json()['state'] == 'finished'
        # The handler captured receipt before the deadline, then waited on DB.
        monkeypatch.setattr(routes, 'now_utc', lambda: receipt)
        result = await c.post(f"/api/v1/contests/{contest['id']}/problems/{p['id']}/submit",headers=headers(env.alice),
                             json={'code':'print(42)','language':'python','requestId':'delayed-admission'})
        assert result.status_code == 202
        assert (await c.get(f"/api/v1/contests/{contest['id']}")).json()['state'] == 'finalizing'
        assert await env.worker().run_once()
        service.finalize_contests(); service.finalize_contests()
        env.db.expire_all()
        assert env.db.get(m.User,'alice').total_score == 120
