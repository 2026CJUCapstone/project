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
