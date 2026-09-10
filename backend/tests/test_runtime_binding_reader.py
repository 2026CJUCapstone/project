"""Bounded subprocess reads for exact runtime evidence binding."""

import importlib.util
from pathlib import Path
import sys

import pytest

from tests.test_edge_deploy import adapter, edge


ROOT = Path(__file__).resolve().parents[2]
_RUNTIME_BINDING_SPEC = importlib.util.spec_from_file_location(
    "runtime_binding", ROOT / "scripts" / "runtime_binding.py"
)
runtime_binding = sys.modules.get("runtime_binding")
if runtime_binding is None:
    runtime_binding = importlib.util.module_from_spec(_RUNTIME_BINDING_SPEC)
    sys.modules[_RUNTIME_BINDING_SPEC.name] = runtime_binding
    assert _RUNTIME_BINDING_SPEC.loader is not None
    _RUNTIME_BINDING_SPEC.loader.exec_module(runtime_binding)


CONTAINER_ID = "a" * 64
RUNTIME = {
    "id": "b" * 32,
    "pool_id": "blue_pool",
    "deployment_sha": "c" * 40,
    "sandbox_pool_id": "sandbox_pool",
}


def expected_command(role=None):
    command = [
        "docker",
        "exec",
        CONTAINER_ID,
        "python",
        "-m",
        "app.runtime_inspect",
        "--runtime",
        RUNTIME["id"],
        "--pool",
        RUNTIME["pool_id"],
        "--release",
        RUNTIME["deployment_sha"],
        "--sandbox-pool",
        RUNTIME["sandbox_pool_id"],
    ]
    if role is not None:
        command += ["--local-role", role]
    return command


@pytest.mark.parametrize("role", [None, "api"])
def test_owned_child_success_returns_output_and_is_reaped(monkeypatch, role):
    process_module = runtime_binding.read_evidence.__globals__["subprocess"]
    create = process_module.Popen
    children = []

    def spawn(args, **options):
        assert args == expected_command(role)
        assert options["stdout"] is process_module.PIPE
        assert options["stderr"] is process_module.DEVNULL
        child = create([sys.executable, "-c", 'print("fixture-evidence", end="")'], **options)
        children.append(child)
        return child

    monkeypatch.setattr(process_module, "Popen", spawn)

    result = runtime_binding.read_evidence(CONTAINER_ID, RUNTIME, role)

    assert result == "fixture-evidence"
    assert len(children) == 1
    assert children[0].poll() is not None


@pytest.mark.parametrize("case", ["oversize", "timeout", "exit", "utf8"])
def test_child_failures_are_bounded_secret_free_and_reaped(monkeypatch, case):
    process_module = runtime_binding.read_evidence.__globals__["subprocess"]
    create = process_module.Popen
    children = []
    scripts = {
        "oversize": (
            "import sys; sys.stdout.write('fixture-secret' * 30000)"
        ),
        "timeout": "import time; time.sleep(60)",
        "exit": "import sys; print('fixture-secret'); sys.exit(2)",
        "utf8": "import sys; sys.stdout.buffer.write(b'\\xfffixture-secret')",
    }

    def spawn(args, **options):
        assert args == expected_command()
        child = create([sys.executable, "-c", scripts[case]], **options)
        children.append(child)
        return child

    monkeypatch.setattr(process_module, "Popen", spawn)
    timeout = 0.2 if case == "timeout" else 2

    with pytest.raises(edge.EdgeError) as error:
        runtime_binding.read_evidence(CONTAINER_ID, RUNTIME, timeout=timeout)

    assert "fixture-secret" not in str(error.value)
    assert len(children) == 1
    assert children[0].poll() is not None


@pytest.mark.parametrize(
    "invalid",
    [
        {"container_id": "a" * 63},
        {"container_id": "A" * 64},
        {"runtime": None},
        {"runtime": {}},
        {"role": "controller"},
        {"timeout": 0},
        {"timeout": True},
        {"timeout": 15.1},
    ],
)
def test_invalid_binding_inputs_fail_before_subprocess_spawn(monkeypatch, invalid):
    process_module = runtime_binding.read_evidence.__globals__["subprocess"]
    spawned = []

    def unexpected_spawn(*args, **options):
        spawned.append(True)
        raise AssertionError("invalid binding input must not spawn a child")

    monkeypatch.setattr(process_module, "Popen", unexpected_spawn)
    kwargs = {
        "container_id": invalid.get("container_id", CONTAINER_ID),
        "runtime": invalid.get("runtime", RUNTIME),
        "role": invalid.get("role"),
        "timeout": invalid.get("timeout", 15),
    }

    with pytest.raises(edge.EdgeError):
        runtime_binding.read_evidence(**kwargs)

    assert spawned == []


def test_launch_error_does_not_expose_infrastructure_details(monkeypatch):
    def failed(*args, **kwargs):
        raise OSError('fixture-secret launch failure')
    monkeypatch.setattr(runtime_binding.subprocess, 'Popen', failed)
    with pytest.raises(edge.EdgeError) as error:
        runtime_binding.read_evidence(CONTAINER_ID, RUNTIME)
    assert 'fixture-secret' not in str(error.value)
