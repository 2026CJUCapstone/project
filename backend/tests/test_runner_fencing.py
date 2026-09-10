import asyncio
from threading import Event
from unittest.mock import Mock

import pytest

from app.services.compiler import DockerCompilerRunner, SandboxExecutionError


@pytest.mark.asyncio
async def test_cancellation_during_docker_create_joins_and_removes_late_container():
    entered, release = Event(), Event()
    container = Mock()

    def create(**kwargs):
        entered.set()
        assert release.wait(2)
        return container

    task = asyncio.create_task(DockerCompilerRunner()._allocate_container(create, image='isolated'))
    assert await asyncio.to_thread(entered.wait, 2)
    task.cancel()
    await asyncio.sleep(0)
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    container.remove.assert_called_once_with(force=True)
    container.start.assert_not_called()


@pytest.mark.asyncio
async def test_fenced_runner_never_starts_a_stale_claim():
    container = Mock()
    with pytest.raises(SandboxExecutionError, match='lease'):
        await DockerCompilerRunner(start_guard=lambda action: False)._start_container(container)
    container.start.assert_not_called()


@pytest.mark.asyncio
async def test_graph_fallback_does_not_multiply_one_jobs_execution_slot(monkeypatch):
    runner = DockerCompilerRunner()
    active, peak = 0, 0

    async def execute(**kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(0.01)
            return {'stdout':'', 'stderr':'', 'exit_code':0, 'execution_time':1}
        finally:
            active -= 1

    monkeypatch.setattr(runner, '_execute', execute)
    await runner.compile(source_code='func main() -> u64 { return 0; }', language='bpp')
    assert peak == 1
