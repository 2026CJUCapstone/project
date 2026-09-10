"""CLI validation rejects non-immutable image scan requests safely."""

from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "scan_image.py"
COMMIT = "a" * 40
IMAGE_ID = "sha256:" + "b" * 64
REMOTE_IMAGE = "registry.example/webcompiler/app@sha256:" + "c" * 64
MISSING = object()


def run_cli(tmp_path, *, image, source, scope, commit=MISSING, trivy=None):
    output = tmp_path / "reports" / "scan"
    cache = tmp_path / "cache"
    executable = trivy or (tmp_path / "scanner-that-does-not-exist")
    command = [
        sys.executable,
        str(SCRIPT),
        "--trivy",
        str(executable),
        "--image",
        image,
        "--source",
        source,
        "--scope",
        scope,
        "--output-dir",
        str(output),
        "--cache-dir",
        str(cache),
    ]
    if commit is not MISSING:
        command.extend(["--commit", commit])
    result = subprocess.run(command, capture_output=True, timeout=5, check=False)
    return result, output


def assert_rejected(result, output, expected_error):
    assert result.returncode != 0
    assert result.stdout.strip() == ("Image scan failed: " + expected_error).encode()
    assert not output.exists()
    assert not (output / "manifest.json").exists()


@pytest.mark.parametrize(
    ("image", "source", "scope", "commit", "expected_error"),
    [
        (
            "registry.example/webcompiler/app:latest",
            "remote",
            "base",
            MISSING,
            "Remote scanning requires an explicit registry and digest",
        ),
        (
            "sha256:" + "d" * 63,
            "docker",
            "base",
            MISSING,
            "Local scanning requires the full immutable image ID",
        ),
        (
            IMAGE_ID,
            "docker",
            "application",
            MISSING,
            "Built application scanning requires an image ID and exact commit",
        ),
        (
            REMOTE_IMAGE,
            "remote",
            "base",
            COMMIT,
            "Base scans cannot attest an application commit",
        ),
    ],
    ids=["mutable-remote-tag", "short-docker-id", "application-without-commit", "base-with-commit"],
)
def test_invalid_scan_requests_fail_before_scanner_execution(
    tmp_path, image, source, scope, commit, expected_error
):
    result, output = run_cli(
        tmp_path, image=image, source=source, scope=scope, commit=commit
    )

    assert_rejected(result, output, expected_error)


def test_nonexistent_scanner_executable_fails_without_report_directory(tmp_path):
    result, output = run_cli(
        tmp_path, image=REMOTE_IMAGE, source="remote", scope="base"
    )

    assert_rejected(result, output, "FileNotFoundError")
