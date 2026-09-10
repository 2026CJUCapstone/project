"""Deterministic CLI tests for private process observation."""

import json

import pytest

from app import process_observe
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
        process_observe.RuntimeIdentity,
        "configured",
        classmethod(lambda cls: runtime),
    )
    return runtime


def arguments(runtime, *, role="worker", epoch=EPOCH):
    return [
        "--role",
        role,
        "--epoch",
        epoch,
        "--runtime",
        runtime.id,
        "--pool",
        runtime.pool_id,
        "--release",
        runtime.deployment_sha,
        "--sandbox-pool",
        runtime.sandbox_pool_id,
    ]


def test_exact_observer_arguments_are_forwarded_to_process_observer(
    configured,
    monkeypatch,
    capsys,
):
    created = []
    observed = []

    class RecordingObserver:
        def __init__(self, sessions, runtime):
            created.append((sessions, runtime))

        def observe(self, role, epoch):
            observed.append((role, epoch))
            return {"role": role, "epoch": epoch, "state": "alive"}

    monkeypatch.setattr(process_observe, "ProcessObserver", RecordingObserver)

    process_observe.main(arguments(configured, role="api"))

    assert created == [(process_observe.SessionLocal, configured)]
    assert observed == [("api", EPOCH)]
    assert json.loads(capsys.readouterr().out) == {
        "role": "api",
        "epoch": EPOCH,
        "state": "alive",
    }


@pytest.mark.parametrize(
    ("option", "replacement"),
    [
        ("--runtime", "d" * 32),
        ("--pool", "green_pool"),
        ("--release", "e" * 40),
        ("--sandbox-pool", "other_sandbox"),
    ],
)
def test_configured_metadata_mismatch_fails_before_observation(
    configured,
    monkeypatch,
    option,
    replacement,
):
    args = arguments(configured)
    args[args.index(option) + 1] = replacement
    monkeypatch.setattr(
        process_observe,
        "ProcessObserver",
        lambda *args: pytest.fail("observer must not be constructed"),
    )

    with pytest.raises(SystemExit) as error:
        process_observe.main(args)

    assert error.value.code == 1


@pytest.mark.parametrize("state", ["alive", "absent", "unknown"])
def test_observation_state_is_reported_and_unknown_exits_one(
    configured,
    monkeypatch,
    capsys,
    state,
):
    class FixedObserver:
        def __init__(self, sessions, runtime):
            assert runtime == configured

        def observe(self, role, epoch):
            return {
                "runtime_id": configured.id,
                "role": role,
                "epoch": epoch,
                "state": state,
            }

    monkeypatch.setattr(process_observe, "ProcessObserver", FixedObserver)

    if state == "unknown":
        with pytest.raises(SystemExit) as error:
            process_observe.main(arguments(configured))
        assert error.value.code == 1
    else:
        process_observe.main(arguments(configured))

    captured = capsys.readouterr()
    assert json.loads(captured.out)["state"] == state


def test_backend_exception_uses_safe_message_without_secret_leak(
    configured,
    monkeypatch,
    capsys,
):
    secret = "fixture-process-observer-secret"

    class FailingObserver:
        def __init__(self, sessions, runtime):
            pass

        def observe(self, role, epoch):
            raise RuntimeError(secret)

    monkeypatch.setattr(process_observe, "ProcessObserver", FailingObserver)

    with pytest.raises(SystemExit) as error:
        process_observe.main(arguments(configured))

    captured = capsys.readouterr()
    assert error.value.code == 1
    assert captured.out == ""
    assert captured.err == (
        "Process observation unavailable; no retirement authorization\n"
    )
    assert secret not in captured.out + captured.err
