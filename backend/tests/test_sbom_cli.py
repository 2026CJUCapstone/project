"""CLI checks for a minimal CycloneDX inventory against an npm lockfile."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "verify_sbom.py"
COMMIT = "a" * 40


def fixture_files(tmp_path):
    lock_bytes = json.dumps(
        {
            "name": "fixture-app",
            "lockfileVersion": 3,
            "packages": {
                "": {"name": "fixture-app", "version": "1.0.0"},
                "node_modules/left-pad": {"name": "left-pad", "version": "1.3.0"},
            },
        },
        separators=(",", ":"),
    ).encode()
    sbom_bytes = json.dumps(
        {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "type": "library",
                    "name": "left-pad",
                    "version": "1.3.0",
                    "bom-ref": "pkg:npm/left-pad@1.3.0",
                }
            ],
        },
        separators=(",", ":"),
    ).encode()
    lockfile = tmp_path / "package-lock.json"
    sbom = tmp_path / "sbom.cdx.json"
    lockfile.write_bytes(lock_bytes)
    sbom.write_bytes(sbom_bytes)
    return lockfile, sbom, lock_bytes, sbom_bytes


def run_cli(lockfile, sbom, manifest, *, commit=COMMIT, input_bytes=None):
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--ecosystem",
            "npm",
            "--lockfile",
            str(lockfile),
            "--sbom",
            str(sbom),
            "--commit",
            commit,
            "--manifest",
            str(manifest),
        ],
        input=input_bytes,
        capture_output=True,
        timeout=5,
        check=False,
    )


def test_valid_npm_inventory_writes_manifest_with_exact_hashes(tmp_path):
    lockfile, sbom, lock_bytes, sbom_bytes = fixture_files(tmp_path)
    manifest = tmp_path / "manifest.json"

    result = run_cli(lockfile, sbom, manifest)

    assert result.returncode == 0, result.stderr.decode()
    assert b"Verified npm lock inventory: 1 package versions" in result.stdout
    assert json.loads(manifest.read_text(encoding="utf-8")) == {
        "schemaVersion": 1,
        "sourceCommit": COMMIT,
        "ecosystem": "npm",
        "inventoryScope": "source-lockfile-not-installed-image",
        "lockfileSha256": hashlib.sha256(lock_bytes).hexdigest(),
        "sbomSha256": hashlib.sha256(sbom_bytes).hexdigest(),
        "componentCount": 1,
        "uniquePackageVersions": 1,
        "cycloneDxVersion": "1.5",
    }


def test_valid_sbom_can_be_read_from_stdin(tmp_path):
    lockfile, _, _, sbom_bytes = fixture_files(tmp_path)
    manifest = tmp_path / "stdin-manifest.json"

    result = run_cli(lockfile, "-", manifest, input_bytes=sbom_bytes)

    assert result.returncode == 0, result.stderr.decode()
    written = json.loads(manifest.read_text(encoding="utf-8"))
    assert written["sbomSha256"] == hashlib.sha256(sbom_bytes).hexdigest()


def test_dependency_mismatch_fails_without_creating_manifest(tmp_path):
    lockfile, sbom, _, _ = fixture_files(tmp_path)
    mismatched = json.loads(sbom.read_text(encoding="utf-8"))
    mismatched["components"][0]["version"] = "9.9.9"
    sbom.write_text(json.dumps(mismatched), encoding="utf-8")
    manifest = tmp_path / "mismatch-manifest.json"

    result = run_cli(lockfile, sbom, manifest)

    assert result.returncode == 1
    assert not manifest.exists()


def test_existing_manifest_is_never_overwritten(tmp_path):
    lockfile, sbom, _, _ = fixture_files(tmp_path)
    manifest = tmp_path / "existing-manifest.json"
    original = b'{"operator": "keep-me"}\n'
    manifest.write_bytes(original)

    result = run_cli(lockfile, sbom, manifest)

    assert result.returncode == 1
    assert manifest.read_bytes() == original


def test_missing_lockfile_fails_without_creating_manifest(tmp_path):
    _, sbom, _, _ = fixture_files(tmp_path)
    manifest = tmp_path / "missing-input-manifest.json"

    result = run_cli(tmp_path / "missing-package-lock.json", sbom, manifest)

    assert result.returncode == 1
    assert not manifest.exists()


def test_invalid_commit_fails_without_creating_manifest(tmp_path):
    lockfile, sbom, _, _ = fixture_files(tmp_path)
    manifest = tmp_path / "invalid-commit-manifest.json"

    result = run_cli(lockfile, sbom, manifest, commit="not-a-commit")

    assert result.returncode == 1
    assert not manifest.exists()
