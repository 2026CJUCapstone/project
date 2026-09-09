import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.core.database import Base, get_db
from app.models import database as m
from app.api.routes import contests as routes
from app.services import contests as service, contest_access as access
from app.services.auth import create_access_token


@pytest.fixture
def env(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{(tmp_path / 'contest.db').as_posix()}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    db = factory()
    admin = m.User(id="admin", username="contest_admin", hashed_password="unused", role="admin")
    alice = m.User(id="alice", username="alice", hashed_password="unused", role="user")
    bob = m.User(id="bob", username="bob", hashed_password="unused", role="user")
    db.add_all([admin, alice, bob]); db.commit()
    clock = [datetime(2030, 1, 1, 0, 0)]
    for module in (routes, service, access):
        monkeypatch.setattr(module, "now_utc", lambda: clock[0])
    monkeypatch.setattr(service, "SessionLocal", factory)
    monkeypatch.setattr(service, "invalidate_rating_cache", lambda *args: None)

    async def queued(**kwargs):
        assert not any(kwargs.get(k) for k in ('user_id', 'username', 'problem_id', 'problem_title'))
        return await kwargs["task"]()
    monkeypatch.setattr(service, "compile_queue", SimpleNamespace(run=queued))
    async def compile_ok(**kwargs):
        return {"exit_code": 0, "stdout": "", "stderr": "", "execution_time": 1}
    async def run_ok(**kwargs):
        return {"exit_code": 0, "stdout": "42", "stderr": "", "execution_time": 1}
    monkeypatch.setattr(service.compiler_service.compiler_instance, "_execute", compile_ok)
    monkeypatch.setattr(service.compiler_service.compiler_instance, "run", run_ok)
    def session_override():
        with factory() as session:
            yield session
    app.dependency_overrides[get_db] = session_override
    yield SimpleNamespace(db=db, factory=factory, clock=clock, admin=admin, alice=alice, bob=bob)
    app.dependency_overrides.clear()
    db.close(); engine.dispose()


def headers(user):
    return {"Authorization": f"Bearer {create_access_token({'sub': user.username})}"}


def payload(env):
    return {"title": "Test contest", "description": "Rules", "published": True,
            "startsAt": access.iso(env.clock[0] + timedelta(seconds=10)), "endsAt": access.iso(env.clock[0] + timedelta(seconds=100)),
            "problems": [{"points": 500, "newProblem": {"title": "Secret problem", "description": "Print 42", "difficulty": "iron5",
                "tags": ["io"], "points": 120, "testCases": [{"input": "", "expectedOutput": "42"}],
                "hiddenTestCases": [{"input": "secret-input", "expectedOutput": "42"}]}}]}


async def setup_contest(client, env):
    response = await client.post('/api/v1/contests', headers=headers(env.admin), json=payload(env))
    assert response.status_code == 201, response.text
    contest = response.json()
    for user in (env.alice, env.bob):
        assert (await client.post(f"/api/v1/contests/{contest['id']}/join", headers=headers(user))).status_code == 200
    return contest, contest["problems"][0]


@pytest.mark.asyncio
async def test_visibility_permissions_and_publication(env):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.post('/api/v1/contests', headers=headers(env.alice), json=payload(env))).status_code == 403
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
        await service.judge_submission(*service.claim_submission())
        service.finalize_contests(); service.finalize_contests()
        assert (await c.get(root)).json()['state'] == 'finished'
        env.db.expire_all()
        assert env.db.get(m.User, 'alice').total_score == 120
        assert env.db.query(m.UserProblemScore).count() == 1
        assert (await c.get(f"{root}/submissions/{response.json()['id']}", headers=headers(env.bob))).status_code == 404
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


def test_scoring_first_accept_penalties_ties_and_no_duplicate_rewards(env):
    start = env.clock[0]
    contest = m.Contest(id='c',creator_id='admin',title='Contest',description='',starts_at=start,ends_at=start+timedelta(hours=2),published=True)
    env.db.add(contest)
    for i in range(2):
        env.db.add(m.Problem(id=f'p{i}', creator_id='admin', title='P', description='', difficulty='iron5', tags=[],points=100,test_cases=[]))
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


@pytest.mark.asyncio
async def test_expired_lease_recovery_and_compile_error(env, monkeypatch):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        contest,p=await setup_contest(c,env)
        env.clock[0] += timedelta(seconds=10)
        r=await c.post(f"/api/v1/contests/{contest['id']}/problems/{p['id']}/submit",headers=headers(env.alice),
                       json={'language':'java','code':'invalid','requestId':'a'})
        assert r.status_code==202
        original=service.claim_submission()
        assert service.claim_submission() is None
        env.clock[0] += timedelta(seconds=121)
        recovered=service.claim_submission()
        assert recovered[0]==original[0] and recovered[1]!=original[1]
        async def broken(**kwargs):
            return {'exit_code':1,'stderr':'syntax error','stdout':'','execution_time':1}
        monkeypatch.setattr(service.compiler_service.compiler_instance,'_execute',broken)
        await service.judge_submission(*original)  # stale worker must not write
        await service.judge_submission(*recovered)
        env.db.expire_all()
        record=env.db.get(m.ContestSubmission,original[0])
        assert record.status=='completed' and record.verdict=='compile_error'
        assert service.scoreboard(env.db,env.db.get(m.Contest,contest['id']))['rows'][0]['penaltySeconds']==0


@pytest.mark.asyncio
@pytest.mark.parametrize('language', ['bpp', 'c', 'cpp', 'python', 'java', 'javascript'])
async def test_exact_start_late_join_and_language_routing(env, monkeypatch, language):
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as c:
        response = await c.post('/api/v1/contests', headers=headers(env.admin), json=payload(env))
        contest = response.json(); p = contest['problems'][0]
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
        monkeypatch.setattr(service.compiler_service.compiler_instance, '_execute', execute)
        monkeypatch.setattr(service.compiler_service.compiler_instance, 'run', execute)
        await service.judge_submission(*service.claim_submission())
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
        monkeypatch.setattr(service.compiler_service.compiler_instance, '_execute', blocked)
        task = asyncio.create_task(service.judge_submission(*service.claim_submission()))
        await started.wait(); task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        env.db.expire_all()
        assert env.db.get(m.ContestSubmission, response.json()['id']).status == 'queued'
        async def unavailable(**kwargs):
            raise RuntimeError('sandbox unavailable')
        monkeypatch.setattr(service.compiler_service.compiler_instance, '_execute', unavailable)
        await service.judge_submission(*service.claim_submission())
        env.db.expire_all()
        assert env.db.get(m.ContestSubmission, response.json()['id']).status == 'queued'
        await service.judge_submission(*service.claim_submission())
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
        manage = (await c.get(root+'/manage',headers=headers(env.admin))).json()
        data['problems'] = manage['problems']; data['published'] = True
        data['problems'][0]['newProblem']['title'] = 'Revised secret'
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
        await service.judge_submission(*service.claim_submission())
        env.clock[0] += timedelta(seconds=90)
        async def practice_case(**kwargs):
            # Another DB session finalizes after practice checked already_solved.
            service.finalize_contests()
            return {'exit_code':0,'stdout':'42','stderr':'','execution_time':1}
        monkeypatch.setattr(practice, 'compile_queue', SimpleNamespace(run=practice_case))
        response = await c.post(f"/api/v1/problems/{p['problemId']}/submit", headers=headers(env.alice),
                                json={'code':'print(42)','language':'python'})
        assert response.status_code == 200, response.text
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
        await service.judge_submission(*service.claim_submission())
        service.finalize_contests(); service.finalize_contests()
        env.db.expire_all()
        assert env.db.get(m.User,'alice').total_score == 120
