"""Offline checks for the fixed A--J source archive builder."""

from __future__ import annotations

import hashlib
import importlib.util
import io
from pathlib import Path, PurePosixPath
import shutil
import sys
import tarfile

import pytest


ROOT = Path(__file__).resolve().parents[2]
BUILDER_PATH = ROOT / "scripts" / "build_freshman_measurement_package.py"
SPEC = importlib.util.spec_from_file_location("freshman_measurement_package_builder", BUILDER_PATH)
assert SPEC is not None and SPEC.loader is not None
builder = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = builder
SPEC.loader.exec_module(builder)


def expected_members() -> set[str]:
    files = set(builder.MODULES)
    if (ROOT / "tools" / "freshman_contest" / "__init__.py").is_file():
        files.add("__init__.py")
    for language, suffix in builder.LANGUAGE_SUFFIXES.items():
        files.update(f"solutions/{language}/{letter}.{suffix}" for letter in builder.LETTERS)
    files.update(f"solutions/java/{letter}/Main.java" for letter in builder.LETTERS)
    return {str(PurePosixPath(builder.PACKAGE_ROOT) / name) for name in files}


def copied_repository_root(tmp_path: Path) -> Path:
    package = ROOT / "tools" / "freshman_contest"
    destination = tmp_path / "tools" / "freshman_contest"
    shutil.copytree(package, destination)
    return tmp_path


def test_archive_has_exact_fixed_membership_and_bounds() -> None:
    data = builder.build_archive_bytes(ROOT)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        members = archive.getmembers()
        assert {member.name for member in members} == expected_members()
        assert len(members) == len(expected_members()) <= builder.MAX_MEMBERS
        assert all(member.isfile() and not member.issym() for member in members)
        assert all("__pycache__" not in PurePosixPath(member.name).parts for member in members)
        assert sum(member.size for member in members) <= builder.MAX_UNCOMPRESSED_BYTES
        assert all(member.mtime == 0 and member.uid == 0 and member.gid == 0 for member in members)


def test_slow_diagnostic_archive_is_separate_and_adds_only_fixed_sources() -> None:
    ordinary = builder.build_archive_bytes(ROOT)
    diagnostic = builder.build_archive_bytes(ROOT, include_slow=True)
    assert ordinary != diagnostic
    with tarfile.open(fileobj=io.BytesIO(diagnostic), mode="r:gz") as archive:
        names = {member.name for member in archive.getmembers()}
        assert names - expected_members() == {
            f"tools/freshman_contest/slow_solutions/python/{letter}.py" for letter in "FIJ"
        }
        assert expected_members() <= names
        assert all(member.isfile() and not member.issym() for member in archive.getmembers())


def test_archive_bytes_are_deterministic_and_default_output_does_not_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_root = copied_repository_root(tmp_path)
    first = builder.build_archive_bytes(source_root)
    assert first == builder.build_archive_bytes(source_root)
    assert hashlib.sha256(first).digest()

    class BinaryStdout:
        def __init__(self) -> None:
            self.buffer = io.BytesIO()

    stdout = BinaryStdout()
    monkeypatch.setattr(builder.sys, "stdout", stdout)
    before = {path.name for path in tmp_path.iterdir()}
    builder.main(["--root", str(source_root)])
    assert stdout.buffer.getvalue() == first
    assert {path.name for path in tmp_path.iterdir()} == before


def test_explicit_output_is_new_only(tmp_path: Path) -> None:
    source_root = copied_repository_root(tmp_path / "source")
    output = tmp_path / "freshman-package.tar.gz"
    builder.main(["--root", str(source_root), "--output", str(output)])
    assert output.read_bytes() == builder.build_archive_bytes(source_root)
    with pytest.raises(FileExistsError, match="overwrite"):
        builder.main(["--root", str(source_root), "--output", str(output)])


def test_rejects_missing_whitelisted_member(tmp_path: Path) -> None:
    source_root = copied_repository_root(tmp_path)
    (source_root / "tools" / "freshman_contest" / "solutions" / "c" / "A.c").unlink()
    with pytest.raises(ValueError, match="Missing required archive member"):
        builder.build_archive_bytes(source_root)


def test_rejects_manifest_source_hash_mismatch(tmp_path: Path) -> None:
    source_root = copied_repository_root(tmp_path)
    source = source_root / "tools" / "freshman_contest" / "a_i.py"
    source.write_bytes(source.read_bytes() + b"\n# tampered\n")
    with pytest.raises(ValueError, match="source hash mismatch: a_i.py"):
        builder.build_archive_bytes(source_root)


def test_rejects_manifest_self_hash_mismatch(tmp_path: Path) -> None:
    source_root = copied_repository_root(tmp_path)
    manifest = source_root / "tools" / "freshman_contest" / "corpus-manifest-draft-v2.json"
    manifest.write_bytes(manifest.read_bytes().replace(b"draft-unapproved", b"draft-tampered  ", 1))
    with pytest.raises(ValueError, match="self-hash mismatch"):
        builder.build_archive_bytes(source_root)


def test_rejects_symlinked_whitelisted_member(tmp_path: Path) -> None:
    source_root = copied_repository_root(tmp_path)
    package = source_root / "tools" / "freshman_contest"
    source = package / "a_i.py"
    source.unlink()
    try:
        source.symlink_to(package / "banks.py")
    except OSError:
        pytest.skip("This Windows environment does not permit test symlink creation")
    with pytest.raises(ValueError, match="Symlinked archive member"):
        builder.build_archive_bytes(source_root)
