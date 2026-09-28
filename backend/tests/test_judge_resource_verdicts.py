"""Regressions from the bounded Linux OOM-child/exit-0 probe (2026-09-26)."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.compile_queue import classify_compile_result, classify_grading_result, classify_run_result
from app.services.compiler import DockerCompilerRunner
from app.services.judging import _judge_cases
from app.services.contests import PENALTY_VERDICTS


@pytest.mark.parametrize('reason', ['memory_limit_exceeded', 'time_limit_exceeded',
                                     'output_limit_exceeded', 'process_limit_exceeded'])
@pytest.mark.parametrize('exit_code', [0, 1, 124, 137])
def test_trusted_resource_evidence_wins_over_successful_parent_and_output(reason, exit_code):
    result = dict(exit_code=exit_code, stdout='42', stderr='', execution_phase='run', failure_reason=reason)
    assert classify_run_result(result) == reason
    assert classify_grading_result(result, '42') == reason
    assert classify_run_result({**result, 'execution_phase':'compile'}) == 'compile_resource_error'
    assert classify_compile_result({**result, 'success':True}) == 'compile_resource_error'


@pytest.mark.parametrize('reason', ['memory_limit_exceeded', 'time_limit_exceeded',
                                     'output_limit_exceeded', 'process_limit_exceeded'])
@pytest.mark.asyncio
async def test_compiler_resource_failure_never_runs_cases_or_penalizes(reason):
    compiled = dict(exit_code=0, stdout='', stderr='', execution_time=1, failure_reason=reason)
    runner = SimpleNamespace(_execute=AsyncMock(return_value=compiled), run=AsyncMock())
    sample=[{'input':'', 'expectedOutput':'42'}]
    result = await _judge_cases(runner, {'code':'source', 'language':'python', 'sample':sample,
                                      'hidden':[]}, contest=False)
    assert result['verdict'] == 'compile_resource_error'
    assert not result['grading_completed'] and not result['grading_passed']
    runner.run.assert_not_called()
    assert result['verdict'] not in PENALTY_VERDICTS
    real_runner = DockerCompilerRunner()
    real_runner._execute = AsyncMock(return_value=compiled)
    response = await real_runner.compile('source', 'python')
    assert response['success'] is False
    assert classify_compile_result(response) == 'compile_resource_error'


def test_output_failure_penalty_and_diagnostics_spoof_resistance():
    assert 'output_limit_exceeded' in PENALTY_VERDICTS
    assert 'process_limit_exceeded' not in PENALTY_VERDICTS
    assert 'compile_resource_error' not in PENALTY_VERDICTS
    for exit_code in (0, 124, 137):
        result = dict(exit_code=exit_code, stdout='42', stderr='memory_limit_exceeded OOM timeout', execution_phase='run')
        assert classify_grading_result(result, '42') == ('accepted' if exit_code == 0 else 'runtime_error')
