"""A terminal result must use the same trusted verdict contract as IDE run."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.durable_queue import DurableQueue
from app.services.execution_worker import ExecutionWorker
from app.services import terminal_broker, terminal_runner
from tests.test_durable_queue import replicas


@pytest.mark.asyncio
@pytest.mark.parametrize('value,expected', [
    ({'exit_code':0,'execution_phase':'run'},'finished'),
    ({'exit_code':1,'execution_phase':'compile'},'compile_error'),
    ({'exit_code':137,'execution_phase':'run'},'runtime_error'),
    ({'exit_code':137,'execution_phase':'run','failure_reason':'memory_limit_exceeded'},'memory_limit_exceeded'),
])
async def test_terminal_worker_publishes_phase_aware_verdict(replicas, monkeypatch, value, expected):
    queue = DurableQueue(replicas[0],concurrency=1)
    job = queue.enqueue(owner_key='terminal:fixture',request_id='request',kind='terminal',
        payload={'code':'fixture code','language':'cpp','terminal_session':'fixture'})
    monkeypatch.setattr(terminal_broker,'TerminalBroker',lambda:None)
    monkeypatch.setattr(terminal_runner,'run_terminal',AsyncMock(return_value=value))
    worker = ExecutionWorker(queue,
        pool=SimpleNamespace(labels=lambda *args:{},reap=lambda *args:None),
        runner_factory=lambda **kwargs:object())
    assert await worker.run_once()
    result = queue.read(job,owner_key='terminal:fixture')
    assert result['status']=='completed'
    assert result['result']['verdict']==expected
    assert result['result']['value']==value
