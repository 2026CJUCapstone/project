"""Deterministic CLI tests for exact runtime evidence inspection."""

import json

import pytest

from app import runtime_inspect
from app.services.runtime_identity import RuntimeIdentity


RUNTIME_ID = "a" * 32
POOL_ID = "blue_pool"
RELEASE = "b" * 40
SANDBOX_POOL_ID = "sandbox_pool"
EPOCH = "c" * 32


@pytest.fixture
def configured(monkeypatch):
    runtime = RuntimeIdentity(RUNTIME_ID, POOL_ID, RELEASE, SANDBOX_POOL_ID)
    monkeypatch.setattr(
        runtime_inspect.RuntimeIdentity,
        "configured",
        classmethod(lambda cls: runtime),
    )
    return runtime


def arguments(runtime):
    return [
        "--runtime",
        runtime.id,
        "--pool",
        runtime.pool_id,
        "--release",
        runtime.deployment_sha,
        "--sandbox-pool",
        runtime.sandbox_pool_id,
    ]


def test_exact_configured_target_and_default_snapshot_are_forwarded(
    configured,
    monkeypatch,
    capsys,
):
    created = []
    events = []
    result = {"runtime": configured.id, "processes": [], "state": "snapshot"}

    class RecordingEvidence:
        def __init__(self, sessions, runtime):
            created.append((sessions, runtime))

        def snapshot(self):
            events.append(("snapshot",))
            return result

        def local(self, role):
            events.append(("local", role))
            return result

    monkeypatch.setattr(runtime_inspect, "RuntimeEvidence", RecordingEvidence)

    runtime_inspect.main(arguments(configured))

    assert created == [(runtime_inspect.SessionLocal, configured)]
    assert events == [("snapshot",)]
    assert json.loads(capsys.readouterr().out) == result


@pytest.mark.parametrize(
    ("option", "replacement"),
    [
        ("--runtime", "d" * 32),
        ("--pool", "green_pool"),
        ("--release", "e" * 40),
        ("--sandbox-pool", "other_sandbox"),
    ],
)
def test_configured_four_tuple_mismatch_fails_before_evidence_construction(
    configured,
    monkeypatch,
    option,
    replacement,
):
    args = arguments(configured)
    args[args.index(option) + 1] = replacement
    monkeypatch.setattr(
        runtime_inspect,
        "RuntimeEvidence",
        lambda *args: pytest.fail("evidence must not be constructed"),
    )

    with pytest.raises(SystemExit) as error:
        runtime_inspect.main(args)

    assert error.value.code == 1


@pytest.mark.parametrize("role", ["api", "worker"])
@pytest.mark.parametrize("state", ["alive", "absent"])
def test_local_alive_and_absent_processes_print_json_and_exit_zero(
    configured,
    monkeypatch,
    capsys,
    role,
    state,
):
    events = []
    result = {
        "version": 1,
        "runtime": configured.id,
        "role": role,
        "processes": [{"epoch": EPOCH, "state": state}],
    }

    class RecordingEvidence:
        def __init__(self, sessions, runtime):
            assert sessions is runtime_inspect.SessionLocal
            assert runtime == configured

        def local(self, requested_role):
            events.append(requested_role)
            return result

    monkeypatch.setattr(runtime_inspect, "RuntimeEvidence", RecordingEvidence)

    runtime_inspect.main(arguments(configured) + ["--local-role", role])

    assert events == [role]
    assert json.loads(capsys.readouterr().out) == result


@pytest.mark.parametrize("processes", [[], [{"epoch": EPOCH, "state": "unknown"}]])
def test_empty_or_unknown_local_processes_print_result_and_exit_one(
    configured,
    monkeypatch,
    capsys,
    processes,
):
    result = {
        "version": 1,
        "runtime": configured.id,
        "role": "worker",
        "processes": processes,
    }

    class FixedEvidence:
        def __init__(self, sessions, runtime):
            pass

        def local(self, role):
            return result

    monkeypatch.setattr(runtime_inspect, "RuntimeEvidence", FixedEvidence)

    with pytest.raises(SystemExit) as error:
        runtime_inspect.main(arguments(configured) + ["--local-role", "worker"])

    assert error.value.code == 1
    assert json.loads(capsys.readouterr().out) == result


def test_database_exception_uses_safe_message_without_fixture_secret(
    configured,
    monkeypatch,
    capsys,
):
    secret = "fixture-runtime-evidence-secret"

    class FailingEvidence:
        def __init__(self, sessions, runtime):
            pass

        def snapshot(self):
            raise RuntimeError(secret)

    monkeypatch.setattr(runtime_inspect, "RuntimeEvidence", FailingEvidence)

    with pytest.raises(SystemExit) as error:
        runtime_inspect.main(arguments(configured))

    captured = capsys.readouterr()
    assert error.value.code == 1
    assert captured.out == ""
    assert captured.err == "Runtime evidence unavailable; no retirement authorization\n"
    assert secret not in captured.out + captured.err


def test_invalid_local_role_is_rejected_by_argparse(configured):
    with pytest.raises(SystemExit) as error:
        runtime_inspect.main(arguments(configured) + ["--local-role", "controller"])

    assert error.value.code == 2


def test_missing_required_runtime_arguments_are_rejected_by_argparse():
    with pytest.raises(SystemExit) as error:
        runtime_inspect.main([])

    assert error.value.code == 2
