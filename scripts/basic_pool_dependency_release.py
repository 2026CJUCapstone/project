"""Exact, private approval for the reviewed October dependency security patch.

Never overlays new application source onto the vulnerable operating libraries.
Clean images and fresh installed-image inventories must bind to the same SHA.
Schema, topology, runtime and rollback checks remain application-release gates.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tarfile

ALLOWED_CHANGES = frozenset({
    "backend/requirements.lock", "frontend/package.json", "frontend/package-lock.json",
})
TRANSITIONS = {
    "pyjwt[crypto]": (
        "2.13.0", "2.15.1",
        ("41571c89ca91598c79e8ef18a2d07367d4810fbbd6f637794879baf1b7703423",
         "66adcc2aff09b3f1bbd95fc1e1577df8ac8723c978552fd43304c8a290ac5728"),
        ("42d59d631f7768a1028a64c7ff581a9bf7519804daf91fc5b6c56e30eec5e193",
         "4f259e80cdfb6b3fc18a7de51fd1ef9ec79652f25019bae68975ca2468a34df8"),
    ),
    "urllib3": (
        "2.7.0", "2.8.0",
        ("231e0ec3b63ceb14667c67be60f2f2c40a518cb38b03af60abc813da26505f4c",
         "9fb4c81ebbb1ce9531cce37674bbc6f1360472bc18ca9a553ede278ef7276897"),
        ("0cf3cae568d36aa9576b28dfb35f11328f1cb974ca7647d9475ebb86c75ac6e3",
         "63bf2ead4c879426ebf22ef2a781eeb4aa3b4ae798a0435506f8687fd5bb9b63"),
    ),
}
DOMPURIFY = {
    "version": "3.4.16",
    "resolved": "https://registry.npmjs.org/dompurify/-/dompurify-3.4.16.tgz",
    "integrity": "sha512-sqo+pNp3qRhCIpbgRi1y8Tgk27Bo2Ry7w0dC1NBeNTdZChWjz9Xb/KOoZbRP/R6pQZ80Qw8YhXw13hWWBbMRnQ==",
}
SCANNER_SHA = "d89bcc6510a267f11b773398cbf1be5520ce39f9e8b6633178c4487f05b7d791"
IMAGE = re.compile(r"sha256:[0-9a-f]{64}\Z")
COMMIT = re.compile(r"[0-9a-f]{40}\Z")


def _bytes(path):
    return path.read_bytes().replace(b"\r\n", b"\n")


def dependency_digest(root):
    digest = hashlib.sha256()
    for name in sorted(ALLOWED_CHANGES):
        path = root / name
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("Dependency contracts must be regular source files")
        digest.update(name.encode() + b"\0" + hashlib.sha256(_bytes(path)).digest())
    return digest.hexdigest()


def validate_changes(previous, candidate):
    old = _bytes(previous / "backend/requirements.lock")
    new = _bytes(candidate / "backend/requirements.lock")
    for name, (before, after, old_hashes, hashes) in TRANSITIONS.items():
        pattern = re.compile(rb"(?im)^" + re.escape(name.encode()) + rb"==[^\n]+\\\n(?:[ \t]+--hash=sha256:[0-9a-f]{64}(?: \\)?\n)+")
        old_blocks, new_blocks = pattern.findall(old), pattern.findall(new)
        if len(old_blocks) != 1 or len(new_blocks) != 1:
            raise ValueError("Exactly one reviewed package block required")
        a, z = old_blocks[0], new_blocks[0]
        if not a.lower().startswith((name + "==" + before + " \\\n").encode()) or not z.lower().startswith((name + "==" + after + " \\\n").encode()):
            raise ValueError("Unreviewed backend package transition")
        observed = re.findall(rb"--hash=sha256:([0-9a-f]{64})", z)
        old_observed = re.findall(rb"--hash=sha256:([0-9a-f]{64})", a)
        if ({v.decode() for v in observed} != set(hashes) or len(observed) != 2
                or {v.decode() for v in old_observed} != set(old_hashes) or len(old_observed) != 2):
            raise ValueError("Unreviewed package artifacts")
        # All other requirement bytes (including existing artifact hashes) stay exact.
        new = new.replace(z, a, 1)
    if new != old:
        raise ValueError("Additional backend dependency changes are not approved")
    old_package, new_package = (json.loads(_bytes(root / "frontend/package.json"))
                                for root in (previous, candidate))
    if old_package["overrides"]["dompurify"] != "3.4.13" or new_package["overrides"]["dompurify"] != "3.4.16":
        raise ValueError("Unreviewed DOMPurify transition")
    new_package["overrides"]["dompurify"] = "3.4.13"
    if old_package != new_package:
        raise ValueError("Additional frontend package changes are not approved")
    old_lock, new_lock = (json.loads(_bytes(root / "frontend/package-lock.json"))
                          for root in (previous, candidate))
    a = old_lock["packages"]["node_modules/dompurify"]
    z = new_lock["packages"]["node_modules/dompurify"]
    if a["version"] != "3.4.13" or any(z.get(key) != value for key, value in DOMPURIFY.items()):
        raise ValueError("Unreviewed DOMPurify locked artifacts")
    for key in DOMPURIFY:
        z[key] = a[key]
    if old_lock != new_lock:
        raise ValueError("Additional frontend lock changes are not approved")


def _private_read(path, limit):
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o077 or info.st_size > limit):
        raise ValueError("Evidence must be private operator-owned regular files")
    return path.read_bytes()


def _fresh(value, now):
    instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if instant.tzinfo is None or not 0 <= (now - instant).total_seconds() <= 48 * 3600:
        raise ValueError("Fresh evidence required, at most 48 hours old")


def validate_manifest(manifest, *, commit, role, image_id, now):
    expected = {
        "schemaVersion": 1, "scope": "application", "sourceCommit": commit,
        "role": role, "target": image_id, "imageId": image_id, "policyPassed": True,
        "policy": "reject-unknown-high-critical-and-eol-no-waivers",
        "scanner": {"name": "Trivy", "version": "0.74.0", "binarySha256": SCANNER_SHA},
    }
    if (any(manifest.get(key) != value for key, value in expected.items())
            or manifest.get("policyPassed") is not True or type(manifest.get("schemaVersion")) is not int):
        raise ValueError("Installed-image security evidence mismatch")
    if manifest.get("database", {}).get("version") != 2:
        raise ValueError("Vulnerability database version mismatch")
    _fresh(manifest["createdAt"], now)
    _fresh(manifest["database"]["updatedAt"], now)
    files = manifest.get("files")
    if not isinstance(files, dict) or set(files) != {"report.json", "sbom.cdx.json"} or any(
            not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v) for v in files.values()):
        raise ValueError("Exact report and inventory hashes required")


def validate_approval(value, *, previous, candidate, old_sha, new_sha, old_images):
    fields = {"version", "previous_sha", "candidate_sha", "previous_images", "images", "dependency_digest", "security_root"}
    if not isinstance(value, dict) or set(value) != fields or type(value["version"]) is not int or value["version"] != 1:
        raise ValueError("Invalid dependency approval shape")
    if (not COMMIT.fullmatch(old_sha) or not COMMIT.fullmatch(new_sha) or old_sha == new_sha
            or value["previous_sha"] != old_sha or value["candidate_sha"] != new_sha):
        raise ValueError("Exact dependency approval revision mismatch")
    images = value["images"]
    if value["previous_images"] != old_images or not isinstance(images, dict) or set(images) != {"backend", "frontend"}:
        raise ValueError("Dependency approval image mismatch")
    if (any(not isinstance(v, str) or not IMAGE.fullmatch(v) for v in [*images.values(), *old_images.values()])
            or len(set(images.values())) != 2 or set(images.values()) & set(old_images.values())):
        raise ValueError("Distinct immutable clean image IDs required")
    validate_changes(previous, candidate)
    if value["dependency_digest"] != dependency_digest(candidate):
        raise ValueError("Approved dependency source mismatch")
    return value


def load_approval(prod, previous, candidate, old_sha, new_sha, old_images, inspect):
    path = prod / ".deploy/basic-pool-dependency-approval.json"
    if not path.exists() and not path.is_symlink():
        return None
    value = json.loads(_private_read(path, 8192))
    if isinstance(value, dict) and value.get("candidate_sha") == old_sha:
        return None  # Consumed approvals never grant a future dependency change.
    value = validate_approval(value, previous=previous, candidate=candidate,
                              old_sha=old_sha, new_sha=new_sha, old_images=old_images)
    evidence = Path(value["security_root"])
    if (not evidence.is_absolute() or evidence.resolve(strict=True) != evidence
            or not evidence.is_relative_to(prod / ".deploy") or not evidence.is_dir()):
        raise ValueError("Security evidence must stay within the private deployment directory")
    info = evidence.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("Private operator-owned evidence directory required")
    scanner_spec = importlib.util.spec_from_file_location("dependency_scan", Path(__file__).with_name("scan_image.py"))
    scanner = importlib.util.module_from_spec(scanner_spec)
    scanner_spec.loader.exec_module(scanner)
    for role, image_id in value["images"].items():
        image = inspect(image_id)
        labels = image.get("Config", {}).get("Labels") or {}
        if (image.get("Id") != image_id or image.get("Os") != "linux" or image.get("Architecture") != "amd64"
                or labels.get("io.webcompiler.source-sha") != new_sha or labels.get("io.webcompiler.image-role") != role):
            raise ValueError("Clean image source provenance mismatch")
        folder = evidence / role
        if folder.resolve(strict=True) != folder:
            raise ValueError("Report directories must not be symlinks")
        manifest = json.loads(_private_read(folder / "manifest.json", 32768))
        validate_manifest(manifest, commit=new_sha, role=role, image_id=image_id, now=datetime.now(timezone.utc))
        reports = {}
        for name, digest in manifest["files"].items():
            raw = _private_read(folder / name, 32 * 1024**2)
            if hashlib.sha256(raw).hexdigest() != digest:
                raise ValueError("Security report content mismatch")
            reports[name] = json.loads(raw)
        report = reports["report.json"]
        if report.get("Metadata", {}).get("ImageID") != image_id or report.get("ArtifactName") != image_id:
            raise ValueError("Security report image mismatch")
        # Sanitized reports intentionally omit labels; independently inspected
        # immutable image labels supply provenance, not caller-provided labels.
        report["Metadata"]["ImageConfig"]["config"] = {"Labels": labels}
        _, actual = scanner.summarize(report, target=image_id, source="docker", scope="application", commit=new_sha, role=role)
        if actual["policyPassed"] is not True or any(actual[key] != manifest[key] for key in
                ("os", "installedPackageEntries", "findingEntriesBySeverity")):
            raise ValueError("Security report does not substantiate the passing policy")
        if scanner.verify_inventory(report, reports["sbom.cdx.json"]) != manifest["uniquePackageIdentities"]:
            raise ValueError("Installed package inventory mismatch")
    return value


def verify_candidate(state, root, run):
    """Inspect clean-image payloads offline before maintenance or database access."""
    expected = {path.relative_to(root / "backend").as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in (root / "backend/app").rglob("*.py")}
    expected["requirements.lock"] = hashlib.sha256((root / "backend/requirements.lock").read_bytes()).hexdigest()
    probe = (
        "import hashlib,json,pathlib,sys; from importlib.metadata import version; "
        "assert version('PyJWT')=='2.15.1' and version('urllib3')=='2.8.0'; "
        "root=pathlib.Path('/app'); actual={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (root/'app').rglob('*.py')}; "
        "actual['requirements.lock']=hashlib.sha256((root/'requirements.lock').read_bytes()).hexdigest(); "
        "assert actual==json.load(sys.stdin)"
    )
    bounded = ["docker", "run", "--rm", "--pull", "never", "--network", "none", "--read-only",
               "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--memory", "256m",
               "--memory-swap", "256m", "--cpus", "0.5", "--pids-limit", "64", "--user", "10001:10001",
               "--tmpfs", "/tmp:size=16m,mode=1777,noexec,nosuid"]
    run(*bounded, "-i", state["images"]["backend"], "python", "-c", probe,
        data=json.dumps(expected).encode(), timeout=60)
    run(*bounded, state["images"]["backend"], "python", "-m", "pip", "check", timeout=60)
    expected_dist = {p.relative_to(root / "frontend-dist").as_posix(): p.read_bytes()
                     for p in (root / "frontend-dist").rglob("*") if p.is_file()}
    container = run("docker", "create", "--pull", "never", "--network", "none", "--read-only",
                    "--entrypoint", "nginx", state["images"]["frontend"]).decode().strip()
    if not re.fullmatch(r"[0-9a-f]{64}", container):
        raise ValueError("Invalid offline image inspection container")
    try:
        actual_dist = archive_files(run("docker", "cp", container + ":/usr/share/nginx/html/.", "-", timeout=60))
        extra = set(actual_dist) - set(expected_dist)
        if extra:
            # The official Nginx base retains its stock 50x page when dist is
            # copied. Allow only that exact previously operating static page;
            # no arbitrary extra application assets are accepted.
            if extra != {"50x.html"}:
                raise ValueError("Unexpected clean frontend assets")
            stock = run("docker", "create", "--pull", "never", "--network", "none", "--read-only",
                        "--entrypoint", "nginx", state["bases"]["frontend"]).decode().strip()
            if not re.fullmatch(r"[0-9a-f]{64}", stock):
                raise ValueError("Invalid stock image inspection container")
            try:
                stock_page = archive_files(run("docker", "cp", stock + ":/usr/share/nginx/html/50x.html", "-"))
                if stock_page != {"50x.html": actual_dist.pop("50x.html")}:
                    raise ValueError("Unexpected stock Nginx error page")
            finally:
                run("docker", "rm", stock)
        marker = ".well-known/webcompiler-release.json"
        if (json.loads(actual_dist.pop(marker)) != {"deployment_sha": state["sha"]}
                or json.loads(expected_dist.pop(marker)) != {"deployment_sha": state["sha"]}
                or actual_dist != expected_dist):
            raise ValueError("Clean frontend differs from CI-tested release assets")
        config = archive_files(run("docker", "cp", container + ":/etc/nginx/conf.d/default.conf", "-"))
        expected_config = _bytes(root / "frontend/nginx.conf").replace(
            b"server backend:8000 resolve;", b"server api-proxy:8080 resolve;")
        if config != {"default.conf": expected_config}:
            raise ValueError("Clean frontend upstream configuration mismatch")
    finally:
        run("docker", "rm", container)
    run(*bounded, "--entrypoint", "nginx", state["images"]["frontend"], "-t", timeout=30)


def archive_files(raw):
    """Read bounded docker-cp payloads without extracting caller-owned paths."""
    if len(raw) > 64 * 1024**2:
        raise ValueError("Image asset archive exceeds the input limit")
    result = {}
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        for entry in archive:
            name = entry.name.removeprefix("./")
            if not name or name == ".":
                if entry.isdir():
                    continue
                raise ValueError("Invalid image asset path")
            if PurePosixPath(name).is_absolute() or ".." in name.split("/") or "\\" in name:
                raise ValueError("Invalid image asset path")
            if entry.isdir():
                continue
            if not entry.isfile() or name in result or entry.size > 32 * 1024**2:
                raise ValueError("Invalid image asset entry")
            result[name] = archive.extractfile(entry).read()
    return result
