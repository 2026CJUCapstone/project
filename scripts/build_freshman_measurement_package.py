"""Build the bounded, offline A--J source archive used by the runtime matrix.

The archive intentionally contains only the code which the in-container
measurement probe imports or executes.  It does not generate a corpus, contact
the network, run Docker, or approve a contest policy.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import sys
import tarfile


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PurePosixPath("tools/freshman_contest")
LETTERS = tuple("ABCDEFGHIJ")
MODULES = (
    "a_i.py",
    "banks.py",
    "stress_cases.py",
    "coverage_cases.py",
    "banks_stress_cases.py",
    "corpus-manifest-draft-v2.json",
)
SOURCE_MODULES = MODULES[:-1]
LANGUAGE_SUFFIXES = {
    "c": "c",
    "cpp": "cpp",
    "python": "py",
    "javascript": "js",
    "bpp": "bpp",
}
MAX_MEMBERS = 150
MAX_UNCOMPRESSED_BYTES = 4 * 1024 * 1024
MAX_MANIFEST_BYTES = 128 * 1024


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _required_relative_paths(package: Path, *, include_slow: bool = False) -> tuple[PurePosixPath, ...]:
    """Return the sole permitted archive members in a stable order."""

    paths = [PurePosixPath(name) for name in MODULES]
    init = package / "__init__.py"
    if init.is_symlink():
        raise ValueError("Optional package initializer must not be a symlink")
    if init.exists():
        paths.append(PurePosixPath("__init__.py"))
    for language, suffix in LANGUAGE_SUFFIXES.items():
        paths.extend(PurePosixPath("solutions") / language / f"{letter}.{suffix}"
                     for letter in LETTERS)
    paths.extend(PurePosixPath("solutions") / "java" / letter / "Main.java"
                 for letter in LETTERS)
    if include_slow:
        paths.extend(PurePosixPath("slow_solutions") / "python" / f"{letter}.py"
                     for letter in "FIJ")
    return tuple(sorted(paths, key=lambda item: item.as_posix()))


def _read_regular_file(package: Path, relative: PurePosixPath) -> bytes:
    """Read one whitelist entry while refusing links at every package level."""

    if package.is_symlink():
        raise ValueError("Freshman package directory must not be a symlink")
    current = package
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError(f"Symlinked archive member is not allowed: {relative.as_posix()}")
    if not current.is_file():
        raise ValueError(f"Missing required archive member: {relative.as_posix()}")
    return current.read_bytes()


def _load_and_verify_manifest(raw: bytes, module_bytes: dict[str, bytes]) -> None:
    """Verify the raw draft self-hash and the hashes of shipped generators."""

    if len(raw) > MAX_MANIFEST_BYTES:
        raise ValueError("Draft corpus manifest exceeds its byte budget")

    def no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Draft corpus manifest has duplicate JSON keys")
            result[key] = value
        return result

    try:
        manifest = json.loads(raw.decode("utf-8"), object_pairs_hook=no_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Draft corpus manifest is not valid UTF-8 JSON") from exc
    if not isinstance(manifest, dict):
        raise ValueError("Draft corpus manifest must be a JSON object")
    declared = manifest.get("manifestHash")
    unsigned = {key: value for key, value in manifest.items() if key != "manifestHash"}
    canonical = json.dumps(unsigned, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")).encode("utf-8")
    if not isinstance(declared, str) or declared != _sha256(canonical):
        raise ValueError("Draft corpus manifest self-hash mismatch")
    if manifest.get("version") != 1 or manifest.get("status") != "draft-unapproved":
        raise ValueError("Draft corpus manifest is not the expected draft identity")
    sources = manifest.get("sources")
    if not isinstance(sources, dict):
        raise ValueError("Draft corpus manifest has no source-hash map")
    for name in SOURCE_MODULES:
        if sources.get(name) != _sha256(module_bytes[name]):
            raise ValueError(f"Draft corpus source hash mismatch: {name}")


def archive_entries(root: Path = ROOT, *, include_slow: bool = False) -> tuple[tuple[str, bytes], ...]:
    """Read and validate the complete, fixed source package before archiving."""

    root = Path(root)
    tools = root / "tools"
    package = tools / "freshman_contest"
    if tools.is_symlink():
        raise ValueError("Tools directory must not be a symlink")
    if not package.is_dir() or package.is_symlink():
        raise ValueError("Missing freshman package directory")

    entries: list[tuple[str, bytes]] = []
    module_bytes: dict[str, bytes] = {}
    total = 0
    for relative in _required_relative_paths(package, include_slow=include_slow):
        data = _read_regular_file(package, relative)
        if "__pycache__" in relative.parts:
            raise ValueError("Bytecode caches are not permitted in the source archive")
        total += len(data)
        if total > MAX_UNCOMPRESSED_BYTES:
            raise ValueError("Freshman source package exceeds its byte budget")
        name = (PACKAGE_ROOT / relative).as_posix()
        entries.append((name, data))
        if relative.name in MODULES and relative.parent == PurePosixPath("."):
            module_bytes[relative.name] = data

    if len(entries) > MAX_MEMBERS:
        raise ValueError("Freshman source package exceeds its member budget")
    manifest = module_bytes.get(MODULES[-1])
    if manifest is None:
        raise AssertionError("The fixed manifest whitelist unexpectedly changed")
    _load_and_verify_manifest(manifest, module_bytes)
    return tuple(entries)


def build_archive_bytes(root: Path = ROOT, *, include_slow: bool = False) -> bytes:
    """Return deterministic gzip/tar bytes for the locally verified package."""

    entries = archive_entries(root, include_slow=include_slow)
    payload = io.BytesIO()
    with gzip.GzipFile(fileobj=payload, mode="wb", filename="", mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w", format=tarfile.USTAR_FORMAT) as archive:
            for name, data in entries:
                info = tarfile.TarInfo(name)
                info.size = len(data)
                info.mode = 0o444
                info.mtime = 0
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                archive.addfile(info, io.BytesIO(data))
    result = payload.getvalue()
    if not result:
        raise AssertionError("Archive construction produced no bytes")
    return result


def write_new_archive(output: Path, data: bytes) -> None:
    """Create exactly one new output file; never replace an existing path."""

    output = Path(output)
    if output.is_symlink() or output.exists():
        raise FileExistsError(f"Refusing to overwrite archive output: {output}")
    if not output.parent.is_dir() or output.parent.is_symlink():
        raise ValueError("Archive output parent must be an existing non-symlink directory")
    with output.open("xb") as stream:
        stream.write(data)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT,
                        help="repository root containing tools/freshman_contest")
    parser.add_argument("--output", type=Path,
                        help="new archive path; defaults to binary stdout")
    parser.add_argument("--include-slow", action="store_true",
                        help="include fixed F/I/J slow probes in a separate diagnostic-only archive")
    args = parser.parse_args(argv)
    data = build_archive_bytes(args.root, include_slow=args.include_slow)
    if args.output is None:
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
        return
    write_new_archive(args.output, data)
    print(json.dumps({"archive": str(args.output), "bytes": len(data),
                      "sha256": _sha256(data)}, sort_keys=True))


if __name__ == "__main__":
    main()
