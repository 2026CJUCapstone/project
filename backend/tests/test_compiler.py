import uuid

import pytest
from httpx import AsyncClient, ASGITransport

from app.core.config import Settings
from app.core.database import SessionLocal
from app.main import app
from app.models.database import User
from app.services import auth
from app.services import compiler as compiler_service


@pytest.mark.asyncio
async def test_health_check():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert "version" in response.json()


@pytest.mark.asyncio
async def test_run_code_unsupported_language():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/compiler/run",
            json={"language": "ruby", "code": "puts 'hello'"},
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_run_contract_accepts_code_alias(monkeypatch: pytest.MonkeyPatch):
    async def fake_run(source_code: str, language: str, stdin: str = "", optimize: bool = False):
        assert source_code == 'import emitln from std.io;\nfunc main() -> u64 { emitln("ok"); return 0; }\n'
        assert language == "bpp"
        assert stdin == ""
        assert optimize is False
        return {
            "stdout": "ok\n",
            "stderr": "",
            "exit_code": 0,
            "execution_time": 8.2,
        }

    monkeypatch.setattr(compiler_service.compiler_instance, "run", fake_run)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/compiler/run",
            json={
                "code": 'import emitln from std.io;\nfunc main() -> u64 { emitln("ok"); return 0; }\n',
                "language": "bpp",
            },
        )

    assert response.status_code == 200
    assert response.json()["stdout"] == "ok\n"


@pytest.mark.asyncio
async def test_compile_contract(monkeypatch: pytest.MonkeyPatch):
    async def fake_compile(source_code: str, language: str, optimize: bool = False, target: str = "all"):
        assert source_code == 'import emitln from std.io;\nfunc main() -> u64 { emitln("ok"); return 0; }\n'
        assert language == "bpp"
        assert optimize is False
        assert target == "all"
        return {
            "success": True,
            "errors": [],
            "warnings": [],
            "execution_time": 12.5,
            "metadata": {"node_count": 1, "optimization_level": 0},
        }

    monkeypatch.setattr(compiler_service.compiler_instance, "compile", fake_compile)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/compiler/compile",
            json={
                "code": 'import emitln from std.io;\nfunc main() -> u64 { emitln("ok"); return 0; }\n',
                "language": "bpp",
                "options": {"optimize": False, "target": "all"},
            },
        )

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["metadata"]["optimization_level"] == 0


@pytest.mark.asyncio
async def test_compile_queue_records_public_problem_and_user_filters(monkeypatch: pytest.MonkeyPatch):
    suffix = uuid.uuid4().hex[:10]
    username = f"queue_{suffix}"
    problem_id = f"problem-{suffix}"
    db = SessionLocal()
    try:
        user = User(
            username=username,
            hashed_password=auth.get_password_hash("password123"),
        )
        db.add(user)
        db.commit()
    finally:
        db.close()

    async def fake_compile(source_code: str, language: str, optimize: bool = False, target: str = "all"):
        return {
            "success": True,
            "errors": [],
            "warnings": [],
            "execution_time": 3.4,
            "metadata": {"node_count": 1, "optimization_level": 0},
        }

    monkeypatch.setattr(compiler_service.compiler_instance, "compile", fake_compile)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            compiled = await client.post(
                "/api/v1/compiler/compile",
                headers={"Authorization": f"Bearer {auth.create_access_token({'sub': username})}"},
                json={
                    "code": "func main() -> u64 { return 0; }",
                    "language": "bpp",
                    "problemId": problem_id,
                    "options": {"optimize": False, "target": "all"},
                },
            )
            queue = await client.get(
                "/api/v1/compiler/queue",
                params={"problemId": problem_id, "username": username},
            )

        assert compiled.status_code == 200
        assert queue.status_code == 200
        jobs = queue.json()["jobs"]
        assert len(jobs) == 1
        assert jobs[0]["problemId"] == problem_id
        assert jobs[0]["username"] == username
        assert jobs[0]["status"] == "completed"
        assert jobs[0]["sourceSizeBytes"] > 0
    finally:
        db = SessionLocal()
        try:
            db.query(User).filter(User.username == username).delete()
            db.commit()
        finally:
            db.close()


def test_cors_origins_parses_csv_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(
        "CORS_ORIGINS",
        "http://localhost:3000,http://localhost:5173,http://127.0.0.1:5173",
    )

    settings = Settings(_env_file=None)

    assert settings.CORS_ORIGINS == [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
