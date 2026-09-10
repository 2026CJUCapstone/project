"""Real worker/runner finalizers preserve evidence after daemon-side effects."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from docker.errors import DockerException
from sqlalchemy import event, inspect

from app.core.config import settings
from app.models.database import ExecutionJob
from app.services.compiler import DockerCompilerRunner
from app.services.durable_queue import DurableQueue
from app.services.execution_worker import ExecutionWorker
from tests.test_durable_queue import replicas
from tests.test_sandbox_operations import pending


@pytest.mark.asyncio
@pytest.mark.parametrize('kind',['create','start'])
@pytest.mark.parametrize('failure',['transport','ack-commit'])
async def test_effect_before_failure_preserves_container_workdir_and_running_claim(
        replicas,tmp_path,monkeypatch,kind,failure):
    monkeypatch.setattr(settings,'SANDBOX_WORKDIR_ROOT',str(tmp_path/'sandboxes'))
    queue=DurableQueue(replicas[0])
    job=queue.enqueue(owner_key='owner',request_id='one',kind='run',
        payload={'code':'print(42)','language':'python'})
    children=[]
    reaped=[]
    removed=[]
    class Container:
        id='a'*64
        running=False
        def attach(self,**kwargs): return iter(())
        def remove(self,**kwargs): removed.append(self.id)
        def start(self):
            self.running=True
            if kind=='start' and failure=='transport': raise DockerException('fixture response lost')
    def create(**kwargs):
        child=Container()
        child.labels=kwargs['labels']
        child.name=kwargs['name']
        child.directory=Path(next(iter(kwargs['volumes'])))
        children.append(child)
        if kind=='create' and failure=='transport': raise DockerException('fixture response lost')
        return child
    client=SimpleNamespace(containers=SimpleNamespace(create=create))
    class Runner(DockerCompilerRunner):
        def _get_client(self): return client
    acknowledged=[]
    def fail_ack(session):
        for record in session.dirty:
            if (isinstance(record,ExecutionJob) and record.sandbox_operation is None
                    and any(isinstance(value,dict) for value in inspect(record).attrs.sandbox_operation.history.deleted)):
                acknowledged.append(True)
                if len(acknowledged)==(1 if kind=='create' else 2):
                    raise RuntimeError('fixture acknowledgment commit failed')
    if failure=='ack-commit': event.listen(replicas[0],'before_commit',fail_ack)
    try:
        worker=ExecutionWorker(queue,runner_factory=Runner,
            pool=SimpleNamespace(reap=lambda *args:reaped.append(args)))
        assert await worker.run_once()
    finally:
        if failure=='ack-commit': event.remove(replicas[0],'before_commit',fail_ack)
    assert len(children)==1 and removed==[] and reaped==[]
    child=children[0]
    assert child.directory.is_dir()
    assert (child.directory/'main.py').read_text()=='print(42)'
    operation=pending(replicas[1],job)
    assert operation['kind']==kind
    if kind=='create':
        assert operation['name']==child.name
        assert operation['id']==child.labels['webcompiler.operation']
    else:
        assert operation['container_id']==child.id and child.running
    assert queue.read(job,owner_key='owner')['status']=='running'


def test_cleanup_guard_rejects_pending_and_foreign_lease_without_calling_action(replicas):
    from tests.test_sandbox_operations import prepared,AT
    queue,claim=prepared(replicas)
    effects=[]
    assert queue.cleanup_lease(claim.id,'f'*32,lambda:effects.append(True)) is False
    with pytest.raises(DockerException):
        queue.sandbox_operation(claim.id,claim.token,'create',
            lambda _:(_ for _ in ()).throw(DockerException()),at=AT)
    assert queue.cleanup_lease(claim.id,claim.token,lambda:effects.append(True)) is False
    assert effects==[]
