"""Pure exact-source / clean-image release guard regressions; no Docker or SSH."""
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[2]


def helper():
    spec = importlib.util.spec_from_file_location("dependency_guard_test", ROOT / "scripts/basic_pool_dependency_release.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def trees(tmp_path):
    module = helper()
    previous, candidate = tmp_path / "old", tmp_path / "new"
    for name in module.ALLOWED_CHANGES:
        old_path, new_path = previous / name, candidate / name
        old_path.parent.mkdir(parents=True, exist_ok=True)
        new_path.parent.mkdir(parents=True, exist_ok=True)
        new_path.write_bytes((ROOT / name).read_bytes())
        # CI uses a shallow checkout: fixtures do not depend on old Git objects.
        content = new_path.read_text()
        if name == "backend/requirements.lock":
            for package, (before, after, old_hashes, hashes) in module.TRANSITIONS.items():
                content = content.replace(package + "==" + after, package + "==" + before)
                for old_hash, new_hash in zip(old_hashes, hashes):
                    content = content.replace(new_hash, old_hash)
        else:
            value = json.loads(content)
            if name.endswith("package.json"):
                value["overrides"]["dompurify"] = "3.4.13"
            else:
                value["packages"]["node_modules/dompurify"].update(
                    version="3.4.13", resolved="https://registry.npmjs.org/dompurify/-/dompurify-3.4.13.tgz",
                    integrity="sha512-2vmYIoqjze2d+kakP8S/nS5shfsl587kzwEjcGlTdiksUVgFHnFCsLYDVj/JNqJVOQZGSYBTmuycv0PodwmnMQ==")
            content = json.dumps(value)
        old_path.write_text(content)
    return module, previous, candidate


def test_only_reviewed_artifacts_pass_including_crlf(trees):
    module, old, new = trees
    module.validate_changes(old, new)
    original = module.dependency_digest(new)
    for name in module.ALLOWED_CHANGES:
        path = new / name
        path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    module.validate_changes(old, new)
    assert module.dependency_digest(new) == original


@pytest.mark.parametrize("kind", ["extra_requirement", "hash", "version", "override", "other_package", "lock_extra"])
def test_extra_dependency_changes_rejected(trees, kind):
    module, old, new = trees
    backend = new / "backend/requirements.lock"
    if kind == "extra_requirement":
        backend.write_bytes(backend.read_bytes() + b"unapproved==1\n")
    elif kind in {"hash", "version"}:
        content = backend.read_text()
        before = module.TRANSITIONS["urllib3"][3][0] if kind == "hash" else "urllib3==2.8.0"
        backend.write_text(content.replace(before, "0" * 64 if kind == "hash" else "urllib3==2.9.0"))
    elif kind in {"override", "other_package"}:
        path = new / "frontend/package.json"
        value = json.loads(path.read_bytes())
        if kind == "override":
            value["overrides"]["dompurify"] = "3.4.17"
        else:
            value["dependencies"]["react"] = "unreviewed"
        path.write_text(json.dumps(value))
    else:
        path = new / "frontend/package-lock.json"
        value = json.loads(path.read_bytes())
        value["packages"]["node_modules/unreviewed"] = {"version": "1"}
        path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        module.validate_changes(old, new)


def approval(module, new):
    return {"version": 1, "previous_sha": "a" * 40, "candidate_sha": "b" * 40,
            "previous_images": {"backend": "sha256:" + "1" * 64, "frontend": "sha256:" + "2" * 64},
            "images": {"backend": "sha256:" + "3" * 64, "frontend": "sha256:" + "4" * 64},
            "dependency_digest": module.dependency_digest(new), "security_root": "/private/.deploy/evidence"}


@pytest.mark.parametrize("mutation", [None, "sha", "digest", "same_image", "duplicate", "tag", "boolean_version", "extra"])
def test_exact_approval_scope(trees, mutation):
    module, old, new = trees
    value = approval(module, new)
    old_images = dict(value["previous_images"])
    if mutation == "sha":
        value["candidate_sha"] = "c" * 40
    elif mutation == "digest":
        value["dependency_digest"] = "0" * 64
    elif mutation == "same_image":
        value["images"]["backend"] = old_images["backend"]
    elif mutation == "duplicate":
        value["images"]["frontend"] = value["images"]["backend"]
    elif mutation == "tag":
        value["images"]["backend"] = "backend:latest"
    elif mutation == "boolean_version":
        value["version"] = True
    elif mutation == "extra":
        value["waiver"] = True
    arguments = dict(previous=old, candidate=new, old_sha="a" * 40, new_sha="b" * 40, old_images=old_images)
    if mutation:
        with pytest.raises(ValueError):
            module.validate_approval(value, **arguments)
    else:
        assert module.validate_approval(value, **arguments) is value


@pytest.mark.parametrize("mutation", [None, "failed", "numeric_pass", "role", "scanner", "image", "old", "future", "naive", "db", "missing_report"])
def test_scan_identity_freshness_and_no_waivers(mutation):
    module = helper()
    now = datetime(2026, 10, 4, tzinfo=timezone.utc)
    image = "sha256:" + "3" * 64
    manifest = {"schemaVersion": 1, "scope": "application", "sourceCommit": "b" * 40,
                "role": "backend", "target": image, "imageId": image, "policyPassed": True,
                "policy": "reject-unknown-high-critical-and-eol-no-waivers",
                "scanner": {"name": "Trivy", "version": "0.74.0", "binarySha256": module.SCANNER_SHA},
                "database": {"version": 2, "updatedAt": now.isoformat()}, "createdAt": now.isoformat(),
                "files": {"report.json": "0" * 64, "sbom.cdx.json": "1" * 64}}
    if mutation in {"failed", "numeric_pass"}:
        manifest["policyPassed"] = False if mutation == "failed" else 1
    elif mutation == "role":
        manifest["role"] = "frontend"
    elif mutation == "scanner":
        manifest["scanner"]["binarySha256"] = "0" * 64
    elif mutation == "image":
        manifest["imageId"] = "sha256:" + "4" * 64
    elif mutation in {"old", "future", "naive"}:
        instant = now - timedelta(hours=49) if mutation == "old" else now + timedelta(seconds=1)
        manifest["createdAt"] = instant.isoformat() if mutation != "naive" else now.replace(tzinfo=None).isoformat()
    elif mutation == "db":
        manifest["database"]["version"] = 1
    elif mutation == "missing_report":
        del manifest["files"]["report.json"]
    arguments = dict(commit="b" * 40, role="backend", image_id=image, now=now)
    if mutation:
        with pytest.raises(ValueError):
            module.validate_manifest(manifest, **arguments)
    else:
        module.validate_manifest(manifest, **arguments)


@pytest.mark.parametrize("kind", ["normal", "parent", "absolute", "symlink", "duplicate"])
def test_docker_cp_archive_is_bounded_and_never_extracted(kind):
    module = helper()
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        entry = tarfile.TarInfo({"parent": "../escape", "absolute": "/escape"}.get(kind, "./index.html"))
        entry.size = 3
        if kind == "symlink":
            entry.type, entry.linkname, entry.size = tarfile.SYMTYPE, "/escape", 0
            archive.addfile(entry)
        else:
            archive.addfile(entry, io.BytesIO(b"app"))
            if kind == "duplicate":
                archive.addfile(entry, io.BytesIO(b"app"))
    if kind == "normal":
        assert module.archive_files(stream.getvalue()) == {"index.html": b"app"}
    else:
        with pytest.raises(ValueError):
            module.archive_files(stream.getvalue())


def test_dependency_approval_cannot_unlock_runtime_or_schema(trees):
    module, old, new = trees
    spec = importlib.util.spec_from_file_location("release_guard_test", ROOT / "scripts/basic_pool_application_release.py")
    release = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(release)
    for name in release.APPLICATION_CONTRACTS:
        if name in module.ALLOWED_CHANGES:
            continue
        for root in (old, new):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((ROOT / name).read_bytes())
    release.check_application_contracts(old, new, dependency_approval=approval(module, new))
    with pytest.raises(AssertionError):
        release.check_application_contracts(old, new)
    with pytest.raises(AssertionError):
        release.check_application_contracts(old, new, dependency_approval=approval(module, new), runtime_approval={"candidate": True})
    path = new / "backend/app/core/config.py"
    path.write_bytes(path.read_bytes() + b"# unreviewed\n")
    with pytest.raises(AssertionError):
        release.check_application_contracts(old, new, dependency_approval=approval(module, new))


@pytest.mark.skipif(os.name != "posix", reason="Private operator ownership/modes require POSIX")
@pytest.mark.parametrize("mutation", [None, "tampered", "failed_policy", "source", "world_readable", "symlink", "inventory"])
def test_actual_private_scan_reports_must_substantiate_approval(trees, tmp_path, mutation):
    module, old, new = trees
    prod = tmp_path / "prod"
    deploy = prod / ".deploy"
    evidence = deploy / "scan"
    evidence.mkdir(parents=True, mode=0o700)
    value = approval(module, new)
    value["security_root"] = str(evidence)
    images = {}
    for role, image_id in value["images"].items():
        images[image_id] = {"Id": image_id, "Os": "linux", "Architecture": "amd64", "Config": {"Labels": {
            "io.webcompiler.source-sha": "b" * 40, "io.webcompiler.image-role": role}}}
        folder = evidence / role
        folder.mkdir(mode=0o700)
        packages = [{"Name": "base", "Version": "1", "Identifier": {"PURL": "pkg:apk/alpine/base@1"}}]
        results = [{"Class": "os-pkgs", "Packages": packages, "Vulnerabilities": []}]
        if role == "backend":
            results.append({"Class": "lang-pkgs", "Packages": [
                {"Name": "fastapi", "Version": "0.141.1", "Identifier": {"PURL": "pkg:pypi/fastapi@0.141.1"}}], "Vulnerabilities": []})
        report = {"SchemaVersion": 2, "ArtifactName": image_id, "ArtifactType": "container_image",
                  "Metadata": {"ImageID": image_id, "OS": {"Family": "alpine", "Name": "3.24"},
                               "ImageConfig": {"os": "linux", "architecture": "amd64"}}, "Results": results}
        all_packages = [package for result in results for package in result["Packages"]]
        inventory = {"bomFormat": "CycloneDX", "metadata": {"component": {
            "type": "container", "name": image_id, "properties": [
                {"name": "aquasecurity:trivy:ImageID", "value": image_id}]}}, "components": [
            {"type": "library", "purl": package["Identifier"]["PURL"], "version": package["Version"]}
            for package in all_packages]}
        if role == "backend" and mutation == "inventory":
            inventory["components"].pop()
        if role == "backend" and mutation == "failed_policy":
            results[0]["Vulnerabilities"] = [{"Severity": "HIGH", "VulnerabilityID": "CVE-fixture"}]
        files = {}
        for name, content in (("report.json", report), ("sbom.cdx.json", inventory)):
            path = folder / name
            path.write_text(json.dumps(content))
            path.chmod(0o600)
            files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        now = datetime.now(timezone.utc).isoformat()
        manifest = {"schemaVersion": 1, "scope": "application", "sourceCommit": "b" * 40,
                    "role": role, "target": image_id, "imageId": image_id, "policyPassed": True,
                    "policy": "reject-unknown-high-critical-and-eol-no-waivers",
                    "scanner": {"name": "Trivy", "version": "0.74.0", "binarySha256": module.SCANNER_SHA},
                    "database": {"version": 2, "updatedAt": now}, "createdAt": now, "files": files,
                    "os": report["Metadata"]["OS"], "installedPackageEntries": len(all_packages),
                    "findingEntriesBySeverity": {}, "uniquePackageIdentities": len(all_packages)}
        path = folder / "manifest.json"
        path.write_text(json.dumps(manifest))
        path.chmod(0o600)
    path = deploy / "basic-pool-dependency-approval.json"
    path.write_text(json.dumps(value))
    path.chmod(0o600)
    if mutation == "tampered":
        (evidence / "backend/report.json").write_text("{}")
    elif mutation == "source":
        images[value["images"]["backend"]]["Config"]["Labels"]["io.webcompiler.source-sha"] = "c" * 40
    elif mutation == "world_readable":
        path.chmod(0o644)
    elif mutation == "symlink":
        other = deploy / "other.json"
        path.rename(other)
        path.symlink_to(other)
    arguments = (prod, old, new, "a" * 40, "b" * 40, value["previous_images"], images.__getitem__)
    if mutation:
        with pytest.raises(ValueError):
            module.load_approval(*arguments)
    else:
        assert module.load_approval(*arguments) == value


def _tar(files):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        for name, data in files.items():
            entry = tarfile.TarInfo(name)
            entry.size = len(data)
            archive.addfile(entry, io.BytesIO(data))
    return stream.getvalue()


@pytest.mark.parametrize("mutation", [None, "js", "extra", "marker", "nginx", "stock_changed"])
def test_offline_payload_check_and_container_cleanup(tmp_path, mutation):
    module = helper()
    (tmp_path / "backend/app").mkdir(parents=True)
    (tmp_path / "backend/app/main.py").write_bytes(b"# app\n")
    (tmp_path / "backend/requirements.lock").write_bytes(b"locked\n")
    (tmp_path / "frontend-dist/.well-known").mkdir(parents=True)
    (tmp_path / "frontend-dist/index.html").write_bytes(b"tested-app")
    marker = json.dumps({"deployment_sha": "b" * 40}).encode()
    (tmp_path / "frontend-dist/.well-known/webcompiler-release.json").write_bytes(marker)
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend/nginx.conf").write_bytes(b"server backend:8000 resolve;\n")
    state = {"sha": "b" * 40, "images": {"backend": "backend", "frontend": "frontend"}, "bases": {"frontend": "old"}}
    actual = {"index.html": b"tested-app", ".well-known/webcompiler-release.json": marker}
    if mutation == "js":
        actual["index.html"] = b"different-app"
    elif mutation == "extra":
        actual["unreviewed.js"] = b"evil"
    elif mutation == "marker":
        actual[".well-known/webcompiler-release.json"] = b'{"deployment_sha":"wrong"}'
    elif mutation == "stock_changed":
        actual["50x.html"] = b"changed-stock"
    config = b"server api-proxy:8080 resolve;\n" if mutation != "nginx" else b"unreviewed upstream"
    calls = []

    def run(*args, **kwargs):
        calls.append(args)
        if args[1] == "create":
            return ("2" * 64 if args[-1] == "old" else "1" * 64).encode()
        if args[1] == "cp":
            if "html/." in args[2]:
                return _tar(actual)
            if "50x.html" in args[2]:
                return _tar({"50x.html": b"old-stock"})
            return _tar({"default.conf": config})
        if args[1] == "run" and "-i" in args:
            expected = json.loads(kwargs["data"])
            assert set(expected) == {"app/main.py", "requirements.lock"}
            assert "version('PyJWT')=='2.15.1'" in args[-1]
        return b""

    if mutation:
        with pytest.raises(ValueError):
            module.verify_candidate(state, tmp_path, run)
    else:
        module.verify_candidate(state, tmp_path, run)
        assert any(args[-2:] == ("pip", "check") for args in calls)
        assert any(args[-1] == "-t" for args in calls)
    created = [args for args in calls if args[1] == "create"]
    removed = [args for args in calls if args[1] == "rm"]
    assert len(created) == len(removed)
    for args in calls:
        if args[1] == "run":
            assert args[args.index("--network") + 1] == "none"
            assert "--read-only" in args and "--memory" in args
