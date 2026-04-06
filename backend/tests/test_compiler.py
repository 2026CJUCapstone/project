import pytest
from httpx import AsyncClient, ASGITransport

from app.core.config import Settings
from app.main import app
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
    async def fake_compile(source_code: str, language: str, optimize: bool = False):
        assert source_code == 'import emitln from std.io;\nfunc main() -> u64 { emitln("ok"); return 0; }\n'
        assert language == "bpp"
        assert optimize is False
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
