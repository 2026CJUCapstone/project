"""Delayed transport completion must not release capacity before reconciliation.

The separate thread models an already accepted daemon create whose HTTP client
has timed out. There are no real containers, sockets or production effects.
The retained claim is safety evidence, not proof of completed recovery.
"""
from threading import Event, Thread
from types import SimpleNamespace

import pytest
from docker.errors import DockerException

from tests.test_execution_worker import queue, submit
from app.services.compiler import DockerCompilerRunner
from app.services.execution_worker import ExecutionWorker


@pytest.mark.asyncio
async def test_timed_out_create_must_retain_claim_until_daemon_outcome_is_reconciled(queue):
    job=submit(queue)
    release=Event()
    materialized=Event()
    sandboxes=[]
    reaped=[]
    def daemon():
        if release.wait(5):
            sandboxes.append('late-owned-sandbox')
            materialized.set()
    pending=Thread(target=daemon)
    pending.start()
    def create(**kwargs):
        # Returning an error doesn't retract the request already at the daemon.
        raise DockerException('fixture transport observation timed out')
    def reap(*args):
        reaped.append(tuple(sandboxes))
        sandboxes.clear()
    class Runner(DockerCompilerRunner):
        async def run(self,**kwargs):
            return await self._allocate_container(create)
    worker=ExecutionWorker(queue,pool=SimpleNamespace(reap=reap),runner_factory=Runner)
    try:
        assert await worker.run_once()
        assert reaped==[]  # Unknown allocation forbids destructive cleanup too.
        status=queue.read(job,owner_key='test')['status']
        release.set()
        assert materialized.wait(3)
        assert sandboxes==['late-owned-sandbox']
        # A queued/completed receipt releases capacity while allocation is
        # still unresolved, and can incorrectly make retirement look idle.
        assert status=='running'
    finally:
        release.set()
        pending.join(6)
        assert not pending.is_alive()
