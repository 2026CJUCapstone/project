from unittest.mock import Mock

import pytest

from app.core.config import settings
from app.services.compile_queue import classify_run_result
from app.services.execution_phase import ExecutionPhaseDecoder


TOKEN = '0123456789abcdef0123456789abcdef'


def marker(phase):
    return f'\x1ewebcompiler:{TOKEN}:{phase}\x1f\n'.encode()


@pytest.mark.parametrize('size', [1, 2, 17, 4096])
def test_phase_frames_split_at_any_chunk_boundary_preserve_diagnostics(size):
    decoder = ExecutionPhaseDecoder(TOKEN)
    data = marker('compile') + b'gcc warning\n' + marker('run') + b'program stderr\n'
    output = b''.join(decoder.feed(data[i:i+size]) for i in range(0, len(data), size)) + decoder.finish()
    assert output == b'gcc warning\nprogram stderr\n'
    assert decoder.phase == 'run'


def test_compile_failure_and_partial_marker_are_not_discarded():
    decoder = ExecutionPhaseDecoder(TOKEN)
    data = marker('compile') + b'error: invalid C++\n' + marker('run')[:8]
    assert decoder.feed(data) + decoder.finish() == b'error: invalid C++\n' + marker('run')[:8]
    assert decoder.phase == 'compile'


def test_user_output_cannot_change_phase_after_execution_started():
    decoder = ExecutionPhaseDecoder(TOKEN)
    user_output = marker('compile') + marker('run') + b'memory compile timeout'
    assert decoder.feed(marker('compile') + marker('run') + user_output) + decoder.finish() == user_output
    assert decoder.phase == 'run'


@pytest.mark.parametrize('data', [b'', b'legacy error', b'\x1ewebcompiler:wrong:compile\x1f\n'])
def test_old_image_without_handshake_keeps_entire_stderr(data):
    decoder = ExecutionPhaseDecoder(TOKEN)
    assert decoder.feed(data) + decoder.finish() == data
    assert decoder.phase is None


@pytest.mark.parametrize('exit_code', [1, 124, 137, 143, 200])
def test_runtime_output_or_exit_code_cannot_spoof_compiler_or_resource_failure(exit_code):
    assert classify_run_result({'exit_code':exit_code,'stderr':'compiler timeout memory oom',
        'execution_phase':'run'}) == 'runtime_error'


def test_compiler_failure_does_not_require_english_compile_keyword():
    assert classify_run_result({'exit_code':1,'stderr':"expected unqualified-id before 'not' token",
        'execution_phase':'compile'}) == 'compile_error'


@pytest.mark.parametrize('reason', ['time_limit_exceeded','memory_limit_exceeded'])
def test_trusted_runner_resource_failure_takes_precedence(reason):
    assert classify_run_result({'exit_code':137,'execution_phase':'compile','failure_reason':reason}) == reason


def test_phase_metadata_does_not_consume_user_output_budget(monkeypatch):
    from app.services.compiler import DockerCompilerRunner
    monkeypatch.setattr(settings, 'SANDBOX_OUTPUT_MAX_BYTES', 10)
    decoder = ExecutionPhaseDecoder(TOKEN)
    container = Mock()
    result = DockerCompilerRunner()._collect_output(
        iter([(None,marker('compile')), (None,marker('run')), (b'12345',b'67890')]), container, decoder)
    assert result == (b'12345',b'67890',False)
    container.kill.assert_not_called()
    assert decoder.phase == 'run'


@pytest.mark.parametrize('size', [1, 7, 4096])
def test_terminal_phase_frames_preserve_early_input_echo_and_utf8(size):
    decoder = ExecutionPhaseDecoder(TOKEN, terminal=True)
    frames = lambda phase: marker(phase).replace(b'\n',b'\r\n')
    data = b'42\r\n' + frames('compile') + b'warning\r\n' + frames('run') + '출력\r\n'.encode()
    output = b''.join(decoder.feed(data[i:i+size]) for i in range(0,len(data),size)) + decoder.finish()
    assert output == b'42\r\nwarning\r\n' + '출력\r\n'.encode()
    assert decoder.phase == 'run'


def test_terminal_old_image_and_partial_frame_are_preserved():
    decoder = ExecutionPhaseDecoder(TOKEN, terminal=True)
    data = b'42\r\nhello\x1ewebcompiler:'
    assert decoder.feed(data) + decoder.finish() == data
    assert decoder.phase is None
