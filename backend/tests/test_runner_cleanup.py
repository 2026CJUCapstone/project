import asyncio
from pathlib import Path

import pytest

from app.core.config import settings
from app.services.compiler import DockerCompilerRunner, SandboxExecutionError


def test_execute_removes_job_directory_when_docker_client_initialization_fails(tmp_path, monkeypatch):
    runner = DockerCompilerRunner()
    monkeypatch.setattr(settings, "SANDBOX_WORKDIR_ROOT", str(tmp_path))
    expected_error = SandboxExecutionError("Docker is unavailable")

    def raise_client_error():
        raise expected_error

    monkeypatch.setattr(runner, "_get_client", raise_client_error)

    with pytest.raises(SandboxExecutionError) as exc_info:
        asyncio.run(runner._execute(mode="compile", source_code="print(1)", language="python"))

    assert exc_info.value is expected_error
    assert list(tmp_path.iterdir()) == []


def test_execute_removes_job_directory_when_source_file_initialization_fails(tmp_path, monkeypatch):
    runner = DockerCompilerRunner()
    monkeypatch.setattr(settings, "SANDBOX_WORKDIR_ROOT", str(tmp_path))

    def raise_write_error(self, data, *args, **kwargs):
        raise OSError("disk is read-only")

    monkeypatch.setattr(Path, "write_text", raise_write_error)

    with pytest.raises(OSError, match="disk is read-only"):
        asyncio.run(runner._execute(mode="compile", source_code="print(1)", language="python"))

    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_workdir_cleanup_failure_is_not_silently_accepted(tmp_path, monkeypatch):
    directory = tmp_path / "still-mounted"
    directory.mkdir()
    (directory / "main.py").write_text("print(42)", encoding="utf-8")
    runner = DockerCompilerRunner(cleanup_guard=lambda action: action())

    monkeypatch.setattr("app.services.compiler.shutil.rmtree", lambda _directory: None)

    with pytest.raises(RuntimeError, match="cleanup was not confirmed"):
        await runner._remove_workdir(directory)
    assert directory.exists()
