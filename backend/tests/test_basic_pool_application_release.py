"""Pure safety checks for the application-only production release helper."""
import importlib.util
import json
from pathlib import Path
import shutil

import pytest


ROOT = Path(__file__).resolve().parents[2]


def load_release():
    path = ROOT / "scripts/basic_pool_application_release.py"
    spec = importlib.util.spec_from_file_location("basic_pool_application_release_tested", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tree(release, root: Path, *, candidate: bool) -> None:
    for relative in release.APPLICATION_CONTRACTS:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"stable\n")
    marker = root / "backend/app/initialize.py"
    marker.write_text("RUNTIME_SCHEMA_VERSION = 'v26'\n", encoding="utf-8")
    legacy = root / "backend/app/legacy_module.py"
    legacy.write_text("# retained module\n", encoding="utf-8")
    nginx = root / "frontend/nginx.conf"
    nginx.parent.mkdir(parents=True, exist_ok=True)
    if candidate:
        shutil.copyfile(ROOT / "frontend/nginx.conf", nginx)
    else:
        nginx.write_text("historical frontend config\n", encoding="utf-8")
    dockerfile = root / "runtime/docker/Dockerfile"
    dockerfile.parent.mkdir(parents=True, exist_ok=True)
    if candidate:
        source = ROOT / "runtime/docker/Dockerfile"
        shutil.copyfile(source, dockerfile)
        verifier = root / "runtime/sandbox/verify_bpp_runtime.py"
        shutil.copyfile(ROOT / "runtime/sandbox/verify_bpp_runtime.py", verifier)
    else:
        dockerfile.write_text("historical sandbox recipe\n", encoding="utf-8")


def test_exact_non_deployed_runtime_gate_is_allowed():
    release = load_release()
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as folder:
        base = Path(folder)
        previous, candidate = base / "previous", base / "candidate"
        _tree(release, previous, candidate=False)
        _tree(release, candidate, candidate=True)
        release.check_application_contracts(previous, candidate)


@pytest.mark.parametrize(
    "change",
    ["schema", "launcher", "extra_runtime", "verifier", "nginx", "removed_module"],
)
def test_application_release_rejects_active_or_unreviewed_contract_changes(tmp_path, change):
    release = load_release()
    previous, candidate = tmp_path / "previous", tmp_path / "candidate"
    _tree(release, previous, candidate=False)
    _tree(release, candidate, candidate=True)
    if change == "schema":
        (candidate / "backend/app/initialize.py").write_text(
            "RUNTIME_SCHEMA_VERSION = 'v27'\n", encoding="utf-8"
        )
    elif change == "launcher":
        (candidate / "runtime/sandbox/run.sh").write_text("changed\n", encoding="utf-8")
    elif change == "extra_runtime":
        (candidate / "runtime/sandbox/unreviewed.py").write_text("# extra\n", encoding="utf-8")
    elif change == "verifier":
        (candidate / "runtime/sandbox/verify_bpp_runtime.py").write_text("# changed\n", encoding="utf-8")
    elif change == "nginx":
        (candidate / "frontend/nginx.conf").write_text("server { return 200; }\n", encoding="utf-8")
    else:
        (candidate / "backend/app/legacy_module.py").unlink()
    with pytest.raises(AssertionError):
        release.check_application_contracts(previous, candidate)


def test_rollout_has_backup_smoke_fingerprints_and_no_migration():
    release = load_release()
    import inspect
    source = inspect.getsource(release.rollout)
    assert 'm._dump(' in source
    assert 'candidate_readonly_smoke()' in source
    assert source.count('m._fingerprints("webcompiler-postgres", columns)') == 2
    assert source.count('schema_markers("webcompiler-postgres")') == 2
    assert source.count('schema_inventory("webcompiler-postgres")') == 2
    assert 'm._columns("webcompiler-postgres") == columns' in source
    assert "_compose_initialize" not in source
    assert '"sandbox": "reused"' in source


def test_candidate_preflight_is_networkless_and_validates_runtime_security():
    release = load_release()
    import inspect
    source = inspect.getsource(release.preflight_candidate_configuration)
    assert '"--network", "none"' in source
    assert '"--read-only"' in source
    assert '"--user", "10001:10001"' in source
    assert 'environment.get("ENVIRONMENT") == "production"' in source
    assert "validate_runtime_security()" in source
    assert '"python", "-I", "-c"' not in source
    assert "candidate-preflight.env" in source


def test_release_is_pinned_to_the_reviewed_operating_transition():
    release = load_release()
    assert release.m.b is release.b
    assert release.EXPECTED_PREVIOUS_RELEASE == "ebd7e367f396dfab20a3a1f1f6ce96a4fdd4c79e"
    assert release.EXPECTED_REVIEWED_BASE == "488356236e7181b7c7a4e7da09d47cdad4cd40b1"
    assert release.EXPECTED_RELEASE_DELTA == {
        "backend/tests/test_basic_pool_application_release.py",
        "scripts/basic_pool_application_release.py",
    }


def _failure_state(release, tmp_path, monkeypatch, value):
    state_path = tmp_path / "release-state.json"
    state_path.write_text(json.dumps(value), encoding="utf-8")
    monkeypatch.setattr(release.b, "STATE", state_path)
    monkeypatch.setattr(
        release.b,
        "save",
        lambda state: state_path.write_text(json.dumps(state), encoding="utf-8"),
    )
    return state_path


def test_failed_post_start_integrity_keeps_maintenance_closed(tmp_path, monkeypatch):
    release = load_release()
    path = _failure_state(
        release,
        tmp_path,
        monkeypatch,
        {"phase": "starting", "candidate_start_attempted": True, "edge_configs": {}},
    )
    calls = []
    monkeypatch.setattr(release.b, "stop_current", lambda: calls.append("stop"))
    monkeypatch.setattr(release.b, "rollback", lambda: calls.append("rollback"))
    monkeypatch.setattr(release.b, "edge", lambda *_args: calls.append("edge"))

    release.handle_rollout_failure(touched=True)

    assert calls == ["stop"]
    state = json.loads(path.read_text(encoding="utf-8"))
    assert state["phase"] == "failed"
    assert state["candidate_stopped_after_failed_integrity"] is True


def test_failure_after_verified_integrity_allows_application_rollback(tmp_path, monkeypatch):
    release = load_release()
    path = _failure_state(
        release,
        tmp_path,
        monkeypatch,
        {
            "phase": "starting",
            "candidate_start_attempted": True,
            "integrity_verified": True,
            "edge_configs": {},
        },
    )
    calls = []
    monkeypatch.setattr(release.b, "stop_current", lambda: calls.append("stop"))
    monkeypatch.setattr(release.b, "rollback", lambda: calls.append("rollback"))
    monkeypatch.setattr(release.b, "edge", lambda *_args: calls.append("edge"))

    release.handle_rollout_failure(touched=True)

    assert calls == ["rollback"]
    assert json.loads(path.read_text(encoding="utf-8"))["phase"] == "failed"


def test_prepublic_smoke_uses_only_unauthenticated_gets():
    release = load_release()
    import inspect
    source = inspect.getsource(release.candidate_readonly_smoke)
    assert "app.login" not in source
    assert "post_json" not in source
    assert "request_json" in source
    assert "/api/v1/problems/" in source


def test_schema_inventory_casts_postgres_internal_char_types_to_text():
    release = load_release()
    import inspect
    source = inspect.getsource(release.schema_inventory)
    assert "c.relkind::text" in source
    assert "contype::text" in source
