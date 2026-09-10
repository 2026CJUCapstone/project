"""Cancellation and delayed RPC completion preserve durable claim capacity."""
import asyncio
from datetime import datetime
from threading import Event
from types import SimpleNamespace

import pytest
from docker.errors import DockerException

from app.services.compiler import DockerCompilerRunner
from app.services.durable_queue import DurableQueue
from tests.test_durable_queue import replicas, add
from tests.test_sandbox_operations import pending


@pytest.mark.asyncio
@pytest.mark.parametrize('transport_error',[False,True])
async def test_canceled_allocation_waits_for_owned_request_and_preserves_uncertainty(replicas,transport_error):
    queue=DurableQueue(replicas[0])
    at=datetime(2026,9,10)
    job=add(queue,at=at)
    claim=queue.claim(at=at)
    entered,release=Event(),Event()
    removals=[]
    child=SimpleNamespace(id='a'*64)
    def create(**kwargs):
        assert kwargs['name'].startswith('compiler-'+claim.token+'-')
        assert kwargs['labels']['webcompiler.operation'] in kwargs['name']
        entered.set()
        assert release.wait(5)
        if transport_error: raise DockerException('fixture timeout')
        return child
    runner=DockerCompilerRunner(operation_guard=lambda kind,action,**kwargs:
        queue.sandbox_operation(job,claim.token,kind,action,at=at,**kwargs))
    async def remove(container): removals.append(container.id)
    runner._remove_container=remove
    task=asyncio.create_task(runner._allocate_container(create))
    try:
        assert await asyncio.to_thread(entered.wait,3)
        task.cancel()
        await asyncio.sleep(.02)
        assert not task.done()
        assert pending(replicas[1],job)['kind']=='create'
        release.set()
        with pytest.raises(asyncio.CancelledError): await task
        if transport_error:
            assert pending(replicas[1],job) is not None and removals==[]
            assert queue.finish(job,claim.token,{'verdict':'system_error'},at=at) is False
        else:
            assert pending(replicas[1],job) is None and removals==[child.id]
    finally:
        release.set()
        await asyncio.gather(task,return_exceptions=True)


@pytest.mark.asyncio
async def test_canceled_start_joins_acknowledgment_before_returning_to_cleanup(replicas):
    queue=DurableQueue(replicas[0])
    at=datetime(2026,9,10)
    job=add(queue,at=at)
    claim=queue.claim(at=at)
    entered,release=Event(),Event()
    def start():
        entered.set()
        assert release.wait(5)
    runner=DockerCompilerRunner(operation_guard=lambda kind,action,**kwargs:
        queue.sandbox_operation(job,claim.token,kind,action,at=at,**kwargs))
    task=asyncio.create_task(runner._start_container(SimpleNamespace(id='b'*64,start=start)))
    try:
        assert await asyncio.to_thread(entered.wait,3)
        task.cancel()
        await asyncio.sleep(.02)
        assert not task.done()
        operation=pending(replicas[1],job)
        assert operation['kind']=='start' and operation['container_id']=='b'*64
        release.set()
        with pytest.raises(asyncio.CancelledError): await task
        assert pending(replicas[1],job) is None
    finally:
        release.set()
        await asyncio.gather(task,return_exceptions=True)
