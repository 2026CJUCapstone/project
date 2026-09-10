"""Compiler Docker operation-guard wiring contracts."""

from types import SimpleNamespace

import pytest

from app.services.compiler import DockerCompilerRunner


@pytest.mark.asyncio
async def test_managed_allocation_uses_guard_operation_name_and_label():
    create_calls = []
    guard_calls = []
    base_labels = {"webcompiler.role": "sandbox", "fixture": "preserved"}
    command = ["run", "python", "/workspace/main.py"]

    def create(**kwargs):
        create_calls.append(kwargs)
        return SimpleNamespace(id="f" * 64)

    def guard(kind, action, **context):
        guard_calls.append((kind, context))
        return action({"id": "operation-123", "name": "sandbox-deterministic"})

    runner = DockerCompilerRunner(
        labels={"runner-default": "unused"}, operation_guard=guard
    )
    result = await runner._allocate_container(
        create,
        image="compiler-sandbox:fixture",
        command=command,
        detach=True,
        labels=base_labels,
        environment={"COMPILER_OPTIMIZE": "0"},
    )

    assert result.id == "f" * 64
    assert guard_calls == [("create", {})]
    assert create_calls == [
        {
            "image": "compiler-sandbox:fixture",
            "command": command,
            "detach": True,
            "labels": {
                "webcompiler.role": "sandbox",
                "fixture": "preserved",
                "webcompiler.operation": "operation-123",
            },
            "environment": {"COMPILER_OPTIMIZE": "0"},
            "name": "sandbox-deterministic",
        }
    ]
    assert base_labels == {"webcompiler.role": "sandbox", "fixture": "preserved"}


@pytest.mark.asyncio
async def test_managed_start_passes_full_container_id_and_callback_to_guard():
    container_id = "a" * 64
    started = []
    guard_calls = []

    def start():
        started.append(True)

    container = SimpleNamespace(id=container_id, start=start)

    def guard(kind, action, **context):
        guard_calls.append((kind, context))
        action({"id": "operation-456", "name": "ignored-for-start"})
        return "guard-result"

    runner = DockerCompilerRunner(
        start_guard=lambda callback: pytest.fail("legacy start guard was used"),
        operation_guard=guard,
    )

    await runner._start_container(container)

    assert guard_calls == [("start", {"container_id": container_id})]
    assert started == [True]


@pytest.mark.asyncio
async def test_unmanaged_allocation_and_start_keep_direct_runner_path():
    create_calls = []
    started = []
    container = SimpleNamespace(id="b" * 64, start=lambda: started.append(True))

    def create(**kwargs):
        create_calls.append(kwargs)
        return container

    runner = DockerCompilerRunner()
    result = await runner._allocate_container(
        create, image="compiler-sandbox:fixture", command=["run"], detach=True
    )
    await runner._start_container(result)

    assert result is container
    assert create_calls == [
        {"image": "compiler-sandbox:fixture", "command": ["run"], "detach": True}
    ]
    assert started == [True]
