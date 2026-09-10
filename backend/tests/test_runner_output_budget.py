from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.core.config import settings
from app.services.compiler import DockerCompilerRunner


def test_combined_stdout_stderr_budget_stops_consuming_and_kills(monkeypatch):
    monkeypatch.setattr(settings, 'SANDBOX_OUTPUT_MAX_BYTES', 10)
    container = Mock()

    def chunks():
        yield b'123456', None
        yield None, b'abcdef'
        pytest.fail('Unbounded stream must not be drained after exceeding its budget')

    assert DockerCompilerRunner()._collect_output(chunks(), container) == (b'123456', b'abcd', True)
    container.kill.assert_called_once()


def test_exact_output_boundary_is_not_a_false_failure(monkeypatch):
    monkeypatch.setattr(settings, 'SANDBOX_OUTPUT_MAX_BYTES', 10)
    container = Mock()
    assert DockerCompilerRunner()._collect_output(iter([(b'12345', b'67890')]), container) == (b'12345', b'67890', False)
    container.kill.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize('overflow', [False, True])
async def test_runner_attaches_before_start_disables_disk_logs_and_cleans_stream(tmp_path, monkeypatch, overflow):
    monkeypatch.setattr(settings, 'SANDBOX_WORKDIR_ROOT', str(tmp_path))
    monkeypatch.setattr(settings, 'SANDBOX_OUTPUT_MAX_BYTES', 10)
    started = Event()
    calls = []

    class Stream:
        closed = False

        def __iter__(self):
            assert started.wait(2)
            yield (b'1'*11 if overflow else b'1'), b''

        def close(self):
            self.closed = True

    stream = Stream()

    def attach(**options):
        calls.append('attach')
        assert options == {'stream': True, 'logs': False, 'demux': True}
        return stream

    def start():
        calls.append('start')
        started.set()

    container = Mock(status='exited')
    container.attach.side_effect = attach
    container.start.side_effect = start
    container.wait.return_value = {'StatusCode': 0}
    client = SimpleNamespace(containers=Mock())
    client.containers.create.return_value = container
    runner = DockerCompilerRunner()
    monkeypatch.setattr(runner, '_get_client', lambda: client)
    result = await runner._execute(mode='run', source_code='print(1)', language='python')
    assert calls == ['attach', 'start']
    assert client.containers.create.call_args.kwargs['log_config']['Type'] == 'none'
    container.logs.assert_not_called()
    container.remove.assert_called_once_with(force=True)
    assert stream.closed
    assert list(tmp_path.iterdir()) == []
    if overflow:
        assert result['exit_code'] != 0
        assert 'Output limit exceeded' in result['stderr']
        assert len(result['stdout']) == 10
        container.kill.assert_called_once()
    else:
        assert result['stdout'] == '1'
        assert result['exit_code'] == 0
