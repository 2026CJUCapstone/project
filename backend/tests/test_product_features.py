import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.core.database import SessionLocal
from app.main import app
from app.models.database import CodeProject, Comment, Problem, Submission, User, UserProblemScore
from app.services import auth
from app.services import compiler as compiler_service


def _token_for(username: str) -> str:
    return auth.create_access_token({"sub": username})


def _auth_headers(username: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token_for(username)}"}


def _create_user(username: str, role: str = "user") -> User:
    db = SessionLocal()
    try:
        user = User(
            username=username,
            hashed_password=auth.get_password_hash("password123"),
            role=role,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def _delete_users(*usernames: str) -> None:
    db = SessionLocal()
    try:
        users = db.query(User).filter(User.username.in_(usernames)).all()
        user_ids = [user.id for user in users]
        if user_ids:
            db.query(CodeProject).filter(CodeProject.user_id.in_(user_ids)).delete(synchronize_session=False)
            db.query(Comment).filter(Comment.user_id.in_(user_ids)).delete(synchronize_session=False)
            db.query(Submission).filter(Submission.user_id.in_(user_ids)).delete(synchronize_session=False)
            db.query(UserProblemScore).filter(UserProblemScore.user_id.in_(user_ids)).delete(synchronize_session=False)
            db.query(User).filter(User.id.in_(user_ids)).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


@pytest.mark.asyncio
async def test_default_admin_password_is_not_accepted():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/login",
            json={"username": settings.ADMIN_USERNAME, "password": "admin1234"},
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_login_rate_limit_blocks_repeated_attempts():
    username = f"ratelimit_{uuid.uuid4().hex[:10]}"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        responses = [
            await client.post(
                "/api/v1/auth/login",
                json={"username": username, "password": "wrong-password"},
            )
            for _ in range(settings.AUTH_RATE_LIMIT_MAX_ATTEMPTS + 1)
        ]

    assert responses[-1].status_code == 429


@pytest.mark.asyncio
async def test_project_storage_is_per_user_and_scope():
    suffix = uuid.uuid4().hex[:10]
    username = f"project_user_{suffix}"
    _create_user(username)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            saved = await client.put(
                "/api/v1/projects/problem:abc",
                headers=_auth_headers(username),
                json={"code": "func main() -> u64 { return 0; }", "language": "bpp", "title": "ABC"},
            )
            loaded = await client.get("/api/v1/projects/problem:abc", headers=_auth_headers(username))

        assert saved.status_code == 200
        assert saved.json()["scope"] == "problem:abc"
        assert loaded.status_code == 200
        assert loaded.json()["code"] == "func main() -> u64 { return 0; }"
    finally:
        _delete_users(username)


@pytest.mark.asyncio
async def test_project_storage_rejects_oversized_code():
    suffix = uuid.uuid4().hex[:10]
    username = f"project_big_{suffix}"
    _create_user(username)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.put(
                "/api/v1/projects/main",
                headers=_auth_headers(username),
                json={"code": "x" * (settings.CODE_PROJECT_MAX_BYTES + 1), "language": "bpp", "title": "big"},
            )

        assert response.status_code == 413
    finally:
        _delete_users(username)


@pytest.mark.asyncio
async def test_notice_posts_require_admin_role():
    suffix = uuid.uuid4().hex[:10]
    username = f"notice_user_{suffix}"
    _create_user(username)
    created_id: str | None = None

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            forbidden = await client.post(
                "/api/v1/community/posts",
                headers=_auth_headers(username),
                json={"problemId": "__notice__", "content": "user notice"},
            )
            created = await client.post(
                "/api/v1/community/posts",
                headers=_auth_headers(settings.ADMIN_USERNAME),
                json={"problemId": "__notice__", "content": "admin notice"},
            )

        assert forbidden.status_code == 403
        assert created.status_code == 200
        created_id = created.json()["id"]
        assert created.json()["canDelete"] is True
    finally:
        db = SessionLocal()
        try:
            if created_id:
                db.query(Comment).filter(Comment.id == created_id).delete()
            db.commit()
        finally:
            db.close()
        _delete_users(username)


@pytest.mark.asyncio
async def test_submission_awards_problem_points_and_records_submission(monkeypatch: pytest.MonkeyPatch):
    suffix = uuid.uuid4().hex[:10]
    owner = _create_user(f"owner_{suffix}", role="admin")
    solver = _create_user(f"solver_{suffix}")
    problem_id: str | None = None

    async def fake_run(source_code: str, language: str, stdin: str = "", optimize: bool = False):
        return {"stdout": "ok\n", "stderr": "", "exit_code": 0, "execution_time": 1.0}

    monkeypatch.setattr(compiler_service.compiler_instance, "run", fake_run)

    db = SessionLocal()
    try:
        problem = Problem(
            creator_id=owner.id,
            title=f"points {suffix}",
            difficulty="iron5",
            tags=["io"],
            description="points",
            points=250,
            test_cases={"sample": [{"input": "", "expected_output": "ok"}], "hidden": []},
        )
        db.add(problem)
        db.commit()
        db.refresh(problem)
        problem_id = problem.id
    finally:
        db.close()

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/problems/{problem_id}/submit",
                headers=_auth_headers(solver.username),
                json={"code": "func main() -> u64 { return 0; }", "language": "bpp"},
            )

        assert response.status_code == 200
        assert response.json()["status"] == "Accepted"
        assert response.json()["totalScore"] == 250

        db = SessionLocal()
        try:
            submission = db.query(Submission).filter(Submission.problem_id == problem_id).one()
            score = db.query(UserProblemScore).filter(UserProblemScore.challenge_id == problem_id).one()
            assert submission.awarded_points == 250
            assert score.points_awarded == 250
        finally:
            db.close()
    finally:
        db = SessionLocal()
        try:
            if problem_id:
                db.query(Submission).filter(Submission.problem_id == problem_id).delete()
                db.query(UserProblemScore).filter(UserProblemScore.challenge_id == problem_id).delete()
                db.query(Problem).filter(Problem.id == problem_id).delete()
            db.commit()
        finally:
            db.close()
        _delete_users(owner.username, solver.username)
