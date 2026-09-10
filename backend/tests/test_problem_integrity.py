"""Practice scoring/archival regressions; no real sandbox is executed."""
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import SessionLocal
from app.main import app
from app.models import database as m
from app.services.auth import create_access_token
from app.services.rating import rating_stats_for_users


@pytest.fixture
def problem_data():
    with SessionLocal() as db:
        user = m.User(username=f"integrity_{uuid.uuid4().hex}", role="admin", hashed_password="", total_score=100)
        db.add(user)
        db.flush()
        problem = m.Problem(creator_id=user.id, title="Integrity problem", difficulty="bronze5", tags=[],
                            description="test", points=100, test_cases=[])
        db.add(problem)
        db.flush()
        db.add(m.UserProblemScore(user_id=user.id, challenge_id=problem.id, points_awarded=100))
        db.add(m.Submission(user_id=user.id, problem_id=problem.id, code="private", language="python",
                            status="Accepted", verdict="accepted"))
        db.add(m.Comment(user_id=user.id, problem_id=problem.id, content="preserve me"))
        db.commit()
        data = user.id, problem.id, {"Authorization": f"Bearer {create_access_token({'sub': user.username})}"}
    yield data
    with SessionLocal() as db:
        db.query(m.Comment).filter_by(problem_id=data[1]).delete()
        db.query(m.Submission).filter_by(problem_id=data[1]).delete()
        db.query(m.UserProblemScore).filter_by(user_id=data[0]).delete()
        db.query(m.Problem).filter_by(id=data[1]).delete()
        db.query(m.User).filter_by(id=data[0]).delete()
        db.commit()


@pytest.mark.asyncio
async def test_empty_tests_rejected_on_create_update_and_legacy_submit(problem_data):
    user_id, problem_id, headers = problem_data
    body = {"title": "Empty", "description": "test", "difficulty": "bronze5", "testCases": [], "hiddenTestCases": []}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://isolated") as client:
        assert (await client.post('/api/v1/problems/', json=body, headers=headers)).status_code == 422
        assert (await client.put(f'/api/v1/problems/{problem_id}', json=body, headers=headers)).status_code == 422
        for request_headers in ({}, headers):
            response = await client.post(f'/api/v1/problems/{problem_id}/submit',
                                         json={"code": "print(1)", "language": "python"}, headers=request_headers)
            assert response.status_code == 409
    with SessionLocal() as db:
        assert db.get(m.User, user_id).total_score == 100
        assert db.query(m.Submission).filter_by(problem_id=problem_id).count() == 1


@pytest.mark.asyncio
async def test_hidden_only_tests_allowed(problem_data):
    _, problem_id, headers = problem_data
    body = {"title": "Hidden only", "description": "test", "difficulty": "bronze5",
            "hiddenTestCases": [{"input": "", "expectedOutput": "1"}]}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://isolated") as client:
        assert (await client.put(f'/api/v1/problems/{problem_id}', json=body, headers=headers)).status_code == 200


@pytest.mark.asyncio
async def test_delete_archives_problem_and_preserves_ledger_rating_history(problem_data):
    user_id, problem_id, headers = problem_data
    with SessionLocal() as db:
        before = rating_stats_for_users(db, [user_id])[user_id]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://isolated") as client:
        assert (await client.delete(f'/api/v1/problems/{problem_id}', headers=headers)).status_code == 200
        for request_headers in ({}, headers):
            assert (await client.get(f'/api/v1/problems/{problem_id}', headers=request_headers)).status_code == 404
            listing = await client.get('/api/v1/problems/', headers=request_headers)
            assert problem_id not in {p['id'] for p in listing.json()}
            assert (await client.get('/api/v1/community/posts', params={"problemId": problem_id}, headers=request_headers)).status_code == 404
        assert (await client.post(f'/api/v1/problems/{problem_id}/submit', json={"code":"print(1)","language":"python"}, headers=headers)).status_code == 404
        library = await client.get('/api/v1/contests/library', headers=headers)
        assert problem_id not in {p['id'] for p in library.json()}
        # A repeated DELETE is idempotent; it cannot remove the archived ledger.
        assert (await client.delete(f'/api/v1/problems/{problem_id}', headers=headers)).status_code == 200
    with SessionLocal() as db:
        assert db.get(m.Problem, problem_id).deleted_at is not None
        assert db.get(m.User, user_id).total_score == 100
        assert db.query(m.UserProblemScore).filter_by(user_id=user_id, challenge_id=problem_id).one().points_awarded == 100
        assert db.query(m.Submission).filter_by(problem_id=problem_id).count() == 1
        assert db.query(m.Comment).filter_by(problem_id=problem_id).count() == 1
        assert rating_stats_for_users(db, [user_id])[user_id] == before
