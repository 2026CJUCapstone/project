"""Namespace-observation failures never become evidence that a target is gone."""

import errno
from pathlib import Path
from uuid import uuid4

import pytest

from app.services import process_observation as observer
from app.services import worker_process as worker
from app.services.worker_process import ProcessIdentity


PID = 73
BOOT_PATH = "/proc/sys/kernel/random/boot_id"
PID_NAMESPACE_PATH = "/proc/self/ns/pid"
LINKS = {
    "/proc/self": str(PID),
    "/proc/self/ns/pid": "pid:[101]",
    "/proc/1/ns/pid": "pid:[101]",
    "/proc/self/ns/user": "user:[201]",
}
BOOT_ID = "01234567-89ab-cdef-0123-456789abcdef"


@pytest.fixture
def exact_linux_proc(monkeypatch):
    """Allow only the proc paths used by the namespace observer."""
    monkeypatch.setattr(worker.sys, "platform", "linux")
    monkeypatch.setattr(worker.os, "getpid", lambda: PID)
    monkeypatch.setattr(worker.os, "geteuid", lambda: 1001, raising=False)

    def readlink(path):
        path = str(path)
        if path not in LINKS:
            raise AssertionError(f"unexpected proc readlink path: {path}")
        return LINKS[path]

    def read_text(path):
        path = path.as_posix()
        if path != BOOT_PATH:
            raise AssertionError(f"unexpected proc read path: {path}")
        return BOOT_ID + "\n"

    monkeypatch.setattr(worker.os, "readlink", readlink)
    monkeypatch.setattr(Path, "read_text", read_text)


def _namespace_error(kind, path):
    if kind == "eacces":
        return PermissionError(errno.EACCES, "fixture namespace access denied", path)
    if kind == "enoent":
        return FileNotFoundError(errno.ENOENT, "fixture namespace missing", path)
    return OSError(errno.EIO, "fixture namespace observer failure", path)


@pytest.mark.parametrize("failure_path", [PID_NAMESPACE_PATH, BOOT_PATH])
@pytest.mark.parametrize("failure_kind", ["eacces", "enoent", "oserror"])
def test_namespace_read_failures_are_unknown_without_target_probe(
    exact_linux_proc, monkeypatch, failure_path, failure_kind
):
    def readlink(path):
        path = str(path)
        if path not in LINKS:
            raise AssertionError(f"unexpected proc readlink path: {path}")
        if path == failure_path:
            raise _namespace_error(failure_kind, path)
        return LINKS[path]

    def read_text(path):
        path = path.as_posix()
        if path != BOOT_PATH:
            raise AssertionError(f"unexpected proc read path: {path}")
        if path == failure_path:
            raise _namespace_error(failure_kind, path)
        return BOOT_ID + "\n"

    monkeypatch.setattr(worker.os, "readlink", readlink)
    monkeypatch.setattr(Path, "read_text", read_text)

    identity = ProcessIdentity(uuid4().hex, PID, "linux:boot:123", "fixture", "a" * 64)

    def unexpected_target_probe(pid):
        pytest.fail(f"target process {pid} must not be probed after namespace failure")

    monkeypatch.setattr(observer, "process_start_token", unexpected_target_probe)
    assert observer.local_process_state(identity) == "unknown"


def test_changed_namespace_token_is_unknown_without_target_stat_read(exact_linux_proc, monkeypatch):
    scope = worker.configured_scope()
    identity = ProcessIdentity(uuid4().hex, PID, "linux:" + BOOT_ID + ":123", "fixture", scope)
    monkeypatch.setattr(worker, "local_namespace_token", lambda: "linux:wrong-namespace")

    def unexpected_target_probe(pid):
        pytest.fail(f"target process {pid} must not be probed for a namespace mismatch")

    monkeypatch.setattr(observer, "process_start_token", unexpected_target_probe)
    assert observer.local_process_state(identity) == "unknown"
