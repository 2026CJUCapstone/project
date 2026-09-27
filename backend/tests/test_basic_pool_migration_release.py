"""Pure safety checks for the migration-aware release helpers.

These tests only use temporary files. They never invoke Docker or SSH and do
not load any production operator state.
"""
import importlib.util
import inspect
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load_release_module():
    path = ROOT / "scripts" / "basic_pool_migration_release.py"
    spec = importlib.util.spec_from_file_location("basic_pool_migration_release_tested", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def release():
    return load_release_module()


def _write_marker(source: Path, value: str) -> None:
    path = source / "backend/app/initialize.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'RUNTIME_SCHEMA_VERSION = "{value}"\n', encoding="utf-8")


def _contract_tree(release, previous: Path, candidate: Path) -> None:
    for relative in release.UNCHANGED_CONTRACTS:
        for root in (previous, candidate):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"stable contract\n")

    for root in (previous, candidate):
        runtime_script = root / "runtime/sandbox/run.sh"
        runtime_script.parent.mkdir(parents=True, exist_ok=True)
        runtime_script.write_bytes(b"#!/bin/sh\nexit 0\n")

        legacy_runtime = root / "runtime/sandbox/legacy_helper.py"
        legacy_runtime.write_text("# retained runtime file\n", encoding="utf-8")

        module = root / "backend/app/models/problem.py"
        module.parent.mkdir(parents=True, exist_ok=True)
        module.write_text("# kept module\n", encoding="utf-8")

    _write_marker(previous, "2026.09.01")
    _write_marker(candidate, "2026.09.27")


def test_marker_extracts_a_valid_runtime_version(release, tmp_path):
    _write_marker(tmp_path, "schema_2.4-release")

    assert release._marker(tmp_path) == "schema_2.4-release"


@pytest.mark.parametrize(
    "source_text",
    [
        "RUNTIME_SCHEMA_VERSION = ''\n",
        "RUNTIME_SCHEMA_VERSION = 'contains spaces'\n",
        "RUNTIME_SCHEMA_VERSION = 'bad/value'\n",
        "# no version marker\n",
    ],
)
def test_marker_rejects_missing_or_malformed_versions(release, tmp_path, source_text):
    path = tmp_path / "backend/app/initialize.py"
    path.parent.mkdir(parents=True)
    path.write_text(source_text, encoding="utf-8")

    with pytest.raises(AssertionError):
        release._marker(tmp_path)


def test_contract_check_requires_the_runtime_file_set_to_remain_unchanged(release, tmp_path):
    previous, candidate = tmp_path / "previous", tmp_path / "candidate"
    _contract_tree(release, previous, candidate)

    release.check_migration_contracts(previous, candidate)


@pytest.mark.parametrize("change", ["extra_runtime", "removed_runtime", "removed_module", "same_marker", "crlf_shell"])
def test_contract_check_rejects_unreviewed_runtime_or_schema_changes(release, tmp_path, change):
    previous, candidate = tmp_path / "previous", tmp_path / "candidate"
    _contract_tree(release, previous, candidate)

    if change == "extra_runtime":
        extra = candidate / "runtime/sandbox/unreviewed.py"
        extra.write_text("# extra\n", encoding="utf-8")
    elif change == "removed_runtime":
        (candidate / "runtime/sandbox/legacy_helper.py").unlink()
    elif change == "removed_module":
        (candidate / "backend/app/models/problem.py").unlink()
    elif change == "same_marker":
        _write_marker(candidate, "2026.09.01")
    elif change == "crlf_shell":
        (candidate / "runtime/sandbox/run.sh").write_bytes(b"#!/bin/sh\r\nexit 0\r\n")

    with pytest.raises(AssertionError):
        release.check_migration_contracts(previous, candidate)


@pytest.mark.parametrize(
    "relative",
    ["backend/Dockerfile", "backend/requirements.lock", "docker-compose.yml", "runtime/docker/Dockerfile"],
)
def test_contract_check_rejects_changes_to_protected_contracts(release, tmp_path, relative):
    previous, candidate = tmp_path / "previous", tmp_path / "candidate"
    _contract_tree(release, previous, candidate)
    (candidate / relative).write_bytes(b"unreviewed change\n")

    with pytest.raises(AssertionError, match="Unreviewed dependency/topology/runtime change"):
        release.check_migration_contracts(previous, candidate)


@pytest.mark.parametrize("value", ["line1\nline2", "line1\rline2"])
def test_env_writer_rejects_line_breaks_before_creating_file(release, tmp_path, value):
    target = tmp_path / "candidate.env"

    with pytest.raises(AssertionError):
        release._write_env(target, {"SAFE_KEY": value})

    assert not target.exists()


@pytest.mark.parametrize("key", ["lowercase", "BAD-KEY", "KEY=value", "_LEADING_UNDERSCORE"])
def test_env_writer_rejects_noncanonical_keys(release, tmp_path, key):
    target = tmp_path / "candidate.env"

    with pytest.raises(AssertionError):
        release._write_env(target, {key: "safe-value"})

    assert not target.exists()


def test_env_writer_is_exclusive_and_writes_sorted_utf8_lf(release, tmp_path):
    target = tmp_path / "candidate.env"
    release._write_env(target, {"ZED": "마지막", "ALPHA_2": "first"})

    assert target.read_bytes() == "ALPHA_2=first\nZED=마지막\n".encode("utf-8")
    if os.name == "posix":
        assert target.stat().st_mode & 0o777 == 0o600

    with pytest.raises(FileExistsError):
        release._write_env(target, {"SAFE_KEY": "replacement"})
    assert "ALPHA_2=first" in target.read_text(encoding="utf-8")


def test_container_environment_reads_exact_container_values(release, monkeypatch):
    monkeypatch.setattr(
        release.b.o,
        "inspect",
        lambda _container: {"Config": {"Env": ["DATABASE_URL=private=value", "RUNTIME_INSTANCE_ID=abc"]}},
    )

    assert release._container_environment("backend-1") == {
        "DATABASE_URL": "private=value",
        "RUNTIME_INSTANCE_ID": "abc",
    }


@pytest.mark.parametrize(
    "entries",
    [["MISSING_SEPARATOR"], ["bad_key=value"], ["DUPLICATE=one", "DUPLICATE=two"]],
)
def test_container_environment_rejects_malformed_or_duplicate_values(release, monkeypatch, entries):
    monkeypatch.setattr(release.b.o, "inspect", lambda _container: {"Config": {"Env": entries}})

    with pytest.raises(AssertionError):
        release._container_environment("backend-1")


def test_postgres_readiness_requires_three_consecutive_successes(release, monkeypatch):
    results = iter([0, 0, 1, 0, 0, 0])
    calls = []

    def fake_run(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=next(results))

    clock = iter(range(20))
    monkeypatch.setattr(release.subprocess, "run", fake_run)
    monkeypatch.setattr(release.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(release.time, "sleep", lambda _seconds: None)

    release._wait_for_stable_postgres("rehearsal-postgres", timeout_seconds=15)

    assert len(calls) == 6


def test_postgres_readiness_times_out_without_a_stable_window(release, monkeypatch):
    results = iter([0, 1, 0, 1, 0, 1])

    monkeypatch.setattr(
        release.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=next(results)),
    )
    clock = iter([0, 1, 2, 3, 4, 5, 6])
    monkeypatch.setattr(release.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(release.time, "sleep", lambda _seconds: None)

    with pytest.raises(AssertionError, match="stably ready"):
        release._wait_for_stable_postgres("rehearsal-postgres", timeout_seconds=4)


def test_rehearsal_uses_the_restored_snapshot_as_its_migration_baseline(release):
    source = inspect.getsource(release.rehearse)
    restore = source.index('"pg_restore"')
    baseline = source.index('before = _fingerprints(postgres, columns)')
    first_initializer = source.index('_run_initialize(state["images"]["backend"]')

    assert restore < baseline < first_initializer
    assert '_fingerprints("webcompiler-postgres", columns)' not in source
    assert source.index("_rehearse_public_quality_cleanup(postgres)") > source.rindex(
        "assert _fingerprints(postgres, columns) == before"
    )


def test_business_fingerprints_exclude_runtime_coordination_tables(release):
    assert "execution_queue_lock" not in release.BUSINESS_TABLES
    assert "execution_jobs" in release.BUSINESS_TABLES
    assert "submissions" in release.BUSINESS_TABLES
    assert "contest_submissions" in release.BUSINESS_TABLES


def test_candidate_edge_configs_add_exact_upload_and_normal_api_limits(release):
    current = {
        "backend": "server {\n    location /api/ {\n        proxy_pass http://127.0.0.1:18003/api/;\n    }\n}\n",
        "frontend": (
            "server {\n"
            "    location /webcompiler/api/ {\n        proxy_pass http://127.0.0.1:18003/api/;\n    }\n"
            "    location /api/ {\n        proxy_pass http://127.0.0.1:18003/api/;\n    }\n"
            "}\n"
        ),
    }

    value = release.candidate_edge_configs(current)

    assert value["backend"].count("client_max_body_size 16m;") == 1
    assert value["frontend"].count("client_max_body_size 16m;") == 2
    assert value["backend"].count("client_max_body_size 512k;") == 1
    assert value["frontend"].count("client_max_body_size 512k;") == 2
    assert value["frontend"].count("proxy_request_buffering off;") == 2
    assert value["backend"].count("limit_conn_zone ") == 2
    assert value["frontend"].count("limit_conn_zone ") == 2
    assert value["backend"].count("limit_conn judge_upload_ip 2;") == 1
    assert value["frontend"].count("limit_conn judge_upload_ip 2;") == 2
    assert "proxy_pass http://127.0.0.1:18003/api/v1/admin/judge-test-data/;" in value["frontend"]


def test_candidate_edge_configs_reject_unexpected_or_already_modified_template(release):
    current = {
        "backend": "server { location /api/ {} }",
        "frontend": "server { location /webcompiler/api/ {} location /api/ {} }",
    }

    with pytest.raises(AssertionError, match="Unexpected edge proxy template"):
        release.candidate_edge_configs(current)
