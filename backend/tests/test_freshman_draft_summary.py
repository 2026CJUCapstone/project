"""Synthetic draft aggregation checks; not actual judge or cgroup evidence."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from summarize_freshman_measurements import summarize


MANIFEST = json.loads((ROOT / "tools" / "freshman_contest" /
                       "corpus-manifest-draft-v2.json").read_text(encoding="utf-8"))
HISTORICAL_MANIFEST = json.loads((ROOT / "tools" / "freshman_contest" /
                                  "corpus-manifest-draft-v1.json").read_text(encoding="utf-8"))
DIGEST = "1" * 64
LIMITS = dict(cpuMs=1, wallMs=1, memoryBytes=1024, outputBytes=2, pids=4, tmpBytes=0)


def _report(manifest: dict = MANIFEST) -> dict:
    usage = dict(phase="run", exitCode=0, failureReason=None, oomKills=0,
                 treeReaped=True, cpuUsec=100, wallNs=200_000,
                 peakMemoryBytes=1024, outputBytes=2)
    rows = []
    phase_count = 0
    for letter, cases in manifest["problems"].items():
        phases = [{**usage, "phase": "compile"}] + [dict(usage) for _ in cases]
        phase_count += len(phases)
        rows.append(dict(letter=letter, language="cpp", repetition=1, passed=True,
                         verdict="accepted", sourceHash="sha256:" + DIGEST,
                         corpusManifestHash=manifest["manifestHash"], cases=cases,
                         contract=dict(kind="measured-v1",policyId="synthetic-"+letter,revision=1,
                            policyHash="sha256:"+DIGEST,testSuiteHash="sha256:"+DIGEST,
                            language="cpp",profile=dict(imageDigest="sha256:" + DIGEST,
                                compile=deepcopy(LIMITS), run=deepcopy(LIMITS)),
                            jobDeadlineMs=5001+len(cases),reservationBytes=1024),
                         phases=phases))
    summary = dict(language="cpp", repetition=1, problemCount=10, passed=10,
                   phaseContainers=phase_count, corpusManifestHash=manifest["manifestHash"],
                   remainingSubmittedContainers=0, remainingJobDirectories=0)
    timeout = 842
    return dict(version=1, suite="freshman-draft", language="cpp", repetition=1,
                timedOut=False, controllerExitCode=0,
                controllerTimeoutSeconds=timeout, controllerElapsedSeconds=20.5,
                controllerTimeoutBasis={
                    "kind":"frozen-suite-inner-deadlines-plus-reviewed-overhead",
                    "frozenInnerDeadlineSeconds":timeout-60,
                    "reviewedNonJobOverheadSeconds":60,
                },
                cleanup={"attempted":True,"discovered":["a"*12],"removed":["a"*12],
                         "remaining":[],"errors":[],"complete":True},
                capacityBefore={"availableMemoryBytes":1,"freeDiskBytes":1},
                capacityBeforeCleanup={"availableMemoryBytes":1,"freeDiskBytes":1},
                capacityAfterCleanup={"availableMemoryBytes":1,"freeDiskBytes":1},
                runtimeImage="sha256:" + DIGEST,
                sourceArchiveSha256=DIGEST, referenceArchiveSha256=DIGEST,
                host={"kernel": "synthetic"}, scriptsSha256={"probe": DIGEST},
                stdout="\n".join(json.dumps(row) for row in rows + [summary]))


def _save(tmp_path: Path, report: dict) -> Path:
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


def test_one_draft_pass_is_bound_but_incomplete_and_unapproved(tmp_path: Path) -> None:
    output = summarize([_save(tmp_path, _report())], suite="freshman-draft", manifest=MANIFEST)
    assert output["corpusManifestHash"] == MANIFEST["manifestHash"]
    assert output["combinationCount"] == 10 and output["recordCount"] == 10
    assert sum(row["caseCount"] for row in output["measurements"]) == 79
    assert output["tenPassDatasetComplete"] is False
    assert output["policyApproved"] is False


def test_historical_78_case_manifest_remains_replayable_as_separate_evidence(tmp_path: Path) -> None:
    output = summarize([_save(tmp_path, _report(HISTORICAL_MANIFEST))],
                       suite="freshman-draft", manifest=HISTORICAL_MANIFEST)
    assert output["corpusManifestHash"] == HISTORICAL_MANIFEST["manifestHash"]
    assert sum(row["caseCount"] for row in output["measurements"]) == 78
    assert output["policyApproved"] is False


def test_draft_aggregator_rejects_changed_case_and_unbound_manifest(tmp_path: Path) -> None:
    report = _report()
    lines = [json.loads(line) for line in report["stdout"].splitlines()]
    lines[0]["cases"][0]["inputHash"] = "sha256:" + "2" * 64
    report["stdout"] = "\n".join(json.dumps(line) for line in lines)
    with pytest.raises(ValueError, match="frozen draft"):
        summarize([_save(tmp_path, report)], suite="freshman-draft", manifest=MANIFEST)
    with pytest.raises(ValueError, match="manifest"):
        summarize([_save(tmp_path, _report())], suite="freshman-draft")


def test_candidate_or_descriptor_evidence_cannot_be_relabelled_as_draft(tmp_path: Path) -> None:
    report = _report()
    report["suite"] = "freshman-draft-candidate"
    with pytest.raises(ValueError, match="Incomplete"):
        summarize([_save(tmp_path, report)], suite="freshman-draft", manifest=MANIFEST)
    report = _report()
    with pytest.raises(ValueError, match="Incomplete"):
        summarize([_save(tmp_path, report)], manifest=MANIFEST)
