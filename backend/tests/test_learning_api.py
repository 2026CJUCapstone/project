"""Real SQL/API permission, compare-and-swap, ranking and retention regressions."""
from datetime import datetime, timedelta
from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from app.core.database import Base, get_db
from app.core.config import settings
from app.models import database as m
from app.api.routes import learning
from app.services.learning import record_attempt
from app.services.auth import create_access_token
from app.services.contest_access import now_utc
from tests.test_durable_queue import replicas


@pytest.fixture
def fixture(replicas):
    # Independent DB sessions; PostgreSQL uses a generated isolated schema only
    # when TEST_POSTGRES_URL is explicitly supplied, otherwise that variant skips.
    factory = replicas[0]
    with factory() as db:
        db.add_all([m.User(id=u, username=u, hashed_password="", role="admin" if u == "admin" else "user") for u in ["alice", "bob", "admin"]])
        db.flush()
        for board_id in ["__notice__", "__free__"]:
            db.add(m.Problem(id=board_id, creator_id="admin", title="System board", difficulty="iron5",
                tags=["io"], description="Board", test_cases=[], points=0))
        for i, difficulty in enumerate(["iron5", "iron4", "bronze5", "silver5", "gold5"]):
            db.add(m.Problem(id=f"p{i}", creator_id="admin", title=f"Public {i}", difficulty=difficulty,
                tags=["io"] if i != 2 else ["array"], description="not in learning payload",
                test_cases={"hidden": [{"input": "SECRET", "expected_output": "SECRET"}], "sample": []}, points=100))
        db.commit()
    app = FastAPI()
    app.include_router(learning.router, prefix="/api/v1/learning")
    def session():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = session
    headers = lambda user: {"Authorization": f"Bearer {create_access_token({'sub': user})}"}
    yield app, factory, headers


@pytest.mark.asyncio
async def test_parallel_first_writers_only_one_version_wins(fixture):
    import asyncio
    app, factory, headers = fixture
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        responses = await asyncio.gather(*(client.put('/api/v1/learning/problems/p0',
            headers=headers('alice'), json=record(note)) for note in ['first tab', 'second tab']))
        assert sorted(r.status_code for r in responses) == [200, 409]
        winner = next(r.json() for r in responses if r.status_code == 200)
        final = (await client.get('/api/v1/learning/problems/p0', headers=headers('alice'))).json()
        assert final == winner and final['version'] == 1


def test_publication_progress_and_award_share_transaction_and_survive_pruning(fixture, monkeypatch):
    from app.services.execution_results import publish_result
    from app.api.routes import problems
    _, factory, _ = fixture
    now = now_utc()
    with factory() as db:
        db.add(m.ExecutionJob(id='job', owner_key='alice', quota_key='alice', request_id='r',
            payload_hash='h', kind='practice', payload={'practice_points': 100}, received_at=now))
        db.flush()
        db.add(m.Submission(id='s', execution_job_id='job', user_id='alice', problem_id='p0',
            language='python', code='print(42)', status='queued', verdict='pending', created_at=now))
        db.commit()
    def fail_prune(*args):
        raise RuntimeError('injected publication failure')
    original_prune = problems._prune_old_submissions
    monkeypatch.setattr(problems, '_prune_old_submissions', fail_prune)
    with factory() as db:
        with pytest.raises(RuntimeError, match='injected'):
            publish_result(db, 'job', {'verdict': 'accepted', 'value': {'grading_completed': True}})
        db.rollback()
    with factory() as db:
        assert db.get(m.ProblemLearningRecord, ('alice', 'p0')) is None
        assert db.query(m.UserProblemScore).count() == 0
        assert db.get(m.User, 'alice').total_score == 0
        assert db.get(m.Submission, 's').verdict == 'pending'
    monkeypatch.setattr(problems, '_prune_old_submissions', original_prune)
    for _ in range(2):
        with factory() as db:
            publish_result(db, 'job', {'verdict': 'accepted', 'value': {'grading_completed': True}})
            db.commit()
    with factory() as db:
        assert db.query(m.UserProblemScore).count() == 1
        assert db.get(m.User, 'alice').total_score == 100
        assert db.get(m.ProblemLearningRecord, ('alice', 'p0')).last_verdict == 'accepted'
        db.query(m.Submission).delete()
        db.commit()
        assert db.get(m.ProblemLearningRecord, ('alice', 'p0')).last_verdict == 'accepted'


def test_infrastructure_failure_does_not_erase_a_review_candidate(fixture):
    _, factory, _ = fixture
    with factory() as db:
        for i, verdict in enumerate(['wrong_answer', 'system_error']):
            record_attempt(db, SimpleNamespace(user_id='alice', problem_id='p0', id=str(i),
                created_at=now_utc()+timedelta(seconds=i), verdict=verdict))
        db.commit()
        assert db.get(m.ProblemLearningRecord, ('alice', 'p0')).last_verdict == 'wrong_answer'


def record(body="", version=0, bookmarked=True, reviewed=False):
    return {"note": body, "version": version, "bookmarked": bookmarked, "reviewed": reviewed}


@pytest.mark.asyncio
async def test_private_notes_auth_and_conflicting_first_writes(fixture):
    app, factory, headers = fixture
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        url = "/api/v1/learning/problems/p0"
        assert (await client.put(url, json=record("secret"))).status_code == 401
        assert (await client.get("/api/v1/learning/review")).status_code == 401
        a = headers("alice")
        initial = await client.get(url, headers=a)
        assert initial.json()["version"] == 0
        assert initial.headers["cache-control"] == "private, no-store"
        saved = await client.put(url, headers=a, json=record("<script>private literal note</script>"))
        assert saved.json()["version"] == 1
        assert (await client.put(url, headers=a, json=record("stale tab"))).status_code == 409
        assert (await client.get(url, headers=a)).json()["note"] == "<script>private literal note</script>"
        assert (await client.get(url, headers=headers("bob"))).json()["note"] == ""
        assert (await client.get(url, headers=headers("admin"))).json()["note"] == ""
        assert (await client.get("/api/v1/learning/review?filter=all", headers=headers("bob"))).json()["total"] == 0
        assert "private literal" not in (await client.get("/api/v1/learning/tracks/io")).text
        for invalid in [record("x" * 5001, 1), record("", -1), {**record("", 1), "userId": "bob"}]:
            assert (await client.put(url, headers=a, json=invalid)).status_code == 422
        assert (await client.put(url, headers=a, json=record("", 1, False))).status_code == 200
        assert (await client.get("/api/v1/learning/review?filter=all", headers=a)).json()["total"] == 0


@pytest.mark.asyncio
async def test_hidden_archived_problems_never_enter_learning_even_for_admin(fixture):
    app, factory, headers = fixture
    with factory() as db:
        contest = m.Contest(id="c", creator_id="admin", title="Contest", description="", published=True,
            starts_at=now_utc()-timedelta(hours=1), ends_at=now_utc()+timedelta(hours=1))
        db.add(contest)
        db.flush()
        db.add(m.ContestProblem(id="cp", contest_id="c", problem_id="p0", position=0, points=100, is_new=True, snapshot={}))
        db.get(m.Problem, "p1").deleted_at = now_utc()
        db.add(m.ProblemLearningRecord(user_id="alice", problem_id="p0", bookmarked=True, note="hidden note"))
        db.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for h in [{}, headers("alice"), headers("admin")]:
            for path in ["/tracks/io", "/recommendations"]:
                response = await client.get("/api/v1/learning"+path, headers=h)
                assert response.status_code == 200
                assert not {"p0", "p1"} & {p["id"] for p in response.json()["items"]}
                assert "SECRET" not in response.text and "hidden note" not in response.text
            if h:
                for p in ["p0", "p1", "missing"]:
                    assert (await client.get("/api/v1/learning/problems/"+p, headers=h)).status_code == 404
                    assert (await client.put("/api/v1/learning/problems/"+p, headers=h, json=record())).status_code == 404
        with factory() as db:
            db.get(m.Contest, "c").ends_at = now_utc()-timedelta(seconds=1)
            db.commit()
        public = await client.get("/api/v1/learning/tracks/io")
        assert "p0" in {p["id"] for p in public.json()["items"]}
        assert "SECRET" not in public.text


@pytest.mark.asyncio
async def test_review_survives_pruning_and_reopens_on_new_wrong_attempt(fixture, monkeypatch):
    app, factory, headers = fixture
    older = now_utc()-timedelta(minutes=10)
    with factory() as db:
        for i in range(3):
            sub = m.Submission(id=f"s{i}", user_id="alice", problem_id=f"p{i}", language="python", code="retained?",
                status="Rejected", verdict="wrong_answer", created_at=older+timedelta(seconds=i))
            db.add(sub)
            db.flush()
            record_attempt(db, sub)
        from app.api.routes.problems import _prune_old_submissions
        monkeypatch.setattr(settings, "SUBMISSION_RETENTION_PER_USER", 1)
        _prune_old_submissions(db, "alice")
        db.commit()
        assert db.query(m.Submission).count() == 1
        assert db.query(m.ProblemLearningRecord).count() == 3
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=headers("alice")) as client:
        assert (await client.get("/api/v1/learning/review")).json()["total"] == 3
        assert (await client.put("/api/v1/learning/problems/p0", json=record("", 0, False, True))).status_code == 200
        assert (await client.get("/api/v1/learning/review")).json()["total"] == 2
        with factory() as db:
            record_attempt(db, SimpleNamespace(user_id="alice", problem_id="p0", id="new",
                created_at=now_utc()+timedelta(seconds=1), verdict="wrong_answer"))
            # Older job finishing after the newer one must not overwrite progress.
            record_attempt(db, SimpleNamespace(user_id="alice", problem_id="p0", id="old",
                created_at=older, verdict="accepted"))
            db.add(m.UserProblemScore(user_id="alice", challenge_id="p1", points_awarded=100))
            db.commit()
        result = (await client.get("/api/v1/learning/review")).json()
        assert {p["id"] for p in result["items"]} == {"p0", "p2"}
        reopened = (await client.get('/api/v1/learning/problems/p0')).json()
        assert reopened['reviewedAt'] is not None and reopened['reviewed'] is False
        page = (await client.get("/api/v1/learning/review?limit=1&offset=1")).json()
        assert page["total"] == 2 and len(page["items"]) == 1
        assert (await client.get("/api/v1/learning/review?limit=1000")).status_code == 422


@pytest.mark.asyncio
async def test_tracks_progress_recommendations_deterministic_and_no_awards(fixture):
    app, factory, headers = fixture
    with factory() as db:
        db.add(m.UserProblemScore(user_id="alice", challenge_id="p0", points_awarded=100))
        db.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        guest = (await client.get("/api/v1/learning/recommendations")).json()
        assert guest["targetDifficulty"] == "iron5" and guest["items"][0]["id"] == "p0"
        for board_id in ["__notice__", "__free__"]:
            assert (await client.get("/api/v1/learning/problems/"+board_id, headers=headers("admin"))).status_code == 404
        a = headers("alice")
        rec = (await client.get("/api/v1/learning/recommendations", headers=a)).json()
        assert rec["targetDifficulty"] == "iron4"
        assert rec["items"][0]["id"] == "p1"
        assert "p0" not in {p["id"] for p in rec["items"]}
        assert rec == (await client.get("/api/v1/learning/recommendations", headers=a)).json()
        tracks = (await client.get("/api/v1/learning/tracks", headers=a)).json()["tracks"]
        assert [t["order"] for t in tracks] == list(range(1, 8))
        assert tracks[0]["solved"] == 1 and tracks[0]["nextProblemId"] == "p1"
        assert tracks[-1]["total"] == 0 and tracks[-1]["nextProblemId"] is None
        detail = (await client.get("/api/v1/learning/tracks/io?limit=1&offset=1", headers=a)).json()
        assert detail["total"] == 4 and detail["items"][0]["id"] == "p1"
        assert "description" not in detail["items"][0] and "testCases" not in detail["items"][0]
        assert (await client.get("/api/v1/learning/tracks/unknown")).status_code == 404
    with factory() as db:
        assert db.get(m.User, "alice").total_score == 0
        assert db.query(m.UserProblemScore).count() == 1
