"""Process binding validation for durable worker identities."""

from dataclasses import FrozenInstanceError

import pytest

from app.services.durable_queue import WorkerIdentity


WORKER_ID = "a" * 32
POOL_ID = "blue_pool-1"
DEPLOYMENT_SHA = "b" * 40
SANDBOX_POOL_ID = "sandbox_pool-1"
RUNTIME_ID = "c" * 32
PROCESS_ID = "d" * 32


def identity(**overrides):
    values = {
        "id": WORKER_ID,
        "pool_id": POOL_ID,
        "deployment_sha": DEPLOYMENT_SHA,
        "sandbox_pool_id": SANDBOX_POOL_ID,
        "runtime_id": "",
        "process_id": "",
    }
    values.update(overrides)
    return WorkerIdentity(**values)


def test_five_positional_arguments_keep_runtime_identity_and_empty_process_binding():
    result = WorkerIdentity(
        WORKER_ID,
        POOL_ID,
        DEPLOYMENT_SHA,
        SANDBOX_POOL_ID,
        RUNTIME_ID,
    )

    assert result.runtime_id == RUNTIME_ID
    assert result.process_id == ""


def test_four_positional_arguments_keep_legacy_empty_runtime_and_process_binding():
    result = WorkerIdentity(
        WORKER_ID,
        POOL_ID,
        DEPLOYMENT_SHA,
        SANDBOX_POOL_ID,
    )

    assert result.runtime_id == ""
    assert result.process_id == ""


@pytest.mark.parametrize("runtime_id", ["", RUNTIME_ID])
def test_empty_process_binding_is_accepted_for_legacy_or_runtime_identity(runtime_id):
    result = identity(runtime_id=runtime_id, process_id="")

    assert result.process_id == ""


def test_explicit_process_binding_is_available_as_the_sixth_positional_argument():
    result = WorkerIdentity(
        WORKER_ID,
        POOL_ID,
        DEPLOYMENT_SHA,
        SANDBOX_POOL_ID,
        RUNTIME_ID,
        PROCESS_ID,
    )

    assert result.runtime_id == RUNTIME_ID
    assert result.process_id == PROCESS_ID


def test_nonempty_process_binding_requires_runtime_identity():
    with pytest.raises((TypeError, ValueError)):
        identity(process_id=PROCESS_ID)


def test_worker_identity_with_process_binding_is_frozen():
    result = identity(runtime_id=RUNTIME_ID, process_id=PROCESS_ID)

    with pytest.raises(FrozenInstanceError):
        result.process_id = "e" * 32


@pytest.mark.parametrize(
    "process_id",
    [
        None,
        123,
        True,
        False,
        b"d" * 32,
        "a" * 31,
        "a" * 33,
        "A" * 32,
        "0" * 32,
        "a" * 31 + "-1",
        "a" * 32 + "\n",
        "a" * 32 + "\r\n",
        "a" * 31 + "-",
    ],
)
def test_process_binding_rejects_nonstring_or_invalid_identity(process_id):
    with pytest.raises((TypeError, ValueError)):
        identity(runtime_id=RUNTIME_ID, process_id=process_id)
