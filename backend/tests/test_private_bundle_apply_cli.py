"""Offline/private-bundle application contract tests; never use a live API."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts import apply_private_contest_bundle as cli
from scripts import build_freshman_private_package as builder
from scripts import import_private_contest as importer


def valid_bundle() -> tuple[dict[str, bytes], object, dict[str, bytes]]:
    payload = builder.documented_template()
    payload.update({
        "packageId": "freshman-private-apply-fixture",
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
            "difficulty": tiers[letter], "contestPoints": index * 100,
            "practicePoints": index * 10, "tags": ["freshman", f"problem-{letter.lower()}"],
        })
    package, blobs, status = builder.build(builder.BuilderConfig.model_validate(payload))
    return builder._bundle_files(package, blobs, status), package, blobs


@pytest.fixture(scope="module")
def bundle_data():
    return valid_bundle()


def validate(files: dict[str, bytes]):
    names = {path.rsplit("/", 1)[-1] for path in files if path.startswith("blobs/sha256/")}
    return cli.validate_contents(files[builder.PACKAGE_FILE], files[builder.UPLOAD_INDEX_FILE],
                                 files[builder.STATUS_FILE], names,
                                 lambda row: files[row.relative_path])


def rewrite(files: dict[str, bytes], name: str, mutate) -> dict[str, bytes]:
    changed = dict(files)
    value = json.loads(changed[name])
    mutate(value)
    changed[name] = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    return changed


def test_whole_bundle_closure_and_safe_summary(bundle_data) -> None:
    files, package, blobs = bundle_data
    result = validate(files)
    assert result.package == package
    assert len(result.entries) == len(blobs) == 89
    assert sum(row.byte_count for row in result.entries) == 12_718_689
    summary = result.summary("validation-only")
    assert summary["problemCount"] == 10 and summary["sampleCount"] == 26
    assert summary["hiddenCount"] == 53 and summary["blockerCount"] == 9
    assert "description" not in summary and "entries" not in summary


@pytest.mark.parametrize("mutation", [
    "wrong-package-hash", "duplicate", "unsorted", "path", "missing-index",
    "extra-index", "status-count", "status-ready", "blockers", "blob-change",
    "missing-blob", "extra-blob",
])
def test_any_control_reference_or_blob_drift_is_rejected(bundle_data, mutation: str) -> None:
    source, _package, _blobs = bundle_data
    files = dict(source)
    if mutation == "wrong-package-hash":
        files = rewrite(files, builder.UPLOAD_INDEX_FILE,
                        lambda value: value.update(packageHash="sha256:" + "0" * 64))
    elif mutation == "duplicate":
        files = rewrite(files, builder.UPLOAD_INDEX_FILE,
                        lambda value: value["entries"].append(dict(value["entries"][-1])))
    elif mutation == "unsorted":
        files = rewrite(files, builder.UPLOAD_INDEX_FILE,
                        lambda value: value["entries"].reverse())
    elif mutation == "path":
        files = rewrite(files, builder.UPLOAD_INDEX_FILE,
                        lambda value: value["entries"][0].update(relativePath="../private"))
    elif mutation == "missing-index":
        files = rewrite(files, builder.UPLOAD_INDEX_FILE, lambda value: value["entries"].pop())
    elif mutation == "extra-index":
        def add(value):
            value["entries"].append({"digest": "sha256:" + "f" * 64, "byteCount": 0,
                                     "encoding": "utf-8", "relativePath": "blobs/sha256/" + "f" * 64})
        files = rewrite(files, builder.UPLOAD_INDEX_FILE, add)
        files["blobs/sha256/" + "f" * 64] = b""
    elif mutation == "status-count":
        files = rewrite(files, builder.STATUS_FILE,
                        lambda value: value.update(storedBlobBytes=value["storedBlobBytes"] + 1))
    elif mutation == "status-ready":
        files = rewrite(files, builder.STATUS_FILE, lambda value: value.update(releaseReady=True))
    elif mutation == "blockers":
        files = rewrite(files, builder.STATUS_FILE, lambda value: value["blockers"].pop())
    elif mutation == "blob-change":
        path = next(path for path in files if path.startswith("blobs/sha256/"))
        files[path] += b"x"
    elif mutation == "missing-blob":
        files.pop(next(path for path in files if path.startswith("blobs/sha256/")))
    else:
        files["blobs/sha256/" + "e" * 64] = b"extra"
    with pytest.raises(ValueError):
        validate(files)


def test_noncanonical_package_and_duplicate_json_keys_are_rejected(bundle_data) -> None:
    source, _package, _blobs = bundle_data
    files = dict(source)
    package = json.loads(files[builder.PACKAGE_FILE])
    files[builder.PACKAGE_FILE] = json.dumps(package, ensure_ascii=False, indent=2).encode()
    with pytest.raises(ValueError, match="canonical"):
        validate(files)
    duplicate = dict(source)
    duplicate[builder.UPLOAD_INDEX_FILE] = b'{"schemaVersion":1,"schemaVersion":1}'
    with pytest.raises(ValueError, match="Duplicate"):
        validate(duplicate)


class Reply(io.BytesIO):
    status = 200
    headers = {"Cache-Control": "no-store", "Content-Encoding": "identity"}


class Transport:
    def __init__(self, package, blobs, *, fail_at: int | None = None):
        self.package = package
        self.blobs = blobs
        self.fail_at = fail_at
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        if self.fail_at == len(self.requests):
            return Reply(b'{"uncertain":true}')
        if request.method == "PUT":
            result = {**cli.data_reference(request.data), "replayed": False}
        else:
            rows = [{"key": entry.key, "problemId": str(uuid4()), "contestProblemId": str(uuid4())}
                    for entry in self.package.entries]
            result = {
                "packageId": self.package.package_id, "revision": self.package.revision,
                "manifestHash": importer.digest(self.package), "contestId": str(uuid4()),
                "replayed": False, "currentPublished": False,
                "problems": [{**row, "removed": False} for row in rows], "originalProblems": rows,
            }
        return Reply(json.dumps(result).encode())


class MemorySession:
    def __init__(self, contents, files):
        self.contents = contents
        self.files = files

    def read_blob(self, row):
        data = self.files[row.relative_path]
        if cli.data_reference(data) != row.public_reference():
            raise ValueError("changed")
        return data


def test_apply_uploads_sorted_blobs_once_then_imports_once(bundle_data) -> None:
    files, package, _blobs = bundle_data
    contents = validate(files)
    transport = Transport(package, files)
    result = cli.apply_bundle(MemorySession(contents, files), "https://example.test/api/v1",
                              "test-token", opener=transport)
    assert result["mode"] == "applied-private-draft"
    assert result["uploadedBlobCount"] == len(contents.entries)
    assert len(transport.requests) == len(contents.entries) + 1
    assert [request.method for request, _timeout in transport.requests[:-1]] == ["PUT"] * len(contents.entries)
    assert transport.requests[-1][0].method == "POST"
    assert [request.full_url.rsplit("/", 1)[-1].split("?", 1)[0]
            for request, _timeout in transport.requests[:-1]] == [row.digest[7:] for row in contents.entries]


def test_first_uncertain_upload_stops_without_import(bundle_data) -> None:
    files, package, _blobs = bundle_data
    contents = validate(files)
    transport = Transport(package, files, fail_at=2)
    with pytest.raises(ValueError):
        cli.apply_bundle(MemorySession(contents, files), "https://example.test/api/v1",
                         "test-token", opener=transport)
    assert len(transport.requests) == 2
    assert all(request.method == "PUT" for request, _timeout in transport.requests)


@pytest.mark.skipif(os.name != "posix", reason="Secret bundle filesystem gate is POSIX-only")
def test_posix_session_rejects_extra_link_and_loose_permissions(bundle_data, tmp_path: Path) -> None:
    _files, _fixture_package, _fixture_blobs = bundle_data
    package, blobs, status = builder.build(builder.BuilderConfig.model_validate(valid_bundle_config()))
    bundle = tmp_path / "bundle"
    builder.write_bundle(bundle, package, blobs, status)
    with cli.BundleSession(bundle) as session:
        assert session.contents is not None and len(session.contents.entries) == len(blobs)
    extra = bundle / "extra"
    extra.write_text("x")
    with pytest.raises(ValueError):
        cli.BundleSession(bundle).__enter__()
    extra.unlink()
    package_path = bundle / builder.PACKAGE_FILE
    package_data = package_path.read_bytes()
    linked_target = tmp_path / "linked-package.json"
    linked_target.write_bytes(package_data)
    linked_target.chmod(0o600)
    package_path.unlink()
    package_path.symlink_to(linked_target)
    with pytest.raises((ValueError, OSError)):
        cli.BundleSession(bundle).__enter__()
    package_path.unlink()
    package_path.write_bytes(package_data)
    package_path.chmod(0o640)
    with pytest.raises(ValueError):
        cli.BundleSession(bundle).__enter__()


def valid_bundle_config() -> dict:
    """Return only the explicit operator facts; kept separate for POSIX write test."""
    payload = builder.documented_template()
    payload.update({"packageId": "freshman-private-posix-fixture", "title": "비공개 초안",
                    "startsAt": "2030-03-02T10:00:00+09:00", "endsAt": "2030-03-02T12:00:00+09:00"})
    tiers = ["bronze5", "bronze4", "bronze3", "bronze2", "bronze1",
             "silver5", "silver4", "silver3", "gold5", "ruby5"]
    for index, (letter, tier) in enumerate(zip(builder.LETTERS, tiers, strict=True), start=1):
        payload["problems"][letter].update({"difficulty": tier, "contestPoints": index * 100,
                                             "practicePoints": index * 10, "tags": ["freshman"]})
    return payload
