"""Offline integrity checks for the draft freshman-contest corpus manifest."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
TESTS = Path(__file__).resolve().parent
for directory in (ROOT, SCRIPTS, TESTS):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from generate_freshman_corpus_manifest import (
    B_MEASURED_COVERAGE,
    MANIFEST,
    build_manifest,
    case_material,
    sha256,
    verify_frozen,
)
from verify_freshman_contest_examples import EXPECTED_COUNTS
import test_freshman_bpp_a_d_sources as bounded_process


def test_frozen_draft_manifest_matches_every_statement_and_generator_byte() -> None:
    manifest = verify_frozen()
    assert manifest["status"] == "draft-unapproved"
    assert set(manifest["problems"]) == set("ABCDEFGHIJ")
    assert set(manifest["sampleData"]) == set("ABCDEFGHIJ")
    assert MANIFEST.is_file()
    for letter, rows in manifest["problems"].items():
        material = list(case_material(letter))
        assert manifest["sampleData"][letter] == [
            dict(name=name, input=input_text, expected_output=expected)
            for name, visibility, _, input_text, expected in material if visibility == "sample"
        ]
        assert len(rows) == len(material)
        assert len({row["name"] for row in rows}) == len(rows)
        assert [row["visibility"] for row in rows[:EXPECTED_COUNTS[letter]]] == ["sample"] * EXPECTED_COUNTS[letter]
        assert all(row["visibility"] == "hidden" for row in rows[EXPECTED_COUNTS[letter]:])
        for row, (name, visibility, provenance, input_text, expected) in zip(rows, material):
            assert (row["name"], row["visibility"], row["provenance"]) == (name, visibility, provenance)
            assert row["inputHash"] == sha256(input_text.encode("utf-8"))
            assert row["expectedHash"] == sha256(expected.encode("utf-8"))
            assert row["inputBytes"] == len(input_text.encode("utf-8"))
            assert row["expectedBytes"] == len(expected.encode("utf-8"))
    assert {row["name"] for row in manifest["problems"]["B"] if row["provenance"] == "coverage-v1"} == B_MEASURED_COVERAGE
    assert len(manifest["problems"]["B"]) < 200


def test_manifest_rejects_changed_case_or_fabricated_approval(tmp_path: Path) -> None:
    actual = build_manifest()
    changed = json.loads(json.dumps(actual))
    changed["problems"]["A"][0]["inputHash"] = "sha256:" + "0" * 64
    path = tmp_path / "changed.json"
    path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="differs"):
        verify_frozen(path)
    changed = json.loads(json.dumps(actual))
    changed["status"] = "approved"
    path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="differs"):
        verify_frozen(path)


def test_standalone_python_references_pass_every_frozen_case(monkeypatch: pytest.MonkeyPatch) -> None:
    """Functional comparison only; this is not a runtime/memory benchmark."""

    monkeypatch.setattr(bounded_process, "MAX_OUTPUT_BYTES", 512 * 1024)
    executed = 0
    for letter in "ABCDEFGHIJ":
        source = ROOT / "tools" / "freshman_contest" / "solutions" / "python" / f"{letter}.py"
        assert source.is_file()
        for name, _, _, input_text, expected in case_material(letter):
            result = bounded_process._run(
                [sys.executable, str(source)], cwd=ROOT, input_text=input_text, timeout=15,
            )
            assert result.returncode == 0, f"{letter}/{name}: exit {result.returncode}"
            actual = result.stdout.decode("utf-8", errors="strict").replace("\r\n", "\n").rstrip("\n")
            assert actual == expected, f"{letter}/{name}: standalone Python output mismatch"
            executed += 1
    assert executed == sum(len(rows) for rows in build_manifest()["problems"].values())
