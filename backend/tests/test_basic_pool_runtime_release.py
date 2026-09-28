"""Exact approval, immutable provenance and unchanged schema/security contracts."""
import copy
import importlib.util
import json
from pathlib import Path
import shutil

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load():
    spec = importlib.util.spec_from_file_location("runtime_release_test", ROOT / "scripts/basic_pool_application_release.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def transition(tmp_path):
    app = load()
    previous, candidate = tmp_path / "previous", tmp_path / "candidate"
    for relative in app.APPLICATION_CONTRACTS:
        path = previous / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("stable\n", newline="\n")
    (previous / "backend/app/initialize.py").write_text("RUNTIME_SCHEMA_VERSION = 'v26'\n")
    shutil.copytree(previous, candidate)
    for relative in app.runtime.ALLOWED_CHANGES:
        if relative == "runtime/bpp-ref.txt":
            continue
        path = candidate / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("reviewed candidate\n", newline="\n")
    approval = dict(version=1, previous_sha="a" * 40, candidate_sha="b" * 40,
                    previous_image="sha256:" + "1" * 64, candidate_image="sha256:" + "2" * 64,
                    runtime_digest=app.runtime.runtime_digest(candidate))
    args = dict(previous=previous, candidate=candidate, old_sha="a" * 40, new_sha="b" * 40,
                old_image="sha256:" + "1" * 64)
    return app, approval, args


def test_exact_reviewed_update_keeps_default_rejection(transition):
    app, approval, args = transition
    verified = app.runtime.validate_approval(approval, **args)
    with pytest.raises(AssertionError):
        app.check_application_contracts(args["previous"], args["candidate"])
    app.check_application_contracts(args["previous"], args["candidate"], runtime_approval=verified)


@pytest.mark.parametrize("field,value", [
    ("version", True), ("previous_sha", "c" * 40), ("candidate_sha", "c" * 40),
    ("previous_image", "sha256:" + "3" * 64), ("candidate_image", "compiler-sandbox:latest"),
    ("candidate_image", "sha256:" + "1" * 64), ("runtime_digest", "0" * 64),
])
def test_mismatched_approval_cannot_select_runtime(transition, field, value):
    app, approval, args = transition
    approval[field] = value
    with pytest.raises(ValueError):
        app.runtime.validate_approval(approval, **args)


@pytest.mark.parametrize("relative", ["runtime/sandbox/run.sh", "runtime/bpp-ref.txt", "runtime/unknown.py"])
def test_even_exact_digest_cannot_approve_unreviewed_runtime(transition, relative):
    app, approval, args = transition
    (args["candidate"] / relative).write_text("unauthorized\n")
    approval["runtime_digest"] = app.runtime.runtime_digest(args["candidate"])
    with pytest.raises(ValueError, match="Unreviewed"):
        app.runtime.validate_approval(approval, **args)


@pytest.mark.parametrize("relative", ["backend/app/initialize.py", "backend/requirements.lock", "docker-compose.yml", "backend/app/core/config.py"])
def test_approved_runtime_never_authorizes_schema_dependencies_topology(transition, relative):
    app, approval, args = transition
    verified = app.runtime.validate_approval(approval, **args)
    (args["candidate"] / relative).write_text("unreviewed\n")
    with pytest.raises(AssertionError):
        app.check_application_contracts(args["previous"], args["candidate"], runtime_approval=verified)


def test_deletion_and_unknown_fields_are_rejected(transition):
    app, approval, args = transition
    extra = copy.deepcopy(approval)
    extra["bypass"] = True
    with pytest.raises(ValueError):
        app.runtime.validate_approval(extra, **args)
    (args["candidate"] / "runtime/sandbox/run.sh").unlink()
    with pytest.raises(ValueError, match="deletion"):
        app.runtime.validate_approval(approval, **args)


def test_only_exact_reviewed_compiler_upgrade_can_be_approved(transition):
    app, approval, args = transition
    for root, ref in zip((args["previous"], args["candidate"]), app.runtime.REVIEWED_COMPILER_TRANSITION):
        (root / "runtime/bpp-ref.txt").write_text(ref + "\n")
    approval["runtime_digest"] = app.runtime.runtime_digest(args["candidate"])
    verified = app.runtime.validate_approval(approval, **args)
    app.check_application_contracts(args["previous"], args["candidate"], runtime_approval=verified)
    for ref in ("main", "c" * 40, app.runtime.REVIEWED_COMPILER_TRANSITION[0]):
        (args["candidate"] / "runtime/bpp-ref.txt").write_text(ref + "\n")
        (args["previous"] / "runtime/bpp-ref.txt").write_text("d" * 40 + "\n")
        approval["runtime_digest"] = app.runtime.runtime_digest(args["candidate"])
        with pytest.raises(ValueError, match="Unreviewed compiler"):
            app.runtime.validate_approval(approval, **args)


def test_networkless_candidate_gate_uses_exact_image_and_limits(transition):
    app, approval, _ = transition
    calls = []
    app.runtime.verify_candidate({"images": {"sandbox": approval["candidate_image"]}}, lambda *a, **kw: calls.append((a, kw)))
    assert len(calls) == 2
    for command, kwargs in calls:
        assert command[command.index("--network") + 1] == "none"
        assert command[command.index("--memory") + 1] == "1g"
        assert command[command.index("--memory-swap") + 1] == "1g"
        assert command[command.index("--pids-limit") + 1] == "64"
        assert command[command.index("--cpus") + 1] == "1"
        assert approval["candidate_image"] in command
        assert "--read-only" in command and "--rm" in command
        assert kwargs["timeout"] == 240


def test_digest_is_path_independent_and_normalizes_only_line_endings(transition):
    app, _, args = transition
    clone = args["candidate"].parent / "clone"
    shutil.copytree(args["candidate"], clone)
    target = clone / "runtime/compiler-patches/exploration.bpp"
    target.write_bytes(target.read_bytes().replace(b"\n", b"\r\n"))
    assert app.runtime.runtime_digest(clone) == app.runtime.runtime_digest(args["candidate"])
    target.write_bytes(target.read_bytes() + b" ")
    assert app.runtime.runtime_digest(clone) != app.runtime.runtime_digest(args["candidate"])


@pytest.mark.parametrize("failure", [None, "digest", "ref", "repo", "policy", "id", "mode", "owner", "stale", "missing"])
def test_private_approval_and_image_provenance(transition, monkeypatch, failure):
    app, approval, args = transition
    prod = args["candidate"].parent / "prod"
    directory = prod / ".deploy"
    directory.mkdir(parents=True)
    path = directory / "basic-pool-runtime-approval.json"
    if failure == "stale":
        approval["candidate_sha"] = args["old_sha"]
    if failure != "missing":
        path.write_text(json.dumps(approval))
    from types import SimpleNamespace
    original_lstat = Path.lstat
    monkeypatch.setattr(Path, "lstat", lambda self: SimpleNamespace(st_mode=0o100644 if failure == "mode" else 0o100600,
        st_uid=11 if failure == "owner" else 10, st_size=1000) if self == path else original_lstat(self))
    monkeypatch.setattr(app.runtime.os, "getuid", lambda: 10, raising=False)
    image = {"Id": approval["candidate_image"], "Config": {"Labels": {
        "io.bpp.runtime_source_digest": approval["runtime_digest"], "io.bpp.ref": "stable",
        "io.bpp.repo": "https://github.com/Creeper0809/Bpp", "io.bpp.test_skip_llvm_build": "1", "io.bpp.test_fast_io": "0",
    }}}
    label_failure = {"digest": "io.bpp.runtime_source_digest", "ref": "io.bpp.ref", "repo": "io.bpp.repo", "policy": "io.bpp.test_fast_io"}
    if failure in label_failure:
        image["Config"]["Labels"][label_failure[failure]] = "wrong"
    if failure == "id":
        image["Id"] = "sha256:" + "3" * 64
    def invoke():
        return app.runtime.load_approval(prod, args["previous"], args["candidate"], args["old_sha"], args["new_sha"], args["old_image"], lambda _: image)
    if failure in (None, "stale", "missing"):
        assert invoke() == (approval if failure is None else None)
    else:
        with pytest.raises(ValueError):
            invoke()
