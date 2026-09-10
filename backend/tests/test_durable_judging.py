import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.judging import judge_code


def payload(sample=None, hidden=None):
    return {'code':'test code', 'language':'python', 'sample':sample or [], 'hidden':hidden or []}


def runner(outputs, compile_code=0):
    return SimpleNamespace(_execute=AsyncMock(return_value={'exit_code':compile_code}),
                           run=AsyncMock(side_effect=[{'stdout':o, 'stderr':'private diagnostic', 'exit_code':0} for o in outputs]))


@pytest.mark.asyncio
async def test_compile_error_is_distinct_and_does_not_run_tests():
    executor = runner([], compile_code=1)
    result = await judge_code(executor, payload(hidden=[{'input':'hidden','expectedOutput':'42'}]))
    assert result['verdict'] == 'compile_error'
    executor.run.assert_not_awaited()


@pytest.mark.asyncio
async def test_hidden_only_problem_is_judged_without_leaking_any_hidden_data():
    executor = runner(['secret actual'])
    result = await judge_code(executor, payload(hidden=[{'input':'secret input','expectedOutput':'secret expected'}]))
    assert result['verdict'] == 'wrong_answer'
    assert result['grading_completed'] and not result['grading_passed']
    assert result['details'] == []
    assert 'secret' not in json.dumps(result) and 'private diagnostic' not in json.dumps(result)


@pytest.mark.asyncio
async def test_sample_failure_skips_hidden_and_preserves_visible_details():
    executor = runner(['wrong'])
    result = await judge_code(executor, payload(sample=[{'input':'visible','expectedOutput':'42'}],
                                              hidden=[{'input':'secret','expectedOutput':'42'}]))
    assert result['status'] == 'SampleFailed'
    assert not result['grading_completed']
    assert result['details'][0]['actual'] == 'wrong'
    executor.run.assert_awaited_once()


@pytest.mark.asyncio
async def test_contest_stops_on_first_wrong_and_returns_no_source_or_test_details():
    executor = runner(['wrong'])
    result = await judge_code(executor, payload(sample=[{'expectedOutput':'42'},{'expectedOutput':'43'}]), contest=True)
    assert result == {'verdict':'wrong_answer'}
    executor.run.assert_awaited_once()


@pytest.mark.asyncio
async def test_all_pass_and_no_tests_never_awards():
    executor = runner(['42','43'])
    result = await judge_code(executor, payload(sample=[{'expectedOutput':'42'}], hidden=[{'expected_output':'43'}]))
    assert result['status'] == 'Accepted' and result['grading_passed']
    empty = await judge_code(executor, payload())
    assert empty['verdict'] == 'system_error' and not empty['grading_passed']


@pytest.mark.asyncio
async def test_large_sample_diagnostics_share_a_utf8_budget_without_changing_the_verdict():
    # Each complete runner output is about 200 KiB. The verdict must use it in
    # full, while the durable public result keeps only a bounded diagnostic view.
    large_wrong_output = 'expected-' + ('가' * ((200 * 1024) // len('가'.encode('utf-8'))))
    executor = runner([large_wrong_output] * 3)

    result = await judge_code(executor, payload(
        sample=[
            {'input': f'sample-{index}', 'expectedOutput': 'expected'}
            for index in range(3)
        ],
        hidden=[{'input': 'hidden-input-must-not-leak', 'expectedOutput': 'hidden-expected-must-not-leak'}],
    ))

    serialized = json.dumps(result, ensure_ascii=False).encode('utf-8')
    assert len(serialized) < 300 * 1024
    assert result['verdict'] == 'wrong_answer'
    assert result['status'] == 'SampleFailed'
    assert not result['grading_completed']
    assert 'hidden-input-must-not-leak' not in serialized.decode('utf-8')
    assert 'hidden-expected-must-not-leak' not in serialized.decode('utf-8')
    executor.run.assert_awaited()
    assert executor.run.await_count == 3
