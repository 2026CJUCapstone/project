"""Explicit, exact-revision approval for a reviewed Bpp runtime update.

No automatic toolchain adoption: the operator first builds/tests an immutable
image, then records the approved old/new revisions and image identities in a
private server-local manifest. All application/schema/topology gates still run.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat

LEGACY_ALLOWED_CHANGES = frozenset({
    "runtime/bpp-ref.txt",
    "runtime/image-lock.json",
    "runtime/docker/Dockerfile",
    "runtime/compiler-patches/apply_exploration.py",
    "runtime/compiler-patches/exploration.bpp",
    "runtime/sandbox/verify_bpp_exploration.py",
})
GRAPH_LATENCY_CHANGES = frozenset({
    "runtime/docker/Dockerfile",
    "runtime/sandbox/run.sh",
    "runtime/sandbox/verify_bpp_latency.py",
    "runtime/compiler-patches/apply_exploration.py",
    "runtime/compiler-patches/apply_performance.py",
    "runtime/compiler-patches/graph_scope.bpp",
})
# Used only after validate_approval has accepted one of the exact profiles
# below.  It is not itself sufficient to authorize an arbitrary subset.
ALLOWED_CHANGES = LEGACY_ALLOWED_CHANGES | GRAPH_LATENCY_CHANGES
REVIEWED_COMPILER_TRANSITION = (
    "2d596233f45973394a5d951c40b11f78171c8870",
    "9859a2dc783c9346be2ab9447e1569218bcc5093",
)
REVIEWED_SANDBOX_BASE = {
    "repository": "library/node", "tag": "24.21.0-alpine",
    "digest": "sha256:ebfe2f90462722a7a4de65e91990e97fe0d401c70e0e762c5b53302f905ec1c1",
    "linuxAmd64": "sha256:83f1c388c31fb2e51f7cbd4dea949b96260798c98f206e8e4696bc93bd964e3a",
    "nodeVersion": "24.21.0", "observedOn": "2026-09-28",
}


def runtime_digest(root: Path) -> str:
    digest = hashlib.sha256()
    paths = sorted(path for path in (root / "runtime").rglob("*") if path.is_file())
    if not paths:
        raise ValueError("Runtime source is empty")
    for path in paths:
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("Runtime source must be regular files")
        name = path.relative_to(root).as_posix().encode()
        content = path.read_bytes().replace(b"\r\n", b"\n")
        digest.update(name + b"\0" + hashlib.sha256(content).digest())
    return digest.hexdigest()


def changed_runtime(previous: Path, candidate: Path) -> set[str]:
    def entries(root):
        return {p.relative_to(root).as_posix(): p.read_bytes().replace(b"\r\n", b"\n")
                for p in (root / "runtime").rglob("*") if p.is_file()}
    old, new = entries(previous), entries(candidate)
    if old.keys() - new.keys():
        raise ValueError("Runtime file deletion is not approved")
    return {key for key in old.keys() | new.keys() if old.get(key) != new.get(key)}


def validate_approval(value, *, previous, candidate, old_sha, new_sha, old_image):
    if not isinstance(value, dict) or set(value) != {
        "version", "previous_sha", "candidate_sha", "previous_image", "candidate_image", "runtime_digest"
    }:
        raise ValueError("Invalid runtime approval shape")
    if type(value["version"]) is not int or value["version"] != 1:
        raise ValueError("Unsupported runtime approval")
    if value["previous_sha"] != old_sha or value["candidate_sha"] != new_sha:
        raise ValueError("Runtime approval revision mismatch")
    if not all(isinstance(v, str) and re.fullmatch(r"[0-9a-f]{40}", v) for v in (old_sha, new_sha)) or old_sha == new_sha:
        raise ValueError("Exact different revisions required")
    if value["previous_image"] != old_image or value["candidate_image"] == old_image:
        raise ValueError("Runtime approval image mismatch")
    if not all(isinstance(v, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", v) for v in (old_image, value["candidate_image"])):
        raise ValueError("Immutable runtime image IDs required")
    changes = changed_runtime(previous, candidate)
    legacy_profile = bool(changes) and changes <= LEGACY_ALLOWED_CHANGES
    latency_profile = changes == GRAPH_LATENCY_CHANGES
    if not legacy_profile and not latency_profile:
        raise ValueError("Unreviewed runtime change")
    if "runtime/bpp-ref.txt" in changes:
        refs = tuple((root / "runtime/bpp-ref.txt").read_text().strip() for root in (previous, candidate))
        if refs != REVIEWED_COMPILER_TRANSITION:
            raise ValueError("Unreviewed compiler revision transition")
    if "runtime/image-lock.json" in changes:
        old_lock, new_lock = (json.loads((root / "runtime/image-lock.json").read_text())
                              for root in (previous, candidate))
        new_images = new_lock.get("images")
        if not isinstance(new_images, dict) or new_images.pop("nodeSandbox", None) != REVIEWED_SANDBOX_BASE:
            raise ValueError("Unreviewed sandbox base image")
        if new_lock != old_lock:
            raise ValueError("Unreviewed change to existing image locks")
    if value["runtime_digest"] != runtime_digest(candidate):
        raise ValueError("Runtime source approval mismatch")
    return value


def load_approval(prod, previous, candidate, old_sha, new_sha, old_image, inspect):
    path = prod / ".deploy/basic-pool-runtime-approval.json"
    if not path.exists() and not path.is_symlink():
        return None
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_size > 4096:
        raise ValueError("Runtime approval must be a private operator-owned regular file")
    value = json.loads(path.read_text())
    # A previous successfully consumed approval never grants future changes.
    if isinstance(value, dict) and value.get("candidate_sha") == old_sha:
        return None
    value = validate_approval(value, previous=previous, candidate=candidate,
                              old_sha=old_sha, new_sha=new_sha, old_image=old_image)
    image = inspect(value["candidate_image"])
    labels = image.get("Config", {}).get("Labels") or {}
    if image.get("Id") != value["candidate_image"] or labels.get("io.bpp.runtime_source_digest") != value["runtime_digest"]:
        raise ValueError("Candidate runtime image provenance mismatch")
    if labels.get("io.bpp.ref") != (candidate / "runtime/bpp-ref.txt").read_text().strip():
        raise ValueError("Candidate compiler revision mismatch")
    if any(labels.get(key) != expected for key, expected in {
        "io.bpp.repo": "https://github.com/Creeper0809/Bpp",
        "io.bpp.test_skip_llvm_build": "1", "io.bpp.test_fast_io": "0",
    }.items()):
        raise ValueError("Candidate compiler build policy mismatch")
    return value


def verify_candidate(state, run):
    image = state["images"]["sandbox"]
    for verifier in ("verify_bpp_runtime.py", "verify_bpp_exploration.py", "verify_bpp_latency.py"):
        run("docker", "run", "--rm", "--pull", "never", "--network", "none",
            "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--memory", "1g", "--memory-swap", "1g", "--cpus", "1", "--pids-limit", "64",
            # The gates compile then execute native binaries in this private
            # tmpfs. Docker defaults tmpfs to noexec unless explicitly enabled.
            "--user", "1000:1000", "--tmpfs", "/tmp:rw,exec,size=128m,mode=1777,nosuid,nodev",
            "--entrypoint", "python3", image, "-I", "/usr/local/share/" + verifier,
            timeout=240)


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3 or sys.argv[1] != "digest":
        raise SystemExit("Usage: basic_pool_runtime_release.py digest SOURCE_ROOT")
    print(runtime_digest(Path(sys.argv[2])))
