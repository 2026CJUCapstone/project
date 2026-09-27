"""Offline contract tests for the A--J private draft package builder."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys

import pytest
from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "build_freshman_private_package.py"
SPEC = importlib.util.spec_from_file_location("freshman_private_package_builder", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
builder = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = builder
SPEC.loader.exec_module(builder)


def valid_payload() -> dict:
    payload = builder.documented_template()
    payload.update({
        "packageId": "freshman-private-fixture",
        "title": "신입생 알고리즘 대회 초안",
        "startsAt": "2030-03-02T10:00:00+09:00",
        "endsAt": "2030-03-02T12:00:00+09:00",
    })
    tiers = {
        "A": "bronze5", "B": "bronze4", "C": "bronze3", "D": "bronze2", "E": "bronze1",
        "F": "silver5", "G": "silver4", "H": "silver3", "I": "gold5", "J": "ruby5",
    }
    for index, letter in enumerate(builder.LETTERS, start=1):
        payload["problems"][letter].update({
            "difficulty": tiers[letter],
            "contestPoints": index * 100,
            "practicePoints": index * 10,
            "tags": ["freshman", f"problem-{letter.lower()}"],
        })
    return payload


def built():
    config = builder.BuilderConfig.model_validate(valid_payload())
    return builder.build(config)


def test_builds_exact_private_draft_from_frozen_corpus() -> None:
    package, blobs, status = built()
    assert [entry.key for entry in package.entries] == list(builder.LETTERS)
    assert sum(len(entry.problem.test_cases) for entry in package.entries) == 26
    assert sum(len(entry.problem.hidden_test_cases) for entry in package.entries) == 53
    assert status["problemCount"] == 10
    assert status["sampleCount"] == 26 and status["hiddenCount"] == 53
    assert status["releaseReady"] is False and status["status"] == "draft-unapproved"
    assert status["storedBlobCount"] == len(blobs)
    assert {"schedule-approval", "contest-and-practice-points-approval",
            "j-scoring-and-ranking-approval"} <= set(status["blockers"])
    assert len(builder.canonical_package_bytes(package)) <= builder.MAX_PACKAGE_BYTES
    assert package.contest_write().published is False
    assert all(entry.problem.judge_policy is None for entry in package.entries)
    assert all(entry.metadata.required_languages == list(builder.LANGUAGES) for entry in package.entries)


def test_samples_are_inline_and_hidden_rows_are_exact_stored_references() -> None:
    package, blobs, _status = built()
    manifest = builder.verify_frozen(builder.MANIFEST)
    for entry in package.entries:
        letter = entry.key
        samples = [case.model_dump(by_alias=True) for case in entry.problem.test_cases]
        assert samples == [
            {"input": row["input"], "expectedOutput": row["expected_output"]}
            for row in manifest["sampleData"][letter]
        ]
        expected_hidden = [row for row in manifest["problems"][letter] if row["visibility"] == "hidden"]
        hidden = [case.model_dump(by_alias=True) for case in entry.problem.hidden_test_cases]
        assert len(hidden) == len(expected_hidden)
        for case, row in zip(hidden, expected_hidden):
            assert case == {
                "kind": "stored-v1",
                "inputRef": {"digest": row["inputHash"], "byteCount": row["inputBytes"], "encoding": "utf-8"},
                "expectedOutputRef": {
                    "digest": row["expectedHash"], "byteCount": row["expectedBytes"], "encoding": "utf-8"
                },
            }
            assert len(blobs[case["inputRef"]["digest"]]) == row["inputBytes"]
            assert len(blobs[case["expectedOutputRef"]["digest"]]) == row["expectedBytes"]


def test_participant_descriptions_exclude_author_notes_and_source_table() -> None:
    package, _blobs, _status = built()
    for entry in package.entries:
        assert "출제자 메모" not in entry.problem.description
        assert "acmicpc.net" not in entry.problem.description
        assert "재사용 조건" not in entry.problem.description
        assert entry.problem.title
        assert all(source.reuse_basis == "pending" for source in entry.metadata.sources)
        roles = {asset.role for asset in entry.metadata.assets}
        assert {"reference", "validator", "generator", "wrong_solution"} <= roles
        assert {asset.language for asset in entry.metadata.assets if asset.role == "reference"} == set(builder.LANGUAGES)
        if entry.key == "J":
            assert any(asset.role == "proof" and asset.name == "docs/banks-reference-proof-2026-09-26.md"
                       for asset in entry.metadata.assets)


def test_build_is_deterministic_and_binds_corpus_and_asset_hashes() -> None:
    config = builder.BuilderConfig.model_validate(valid_payload())
    first, first_blobs, first_status = builder.build(config)
    second, second_blobs, second_status = builder.build(config)
    assert builder.canonical_package_bytes(first) == builder.canonical_package_bytes(second)
    assert first_blobs == second_blobs and first_status == second_status
    assert first_status["manifestHash"] == config.corpus_manifest_hash
    assert first_status["assetManifestHash"] == config.asset_manifest_hash


@pytest.mark.parametrize("mutation,match", [
    ("problem", "exactly A-J"),
    ("corpus", "corpusManifestHash"),
    ("asset", "assetManifestHash"),
    ("rights", "Input should be 'pending'"),
    ("declaration", "Input should be 'forbidden'"),
])
def test_refuses_missing_or_invented_operator_facts(mutation: str, match: str) -> None:
    payload = valid_payload()
    if mutation == "problem":
        del payload["problems"]["J"]
        with pytest.raises(ValidationError, match=match):
            builder.BuilderConfig.model_validate(payload)
        return
    if mutation == "corpus":
        payload["corpusManifestHash"] = "sha256:" + "0" * 64
    elif mutation == "asset":
        payload["assetManifestHash"] = "sha256:" + "0" * 64
    elif mutation == "rights":
        payload["problems"]["A"]["sources"][0]["reuseBasis"] = "permission"
        payload["problems"]["A"]["sources"][0]["reuseEvidence"] = "invented"
        with pytest.raises(ValidationError, match=match):
            builder.BuilderConfig.model_validate(payload)
        return
    else:
        payload["declarations"]["publication"] = "approved"
        with pytest.raises(ValidationError, match=match):
            builder.BuilderConfig.model_validate(payload)
        return
    config = builder.BuilderConfig.model_validate(payload)
    with pytest.raises(ValueError, match=match):
        builder.build(config)


def test_template_leaves_external_choices_unset_and_cannot_build(tmp_path: Path) -> None:
    template = builder.documented_template()
    assert template["packageId"] is None and template["startsAt"] is None and template["endsAt"] is None
    assert all(row["difficulty"] is None and row["contestPoints"] is None for row in template["problems"].values())
    assert template["declarations"]["publication"] == "forbidden"
    with pytest.raises(ValidationError):
        builder.BuilderConfig.model_validate(template)
    output = tmp_path / "config-template.json"
    builder.write_template(output)
    assert json.loads(output.read_text(encoding="utf-8")) == template
    with pytest.raises(FileExistsError, match="overwrite"):
        builder.write_template(output)


def test_explicit_bundle_contains_only_canonical_package_index_status_and_blobs(tmp_path: Path) -> None:
    if os.name != "posix":
        pytest.skip("Secret bundle output intentionally requires POSIX permissions")
    package, blobs, status = built()
    output = tmp_path / "bundle"
    assert builder.write_bundle(output, package, blobs, status) == "created"
    assert (output / builder.PACKAGE_FILE).read_bytes() == builder.canonical_package_bytes(package)
    assert json.loads((output / builder.STATUS_FILE).read_text(encoding="utf-8"))["releaseReady"] is False
    index = json.loads((output / builder.UPLOAD_INDEX_FILE).read_text(encoding="utf-8"))
    assert index["packageHash"] == status["packageHash"]
    assert len(index["entries"]) == len(blobs)
    for row in index["entries"]:
        data = (output / row["relativePath"]).read_bytes()
        assert len(data) == row["byteCount"]
        assert "sha256:" + hashlib.sha256(data).hexdigest() == row["digest"]
        if os.name == "posix":
            assert stat.S_IMODE((output / row["relativePath"]).stat().st_mode) & 0o077 == 0
    assert builder.write_bundle(output, package, blobs, status) == "replayed"
    (output / builder.STATUS_FILE).write_text("tampered", encoding="utf-8")
    with pytest.raises(FileExistsError, match="different or unsafe"):
        builder.write_bundle(output, package, blobs, status)


def test_partial_bundle_is_removed_after_write_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if os.name != "posix":
        pytest.skip("Secret bundle output intentionally requires POSIX permissions")
    package, blobs, status = built()
    output = tmp_path / "bundle"
    original = builder._write_new_file
    calls = 0

    def fail_after_two(path: Path, data: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("synthetic write failure")
        original(path, data)

    monkeypatch.setattr(builder, "_write_new_file", fail_after_two)
    with pytest.raises(OSError, match="synthetic"):
        builder.write_bundle(output, package, blobs, status)
    assert not output.exists()
    assert not list(tmp_path.glob(".bundle.partial-*"))


def test_output_rejects_symlinked_ancestor(tmp_path: Path) -> None:
    if os.name != "posix":
        pytest.skip("Secret bundle output intentionally requires POSIX permissions")
    package, blobs, status = built()
    actual = tmp_path / "actual"
    actual.mkdir()
    linked = tmp_path / "linked"
    try:
        linked.symlink_to(actual, target_is_directory=True)
    except OSError:
        pytest.skip("This environment does not permit directory symlinks")
    with pytest.raises(ValueError, match="links or junctions"):
        builder.write_bundle(linked / "bundle", package, blobs, status)


def test_secret_bundle_output_fails_closed_without_posix_permissions(tmp_path: Path) -> None:
    if os.name == "posix":
        pytest.skip("POSIX output permissions are covered by the bundle tests")
    package, blobs, status = built()
    with pytest.raises(ValueError, match="requires POSIX"):
        builder.write_bundle(tmp_path / "bundle", package, blobs, status)


@pytest.mark.parametrize("field", ("reuseBasis", "reuseEvidence", "externalTier", "tierCheckedAt"))
def test_pending_source_state_must_be_explicit(field: str) -> None:
    payload = valid_payload()
    del payload["problems"]["A"]["sources"][0][field]
    with pytest.raises(ValidationError):
        builder.BuilderConfig.model_validate(payload)


def test_invalid_cli_does_not_echo_operator_evidence(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    payload = valid_payload()
    marker = "PRIVATE-PERMISSION-EVIDENCE-MUST-NOT-ECHO"
    payload["problems"]["A"]["sources"][0]["reuseBasis"] = "permission"
    payload["problems"]["A"]["sources"][0]["reuseEvidence"] = marker
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    assert builder.main([str(path)]) == 2
    captured = capsys.readouterr()
    assert marker not in captured.out + captured.err


def test_cli_defaults_to_validation_only_and_does_not_write(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(valid_payload(), ensure_ascii=False), encoding="utf-8")
    before = {path.name for path in tmp_path.iterdir()}
    assert builder.main([str(config_path)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["mode"] == "validation-only" and result["releaseReady"] is False
    assert {path.name for path in tmp_path.iterdir()} == before
    assert "input" not in result and "expected" not in result
