"""Bounded graceful-stop requests for exact owned containers."""

import importlib.util
from pathlib import Path
import sys

import pytest

from tests.test_edge_deploy import adapter, edge


ROOT = Path(__file__).resolve().parents[2]
_RETIREMENT_SPEC = importlib.util.spec_from_file_location(
    "runtime_retirement", ROOT / "scripts" / "runtime_retirement.py"
)
runtime_retirement = sys.modules.get("runtime_retirement")
if runtime_retirement is None:
    runtime_retirement = importlib.util.module_from_spec(_RETIREMENT_SPEC)
    sys.modules[_RETIREMENT_SPEC.name] = runtime_retirement
    assert _RETIREMENT_SPEC.loader is not None
    _RETIREMENT_SPEC.loader.exec_module(runtime_retirement)


CONTAINER_ID = "a" * 64


def expected_command(signal):
    return [
        "docker",
        "container",
        "stop",
        "--signal",
        signal,
        "--timeout",
        "-1",
        CONTAINER_ID,
    ]


@pytest.mark.parametrize("signal", ["SIGTERM", "SIGQUIT"])
def test_graceful_stop_uses_exact_command_and_reaps_owned_cli_child(
    monkeypatch,
    signal,
):
    process_module = runtime_retirement.request_stop.__globals__["subprocess"]
    calls = []
    children = []

    def spawn(args, **options):
        calls.append((args, options.copy()))
        assert args == expected_command(signal)
        assert options["stdout"] is process_module.DEVNULL
        assert options["stderr"] is process_module.DEVNULL
        child = real_popen(
            [sys.executable, "-c", "raise SystemExit(0)"], **options
        )
        children.append(child)
        return child

    real_popen = process_module.Popen
    monkeypatch.setattr(process_module, "Popen", spawn)

    assert runtime_retirement.request_stop(CONTAINER_ID, signal=signal) is True
    assert len(calls) == 1
    assert len(children) == 1 and children[0].poll() is not None


def test_cli_timeout_returns_false_without_force_or_remove_and_reaps_child(monkeypatch):
    process_module = runtime_retirement.request_stop.__globals__["subprocess"]
    calls = []
    children = []

    def spawn(args, **options):
        calls.append((args, options.copy()))
        assert args == expected_command("SIGTERM")
        assert options["stdout"] is process_module.DEVNULL
        assert options["stderr"] is process_module.DEVNULL
        child = real_popen(
            [sys.executable, "-c", "import time; time.sleep(60)"], **options
        )
        children.append(child)
        return child

    real_popen = process_module.Popen
    monkeypatch.setattr(process_module, "Popen", spawn)

    assert runtime_retirement.request_stop(CONTAINER_ID, timeout=0.2) is False
    assert len(calls) == 1
    assert all(token not in calls[0][0] for token in ("kill", "rm", "remove", "force"))
    assert len(children) == 1 and children[0].poll() is not None


def test_nonzero_stop_result_is_sanitized_and_has_no_fallback_command(monkeypatch):
    process_module = runtime_retirement.request_stop.__globals__["subprocess"]
    calls = []

    def run(args, **options):
        calls.append((args, options))
        return process_module.CompletedProcess(args, 7)

    monkeypatch.setattr(process_module, "run", run)

    with pytest.raises(edge.EdgeError) as error:
        runtime_retirement.request_stop(CONTAINER_ID)

    assert str(error.value) == "Graceful stop request failed; state unproven"
    assert calls[0][0] == expected_command("SIGTERM")
    assert all(token not in calls[0][0] for token in ("kill", "rm", "remove", "force"))


def test_launch_error_is_sanitized(monkeypatch):
    secret = "fixture-stop-launch-secret"
    process_module = runtime_retirement.request_stop.__globals__["subprocess"]

    def run(*args, **options):
        raise OSError(secret)

    monkeypatch.setattr(process_module, "run", run)

    with pytest.raises(edge.EdgeError) as error:
        runtime_retirement.request_stop(CONTAINER_ID)

    assert str(error.value) == "Graceful stop request unavailable; state unproven"
    assert secret not in str(error.value)


@pytest.mark.parametrize(
    "invalid",
    [
        {"container_id": "a" * 63},
        {"container_id": "A" * 64},
        {"signal": "SIGKILL"},
        {"signal": None},
        {"timeout": True},
        {"timeout": 0},
        {"timeout": 10.1},
        {"timeout": "1"},
    ],
)
def test_invalid_stop_parameters_fail_before_subprocess_spawn(monkeypatch, invalid):
    process_module = runtime_retirement.request_stop.__globals__["subprocess"]
    spawned = []

    def unexpected_run(*args, **options):
        spawned.append(True)
        raise AssertionError("invalid stop input must not launch a CLI")

    monkeypatch.setattr(process_module, "run", unexpected_run)
    kwargs = {"container_id": invalid.get("container_id", CONTAINER_ID)}
    kwargs.update({key: value for key, value in invalid.items() if key != "container_id"})

    with pytest.raises(edge.EdgeError):
        runtime_retirement.request_stop(**kwargs)

    assert spawned == []
