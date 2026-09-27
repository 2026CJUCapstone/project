#!/usr/bin/env python3
"""Drift-safe installer for the host Nginx webcompiler location include.

The default command is read-only. ``apply`` must run as root, requires the
caller's observed current target hash, keeps a content-addressed rollback copy,
tests Nginx before reload, verifies the public readiness response, and restores
the prior bytes if any step fails.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from typing import Callable, Sequence
from urllib import error, request


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "deploy" / "nginx" / "webcompiler.locations.conf"
DEFAULT_TARGET = Path("/etc/nginx/snippets/webcompiler.locations.conf")
DEFAULT_VERIFY_URL = "https://cuha.cju.ac.kr/webcompiler/ready"
DEFAULT_LOCK = Path("/etc/nginx/snippets/.webcompiler.locations.conf.lock")


class InstallError(RuntimeError):
    """A fail-closed installation or verification error."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_regular(path: Path, label: str) -> tuple[bytes, os.stat_result]:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise InstallError(f"{label} does not exist: {path}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise InstallError(f"{label} must be a regular non-symlink file: {path}")
    return path.read_bytes(), metadata


def validate_candidate(data: bytes) -> None:
    try:
        config = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InstallError("candidate include must be UTF-8") from exc

    for public_path, upstream_path in (
        ("/webcompiler/health", "/health"),
        ("/webcompiler/ready", "/ready"),
    ):
        exact = f"location = {public_path} {{"
        if config.count(exact) != 1:
            raise InstallError(f"candidate must contain exactly one {exact!r}")
        block = config.split(exact, 1)[1].split("}", 1)[0]
        expected = f"proxy_pass http://127.0.0.1:18000{upstream_path};"
        if expected not in block:
            raise InstallError(f"{public_path} must proxy to {expected}")

    if config.count("location /webcompiler/ {") != 1:
        raise InstallError("candidate must retain exactly one SPA prefix route")


def inspect(source: Path, target: Path) -> dict[str, object]:
    source_data, _ = read_regular(source, "source")
    target_data, target_stat = read_regular(target, "target")
    validate_candidate(source_data)
    return {
        "source": str(source),
        "sourceSha256": sha256(source_data),
        "target": str(target),
        "targetSha256": sha256(target_data),
        "targetMode": format(stat.S_IMODE(target_stat.st_mode), "04o"),
        "targetUid": target_stat.st_uid,
        "targetGid": target_stat.st_gid,
        "matches": source_data == target_data,
    }


def _fsync_directory(directory: Path) -> None:
    if os.name != "posix":
        return
    descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_replace(
    path: Path,
    data: bytes,
    metadata: os.stat_result,
    *,
    mode: int | None = None,
) -> None:
    temporary = path.with_name(f".{path.name}.candidate-{os.getpid()}")
    if temporary.exists():
        raise InstallError(f"refusing to reuse temporary path: {temporary}")
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb", closefd=True) as output:
                output.write(data)
                output.flush()
                if hasattr(os, "fchmod"):
                    os.fchmod(output.fileno(), stat.S_IMODE(metadata.st_mode) if mode is None else mode)
                else:  # pragma: no cover - POSIX production always has fchmod
                    os.chmod(temporary, stat.S_IMODE(metadata.st_mode) if mode is None else mode)
                if os.name == "posix":
                    os.fchown(output.fileno(), metadata.st_uid, metadata.st_gid)
                os.fsync(output.fileno())
            os.replace(temporary, path)
            _fsync_directory(path.parent)
        except BaseException:
            if temporary.exists():
                temporary.unlink()
            raise
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_backup(path: Path, data: bytes, metadata: os.stat_result) -> None:
    if path.exists():
        existing, _ = read_regular(path, "rollback backup")
        if existing != data:
            raise InstallError(f"rollback backup hash collision: {path}")
        return
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb", closefd=True) as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())
    if os.name == "posix":
        os.chown(path, metadata.st_uid, metadata.st_gid)
    _fsync_directory(path.parent)


def run_checked(command: Sequence[str]) -> None:
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        raise InstallError(f"command failed ({completed.returncode}): {' '.join(command)}: {detail}")


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _fetch_public(url: str, timeout: float = 8.0) -> tuple[int, str, str, bytes]:
    opener = request.build_opener(_NoRedirect)
    response = None
    try:
        response = opener.open(request.Request(url, headers={"Accept": "application/json"}), timeout=timeout)
    except error.HTTPError as exc:
        response = exc
    except (error.URLError, TimeoutError) as exc:
        raise InstallError(f"readiness endpoint is unreachable: {exc}") from exc

    assert response is not None
    with response:
        status_code = response.status
        content_type = response.headers.get_content_type()
        cache_control = response.headers.get("Cache-Control", "").lower()
        body = response.read(65537)
    if len(body) > 65536:
        raise InstallError("readiness response exceeds 64 KiB")
    return status_code, content_type, cache_control, body


def observe_public_url(url: str) -> dict[str, object]:
    status_code, content_type, cache_control, body = _fetch_public(url)
    return {
        "status": status_code,
        "contentType": content_type,
        "cacheControl": cache_control,
        "bodySha256": sha256(body),
    }


def verify_ready_url(url: str, timeout: float = 8.0) -> None:
    status_code, content_type, cache_control, body = _fetch_public(url, timeout)
    if content_type != "application/json":
        raise InstallError(f"readiness endpoint returned {content_type}, not JSON")
    if "no-store" not in cache_control:
        raise InstallError("readiness endpoint must be no-store")
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InstallError("readiness endpoint returned invalid JSON") from exc
    if status_code != 200 or payload != {"status": "ready"}:
        raise InstallError(f"unexpected readiness response: HTTP {status_code} {payload!r}")


def validate_target_trust(target: Path, target_stat: os.stat_result) -> None:
    if target_stat.st_uid != 0 or target_stat.st_gid != 0:
        raise InstallError("target must be owned by root:root")
    if stat.S_IMODE(target_stat.st_mode) & (stat.S_IWGRP | stat.S_IWOTH):
        raise InstallError("target must not be group/other writable")

    current = target.parent
    while True:
        try:
            metadata = current.lstat()
        except FileNotFoundError as exc:
            raise InstallError(f"target parent does not exist: {current}") from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise InstallError(f"target parent must be a real directory: {current}")
        if metadata.st_uid != 0 or metadata.st_gid != 0:
            raise InstallError(f"target parent must be owned by root:root: {current}")
        if stat.S_IMODE(metadata.st_mode) & (stat.S_IWGRP | stat.S_IWOTH):
            raise InstallError(f"target parent must not be group/other writable: {current}")
        if current.parent == current:
            break
        current = current.parent


@contextmanager
def installation_lock(path: Path):
    if os.name != "posix":
        raise InstallError("host installation lock requires POSIX")
    validate_target_trust(path.with_name("lock-placeholder"), type("Metadata", (), {
        "st_uid": 0, "st_gid": 0, "st_mode": stat.S_IFREG | 0o600,
    })())
    if not hasattr(os, "O_NOFOLLOW"):
        raise InstallError("host does not support no-follow lock creation")

    flags = os.O_RDWR | getattr(os, "O_CLOEXEC", 0) | os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags | os.O_CREAT | os.O_EXCL, 0o600)
        created = True
    except FileExistsError:
        descriptor = os.open(path, flags)
        created = False
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise InstallError(f"installation lock must be a regular file: {path}")
        if created:
            os.fchmod(descriptor, 0o600)
            os.fchown(descriptor, 0, 0)
            os.fsync(descriptor)
        elif (metadata.st_uid != 0 or metadata.st_gid != 0
              or stat.S_IMODE(metadata.st_mode) & (stat.S_IWGRP | stat.S_IWOTH)):
            raise InstallError("existing installation lock is not root-owned and private")
        import fcntl
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise InstallError("another host Nginx include installation is active") from exc
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def validate_hash(value: str, label: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise InstallError(f"{label} must be exactly 64 lowercase hexadecimal characters")


def validate_installed_target(
    data: bytes,
    metadata: os.stat_result,
    expected_data: bytes,
    expected_uid: int,
    expected_gid: int,
) -> None:
    if (data != expected_data or metadata.st_uid != expected_uid
            or metadata.st_gid != expected_gid
            or stat.S_IMODE(metadata.st_mode) != 0o644):
        raise InstallError("installed target bytes or metadata do not match the approved candidate")


def _apply_locked(
    source: Path,
    target: Path,
    *,
    expected_source_sha256: str,
    expected_current_sha256: str,
    nginx_binary: str,
    verify_url: str,
    runner: Callable[[Sequence[str]], None] = run_checked,
    verifier: Callable[[str], None] = verify_ready_url,
    observer: Callable[[str], dict[str, object]] = observe_public_url,
    trust_validator: Callable[[Path, os.stat_result], None] = validate_target_trust,
    installed_validator: Callable[[bytes, os.stat_result, bytes, int, int], None] = validate_installed_target,
    effective_uid: int | None = None,
    platform_name: str | None = None,
) -> dict[str, object]:
    platform_name = os.name if platform_name is None else platform_name
    effective_uid = (os.geteuid() if hasattr(os, "geteuid") else -1) if effective_uid is None else effective_uid
    if platform_name != "posix" or effective_uid != 0:
        raise InstallError("apply must run as root on the target POSIX host")

    source_data, _ = read_regular(source, "source")
    target_data, target_stat = read_regular(target, "target")
    validate_candidate(source_data)
    source_hash, target_hash = sha256(source_data), sha256(target_data)
    validate_hash(expected_source_sha256, "expected source SHA-256")
    validate_hash(expected_current_sha256, "expected current SHA-256")
    if expected_source_sha256 != source_hash:
        raise InstallError(
            f"source drift: expected {expected_source_sha256}, observed {source_hash}"
        )
    trust_validator(target, target_stat)

    if source_data == target_data:
        runner((nginx_binary, "-t"))
        verifier(verify_url)
        return {"changed": False, "sourceSha256": source_hash, "targetSha256": target_hash}
    if expected_current_sha256 != target_hash:
        raise InstallError(
            f"target drift: expected {expected_current_sha256}, observed {target_hash}"
        )

    backup = target.with_name(f"{target.name}.rollback-{target_hash[:16]}")
    _write_backup(backup, target_data, target_stat)
    baseline_public = observer(verify_url)
    try:
        _atomic_replace(target, source_data, target_stat, mode=0o644)
        installed_data, installed_stat = read_regular(target, "installed target")
        installed_validator(installed_data, installed_stat, source_data,
                            target_stat.st_uid, target_stat.st_gid)
        runner((nginx_binary, "-t"))
        runner((nginx_binary, "-s", "reload"))
        verifier(verify_url)
    except BaseException as failure:
        rollback_errors: list[str] = []
        try:
            _atomic_replace(target, target_data, target_stat)
        except BaseException as exc:  # pragma: no cover - catastrophic filesystem failure
            rollback_errors.append(f"restore failed: {exc}")
        else:
            for command in ((nginx_binary, "-t"), (nginx_binary, "-s", "reload")):
                try:
                    runner(command)
                except BaseException as exc:  # pragma: no cover - platform/service failure
                    rollback_errors.append(f"rollback command failed: {exc}")
            try:
                if observer(verify_url) != baseline_public:
                    rollback_errors.append("rollback public response differs from the pre-apply response")
            except BaseException as exc:  # pragma: no cover - external network failure
                rollback_errors.append(f"rollback public verification failed: {exc}")
        suffix = "; ".join(rollback_errors) if rollback_errors else "rollback verified"
        raise InstallError(f"candidate activation failed: {failure}; {suffix}") from failure

    return {
        "changed": True,
        "sourceSha256": source_hash,
        "previousTargetSha256": target_hash,
        "rollbackBackup": str(backup),
        "verifiedUrl": verify_url,
    }


def apply(
    source: Path,
    target: Path,
    *,
    expected_source_sha256: str,
    expected_current_sha256: str,
    nginx_binary: str,
    verify_url: str,
    lock_file: Path = DEFAULT_LOCK,
    runner: Callable[[Sequence[str]], None] = run_checked,
    verifier: Callable[[str], None] = verify_ready_url,
    observer: Callable[[str], dict[str, object]] = observe_public_url,
    trust_validator: Callable[[Path, os.stat_result], None] = validate_target_trust,
    installed_validator: Callable[[bytes, os.stat_result, bytes, int, int], None] = validate_installed_target,
    lock_factory: Callable[[Path], object] = installation_lock,
    effective_uid: int | None = None,
    platform_name: str | None = None,
) -> dict[str, object]:
    platform_name = os.name if platform_name is None else platform_name
    effective_uid = (os.geteuid() if hasattr(os, "geteuid") else -1) if effective_uid is None else effective_uid
    if platform_name != "posix" or effective_uid != 0:
        raise InstallError("apply must run as root on the target POSIX host")
    with lock_factory(lock_file):
        return _apply_locked(
            source,
            target,
            expected_source_sha256=expected_source_sha256,
            expected_current_sha256=expected_current_sha256,
            nginx_binary=nginx_binary,
            verify_url=verify_url,
            runner=runner,
            verifier=verifier,
            observer=observer,
            trust_validator=trust_validator,
            installed_validator=installed_validator,
            effective_uid=effective_uid,
            platform_name=platform_name,
        )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "apply"))
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--expect-current-sha256")
    parser.add_argument("--expect-source-sha256")
    parser.add_argument("--nginx-binary", default="/usr/sbin/nginx")
    parser.add_argument("--verify-url", default=DEFAULT_VERIFY_URL)
    parser.add_argument("--lock-file", type=Path, default=DEFAULT_LOCK)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.action == "check":
            result = inspect(args.source, args.target)
        else:
            if not args.expect_current_sha256 or not args.expect_source_sha256:
                raise InstallError("apply requires --expect-source-sha256 and --expect-current-sha256")
            result = apply(
                args.source,
                args.target,
                expected_source_sha256=args.expect_source_sha256,
                expected_current_sha256=args.expect_current_sha256,
                nginx_binary=args.nginx_binary,
                verify_url=args.verify_url,
                lock_file=args.lock_file,
            )
    except InstallError as exc:
        print(f"host nginx include: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
