"""Build the offline A--J private-contest draft package and stored-data files.

This tool never contacts the API, imports a contest, publishes a problem, or
creates review approvals.  Schedule, exact tiers and point values must be
provided explicitly.  Documented source candidates default to ``pending`` in
the optional config template and therefore cannot serve as reuse approval.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import sys
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
SCRIPTS = ROOT / "scripts"
for entry in (str(ROOT), str(BACKEND), str(SCRIPTS)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from app.models.problem_authoring import (
    MAX_PACKAGE_BYTES,
    PrivateContestPackage,
    canonical_package_bytes,
)
from app.models.judge_test_manifest import StoredTestCase, TestDataReference
from generate_freshman_corpus_manifest import MANIFEST, case_material, sha256, verify_frozen


LETTERS = tuple("ABCDEFGHIJ")
LANGUAGES = ("bpp", "c", "cpp", "python", "java", "javascript")
STATEMENTS = ROOT / "docs" / "freshman-contest-statements-a-i-2026-09-26.md"
MAX_CONFIG_BYTES = MAX_PACKAGE_BYTES
PACKAGE_FILE = "package.json"
UPLOAD_INDEX_FILE = "upload-index.json"
STATUS_FILE = "draft-status.json"
SOURCE_CANDIDATES = {
    "A": ("https://www.acmicpc.net/problem/1000", "BOJ 1000 A+B"),
    "B": ("https://www.acmicpc.net/problem/2480", "BOJ 2480 주사위 세개"),
    "C": ("https://www.acmicpc.net/problem/10818", "BOJ 10818 최소, 최대"),
    "D": ("https://www.acmicpc.net/problem/2675", "BOJ 2675 문자열 반복"),
    "E": ("https://www.acmicpc.net/problem/1157", "BOJ 1157 단어 공부"),
    "F": ("https://www.acmicpc.net/problem/1920", "BOJ 1920 수 찾기"),
    "G": ("https://www.acmicpc.net/problem/11399", "BOJ 11399 ATM"),
    "H": ("https://www.acmicpc.net/problem/2178", "BOJ 2178 미로 탐색"),
    "I": ("https://www.acmicpc.net/problem/7576", "BOJ 7576 토마토"),
    "J": ("https://www.acmicpc.net/problem/10350", "BOJ 10350 Banks"),
}
ADAPTATION_NOTES = {
    "A": "두 조의 이름표 수로 설명하고 예제를 새로 작성한 초안",
    "B": "카드 행사 배경으로 바꾸고 세 점수식을 명시하며 예제를 새로 작성한 초안",
    "C": "학생별 점수 변화 배경으로 바꾸고 음수 의미를 설명하며 예제를 새로 작성한 초안",
    "D": "축제 전광판 배경으로 바꾸고 허용 문자를 한정하며 예제를 새로 작성한 초안",
    "E": "동아리 소개 문구 배경으로 바꾸고 대소문자와 동률 규칙을 명시한 초안",
    "F": "참가 신청 조회 배경으로 바꾸고 음수, 중복, 비소모 조회를 명시한 초안",
    "G": "장비 대여 배경으로 바꾸고 완료 시간 합의 정의를 명시한 초안",
    "H": "건물 내 이동 배경으로 바꾸고 시작·도착 포함과 도달 가능 조건을 명시한 초안",
    "I": "컴퓨터 설치 배경으로 바꾸고 동시 전파, 0일, 빈자리 규칙을 명시한 초안",
    "J": "원형 연구실 배경과 새 예제를 사용하고 중복 이웃 처리 해석을 명시한 초안",
}


def _camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(word.title() for word in tail)


class StrictConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, alias_generator=_camel)


class DraftSource(StrictConfig):
    url: HttpUrl
    title: str = Field(min_length=1, max_length=300)
    author: str = Field(default="", max_length=300)
    event: str = Field(default="", max_length=300)
    reuse_basis: Literal["pending"]
    reuse_evidence: Literal[""]
    external_tier: Literal[None]
    tier_checked_at: Literal[None]


class ProblemChoice(StrictConfig):
    difficulty: str = Field(min_length=1)
    contest_points: int = Field(strict=True, ge=1, le=100_000)
    practice_points: int = Field(strict=True, ge=0, le=10_000)
    tags: list[str] = Field(min_length=1, max_length=12)
    sources: list[DraftSource] = Field(min_length=1, max_length=20)
    adaptation_notes: str = Field(min_length=1, max_length=10_000)

class DraftDeclarations(StrictConfig):
    schedule: Literal["draft-unapproved"]
    contest_points: Literal["unapproved"]
    j_scoring_and_ranking: Literal["unapproved"]
    rights_and_external_tier: Literal["pending"]
    resource_limits: Literal["unmeasured"]
    post_contest_visibility: Literal["unresolved"]
    publication: Literal["forbidden"]


class BuilderConfig(StrictConfig):
    schema_version: Literal[1] = 1
    package_id: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")
    revision: int = Field(strict=True, ge=1)
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=20_000)
    starts_at: datetime
    ends_at: datetime
    corpus_manifest_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    asset_manifest_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    problems: dict[str, ProblemChoice]
    declarations: DraftDeclarations

    @field_validator("problems")
    @classmethod
    def exact_problem_keys(cls, value: dict[str, ProblemChoice]) -> dict[str, ProblemChoice]:
        if set(value) != set(LETTERS):
            missing = "".join(letter for letter in LETTERS if letter not in value) or "-"
            extra = ",".join(sorted(set(value) - set(LETTERS))) or "-"
            raise ValueError(f"problems must contain exactly A-J (missing={missing}, extra={extra})")
        return value


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def read_config(path: Path) -> BuilderConfig:
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("Config must be a regular, non-symlink file")
    raw = path.read_bytes()
    if len(raw) > MAX_CONFIG_BYTES:
        raise ValueError("Config exceeds the 512 KiB byte limit")
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Config must be unique-key UTF-8 JSON") from exc
    return BuilderConfig.model_validate(payload)


def _problem_statements(path: Path = STATEMENTS) -> dict[str, tuple[str, str]]:
    text = path.read_text(encoding="utf-8")
    participant, separator, _notes = text.partition("## 출제자 메모 — 참가자용 본문에 포함하지 않음")
    if not separator:
        raise ValueError("Statement author-note boundary is missing")
    matches = list(re.finditer(r"(?m)^## ([A-J])\. (.+)$", participant))
    if tuple(match.group(1) for match in matches) != LETTERS:
        raise ValueError("Statement headings must contain A-J exactly once and in order")
    result: dict[str, tuple[str, str]] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(participant)
        description = participant[match.end():end].strip()
        description = re.sub(r"\n---\s*$", "", description).strip()
        if not description:
            raise ValueError(f"{match.group(1)} statement is empty")
        result[match.group(1)] = (match.group(2).strip(), description)
    return result


def _read_regular(root: Path, relative: Path) -> bytes:
    current = root
    if current.is_symlink():
        raise ValueError("Repository root must not be a symlink")
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError(f"Asset path must not contain symlinks: {relative.as_posix()}")
    if not current.is_file():
        raise ValueError(f"Missing package asset: {relative.as_posix()}")
    return current.read_bytes()


def _asset(root: Path, role: str, relative: Path, language: str | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {
        "role": role,
        "name": relative.as_posix(),
        "digest": sha256(_read_regular(root, relative)),
    }
    if language is not None:
        row["language"] = language
    return row


def _assets(root: Path, letter: str) -> list[dict[str, Any]]:
    suffixes = {"bpp": "bpp", "c": "c", "cpp": "cpp", "python": "py", "javascript": "js"}
    assets = [
        _asset(root, "reference", Path("tools/freshman_contest/solutions") / language / f"{letter}.{suffix}", language)
        for language, suffix in suffixes.items()
    ]
    assets.append(_asset(root, "reference", Path("tools/freshman_contest/solutions/java") / letter / "Main.java", "java"))
    if letter == "J":
        assets.extend((
            _asset(root, "validator", Path("tools/freshman_contest/banks.py")),
            _asset(root, "generator", Path("tools/freshman_contest/banks_stress_cases.py")),
            _asset(root, "wrong_solution", Path("tools/freshman_contest/banks_wrong.py")),
            _asset(root, "proof", Path("docs/banks-reference-proof-2026-09-26.md")),
        ))
    else:
        assets.extend((
            _asset(root, "validator", Path("tools/freshman_contest/a_i.py")),
            _asset(root, "generator", Path("tools/freshman_contest/stress_cases.py")),
            _asset(root, "generator", Path("tools/freshman_contest/coverage_cases.py")),
            _asset(root, "wrong_solution", Path("tools/freshman_contest/wrong_solutions.py")),
        ))
    return assets


def asset_manifest(root: Path = ROOT) -> dict[str, str]:
    result: dict[str, str] = {}
    for letter in LETTERS:
        for asset in _assets(root, letter):
            previous = result.setdefault(asset["name"], asset["digest"])
            if previous != asset["digest"]:
                raise ValueError(f"Conflicting asset digest: {asset['name']}")
    return dict(sorted(result.items()))


def asset_manifest_hash(root: Path = ROOT) -> str:
    return sha256(_json_bytes(asset_manifest(root)))


def _reference(data: bytes) -> TestDataReference:
    return TestDataReference(digest=sha256(data), byte_count=len(data), encoding="utf-8")


def _add_blob(blobs: dict[str, bytes], data: bytes) -> TestDataReference:
    reference = _reference(data)
    previous = blobs.setdefault(reference.digest, data)
    if previous != data:
        raise ValueError("SHA-256 collision while constructing stored test data")
    return reference


def build(config: BuilderConfig, root: Path = ROOT) -> tuple[PrivateContestPackage, dict[str, bytes], dict[str, Any]]:
    root = Path(root)
    if root != ROOT:
        raise ValueError("This draft builder is bound to the reviewed current repository root")
    manifest = verify_frozen(MANIFEST)
    if config.corpus_manifest_hash != manifest["manifestHash"]:
        raise ValueError("Configured corpusManifestHash does not match the frozen reviewed draft")
    current_asset_hash = asset_manifest_hash(root)
    if config.asset_manifest_hash != current_asset_hash:
        raise ValueError("Configured assetManifestHash does not match the fixed authoring assets")
    statements = _problem_statements()
    blobs: dict[str, bytes] = {}
    entries: list[dict[str, Any]] = []
    sample_count = hidden_count = 0
    for letter in LETTERS:
        choice = config.problems[letter]
        rows = manifest["problems"][letter]
        material = list(case_material(letter))
        if len(rows) != len(material):
            raise ValueError(f"{letter}: frozen manifest/material count mismatch")
        samples: list[dict[str, str]] = []
        hidden: list[dict[str, Any]] = []
        for row, (name, visibility, provenance, input_text, expected) in zip(rows, material):
            input_data, expected_data = input_text.encode("utf-8"), expected.encode("utf-8")
            actual = {
                "name": name,
                "visibility": visibility,
                "provenance": provenance,
                "inputBytes": len(input_data),
                "inputHash": sha256(input_data),
                "expectedBytes": len(expected_data),
                "expectedHash": sha256(expected_data),
            }
            if row != actual:
                raise ValueError(f"{letter}/{name}: frozen manifest row mismatch")
            if visibility == "sample":
                samples.append({"input": input_text, "expectedOutput": expected})
                sample_count += 1
            elif visibility == "hidden":
                hidden.append(StoredTestCase(kind="stored-v1", input_ref=_add_blob(blobs, input_data),
                                             expected_output_ref=_add_blob(blobs, expected_data)).model_dump(by_alias=True))
                hidden_count += 1
            else:
                raise ValueError(f"{letter}/{name}: unknown visibility")
        title, description = statements[letter]
        problem: dict[str, Any] = {
            "title": title,
            "difficulty": choice.difficulty,
            "tags": choice.tags,
            "description": description,
            "points": choice.practice_points,
            "testCases": samples,
            "hiddenTestCases": hidden,
        }
        entries.append({
            "key": letter,
            "points": choice.contest_points,
            "problem": problem,
            "metadata": {
                "sources": [source.model_dump(mode="json", by_alias=True) for source in choice.sources],
                "adaptationNotes": choice.adaptation_notes,
                "assets": _assets(root, letter),
                "requiredLanguages": list(LANGUAGES),
            },
        })
    package = PrivateContestPackage.model_validate({
        "schemaVersion": 1,
        "packageId": config.package_id,
        "revision": config.revision,
        "title": config.title,
        "description": config.description,
        "startsAt": config.starts_at,
        "endsAt": config.ends_at,
        "entries": entries,
    })
    package_bytes = canonical_package_bytes(package)
    status = {
        "schemaVersion": 1,
        "status": "draft-unapproved",
        "releaseReady": False,
        "manifestHash": manifest["manifestHash"],
        "assetManifestHash": current_asset_hash,
        "packageHash": sha256(package_bytes),
        "packageBytes": len(package_bytes),
        "problemCount": len(entries),
        "sampleCount": sample_count,
        "hiddenCount": hidden_count,
        "storedBlobCount": len(blobs),
        "storedBlobBytes": sum(map(len, blobs.values())),
        "blockers": [
            "schedule-approval",
            "contest-and-practice-points-approval",
            "j-scoring-and-ranking-approval",
            "participant-statement-approval",
            "source-reuse-and-current-tier-review",
            "verified-six-language-resource-policy",
            "ai-usage-policy-decision",
            "post-contest-visibility-decision",
            "private-import-and-judge-integration-acceptance",
        ],
    }
    return package, blobs, status


def documented_template() -> dict[str, Any]:
    manifest = verify_frozen(MANIFEST)
    problems: dict[str, Any] = {}
    for letter in LETTERS:
        url, title = SOURCE_CANDIDATES[letter]
        sources = [{
            "url": url,
            "title": title,
            "reuseBasis": "pending",
            "reuseEvidence": "",
            "externalTier": None,
            "tierCheckedAt": None,
        }]
        if letter == "J":
            sources.append({
                "url": "https://seerc.icpc.global/2014/prob/probleme/A.pdf",
                "title": "SEERC 2014 Problem A",
                "reuseBasis": "pending",
                "reuseEvidence": "",
                "externalTier": None,
                "tierCheckedAt": None,
            })
        problems[letter] = {
            "difficulty": None,
            "contestPoints": None,
            "practicePoints": None,
            "tags": [],
            "sources": sources,
            "adaptationNotes": ADAPTATION_NOTES[letter],
        }
    return {
        "schemaVersion": 1,
        "packageId": None,
        "revision": 1,
        "title": None,
        "description": "",
        "startsAt": None,
        "endsAt": None,
        "corpusManifestHash": manifest["manifestHash"],
        "assetManifestHash": asset_manifest_hash(ROOT),
        "problems": problems,
        "declarations": {
            "schedule": "draft-unapproved",
            "contestPoints": "unapproved",
            "jScoringAndRanking": "unapproved",
            "rightsAndExternalTier": "pending",
            "resourceLimits": "unmeasured",
            "postContestVisibility": "unresolved",
            "publication": "forbidden",
        },
    }


def _json_bytes(value: Any, *, pretty: bool = False) -> bytes:
    if pretty:
        return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _write_new_file(path: Path, data: bytes) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"Refusing to overwrite output: {path}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as output:
            descriptor = -1
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        path.chmod(0o600)
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _require_plain_directory(path: Path, label: str) -> Path:
    absolute = Path(os.path.abspath(path))
    if not absolute.is_dir():
        raise ValueError(f"{label} must be an existing directory")
    for candidate in (absolute, *absolute.parents):
        is_junction = getattr(candidate, "is_junction", lambda: False)
        if candidate.is_symlink() or is_junction():
            raise ValueError(f"{label} path must not contain links or junctions")
        if candidate == Path(candidate.anchor):
            break
    return absolute


def _bundle_files(package: PrivateContestPackage, blobs: dict[str, bytes], status: dict[str, Any]) -> dict[str, bytes]:
    package_data = canonical_package_bytes(package)
    index_entries = []
    files: dict[str, bytes] = {}
    for digest, data in sorted(blobs.items()):
        name = digest.removeprefix("sha256:")
        relative = f"blobs/sha256/{name}"
        index_entries.append({"digest": digest, "byteCount": len(data), "encoding": "utf-8",
                              "relativePath": relative})
        files[relative] = data
    index = {
        "schemaVersion": 1,
        "status": "draft-unapproved",
        "packageHash": sha256(package_data),
        "entries": index_entries,
    }
    files[PACKAGE_FILE] = package_data
    files[UPLOAD_INDEX_FILE] = _json_bytes(index, pretty=True)
    files[STATUS_FILE] = _json_bytes(status, pretty=True)
    return files


def _matches_existing_bundle(output_dir: Path, files: dict[str, bytes]) -> bool:
    if output_dir.is_symlink() or getattr(output_dir, "is_junction", lambda: False)() or not output_dir.is_dir():
        return False
    if os.name == "posix" and stat.S_IMODE(output_dir.stat().st_mode) & 0o077:
        return False
    actual: set[str] = set()
    for path in output_dir.rglob("*"):
        relative = path.relative_to(output_dir).as_posix()
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            return False
        if path.is_file():
            actual.add(relative)
            if ((os.name == "posix" and stat.S_IMODE(path.stat().st_mode) & 0o077)
                    or path.read_bytes() != files.get(relative)):
                return False
        elif not path.is_dir() or (os.name == "posix" and stat.S_IMODE(path.stat().st_mode) & 0o077):
            return False
    return actual == set(files)


def _fsync_directory(path: Path) -> None:
    if os.name != "posix" or not hasattr(os, "O_DIRECTORY"):
        return
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_template(path: Path) -> None:
    path = Path(path)
    _require_plain_directory(path.parent, "Template parent")
    _write_new_file(path, _json_bytes(documented_template(), pretty=True))


def write_bundle(output_dir: Path, package: PrivateContestPackage, blobs: dict[str, bytes],
                 status: dict[str, Any]) -> Literal["created", "replayed"]:
    if os.name != "posix":
        raise ValueError("Secret bundle output requires POSIX owner-only permissions")
    output_dir = Path(os.path.abspath(output_dir))
    parent = _require_plain_directory(output_dir.parent, "Output parent")
    files = _bundle_files(package, blobs, status)
    if output_dir.exists() or output_dir.is_symlink():
        if _matches_existing_bundle(output_dir, files):
            return "replayed"
        raise FileExistsError(f"Refusing to replace a different or unsafe output bundle: {output_dir}")
    staging = parent / f".{output_dir.name}.partial-{secrets.token_hex(8)}"
    try:
        staging.mkdir(mode=0o700)
        (staging / "blobs").mkdir(mode=0o700)
        (staging / "blobs" / "sha256").mkdir(mode=0o700)
        for relative, data in sorted(files.items()):
            _write_new_file(staging / Path(relative), data)
        _fsync_directory(staging / "blobs" / "sha256")
        _fsync_directory(staging / "blobs")
        _fsync_directory(staging)
        os.rename(staging, output_dir)
        _fsync_directory(parent)
        return "created"
    finally:
        if staging.exists():
            # This exact, randomly named directory was created above under the
            # already verified parent and is never supplied by the caller.
            shutil.rmtree(staging)


def summary(package: PrivateContestPackage, blobs: dict[str, bytes], status: dict[str, Any], mode: str) -> dict[str, Any]:
    return {
        "mode": mode,
        "status": status["status"],
        "releaseReady": False,
        "packageId": package.package_id,
        "revision": package.revision,
        "packageHash": status["packageHash"],
        "packageBytes": status["packageBytes"],
        "problemCount": len(package.entries),
        "sampleCount": status["sampleCount"],
        "hiddenCount": status["hiddenCount"],
        "storedBlobCount": len(blobs),
        "blockers": status["blockers"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path, nargs="?", help="explicit operator config JSON")
    parser.add_argument("--output-dir", type=Path, help="create a new package/blob bundle directory")
    parser.add_argument("--template-output", type=Path,
                        help="create a non-runnable config template with unresolved values left null")
    args = parser.parse_args(argv)
    if args.template_output is not None:
        if args.config is not None or args.output_dir is not None:
            parser.error("--template-output cannot be combined with config or --output-dir")
        write_template(args.template_output)
        print(json.dumps({"mode": "template-created", "path": str(args.template_output)}, ensure_ascii=False))
        return 0
    if args.config is None:
        parser.error("config is required unless --template-output is used")
    try:
        config = read_config(args.config)
        package, blobs, status = build(config)
        mode = "validation-only"
        if args.output_dir is not None:
            mode = "bundle-" + write_bundle(args.output_dir, package, blobs, status)
        print(json.dumps(summary(package, blobs, status, mode), ensure_ascii=False, sort_keys=True))
        return 0
    except (ValueError, OSError):
        # Pydantic errors may echo operator evidence. Never reflect config or
        # hidden data into logs; the detailed cause remains testable via APIs.
        print("Draft package validation failed; no upload or import was attempted.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
