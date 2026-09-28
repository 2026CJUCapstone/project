"""Wait notifications must preserve timeout, OOM and cancellation cleanup."""
import asyncio
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from requests.exceptions import ReadTimeout
from docker.errors import APIError, NotFound

from app.core.config import settings
from app.services.compiler import DockerCompilerRunner


@pytest.mark.asyncio
async def test_wait_uses_one_bounded_notification_then_refreshes_oom(monkeypatch):
    monkeypatch.setattr(settings, 'EXECUTION_TIMEOUT', 2)
    container = Mock()
    container.wait.return_value = {'StatusCode': 137}
    container.attrs = {'State': {'OOMKilled': False}}
    def reload():
        container.attrs['State']['OOMKilled'] = True
    container.reload.side_effect = reload
    result = await DockerCompilerRunner()._wait_for_exit(container)
    assert result == {'StatusCode': 137}
    container.wait.assert_called_once_with(timeout=2)
    container.reload.assert_called_once()
    assert container.attrs['State']['OOMKilled']


@pytest.mark.asyncio
async def test_wait_http_timeout_remains_execution_timeout():
    container = Mock()
    container.wait.side_effect = ReadTimeout('bounded wait')
    with pytest.raises(TimeoutError):
        await DockerCompilerRunner()._wait_for_exit(container)
    container.reload.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize('cancel', [False, True])
async def test_wait_deadline_or_cancellation_reaps_and_unblocks_waiter(tmp_path, monkeypatch, cancel):
    monkeypatch.setattr(settings, 'SANDBOX_WORKDIR_ROOT', str(tmp_path))
    monkeypatch.setattr(settings, 'EXECUTION_TIMEOUT', 0.08)
    waiting, removed, finished = Event(), Event(), Event()
    container = Mock()
    container.attrs = {'State': {'OOMKilled': False}}
    stream = Mock()
    stream.__iter__ = Mock(return_value=iter(()))
    container.attach.return_value = stream
    def wait(**kwargs):
        waiting.set()
        try:
            assert removed.wait(2), 'wait socket must unblock after sandbox cleanup'
            return {'StatusCode': 137}
        finally:
            finished.set()
    container.wait.side_effect = wait
    container.remove.side_effect = lambda **kwargs: removed.set()
    runner = DockerCompilerRunner(client_factory=lambda: SimpleNamespace(
        containers=SimpleNamespace(create=lambda **kwargs: container)))
    task = asyncio.create_task(runner._execute(mode='compile', source_code='pass', language='python'))
    assert await asyncio.to_thread(waiting.wait, 2)
    if cancel:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        result = await task
        assert result['failure_reason'] == 'time_limit_exceeded'
        assert result['exit_code'] == 124
        container.kill.assert_called_once()
    assert await asyncio.to_thread(finished.wait, 2)
    container.remove.assert_called_once_with(force=True)
    stream.close.assert_called_once()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_cleanup_batches_container_and_source_under_one_durable_guard(tmp_path):
    directory = tmp_path / 'source'
    directory.mkdir()
    events = []
    container = Mock()
    container.remove.side_effect = lambda **kwargs: events.append('container')
    def guard(action):
        events.append('intent')
        action()
        assert not directory.exists()
        events.append('ack')
        return True
    runner = DockerCompilerRunner(cleanup_guard=guard)
    assert await runner._remove_execution_resources(container, directory)
    assert events == ['intent', 'container', 'ack']


@pytest.mark.asyncio
@pytest.mark.parametrize('missing', [False, True])
async def test_uncertain_container_removal_keeps_source_and_unacknowledged_intent(tmp_path, missing):
    directory = tmp_path / 'source'
    directory.mkdir()
    container = Mock()
    container.remove.side_effect = NotFound('gone') if missing else APIError('uncertain response')
    acknowledged = []
    def guard(action):
        action()
        acknowledged.append(True)
        return True
    runner = DockerCompilerRunner(cleanup_guard=guard)
    if missing:
        assert await runner._remove_execution_resources(container, directory)
        assert not directory.exists() and acknowledged == [True]
    else:
        with pytest.raises(APIError):
            await runner._remove_execution_resources(container, directory)
        assert directory.exists() and acknowledged == []
