#!/usr/bin/env python3
"""Release only an isolated E2E builder's cache after all E2E images exist.

This is deliberately not a general Docker cleanup utility.  It accepts only
the nonce namespace written by ``e2e_stack_test.py`` and uses the existing
immutable BuildKit verifier before and after the cache operation.  Images,
containers, volumes, networks, and the builder itself are never removed.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from typing import Callable


PROJECT_RE = re.compile(r"webcompiler-e2e-[a-f0-9]{32}")
BUILDER_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,79}")
ID_RE = re.compile(r"sha256:[a-f0-9]{64}")
CONTAINER_ID_RE = re.compile(r"[0-9a-f]{64}")
MAX_JOURNAL_BYTES = 4096


class CacheReleaseError(RuntimeError):
    """A scoped cache release could not be proven safe."""


@dataclass(frozen=True)
class Scope:
    root: Path
    project: str
    builder: str
    builder_id: str
    sandbox_image: str
    backend_image: str
    frontend_image: str

    def __post_init__(self) -> None:
        root = Path(self.root)
        if (not root.is_absolute() or root.is_symlink() or root.resolve() != root
                or not root.is_dir()):
            raise CacheReleaseError("An explicit non-symlink E2E root is required")
        object.__setattr__(self, "root", root)
        if PROJECT_RE.fullmatch(self.project) is None:
            raise CacheReleaseError("An exact E2E project namespace is required")
        if BUILDER_RE.fullmatch(self.builder) is None or self.builder == "default":
            raise CacheReleaseError("An explicit bound builder is required")
        if CONTAINER_ID_RE.fullmatch(self.builder_id) is None:
            raise CacheReleaseError("An exact bound builder identity is required")
        expected = {
            "sandbox_image": f"{self.project}-sandbox:latest",
            "backend_image": f"{self.project}-backend:latest",
            "frontend_image": f"{self.project}-frontend:latest",
        }
        for field, value in expected.items():
            if getattr(self, field) != value:
                raise CacheReleaseError("E2E image tags must exactly match the ownership namespace")

    @property
    def images(self) -> tuple[str, str, str]:
        return self.sandbox_image, self.backend_image, self.frontend_image


def validate_owner_record(value: object, root: Path, project: str) -> None:
    expected = {"version": 1, "root": str(root), "namespace": project}
    if value != expected:
        raise CacheReleaseError("E2E ownership journal does not match this root and namespace")


def read_owner_record(root: Path, project: str, *, uid: int | None = None) -> None:
    """Read the private journal through the checked root directory descriptor.

    ``uid`` exists solely for platform-neutral unit tests.  Production callers
    use the current POSIX account and require no-follow directory operations.
    """
    if uid is None:
        if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
            raise CacheReleaseError("E2E cache release requires POSIX private-file checks")
        uid = os.getuid()
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        directory = os.open(root, flags)
    except OSError as error:
        raise CacheReleaseError("E2E root cannot be safely opened") from error
    try:
        try:
            descriptor = os.open(
                ".e2e-stack-owner.json",
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=directory,
            )
        except OSError as error:
            raise CacheReleaseError("Private E2E ownership journal is required") from error
    finally:
        os.close(directory)
    try:
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != uid
                    or info.st_mode & 0o077 or not 0 < info.st_size <= MAX_JOURNAL_BYTES):
                raise CacheReleaseError("Invalid private E2E ownership journal")
            raw = stream.read(MAX_JOURNAL_BYTES + 1)
    except OSError as error:
        raise CacheReleaseError("Private E2E ownership journal cannot be read") from error
    if len(raw) > MAX_JOURNAL_BYTES:
        raise CacheReleaseError("Invalid private E2E ownership journal")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CacheReleaseError("Invalid private E2E ownership journal") from error
    validate_owner_record(value, root, project)


def validate_local_docker_environment(environment: dict[str, str] | os._Environ[str] = os.environ) -> None:
    if os.name != "posix" or environment.get("DOCKER_HOST") != "unix:///var/run/docker.sock":
        raise CacheReleaseError("E2E cache release requires the explicit local Docker socket")
    if any(environment.get(key) for key in ("DOCKER_CONTEXT", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH")):
        raise CacheReleaseError("E2E cache release refuses remote Docker selection")


def prune_command(builder: str) -> list[str]:
    if BUILDER_RE.fullmatch(builder) is None or builder == "default":
        raise CacheReleaseError("An explicit bound builder is required")
    # --builder scopes pruning to that BuildKit instance; --all still does not
    # remove loaded images, containers, volumes, networks, or the builder.
    return ["docker", "buildx", "prune", "--builder", builder, "--all", "--force"]


def release(
    scope: Scope,
    *,
    verify_builder: Callable[[], str],
    inspect_image: Callable[[str], str],
    prune_builder: Callable[[str], None],
    read_owner: Callable[[Path, str], None] = read_owner_record,
) -> None:
    """Prove image identity survives a scoped cache prune or fail before ``up``."""
    read_owner(scope.root, scope.project)
    if verify_builder() != scope.builder_id:
        raise CacheReleaseError("Bound builder identity changed before E2E cache release")
    before = {image: inspect_image(image) for image in scope.images}
    if any(ID_RE.fullmatch(identity) is None for identity in before.values()):
        raise CacheReleaseError("All three completed E2E image identities are required")
    prune_builder(scope.builder)
    if verify_builder() != scope.builder_id:
        raise CacheReleaseError("Bound builder identity changed after E2E cache release")
    after = {image: inspect_image(image) for image in scope.images}
    if before != after:
        raise CacheReleaseError("E2E image identity changed during cache release")


def _run(arguments: list[str], *, timeout: int, capture: bool) -> str:
    try:
        result = subprocess.run(
            arguments,
            check=False,
            text=True,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise CacheReleaseError("E2E cache release command was unavailable") from error
    if result.returncode:
        raise CacheReleaseError("E2E cache release command failed")
    return result.stdout if capture and isinstance(result.stdout, str) else ""


def verified_builder_id(scope: Scope) -> str:
    output = _run(
        [sys.executable, str(scope.root / "scripts" / "verify_build_builder.py")],
        timeout=45,
        capture=True,
    )
    value = output.strip()
    if value != scope.builder_id or output not in (value, value + "\n", value + "\r\n"):
        raise CacheReleaseError("Bound builder verification did not return the expected identity")
    return value


def inspected_image_id(image: str) -> str:
    output = _run(["docker", "image", "inspect", "--format", "{{.Id}}", image], timeout=30, capture=True)
    value = output.strip()
    if ID_RE.fullmatch(value) is None or output not in (value, value + "\n", value + "\r\n"):
        raise CacheReleaseError("Completed E2E image identity is unavailable")
    return value


def prune_bound_builder(builder: str) -> None:
    _run(prune_command(builder), timeout=300, capture=False)


def parse_scope(arguments: argparse.Namespace) -> Scope:
    # ``verify_build_builder.py`` deliberately reads its builder selection from
    # the environment.  Bind the CLI prune target to that same value before
    # inspecting the journal or making any Docker request.
    environment_builder = os.environ.get("WEBCOMPILER_BUILD_BUILDER", "")
    if arguments.builder != environment_builder:
        raise CacheReleaseError("E2E cache release builder differs from the verified builder")
    return Scope(
        root=Path(arguments.root),
        project=arguments.project,
        builder=arguments.builder,
        builder_id=os.environ.get("WEBCOMPILER_BUILD_CONTAINER_ID", ""),
        sandbox_image=arguments.sandbox_image,
        backend_image=arguments.backend_image,
        frontend_image=arguments.frontend_image,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--project", required=True)
    parser.add_argument("--builder", required=True)
    parser.add_argument("--sandbox-image", required=True)
    parser.add_argument("--backend-image", required=True)
    parser.add_argument("--frontend-image", required=True)
    parser.add_argument("--validate-only", action="store_true")
    arguments = parser.parse_args()
    try:
        scope = parse_scope(arguments)
        validate_local_docker_environment()
        read_owner_record(scope.root, scope.project)
        if arguments.validate_only:
            return 0
        release(
            scope,
            verify_builder=lambda: verified_builder_id(scope),
            inspect_image=inspected_image_id,
            prune_builder=prune_bound_builder,
        )
    except CacheReleaseError as error:
        print("E2E build-cache release refused: " + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
