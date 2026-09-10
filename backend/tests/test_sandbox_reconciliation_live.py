"""Opt-in actual daemon effects followed by deliberately lost client receipts."""
from datetime import timedelta
import os
from pathlib import Path
from uuid import uuid4

import docker
from docker.errors import DockerException, NotFound
from docker.types import LogConfig
import pytest

from app.services.durable_queue import DurableQueue, WorkerIdentity
from app.services.execution_worker import SandboxPool
from app.services.sandbox_identity import sandbox_labels
from tests.test_durable_queue import replicas, add
from tests.test_sandbox_operations import AT, pending

pytestmark = pytest.mark.skipif(os.getenv('RUN_SANDBOX_INTEGRATION') != '1',
    reason='Explicit isolated Docker test environment required')


@pytest.mark.parametrize('kind', ['create', 'start'])
@pytest.mark.parametrize('lost_remove', [False, True])
def test_actual_effect_lost_receipt_recovers_exact_container(replicas, kind, lost_remove):
    root = Path(os.environ['AUDIT_ROOT']).resolve()
    assert root.name.startswith('webcompiler-audit-')
    client = docker.from_env(timeout=10)
    queue = DurableQueue(replicas[0], concurrency=1)
    add(queue, at=AT)
    nonce = uuid4().hex
    identity = WorkerIdentity(uuid4().hex, 'audit-reconcile', '', 'audit-' + nonce)
    claim = queue.claim(at=AT, worker=identity)
    labels = sandbox_labels(claim.id, claim.token, identity) | {'webcompiler.audit.reconcile': nonce}
    children = []
    try:
        image = client.images.get('nginx:1.30.4-alpine-slim@sha256:77da26c31397bf6694b4bf93275f5b40b0b120ba1b8f114264b603e592c561d6').id  # No pull/fallback.
        def create(operation):
            child = client.containers.create(image, entrypoint='/bin/sh',
                command=['-c', 'sleep 30'], name=operation['name'],
                labels=labels | {'webcompiler.operation': operation['id']},
                network_mode='none', user='10001:10001', read_only=True,
                cap_drop=['ALL'], security_opt=['no-new-privileges'],
                mem_limit='32m', memswap_limit='32m', nano_cpus=100_000_000,
                pids_limit=16, log_config=LogConfig(type='none'),
                restart_policy={'Name': 'no'})
            children.append(child.id)
            if kind == 'create':
                raise DockerException('fixture lost actual create receipt')
            return child
        if kind == 'create':
            with pytest.raises(DockerException):
                queue.sandbox_operation(claim.id, claim.token, 'create', create, at=AT)
        else:
            child = queue.sandbox_operation(claim.id, claim.token, 'create', create, at=AT)
            def start(operation):
                child.start()
                child.reload()
                assert child.status == 'running'
                raise DockerException('fixture lost actual start receipt')
            with pytest.raises(DockerException):
                queue.sandbox_operation(claim.id, claim.token, 'start', start,
                    container_id=child.id, at=AT)
        assert len(children) == 1
        child_id = children[0]
        original = pending(replicas[1], claim.id)
        real_pool = SandboxPool(lambda: client, pool_id=identity.sandbox_pool_id)
        class LostRemovalPool(SandboxPool):
            def remove_operation(self, operation, expected):
                assert pending(replicas[1], claim.id)['resolved_container_id'] == child_id
                super().remove_operation(operation, expected)
                raise DockerException('fixture lost actual removal receipt')
        later = AT + timedelta(hours=1)
        if lost_remove:
            pool = LostRemovalPool(lambda: client, pool_id=identity.sandbox_pool_id)
            with pytest.raises(DockerException):
                queue.reconcile_pending(pool, at=later)
            assert pending(replicas[1], claim.id)['phase'] == 'removing'
        else:
            assert pending(replicas[1], claim.id) == original
        restarted = DurableQueue(replicas[1], concurrency=1, reap_expired=real_pool.reap)
        assert restarted.reconcile_pending(real_pool, at=later) == 1
        with pytest.raises(NotFound):
            client.containers.get(child_id)
        assert pending(replicas[0], claim.id) is None
        restarted.recover_expired(real_pool, at=later)
        next_claim = restarted.claim(at=later)
        assert next_claim.id == claim.id and next_claim.token != claim.token
        # A late actual start request cannot resurrect the removed immutable ID.
        with pytest.raises(NotFound):
            client.api.start(child_id)
    finally:
        for child_id in children:
            try:
                child = client.containers.get(child_id)
            except NotFound:
                continue
            assert child.id == child_id and child.labels['webcompiler.audit.reconcile'] == nonce
            child.remove(force=True)
        client.close()
