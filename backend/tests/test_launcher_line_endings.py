from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SERVICES = ROOT / "backend" / "app" / "services"
ARCHIVE = SERVICES / "launcher_archive"
FRESHMAN_PACKAGE = ROOT / "tools" / "freshman_contest"
FROZEN_CORPUS_SOURCES = (
    ROOT / "docs" / "freshman-contest-statements-a-i-2026-09-26.md",
    ROOT / "scripts" / "generate_freshman_corpus_manifest.py",
    ROOT / "scripts" / "verify_freshman_contest_examples.py",
)


def test_content_addressed_launchers_are_forced_to_lf() -> None:
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    assert "backend/app/services/linux_phase_launcher.py text eol=lf" in attributes
    assert "backend/app/services/launcher_archive/*.py text eol=lf" in attributes

    active = (SERVICES / "linux_phase_launcher.py").read_bytes()
    assert b"\r\n" not in active

    archived = list(ARCHIVE.glob("sha256-*.py"))
    assert archived
    for path in archived:
        match = re.fullmatch(r"sha256-([a-f0-9]{64})\.py", path.name)
        assert match is not None
        payload = path.read_bytes()
        assert b"\r\n" not in payload
        assert hashlib.sha256(payload).hexdigest() == match.group(1)


def test_freshman_package_is_forced_to_lf() -> None:
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    assert "tools/freshman_contest/** text eol=lf" in attributes
    for path in FROZEN_CORPUS_SOURCES:
        assert f"{path.relative_to(ROOT).as_posix()} text eol=lf" in attributes

    package_files = [
        *FROZEN_CORPUS_SOURCES,
        *(path for path in FRESHMAN_PACKAGE.rglob("*") if path.is_file()),
    ]
    assert package_files
    for path in package_files:
        assert b"\r\n" not in path.read_bytes(), path.relative_to(ROOT).as_posix()


def test_git_checkout_and_archive_preserve_launcher_identity(tmp_path: Path) -> None:
    if shutil.which("git") is None:
        pytest.skip("Git is required for checkout/archive line-ending verification")

    source = tmp_path / "source"
    checkout = tmp_path / "checkout"
    source.mkdir()
    relative_files = [
        Path(".gitattributes"),
        Path("backend/app/services/linux_phase_launcher.py"),
        *(
            Path("backend/app/services/launcher_archive") / path.name
            for path in sorted(ARCHIVE.glob("sha256-*.py"))
        ),
        *(
            path.relative_to(ROOT)
            for path in sorted(FRESHMAN_PACKAGE.rglob("*"))
            if path.is_file()
        ),
        *(path.relative_to(ROOT) for path in FROZEN_CORPUS_SOURCES),
    ]
    for relative in relative_files:
        destination = source / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / relative).read_bytes())

    def git(*args: str, cwd: Path = source, stdout=None) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            ["git", *args], cwd=cwd, check=True, stdout=stdout,
            stderr=subprocess.PIPE, timeout=30,
        )

    git("init", "--quiet")
    git("add", ".")
    git(
        "-c", "user.name=Launcher Contract Test",
        "-c", "user.email=launcher-contract@example.invalid",
        "commit", "--quiet", "-m", "fixture",
    )
    git("-c", "core.autocrlf=true", "clone", "--quiet", "--no-local", str(source), str(checkout))

    archive_file = tmp_path / "snapshot.tar"
    with archive_file.open("wb") as output:
        git("archive", "HEAD", stdout=output)
    with tarfile.open(archive_file, "r") as archive:
        archived_bytes = {
            relative.as_posix(): archive.extractfile(relative.as_posix()).read()
            for relative in relative_files[1:]
        }

    for relative in relative_files[1:]:
        checkout_bytes = (checkout / relative).read_bytes()
        source_bytes = (source / relative).read_bytes()
        assert checkout_bytes == source_bytes
        assert archived_bytes[relative.as_posix()] == source_bytes

    for path in sorted((checkout / "backend/app/services/launcher_archive").glob("sha256-*.py")):
        expected = path.stem.removeprefix("sha256-")
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
