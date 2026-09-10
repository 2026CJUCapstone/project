"""Terminal cleanup retains evidence while Docker mutations are uncertain."""

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from docker.errors import DockerException

from app.core.config import settings
from app.services.compiler import DockerCompilerRunner
from app.services.durable_queue import DurableQueue
from app.services.terminal_runner import run_terminal
from tests.test_durable_queue import replicas
from tests.test_sandbox_operations import pending


AT = datetime(2030, 1, 1)


class Broker:
    def __init__(self):
        self.active_calls = []

    def active(self, session_id):
        self.active_calls.append(session_id)
        return True


class TerminalSocket:
    def __init__(self):
        self.closed = False
        self.timeouts = []

    def settimeout(self, value):
        self.timeouts.append(value)

    def close(self):
        self.closed = True


def claim_terminal(replicas):
    queue = DurableQueue(replicas[0], concurrency=1)
    job_id = queue.enqueue(
        owner_key="terminal",
        request_id="session",
        kind="terminal",
        payload={"code": "print(42)", "language": "python"},
        at=AT,
    )
    claim = queue.claim(at=AT)
    assert claim is not None and claim.id == job_id
    return queue, claim


def runner_for_claim(queue, claim, client):
    operation_events = []

    def operation_guard(kind, action, **metadata):
        operation_events.append((kind, metadata))
        return queue.sandbox_operation(
            claim.id,
            claim.token,
            kind,
            action,
            at=AT,
            **metadata,
        )

    def cleanup_guard(action):
        return queue.cleanup_lease(claim.id, claim.token, action)

    class Runner(DockerCompilerRunner):
        def _get_client(self):
            return client

    runner = Runner(
        labels={"webcompiler.job": claim.id, "webcompiler.lease": claim.token},
        operation_guard=operation_guard,
        cleanup_guard=cleanup_guard,
    )
    return runner, operation_events


@pytest.mark.asyncio
async def test_pending_create_failure_retains_workdir_evidence(replicas, tmp_path, monkeypatch):
    root = tmp_path / "sandboxes"
    monkeypatch.setattr(settings, "SANDBOX_WORKDIR_ROOT", str(root))
    queue, claim = claim_terminal(replicas)
    broker = Broker()
    create_calls = []

    class Containers:
        def create(self, **kwargs):
            create_calls.append(kwargs)
            raise DockerException("fixture create transport uncertainty")

    runner, operation_events = runner_for_claim(
        queue, claim, SimpleNamespace(containers=Containers())
    )

    with pytest.raises(DockerException, match="fixture create transport uncertainty"):
        await run_terminal(
            runner,
            broker,
            {
                "terminal_session": "session",
                "language": "python",
                "code": "print(42)",
            },
        )

    assert operation_events and operation_events[0][0] == "create"
    operation = pending(replicas[1], claim.id)
    assert operation["kind"] == "create"
    assert create_calls and create_calls[0]["name"] == operation["name"]
    assert root.exists()
    workdirs = list(root.glob(f"job-{claim.id}-{claim.token}-*"))
    assert len(workdirs) == 1
    assert (workdirs[0] / "main.py").read_text() == "print(42)"


@pytest.mark.asyncio
async def test_pending_start_failure_retains_container_and_workdir_evidence(
    replicas,
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "sandboxes"
    monkeypatch.setattr(settings, "SANDBOX_WORKDIR_ROOT", str(root))
    queue, claim = claim_terminal(replicas)
    broker = Broker()
    terminal_socket = TerminalSocket()
    containers = []

    class Container:
        id = "a" * 64

        def __init__(self):
            self.removed = []
            self.started = 0

        def attach_socket(self, **kwargs):
            return terminal_socket

        def start(self):
            self.started += 1
            raise DockerException("fixture start transport uncertainty")

        def remove(self, **kwargs):
            self.removed.append(kwargs)

    class DockerContainers:
        def create(self, **kwargs):
            container = Container()
            containers.append(container)
            return container

    runner, operation_events = runner_for_claim(
        queue, claim, SimpleNamespace(containers=DockerContainers())
    )

    with pytest.raises(DockerException, match="fixture start transport uncertainty"):
        await run_terminal(
            runner,
            broker,
            {
                "terminal_session": "session",
                "language": "python",
                "code": "print(42)",
            },
        )

    assert [kind for kind, _ in operation_events] == ["create", "start"]
    operation = pending(replicas[1], claim.id)
    assert operation["kind"] == "start"
    assert operation["container_id"] == containers[0].id
    assert containers[0].started == 1
    assert containers[0].removed == []
    assert terminal_socket.closed
    workdirs = list(root.glob(f"job-{claim.id}-{claim.token}-*"))
    assert len(workdirs) == 1
    assert (workdirs[0] / "main.py").read_text() == "print(42)"
