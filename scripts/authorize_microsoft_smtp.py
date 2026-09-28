#!/usr/bin/env python3
"""Authorize one Outlook.com mailbox and update the private mail credential.

The refresh/access tokens are never printed. The runtime secret file is only
replaced after Microsoft consent and a real STARTTLS + XOAUTH2 + NOOP probe all
succeed for the requested mailbox.
"""

from __future__ import annotations

import argparse
import base64
from email.utils import parseaddr
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import smtplib
import ssl
import sys
import time
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
from app.services.microsoft_smtp_oauth import (  # noqa: E402
    MAX_RESPONSE_BYTES,
    SMTP_SCOPE,
    TOKEN_URL,
    encode_credential,
)

DEVICE_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/devicecode"
SMTP_HOST = "smtp-mail.outlook.com"
SMTP_PORT = 587
RESET_URL = "https://cuha.cju.ac.kr/webcompiler/reset-password"


class AuthorizationError(RuntimeError):
    pass


def _runtime_secrets():
    path = Path(__file__).with_name("runtime_secrets.py")
    spec = importlib.util.spec_from_file_location("authorize_runtime_secrets", path)
    if spec is None or spec.loader is None:
        raise AuthorizationError("Runtime secret helper is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _post(url: str, fields: dict[str, str], *, allow_error: bool = False) -> dict:
    request = urllib.request.Request(
        url,
        data=urlencode(fields).encode("ascii"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ssl.create_default_context())
    )
    try:
        response = opener.open(request, timeout=15)
    except HTTPError as error:
        if not allow_error:
            raise AuthorizationError("Microsoft authorization request failed") from error
        response = error
    except OSError as error:
        raise AuthorizationError("Microsoft authorization request failed") from error
    try:
        with response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError
        return value
    except (ValueError, UnicodeError, json.JSONDecodeError) as error:
        raise AuthorizationError("Microsoft authorization response is invalid") from error


def authorize(client_id: str, *, output=print, sleeper=time.sleep) -> tuple[str, str]:
    if re.fullmatch(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
        client_id,
    ) is None:
        raise AuthorizationError("Microsoft application client ID is invalid")
    device = _post(DEVICE_URL, {"client_id": client_id, "scope": SMTP_SCOPE})
    try:
        device_code = device["device_code"]
        user_code = device["user_code"]
        verification_uri = device["verification_uri"]
        expires_in = int(device["expires_in"])
        interval = max(1, int(device.get("interval", 5)))
    except (KeyError, TypeError, ValueError) as error:
        raise AuthorizationError("Microsoft device authorization response is invalid") from error
    parsed = urlsplit(verification_uri)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"microsoft.com", "www.microsoft.com", "aka.ms"}
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or not isinstance(device_code, str)
        or not device_code
        or not isinstance(user_code, str)
        or not re.fullmatch(r"[A-Z0-9-]{4,32}", user_code)
        or not 60 <= expires_in <= 1800
    ):
        raise AuthorizationError("Microsoft device authorization response is invalid")
    output("Microsoft 로그인 주소: " + verification_uri)
    output("일회용 코드: " + user_code)
    output("로그인 후 이 코드 입력을 완료하세요. 토큰은 화면에 표시되지 않습니다.")
    deadline = time.monotonic() + expires_in
    while time.monotonic() < deadline:
        sleeper(interval)
        token = _post(
            TOKEN_URL,
            {
                "client_id": client_id,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
            allow_error=True,
        )
        error = token.get("error")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval += 5
            continue
        if error:
            raise AuthorizationError("Microsoft account authorization was not completed")
        refresh_token = token.get("refresh_token")
        access_token = token.get("access_token")
        if not isinstance(refresh_token, str) or not isinstance(access_token, str):
            raise AuthorizationError("Microsoft authorization response is missing credentials")
        return encode_credential(client_id, refresh_token), access_token
    raise AuthorizationError("Microsoft account authorization timed out")


def verify_mailbox(account: str, access_token: str) -> None:
    if parseaddr(account)[1] != account or "@" not in account or any(
        character in account for character in "\r\n\0\x01"
    ):
        raise AuthorizationError("SMTP account is invalid")
    if not access_token or any(character in access_token for character in "\r\n\0\x01"):
        raise AuthorizationError("Microsoft access token is invalid")
    payload = base64.b64encode(
        f"user={account}\x01auth=Bearer {access_token}\x01\x01".encode("utf-8")
    ).decode("ascii")
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            code, message = smtp.docmd("AUTH", "XOAUTH2 " + payload)
            if code != 235:
                raise smtplib.SMTPAuthenticationError(code, message)
            code, _message = smtp.noop()
            if code != 250:
                raise smtplib.SMTPResponseException(code, b"SMTP NOOP rejected")
    except (OSError, smtplib.SMTPException) as error:
        raise AuthorizationError("Hotmail SMTP OAuth verification failed") from error


def update_secret_file(path: Path, account: str, credential: str) -> None:
    if os.name != "posix":
        raise AuthorizationError("Production secret update requires POSIX file locking")
    import fcntl

    runtime = _runtime_secrets()
    if path.is_symlink():
        raise AuthorizationError("Runtime secret path is invalid")
    path = path.resolve(strict=True)
    deploy_dir = path.parent
    if path.name != "runtime-secrets.env" or deploy_dir.name != ".deploy":
        raise AuthorizationError("Runtime secret path is invalid")
    lock_path = deploy_dir / "deploy.lock"
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    lock_descriptor = os.open(lock_path, flags, 0o600)
    try:
        fcntl.flock(lock_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            values = runtime.load(path)
        except (runtime.RuntimeSecretsError, OSError) as error:
            raise AuthorizationError("Runtime secret file is invalid") from error
        values.update(
            SMTP_HOST=SMTP_HOST,
            SMTP_PORT=str(SMTP_PORT),
            SMTP_USERNAME=account,
            SMTP_PASSWORD=credential,
            SMTP_FROM=account,
            SMTP_STARTTLS="true",
            PASSWORD_RESET_BASE_URL=RESET_URL,
        )
        try:
            runtime.mail_environment(values, required=True)
        except runtime.RuntimeSecretsError as error:
            raise AuthorizationError("Runtime mail configuration is invalid") from error
        rendered = (runtime.exports(values) + "\n").encode("utf-8")
        with runtime.private_directory(path) as directory:
            before = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
            temporary_name = ".runtime-secrets.env.oauth." + secrets.token_hex(8)
            temporary_descriptor = os.open(
                temporary_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=directory,
            )
            try:
                with os.fdopen(temporary_descriptor, "wb") as output:
                    output.write(rendered)
                    output.flush()
                    os.fsync(output.fileno())
                current = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
                if (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino):
                    raise AuthorizationError("Runtime secret file changed during authorization")
                os.replace(temporary_name, path.name, src_dir_fd=directory, dst_dir_fd=directory)
                os.fsync(directory)
            finally:
                try:
                    os.unlink(temporary_name, dir_fd=directory)
                except FileNotFoundError:
                    pass
    except BlockingIOError as error:
        raise AuthorizationError("Another deployment is running") from error
    finally:
        os.close(lock_descriptor)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--account", required=True)
    parser.add_argument("--file", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        credential, access_token = authorize(arguments.client_id)
        verify_mailbox(arguments.account, access_token)
        update_secret_file(arguments.file, arguments.account, credential)
    except AuthorizationError as error:
        print(str(error), file=sys.stderr)
        return 1
    print("Hotmail OAuth 인증과 SMTP 연결 확인이 완료되었습니다.")
    print("발신자: CUHA <" + arguments.account + ">")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
