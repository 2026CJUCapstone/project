"""Configuration and scope isolation for the worker process marker."""

import hashlib
import json
import re

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.services import runtime_health
from app.services import worker_process
from app.services.worker_process import ProcessIdentity


@pytest.fixture(autouse=True)
def isolate_worker_configuration_environment(monkeypatch):
    for name in (
        "REDIS_KEY_PREFIX",
        "RUNTIME_POOL_ID",
        "DEPLOYMENT_SHA",
        "RUNTIME_INSTANCE_ID",
        "SANDBOX_POOL_ID",
        "SANDBOX_IMAGE",
        "WORKER_STATE_DIRECTORY",
    ):
        monkeypatch.delenv(name, raising=False)


def test_worker_state_directory_defaults_to_empty_without_external_environment():
    config = Settings(_env_file=None)

    assert config.WORKER_STATE_DIRECTORY == ""


@pytest.mark.parametrize(
    "value",
    [
        "worker-state",
        b"/tmp/worker-state",
        None,
        "C:/worker-state\x00marker",
    ],
)
def test_worker_state_directory_rejects_non_absolute_or_unsafe_values(value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, WORKER_STATE_DIRECTORY=value)


def test_worker_state_directory_accepts_explicit_absolute_path(tmp_path):
    path = str(tmp_path / "worker-state")

    config = Settings(_env_file=None, WORKER_STATE_DIRECTORY=path)

    assert config.WORKER_STATE_DIRECTORY == path


def test_default_worker_scope_is_stable_and_exactly_uses_all_scope_inputs(
    monkeypatch,
):
    first = Settings(_env_file=None)
    second = Settings(_env_file=None)
    monkeypatch.setattr(worker_process, "settings", first)

    scope = worker_process.configured_scope()
    expected_inputs = [
        first.REDIS_KEY_PREFIX,
        first.RUNTIME_POOL_ID,
        first.DEPLOYMENT_SHA,
        first.RUNTIME_INSTANCE_ID,
        first.SANDBOX_POOL_ID,
        first.SANDBOX_IMAGE,
        first.WORKER_STATE_DIRECTORY,
        "process-scope-v3",
        worker_process.local_namespace_token(),
    ]
    expected = hashlib.sha256(
        json.dumps(expected_inputs, separators=(",", ":")).encode()
    ).hexdigest()

    monkeypatch.setattr(worker_process, "settings", second)
    assert worker_process.configured_scope() == scope == expected
    assert re.fullmatch(r"[0-9a-f]{64}", scope)


def test_explicit_worker_directories_separate_scope_and_process_slots(
    monkeypatch,
    tmp_path,
):
    common = dict(
        REDIS_KEY_PREFIX="test-namespace",
        RUNTIME_POOL_ID="test-pool",
        DEPLOYMENT_SHA="a" * 40,
        RUNTIME_INSTANCE_ID="b" * 32,
        SANDBOX_POOL_ID="test-sandbox",
        SANDBOX_IMAGE="test-image",
    )
    first = Settings(
        _env_file=None,
        **common,
        WORKER_STATE_DIRECTORY=str(tmp_path / "worker-a"),
    )
    second = Settings(
        _env_file=None,
        **common,
        WORKER_STATE_DIRECTORY=str(tmp_path / "worker-b"),
    )

    monkeypatch.setattr(worker_process, "settings", first)
    first_scope = worker_process.configured_scope()
    monkeypatch.setattr(worker_process, "settings", second)
    second_scope = worker_process.configured_scope()

    assert first_scope != second_scope
    first_identity = ProcessIdentity(
        "c" * 31 + "1", 1, "worker-start", "same-host", first_scope
    )
    second_identity = ProcessIdentity(
        "d" * 31 + "1", 1, "worker-start", "same-host", second_scope
    )
    assert runtime_health.process_slot(first_identity) != runtime_health.process_slot(
        second_identity
    )


def test_same_local_namespace_token_keeps_worker_scope_stable(monkeypatch):
    config = Settings(_env_file=None)
    monkeypatch.setattr(worker_process, "settings", config)
    monkeypatch.setattr(worker_process, "local_namespace_token", lambda: "namespace-a")

    first_scope = worker_process.configured_scope()
    second_scope = worker_process.configured_scope()

    assert second_scope == first_scope


def test_different_local_namespace_tokens_separate_scope_and_process_slot(
    monkeypatch,
):
    config = Settings(_env_file=None)
    monkeypatch.setattr(worker_process, "settings", config)
    monkeypatch.setattr(worker_process, "local_namespace_token", lambda: "namespace-a")
    first_scope = worker_process.configured_scope()
    monkeypatch.setattr(worker_process, "local_namespace_token", lambda: "namespace-b")
    second_scope = worker_process.configured_scope()

    assert first_scope != second_scope
    first_identity = ProcessIdentity(
        "c" * 31 + "1", 1, "worker-start", "same-host", first_scope
    )
    second_identity = ProcessIdentity(
        "d" * 31 + "1", 1, "worker-start", "same-host", second_scope
    )
    assert runtime_health.process_slot(first_identity) != runtime_health.process_slot(
        second_identity
    )
