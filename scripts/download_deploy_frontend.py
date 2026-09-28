#!/usr/bin/env python3
"""Download one verified GitHub Actions frontend artifact without leaking auth."""

from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import urllib.parse
import urllib.request
import zipfile


MAX_DOWNLOAD_BYTES = 40 * 1024 * 1024
MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
USER_AGENT = "webcompiler-deploy-artifact/1"


class ArtifactDownloadError(RuntimeError):
    pass


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    """Follow HTTPS redirects while dropping every credential header."""

    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        parsed = urllib.parse.urlsplit(new_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ArtifactDownloadError("Unsafe artifact redirect")
        if parsed.port not in (None, 443):
            raise ArtifactDownloadError("Unsafe artifact redirect port")
        return urllib.request.Request(
            new_url,
            headers={"Accept": "application/octet-stream", "User-Agent": USER_AGENT},
            method="GET",
        )


def _repository_slug(repository_url: str) -> str:
    match = re.fullmatch(
        r"https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)\.git",
        repository_url,
    )
    if not match:
        raise ArtifactDownloadError("Invalid deployment repository URL")
    return f"{match.group(1)}/{match.group(2)}"


def _download(repository_url: str, artifact_id: str, token: str) -> bytes:
    if not re.fullmatch(r"[1-9][0-9]{0,19}", artifact_id):
        raise ArtifactDownloadError("Invalid frontend artifact ID")
    slug = _repository_slug(repository_url)
    request = urllib.request.Request(
        f"https://api.github.com/repos/{slug}/actions/artifacts/{artifact_id}/zip",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="GET",
    )
    opener = urllib.request.build_opener(_SafeRedirect())
    try:
        with opener.open(request, timeout=30) as response:
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_DOWNLOAD_BYTES:
                raise ArtifactDownloadError("Frontend artifact download is too large")
            data = response.read(MAX_DOWNLOAD_BYTES + 1)
    except ArtifactDownloadError:
        raise
    except (OSError, ValueError) as exc:
        raise ArtifactDownloadError("Frontend artifact download failed") from exc
    if len(data) > MAX_DOWNLOAD_BYTES:
        raise ArtifactDownloadError("Frontend artifact download is too large")
    return data


def _extract_archive(artifact_zip: bytes, expected_sha256: str) -> bytes:
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ArtifactDownloadError("Invalid frontend archive SHA-256")
    try:
        with zipfile.ZipFile(io.BytesIO(artifact_zip)) as archive:
            files = [entry for entry in archive.infolist() if not entry.is_dir()]
            if len(files) != 1 or files[0].filename != "frontend-deploy.tar.gz":
                raise ArtifactDownloadError("Unexpected frontend artifact contents")
            entry = files[0]
            mode = (entry.external_attr >> 16) & 0o170000
            if mode == stat.S_IFLNK or entry.file_size > MAX_ARCHIVE_BYTES:
                raise ArtifactDownloadError("Unsafe frontend artifact member")
            data = archive.read(entry)
    except ArtifactDownloadError:
        raise
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        raise ArtifactDownloadError("Invalid frontend artifact archive") from exc
    if len(data) > MAX_ARCHIVE_BYTES:
        raise ArtifactDownloadError("Frontend archive is too large")
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise ArtifactDownloadError("Frontend archive digest mismatch")
    return data


def _atomic_write(output_path: str, data: bytes) -> None:
    output = Path(output_path)
    if not output.is_absolute() or output.parent.resolve(strict=True) != output.parent:
        raise ArtifactDownloadError("Invalid frontend artifact output path")
    if output.is_symlink() or (output.exists() and not output.is_file()):
        raise ArtifactDownloadError("Unsafe frontend artifact output")
    temporary = output.with_name(output.name + ".part." + secrets.token_hex(8))
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
        output.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)


def download_from_environment(environment: dict[str, str]) -> None:
    token = environment.get("GITHUB_TOKEN", "")
    if not token or len(token) > 4096 or any(character in token for character in "\r\n\0"):
        raise ArtifactDownloadError("GitHub artifact credential is unavailable")
    artifact_zip = _download(
        environment.get("DEPLOY_REPO", ""),
        environment.get("DEPLOY_FRONTEND_ARTIFACT_ID", ""),
        token,
    )
    archive = _extract_archive(
        artifact_zip,
        environment.get("DEPLOY_FRONTEND_SHA256", ""),
    )
    _atomic_write(environment.get("WEBCOMPILER_FRONTEND_ARCHIVE", ""), archive)


def main() -> int:
    try:
        download_from_environment(dict(os.environ))
    except ArtifactDownloadError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
