"""Explicitly advance a durable worker in API tests, never run a host sandbox."""
from types import SimpleNamespace

from app.services import compiler
from app.services.execution_runtime import execution_queue
from app.services.execution_worker import ExecutionWorker


async def finish_receipt(client, response, *, headers=None, queue=None, runner=None):
    assert response.status_code == 202, response.text
    receipt = response.json()
    job_id = receipt.get('executionId', receipt['id'])
    worker = ExecutionWorker(queue or execution_queue(),
        pool=SimpleNamespace(labels=lambda *args:{}, reap=lambda *args:None),
        runner_factory=lambda **kwargs:runner or compiler.compiler_instance)
    for _ in range(20):
        result = await client.get(f'/api/v1/executions/{job_id}', headers=headers)
        assert result.status_code == 200, result.text
        if result.json()['status'] in ('completed','failed'):
            return result.json()['result']
        assert await worker.run_once()
    raise AssertionError('Test worker did not finish accepted receipt')


def install_measured_fake_judge(tmp_path, monkeypatch):
    """Exercise measured receipt/report publication without contacting Docker."""
    from app.core.config import settings
    from app.services.judge_metrics import JudgeMetrics
    from app.services.judging import _judge_cases
    from tests.test_judge_metrics import phase_result
    from tests.test_judge_policy import install_synthetic_registry

    install_synthetic_registry(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, 'JUDGE_WORKER_CLASS', 'test-cpu')

    async def synthetic_judge(runner, payload, *, contest=False, load_case=None):
        class MeteredRunner:
            async def _execute(self, **kwargs):
                value = await runner._execute(**kwargs)
                protected = phase_result('compile', exitCode=value.get('exit_code', 0),
                    failureReason=value.get('failure_reason'))
                return {**value, 'execution_phase':'compile',
                    'resource_usage':protected['resource_usage']}

            async def run(self, **kwargs):
                value = await runner.run(**kwargs)
                protected = phase_result('run', exitCode=value.get('exit_code', 0),
                    failureReason=value.get('failure_reason'))
                return {**value, 'execution_phase':'run',
                    'resource_usage':protected['resource_usage']}

        metrics = JudgeMetrics(payload)
        result = await _judge_cases(MeteredRunner(), payload, contest=contest,
            metrics=metrics, load_case=load_case)
        result['_resource_report'] = metrics.finish()
        return result

    monkeypatch.setattr('app.services.execution_worker.judge_code', synthetic_judge)
