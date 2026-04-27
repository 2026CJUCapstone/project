import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services import compiler as compiler_service


@pytest.mark.asyncio
async def test_compile_route_returns_400_for_unsupported_language(monkeypatch: pytest.MonkeyPatch):
    async def fake_compile(source_code: str, language: str, optimize: bool = False, target: str = "all"):
        raise ValueError(f"지원하지 않는 언어입니다: {language}")

    monkeypatch.setattr(compiler_service.compiler_instance, "compile", fake_compile)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/compiler/compile",
            json={
                "code": 'print("hello")',
                "language": "python",
                "options": {"optimize": False, "target": "all"},
            },
        )

    assert response.status_code == 400
    assert "지원하지 않는 언어" in response.json()["detail"]


@pytest.mark.asyncio
async def test_compile_route_returns_500_for_sandbox_failure(monkeypatch: pytest.MonkeyPatch):
    async def fake_compile(source_code: str, language: str, optimize: bool = False, target: str = "all"):
        raise compiler_service.SandboxExecutionError("docker unavailable")

    monkeypatch.setattr(compiler_service.compiler_instance, "compile", fake_compile)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/compiler/compile",
            json={
                "code": 'import emitln from std.io;\nfunc main() -> u64 { emitln("x"); return 0; }\n',
                "language": "bpp",
                "options": {"optimize": False, "target": "all"},
            },
        )

    assert response.status_code == 500
    assert response.json()["detail"] == "docker unavailable"


@pytest.mark.asyncio
async def test_run_route_returns_500_for_sandbox_failure(monkeypatch: pytest.MonkeyPatch):
    async def fake_run(source_code: str, language: str, stdin: str = "", optimize: bool = False):
        raise compiler_service.SandboxExecutionError("sandbox failed")

    monkeypatch.setattr(compiler_service.compiler_instance, "run", fake_run)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/compiler/run",
            json={
                "code": 'import emitln from std.io;\nfunc main() -> u64 { emitln("x"); return 0; }\n',
                "language": "bpp",
            },
        )

    assert response.status_code == 500
    assert response.json()["detail"] == "sandbox failed"
