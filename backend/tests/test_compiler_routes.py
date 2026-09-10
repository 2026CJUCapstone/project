import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services import compiler as compiler_service
from tests.execution_helpers import finish_receipt


@pytest.mark.asyncio
async def test_compile_route_accepts_runner_value_error_then_returns_generic_worker_error(monkeypatch: pytest.MonkeyPatch):
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
        result = await finish_receipt(client, response)

    assert result["ok"] is False
    assert result["value"] is None
    assert result["verdict"] == "system_error"
    assert result["error"] == "실행 서비스를 사용할 수 없습니다."


@pytest.mark.asyncio
async def test_compile_route_accepts_sandbox_failure_then_returns_generic_worker_error(monkeypatch: pytest.MonkeyPatch):
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
        result = await finish_receipt(client, response)

    assert result["ok"] is False
    assert result["value"] is None
    assert result["verdict"] == "system_error"
    assert result["error"] == "실행 서비스를 사용할 수 없습니다."


@pytest.mark.asyncio
async def test_run_route_accepts_sandbox_failure_then_returns_generic_worker_error(monkeypatch: pytest.MonkeyPatch):
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
        result = await finish_receipt(client, response)

    assert result["ok"] is False
    assert result["value"] is None
    assert result["verdict"] == "system_error"
    assert result["error"] == "실행 서비스를 사용할 수 없습니다."
