"""Offline contracts for the deliberately-slow F/I/J separation probe."""

from __future__ import annotations

from pathlib import Path
import shutil
import stat
import sys
from types import ModuleType, SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
for directory in (ROOT, ROOT / "scripts"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import verify_freshman_slow as probe


BASE = ROOT / "tools" / "freshman_contest"
TARGETS = {
    "F": "f-linear-scan-discriminator-mostly-absent-queries",
    "I": "i-maximum-many-sources-front-delete-discriminator",
    "J": "j-maximum-unit-total-long-positive-negative-blocks-int64",
}


def _payload() -> dict:
    return {"judge_contract": {"profile": {"run": {"cpuMs": 1_000, "wallMs": 2_000}}}}


def _usage(*, phase: str = "run", **changes: object) -> dict:
    return {
        "phase": phase,
        "exitCode": 0,
        "failureReason": None,
        "cpuUsec": 100,
        "wallNs": 1_000_000,
        "peakMemoryBytes": 100_000,
        "oomKills": 0,
        "outputBytes": 2,
        "treeReaped": True,
        **changes,
    }


def _result(payload: dict, *, verdict: str, case_verdict: str, usage: dict | None = None) -> dict:
    report = dict(
        version=1,
        compile=_usage(phase="compile"),
        cases=[dict(phase="grading", index=1, verdict=case_verdict,
                    usage=usage or _usage())],
    )
    return dict(verdict=verdict, _resource_report=report)


def _validate_report(report: object, payload: dict) -> None:
    """Small stand-in for the protected validator; no Docker/app dependency."""
    if not isinstance(report, dict) or set(report) != {"version", "compile", "cases"}:
        raise ValueError("invalid synthetic report")
    if not isinstance(report["cases"], list):
        raise ValueError("invalid synthetic cases")
    for phase in [report["compile"], *(case.get("usage") for case in report["cases"] if isinstance(case, dict))]:
        if not isinstance(phase, dict) or not {
            "phase", "exitCode", "failureReason", "cpuUsec", "wallNs", "oomKills", "treeReaped",
        } <= set(phase):
            raise ValueError("invalid synthetic phase")


def _validate_fast_result(result: dict, payload: dict, phase_names: tuple[str, str]) -> list[dict]:
    _validate_report(result.get("_resource_report"), payload)
    report = result["_resource_report"]
    phases = [report["compile"], *(case["usage"] for case in report["cases"])]
    if (result.get("verdict") != "accepted" or len(phases) != len(phase_names)
            or len(set(phase_names)) != len(phase_names)
            or any(case.get("verdict") != "accepted" for case in report["cases"])
            or any(phase["exitCode"] != 0 or phase["failureReason"] is not None
                   or phase["oomKills"] != 0 or phase["treeReaped"] is not True
                   for phase in phases)):
        raise ValueError("fast solution is not a clean acceptance")
    return phases


@pytest.fixture
def protected_report_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep these verifier unit tests independent from the Docker-backed app package."""
    app = ModuleType("app")
    services = ModuleType("app.services")
    judge_metrics = ModuleType("app.services.judge_metrics")
    judge_metrics.validate_report = _validate_report
    app.services = services
    services.judge_metrics = judge_metrics
    monkeypatch.setitem(sys.modules, "app", app)
    monkeypatch.setitem(sys.modules, "app.services", services)
    monkeypatch.setitem(sys.modules, "app.services.judge_metrics", judge_metrics)
    monkeypatch.setattr(probe, "validate_reference_result", _validate_fast_result)


def _copy_slow_sources(tmp_path: Path) -> Path:
    base = tmp_path / "freshman_contest"
    shutil.copytree(BASE / "slow_solutions", base / "slow_solutions")
    return base


def test_fixed_slow_target_descriptors_are_the_v2_discriminators() -> None:
    assert probe.TARGETS == TARGETS
    assert tuple(probe.TARGETS) == ("F", "I", "J")


def test_slow_probe_reuses_private_empty_workspace_guard(tmp_path: Path) -> None:
    workspace=tmp_path/'webcompiler-launcher-test.Slow123'/'work'
    workspace.parent.mkdir()
    workspace.mkdir()
    safe=SimpleNamespace(st_mode=stat.S_IFDIR|0o700)
    assert probe.require_disposable_workspace(
        workspace,expected_parent=tmp_path,metadata=safe)==workspace.resolve()
    for mode in (0o770,0o707,0o755):
        with pytest.raises(RuntimeError,match='Private empty'):
            probe.require_disposable_workspace(
                workspace,expected_parent=tmp_path,
                metadata=SimpleNamespace(st_mode=stat.S_IFDIR|mode))


@pytest.mark.parametrize("letter", ("F", "I", "J"))
def test_target_case_selects_the_exact_hidden_v2_descriptor(letter: str) -> None:
    case, identity, manifest_hash = probe.target_case(BASE, letter)
    assert identity["name"] == TARGETS[letter]
    assert identity["visibility"] == "hidden"
    assert case["input"].encode()
    assert case["expected_output"].encode()
    assert manifest_hash == "sha256:e5213ca9d1aaf3691c91db22aa021870b532b653c015c58c4bf90fff8a8539fc"


@pytest.mark.parametrize("letter", ("F", "I", "J"))
def test_slow_source_path_is_fixed_to_the_pinned_authored_source(letter: str) -> None:
    assert probe.slow_source_path(BASE, letter) == BASE / "slow_solutions" / "python" / f"{letter}.py"


def test_slow_source_path_rejects_unknown_letters_and_changed_or_oversized_bytes(tmp_path: Path) -> None:
    base = _copy_slow_sources(tmp_path)
    with pytest.raises(ValueError):
        probe.slow_source_path(base, "../F")
    with pytest.raises(ValueError):
        probe.slow_source_path(base, "K")

    source = base / "slow_solutions" / "python" / "F.py"
    source.write_bytes(source.read_bytes() + b"\n# mutated\n")
    with pytest.raises(ValueError):
        probe.slow_source_path(base, "F")

    source.write_bytes(b"x" * 65_537)
    with pytest.raises(ValueError):
        probe.slow_source_path(base, "F")


def test_slow_source_path_rejects_a_non_regular_path(tmp_path: Path) -> None:
    base = _copy_slow_sources(tmp_path)
    source = base / "slow_solutions" / "python" / "I.py"
    source.unlink()
    source.mkdir()
    with pytest.raises(ValueError):
        probe.slow_source_path(base, "I")


def test_slow_source_path_rejects_a_symlink_even_when_its_target_is_pinned(tmp_path: Path) -> None:
    base = _copy_slow_sources(tmp_path)
    source = base / "slow_solutions" / "python" / "J.py"
    target = source.with_name("J-target.py")
    source.replace(target)
    try:
        source.symlink_to(target)
    except OSError as error:
        pytest.skip(f"symlink creation is unavailable: {error}")
    with pytest.raises(ValueError):
        probe.slow_source_path(base, "J")


def test_pair_requires_a_clean_accepted_fast_solution(protected_report_contract: None) -> None:
    payload = _payload()
    fast = _result(payload, verdict="wrong_answer", case_verdict="wrong_answer")
    slow = _result(payload, verdict="accepted", case_verdict="accepted")
    with pytest.raises(ValueError):
        probe.validate_pair(fast, slow, payload, ("compile", "target"), ("compile", "target"))

    fast = _result(payload, verdict="accepted", case_verdict="accepted",
                   usage=_usage(exitCode=-9, failureReason="time_limit_exceeded",
                                cpuUsec=1_000_000))
    with pytest.raises(ValueError):
        probe.validate_pair(fast, slow, payload, ("compile", "target"), ("compile", "target"))


def test_pair_records_a_slow_timeout_as_a_separation_only_with_a_limit_witness(
        protected_report_contract: None) -> None:
    payload = _payload()
    fast = _result(payload, verdict="accepted", case_verdict="accepted")
    timeout = _usage(exitCode=-9, failureReason="time_limit_exceeded", cpuUsec=1_000_000)
    slow = _result(payload, verdict="time_limit_exceeded", case_verdict="time_limit_exceeded", usage=timeout)

    row = probe.validate_pair(fast, slow, payload, ("compile", "target"), ("compile", "target"))
    assert row["fastVerdict"] == "accepted"
    assert row["slowVerdict"] == "time_limit_exceeded"
    assert row["separates"] is True
    assert row["fastRun"] == fast["_resource_report"]["cases"][0]["usage"]
    assert row["slowRun"] == timeout

    unproven = _result(payload, verdict="time_limit_exceeded", case_verdict="time_limit_exceeded",
                       usage=_usage(exitCode=-9, failureReason="time_limit_exceeded", cpuUsec=999_999))
    with pytest.raises(ValueError):
        probe.validate_pair(fast, unproven, payload, ("compile", "target"), ("compile", "target"))


def test_slow_acceptance_and_non_timeout_user_outcomes_are_reported_without_separation(
        protected_report_contract: None) -> None:
    payload = _payload()
    fast = _result(payload, verdict="accepted", case_verdict="accepted")
    accepted = _result(payload, verdict="accepted", case_verdict="accepted")
    accepted_row = probe.validate_pair(fast, accepted, payload, ("compile", "target"), ("compile", "target"))
    assert accepted_row["slowVerdict"] == "accepted"
    assert accepted_row["separates"] is False

    runtime_error = _result(payload, verdict="runtime_error", case_verdict="runtime_error",
                            usage=_usage(exitCode=1))
    error_row = probe.validate_pair(fast, runtime_error, payload, ("compile", "target"), ("compile", "target"))
    assert error_row["slowVerdict"] == "runtime_error"
    assert error_row["separates"] is False


def test_pair_rejects_missing_or_infrastructure_slow_reports(protected_report_contract: None) -> None:
    payload = _payload()
    fast = _result(payload, verdict="accepted", case_verdict="accepted")
    with pytest.raises(ValueError):
        probe.validate_pair(fast, {"verdict": "accepted"}, payload,
                            ("compile", "target"), ("compile", "target"))

    infrastructure = _result(payload, verdict="system_error", case_verdict="system_error",
                             usage=_usage(exitCode=1))
    with pytest.raises(ValueError):
        probe.validate_pair(fast, infrastructure, payload,
                            ("compile", "target"), ("compile", "target"))
