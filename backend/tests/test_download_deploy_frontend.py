import hashlib
import importlib.util
import io
import os
from pathlib import Path
import urllib.request
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "download_deploy_frontend", ROOT / "scripts/download_deploy_frontend.py"
)
download = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(download)


def artifact_zip(data: bytes, name: str = "frontend-deploy.tar.gz") -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(name, data)
    return output.getvalue()


def test_extracts_exact_named_member_and_checks_digest():
    data = b"verified frontend tar fixture"
    digest = hashlib.sha256(data).hexdigest()
    assert download._extract_archive(artifact_zip(data), digest) == data


@pytest.mark.parametrize("name", ["../frontend-deploy.tar.gz", "nested/frontend-deploy.tar.gz", "other.tar.gz"])
def test_rejects_unexpected_artifact_member(name):
    data = b"frontend"
    with pytest.raises(download.ArtifactDownloadError, match="contents"):
        download._extract_archive(artifact_zip(data, name), hashlib.sha256(data).hexdigest())


def test_rejects_digest_mismatch():
    with pytest.raises(download.ArtifactDownloadError, match="digest"):
        download._extract_archive(artifact_zip(b"frontend"), "0" * 64)


def test_redirect_drops_authorization_and_requires_https():
    handler = download._SafeRedirect()
    request = urllib.request.Request(
        "https://api.github.com/example",
        headers={"Authorization": "Bearer secret-test-token"},
    )
    redirected = handler.redirect_request(
        request, None, 302, "Found", {}, "https://artifact.example.invalid/archive.zip"
    )
    assert redirected.get_header("Authorization") is None
    assert redirected.full_url == "https://artifact.example.invalid/archive.zip"
    with pytest.raises(download.ArtifactDownloadError, match="Unsafe artifact redirect"):
        handler.redirect_request(request, None, 302, "Found", {}, "http://example.invalid/archive.zip")


def test_environment_download_writes_private_verified_archive(tmp_path, monkeypatch):
    data = b"frontend archive"
    zipped = artifact_zip(data)
    monkeypatch.setattr(download, "_download", lambda repository, artifact_id, token: zipped)
    output = tmp_path / "frontend.tar.gz"
    environment = {
        "GITHUB_TOKEN": "test-token",
        "DEPLOY_REPO": "https://github.com/test/project.git",
        "DEPLOY_FRONTEND_ARTIFACT_ID": "123",
        "DEPLOY_FRONTEND_SHA256": hashlib.sha256(data).hexdigest(),
        "WEBCOMPILER_FRONTEND_ARCHIVE": str(output),
    }
    download.download_from_environment(environment)
    assert output.read_bytes() == data
    if os.name != "nt":
        assert output.stat().st_mode & 0o777 == 0o600


def test_missing_token_fails_without_calling_network(monkeypatch, tmp_path):
    monkeypatch.setattr(
        download,
        "_download",
        lambda *args: pytest.fail("Network must not be called"),
    )
    with pytest.raises(download.ArtifactDownloadError, match="credential"):
        download.download_from_environment({
            "WEBCOMPILER_FRONTEND_ARCHIVE": str(tmp_path / "frontend.tar.gz")
        })
