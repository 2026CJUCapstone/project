"""Validate and optionally apply one immutable private-contest bundle.

The default is offline validation only.  ``--apply`` first validates the
entire owner-only POSIX tree, then uploads every exact stored test object, and
only after every receipt matches imports the exact canonical package.  There
are no redirects, retries, publication actions, generated IDs, or rollback
claims.  A failed/uncertain run may be resumed only with the identical bundle.
"""

from __future__ import annotations

import argparse
import codecs
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Callable
from urllib.request import ProxyHandler, build_opener


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
SCRIPTS = ROOT / "scripts"
for entry in (str(ROOT), str(BACKEND), str(SCRIPTS)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from app.models.judge_test_manifest import (  # noqa: E402
    MAX_SUITE_DATA_BYTES,
    MAX_TEST_DATA_BYTES,
    StoredTestCase,
)
from app.models.problem_authoring import (  # noqa: E402
    MAX_PACKAGE_BYTES,
    PrivateContestPackage,
    canonical_package_bytes,
)
from import_private_contest import NoRedirect, apply_manifest, endpoint  # noqa: E402
from upload_judge_test_data import reference as data_reference, upload_data  # noqa: E402


PACKAGE_FILE = "package.json"
INDEX_FILE = "upload-index.json"
STATUS_FILE = "draft-status.json"
CONTROL_FILES = frozenset((PACKAGE_FILE, INDEX_FILE, STATUS_FILE))
CONTROL_BYTES = 2 * 1024**2
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
NAME_RE = re.compile(r"^[0-9a-f]{64}$")
EXPECTED_KEYS = tuple("ABCDEFGHIJ")
EXPECTED_LANGUAGES = ("bpp", "c", "cpp", "python", "java", "javascript")
EXPECTED_BLOCKERS = (
    "schedule-approval",
    "contest-and-practice-points-approval",
    "j-scoring-and-ranking-approval",
    "participant-statement-approval",
    "source-reuse-and-current-tier-review",
    "verified-six-language-resource-policy",
    "ai-usage-policy-decision",
    "post-contest-visibility-decision",
    "private-import-and-judge-integration-acceptance",
)


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate JSON key")
        value[key] = item
    return value


def _reject_constant(_value: str) -> None:
    raise ValueError("Non-finite JSON value")


def strict_json(data: bytes, *, maximum: int = CONTROL_BYTES) -> dict[str, Any]:
    if len(data) > maximum:
        raise ValueError("Control file exceeds byte cap")
    try:
        value = json.loads(data.decode("utf-8", "strict"), object_pairs_hook=_pairs,
                           parse_constant=_reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("Invalid UTF-8 JSON") from None
    if not isinstance(value, dict):
        raise ValueError("Control file must be a JSON object")
    return value


def _exact_keys(value: dict[str, Any], expected: set[str] | frozenset[str], label: str) -> None:
    if set(value) != set(expected):
        raise ValueError(f"Unexpected {label} fields")


def _integer(value: Any, label: str, *, minimum: int = 0, maximum: int | None = None) -> int:
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f"Invalid {label}")
    return value


def _digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or DIGEST_RE.fullmatch(value) is None:
        raise ValueError(f"Invalid {label}")
    return value


@dataclass(frozen=True)
class BlobEntry:
    digest: str
    byte_count: int
    relative_path: str

    def public_reference(self) -> dict[str, Any]:
        return {"digest": self.digest, "byteCount": self.byte_count, "encoding": "utf-8"}


@dataclass(frozen=True)
class ValidatedContents:
    package: PrivateContestPackage
    package_hash: str
    package_bytes: int
    entries: tuple[BlobEntry, ...]
    status: dict[str, Any]

    def summary(self, mode: str) -> dict[str, Any]:
        return {
            "mode": mode,
            "status": self.status["status"],
            "releaseReady": False,
            "packageId": self.package.package_id,
            "revision": self.package.revision,
            "packageHash": self.package_hash,
            "packageBytes": self.package_bytes,
            "problemCount": len(self.package.entries),
            "sampleCount": self.status["sampleCount"],
            "hiddenCount": self.status["hiddenCount"],
            "storedBlobCount": len(self.entries),
            "storedBlobBytes": self.status["storedBlobBytes"],
            "blockerCount": len(self.status["blockers"]),
        }


BlobReader = Callable[[BlobEntry], bytes]


def validate_contents(package_data: bytes, index_data: bytes, status_data: bytes,
                      blob_names: set[str], read_blob: BlobReader) -> ValidatedContents:
    """Validate hashes, schemas, reference closure and every blob before IO."""
    if len(package_data) > MAX_PACKAGE_BYTES:
        raise ValueError("Package exceeds byte cap")
    package_raw = strict_json(package_data, maximum=MAX_PACKAGE_BYTES)
    package = PrivateContestPackage.model_validate(package_raw)
    canonical = canonical_package_bytes(package)
    if package_data != canonical:
        raise ValueError("Package is not the exact canonical representation")
    package_hash = "sha256:" + hashlib.sha256(package_data).hexdigest()

    index = strict_json(index_data)
    _exact_keys(index, {"schemaVersion", "status", "packageHash", "entries"}, "index")
    if index["schemaVersion"] != 1 or type(index["schemaVersion"]) is not int:
        raise ValueError("Invalid index schema version")
    if index["status"] != "draft-unapproved" or index["packageHash"] != package_hash:
        raise ValueError("Index does not identify the package draft")
    if not isinstance(index["entries"], list):
        raise ValueError("Invalid index entries")

    rows: list[BlobEntry] = []
    seen: set[str] = set()
    for raw in index["entries"]:
        if not isinstance(raw, dict):
            raise ValueError("Invalid index entry")
        _exact_keys(raw, {"digest", "byteCount", "encoding", "relativePath"}, "index entry")
        digest = _digest(raw["digest"], "blob digest")
        count = _integer(raw["byteCount"], "blob byte count", maximum=MAX_TEST_DATA_BYTES)
        name = digest.removeprefix("sha256:")
        expected_path = f"blobs/sha256/{name}"
        if raw["encoding"] != "utf-8" or raw["relativePath"] != expected_path or digest in seen:
            raise ValueError("Invalid or duplicate index entry")
        seen.add(digest)
        rows.append(BlobEntry(digest, count, expected_path))
    if [row.digest for row in rows] != sorted(row.digest for row in rows):
        raise ValueError("Index entries must be sorted")
    if sum(row.byte_count for row in rows) > MAX_SUITE_DATA_BYTES:
        raise ValueError("Bundle data exceeds aggregate byte cap")
    if blob_names != {row.digest[7:] for row in rows}:
        raise ValueError("Blob directory and index are not an exact match")

    refs: dict[str, dict[str, Any]] = {}
    sample_count = hidden_count = 0
    if tuple(entry.key for entry in package.entries) != EXPECTED_KEYS:
        raise ValueError("Freshman bundle must contain ordered A-J entries")
    for entry in package.entries:
        if entry.problem.judge_policy is not None:
            raise ValueError("Unmeasured draft must not contain a judge policy")
        if tuple(entry.metadata.required_languages) != EXPECTED_LANGUAGES:
            raise ValueError("Draft language evidence set is incomplete")
        for source in entry.metadata.sources:
            if (source.reuse_basis != "pending" or source.reuse_evidence
                    or source.external_tier is not None or source.tier_checked_at is not None):
                raise ValueError("Source review state is not the expected pending draft")
        sample_count += len(entry.problem.test_cases)
        hidden_count += len(entry.problem.hidden_test_cases)
        for case in entry.problem.hidden_test_cases:
            if not isinstance(case, StoredTestCase):
                raise ValueError("Bundle hidden cases must all use stored-v1")
            raw_case = case.model_dump(mode="json", by_alias=True)
            for ref in (raw_case["inputRef"], raw_case["expectedOutputRef"]):
                previous = refs.get(ref["digest"])
                if previous is not None and previous != ref:
                    raise ValueError("Conflicting package references")
                refs[ref["digest"]] = ref
    indexed = {row.digest: row.public_reference() for row in rows}
    if refs != indexed:
        raise ValueError("Package references and index are not an exact match")

    status = strict_json(status_data)
    expected_status = {
        "schemaVersion", "status", "releaseReady", "manifestHash", "assetManifestHash",
        "packageHash", "packageBytes", "problemCount", "sampleCount", "hiddenCount",
        "storedBlobCount", "storedBlobBytes", "blockers",
    }
    _exact_keys(status, expected_status, "status")
    if (type(status["schemaVersion"]) is not int or status["schemaVersion"] != 1
            or status["status"] != "draft-unapproved" or status["releaseReady"] is not False):
        raise ValueError("Invalid draft status")
    _digest(status["manifestHash"], "manifest hash")
    _digest(status["assetManifestHash"], "asset manifest hash")
    if status["packageHash"] != package_hash:
        raise ValueError("Status package hash mismatch")
    expected_counts = {
        "packageBytes": len(package_data),
        "problemCount": len(package.entries),
        "sampleCount": sample_count,
        "hiddenCount": hidden_count,
        "storedBlobCount": len(rows),
        "storedBlobBytes": sum(row.byte_count for row in rows),
    }
    for key, expected in expected_counts.items():
        if _integer(status[key], key) != expected:
            raise ValueError("Status count mismatch")
    blockers = status["blockers"]
    if (not isinstance(blockers, list) or tuple(blockers) != EXPECTED_BLOCKERS):
        raise ValueError("Invalid blocker list")

    for row in rows:
        data = read_blob(row)
        if len(data) != row.byte_count or data_reference(data) != row.public_reference():
            raise ValueError("Blob identity mismatch")
        try:
            data.decode("utf-8", "strict")
        except UnicodeDecodeError:
            raise ValueError("Blob is not UTF-8") from None
    return ValidatedContents(package, package_hash, len(package_data), tuple(rows), status)


def _plain_ancestors(path: Path) -> Path:
    absolute = Path(os.path.abspath(path))
    for candidate in (absolute, *absolute.parents):
        try:
            info = candidate.lstat()
        except OSError:
            raise ValueError("Bundle path must already exist") from None
        if stat.S_ISLNK(info.st_mode):
            raise ValueError("Bundle path must not contain links")
        if candidate != absolute and stat.S_IMODE(info.st_mode) & 0o022:
            sticky_trusted = bool(info.st_mode & stat.S_ISVTX) and info.st_uid in (0, os.geteuid())
            if not sticky_trusted:
                raise ValueError("Bundle parent is writable by another user")
        if candidate == Path(candidate.anchor):
            break
    return absolute


def _secure_stat(info: os.stat_result, *, directory: bool) -> None:
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise ValueError("Bundle tree is not owner-only")
    required = stat.S_IRUSR | (stat.S_IXUSR if directory else 0)
    if stat.S_IMODE(info.st_mode) & required != required:
        raise ValueError("Bundle tree is not readable")
    if not directory and info.st_nlink != 1:
        raise ValueError("Bundle files must not be hard-linked")


def _open_directory(path_or_name: str, *, parent_fd: int | None = None) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path_or_name, flags, dir_fd=parent_fd)
    try:
        _secure_stat(os.fstat(descriptor), directory=True)
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _read_file(parent_fd: int, name: str, maximum: int, *, expected: int | None = None) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(name, flags, dir_fd=parent_fd)
    try:
        before = os.fstat(descriptor)
        _secure_stat(before, directory=False)
        if before.st_size > maximum or (expected is not None and before.st_size != expected):
            raise ValueError("Bundle file size mismatch")
        pieces: list[bytes] = []
        remaining = maximum + 1
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            pieces.append(chunk)
            remaining -= len(chunk)
        data = b"".join(pieces)
        after = os.fstat(descriptor)
        identity = lambda value: (value.st_dev, value.st_ino, value.st_size,
                                  value.st_mtime_ns, value.st_ctime_ns)
        if len(data) > maximum or identity(before) != identity(after):
            raise ValueError("Bundle file changed during validation")
        if expected is not None and len(data) != expected:
            raise ValueError("Bundle file size mismatch")
        return data
    finally:
        os.close(descriptor)


class BundleSession:
    """Pinned POSIX directory descriptors prevent path substitution mid-run."""

    def __init__(self, path: Path):
        if os.name != "posix" or not hasattr(os, "geteuid"):
            raise ValueError("Secret bundle application requires POSIX owner-only permissions")
        self.path = _plain_ancestors(path)
        self.root_fd = self.blobs_fd = self.sha_fd = -1
        self.contents: ValidatedContents | None = None

    def __enter__(self) -> "BundleSession":
        try:
            self.root_fd = _open_directory(str(self.path))
            if set(os.listdir(self.root_fd)) != CONTROL_FILES | {"blobs"}:
                raise ValueError("Unexpected bundle tree entries")
            self.blobs_fd = _open_directory("blobs", parent_fd=self.root_fd)
            if set(os.listdir(self.blobs_fd)) != {"sha256"}:
                raise ValueError("Unexpected blob tree entries")
            self.sha_fd = _open_directory("sha256", parent_fd=self.blobs_fd)
            names = set(os.listdir(self.sha_fd))
            if any(NAME_RE.fullmatch(name) is None for name in names):
                raise ValueError("Invalid blob filename")
            package_data = _read_file(self.root_fd, PACKAGE_FILE, MAX_PACKAGE_BYTES)
            index_data = _read_file(self.root_fd, INDEX_FILE, CONTROL_BYTES)
            status_data = _read_file(self.root_fd, STATUS_FILE, CONTROL_BYTES)
            self.contents = validate_contents(package_data, index_data, status_data, names, self.read_blob)
            return self
        except Exception:
            self.close()
            raise

    def read_blob(self, row: BlobEntry) -> bytes:
        if self.sha_fd < 0:
            raise ValueError("Bundle is closed")
        data = _read_file(self.sha_fd, row.digest[7:], MAX_TEST_DATA_BYTES, expected=row.byte_count)
        decoder = codecs.getincrementaldecoder("utf-8")("strict")
        for start in range(0, len(data), 65536):
            decoder.decode(data[start:start + 65536], final=False)
        decoder.decode(b"", final=True)
        if data_reference(data) != row.public_reference():
            raise ValueError("Blob identity mismatch")
        return data

    def close(self) -> None:
        for attribute in ("sha_fd", "blobs_fd", "root_fd"):
            descriptor = getattr(self, attribute, -1)
            if descriptor >= 0:
                os.close(descriptor)
                setattr(self, attribute, -1)

    def __exit__(self, *_args: object) -> None:
        self.close()


def apply_bundle(session: BundleSession, api_base: str, token: str, *, opener=None) -> dict[str, Any]:
    contents = session.contents
    if contents is None:
        raise ValueError("Bundle has not been validated")
    endpoint(api_base)
    sender = opener or build_opener(ProxyHandler({}), NoRedirect())
    uploaded = replayed = 0
    for row in contents.entries:
        receipt = upload_data(session.read_blob(row), api_base, token, opener=sender)
        if {key: receipt[key] for key in ("digest", "byteCount", "encoding")} != row.public_reference():
            raise ValueError("Upload receipt mismatch")
        uploaded += 1
        replayed += int(receipt["replayed"])
    imported = apply_manifest(contents.package, api_base, token, opener=sender)
    if imported["currentPublished"] is not False:
        raise ValueError("Imported package is no longer a private draft")
    return {
        **contents.summary("applied-private-draft"),
        "uploadedBlobCount": uploaded,
        "replayedBlobCount": replayed,
        "import": imported,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--api-base")
    parser.add_argument("--token-env", default="CONTEST_IMPORT_TOKEN")
    args = parser.parse_args(argv)
    try:
        with BundleSession(args.bundle) as session:
            assert session.contents is not None
            if args.apply:
                if not args.api_base:
                    raise ValueError("--apply requires --api-base")
                endpoint(args.api_base)  # Validate target before credential lookup.
                token = os.environ.get(args.token_env, "")
                result = apply_bundle(session, args.api_base, token)
            else:
                result = session.contents.summary("validation-only")
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (ValueError, OSError):
        print("Bundle validation/application failed. No automatic retry, import, or publication was attempted.",
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
