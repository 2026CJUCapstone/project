import base64
import importlib.util
import os
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "authorize_microsoft_smtp", ROOT / "scripts/authorize_microsoft_smtp.py"
)
authorize = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(authorize)

CLIENT_ID = "12345678-1234-4234-8234-123456789abc"


def test_device_flow_prints_only_user_code_and_returns_opaque_credential(monkeypatch):
    responses = iter(
        [
            {
                "device_code": "private-device-code",
                "user_code": "ABCD-EFGH",
                "verification_uri": "https://microsoft.com/devicelogin",
                "expires_in": 900,
                "interval": 1,
            },
            {"error": "authorization_pending"},
            {"refresh_token": "private-refresh-token", "access_token": "private-access-token"},
        ]
    )
    calls = []
    monkeypatch.setattr(
        authorize,
        "_post",
        lambda url, fields, **kwargs: calls.append((url, fields, kwargs)) or next(responses),
    )
    output = []
    credential, token = authorize.authorize(
        CLIENT_ID, output=output.append, sleeper=lambda _seconds: None
    )
    rendered = "\n".join(output)
    assert "ABCD-EFGH" in rendered
    assert "private-device-code" not in rendered
    assert "private-refresh-token" not in rendered
    assert "private-access-token" not in rendered
    assert credential.startswith("ms-oauth2-v1.")
    assert token == "private-access-token"
    assert calls[0][0] == authorize.DEVICE_URL
    assert calls[-1][0] == authorize.TOKEN_URL


def test_device_flow_rejects_untrusted_verification_uri(monkeypatch):
    monkeypatch.setattr(
        authorize,
        "_post",
        lambda *_args, **_kwargs: {
            "device_code": "private-device-code",
            "user_code": "ABCD-EFGH",
            "verification_uri": "https://attacker.example/devicelogin",
            "expires_in": 900,
        },
    )
    with pytest.raises(authorize.AuthorizationError, match="device authorization"):
        authorize.authorize(CLIENT_ID, output=lambda _line: None, sleeper=lambda _seconds: None)


def test_real_smtp_probe_uses_tls_xoauth2_and_noop(monkeypatch):
    events = []

    class SMTP:
        def __init__(self, host, port, *, timeout):
            assert (host, port, timeout) == (authorize.SMTP_HOST, authorize.SMTP_PORT, 15)
        def __enter__(self): return self
        def __exit__(self, *_args): events.append("close")
        def starttls(self, *, context): events.append("tls")
        def docmd(self, command, argument):
            assert command == "AUTH"
            decoded = base64.b64decode(argument.removeprefix("XOAUTH2 ")).decode()
            assert decoded == (
                "user=creeper0809@hotmail.com\x01auth=Bearer private-access-token\x01\x01"
            )
            events.append("oauth")
            return 235, b"ok"
        def noop(self): events.append("noop"); return 250, b"ok"

    monkeypatch.setattr(authorize.smtplib, "SMTP", SMTP)
    authorize.verify_mailbox("creeper0809@hotmail.com", "private-access-token")
    assert events == ["tls", "oauth", "noop", "close"]


def test_smtp_rejection_is_fixed_and_does_not_expose_token(monkeypatch):
    class SMTP:
        def __init__(self, *_args, **_kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *_args): pass
        def starttls(self, *, context): pass
        def docmd(self, *_args): return 535, b"rejected"

    monkeypatch.setattr(authorize.smtplib, "SMTP", SMTP)
    token = "private-access-token-never-log"
    with pytest.raises(authorize.AuthorizationError) as error:
        authorize.verify_mailbox("creeper0809@hotmail.com", token)
    assert token not in str(error.value)


@pytest.mark.skipif(os.name != "posix", reason="Production secret update requires POSIX locks")
def test_verified_credential_is_atomically_merged_into_private_runtime_file(tmp_path):
    deploy = tmp_path / ".deploy"
    deploy.mkdir()
    secret_file = deploy / "runtime-secrets.env"
    secret_file.write_text(
        "WEBCOMPILER_SECRET_KEY=preserve-existing-secret\n"
        "WEBCOMPILER_ADMIN_PASSWORD=preserve-existing-admin\n",
        encoding="utf-8",
    )
    secret_file.chmod(0o600)
    credential = authorize.encode_credential(CLIENT_ID, "private-refresh-token")

    authorize.update_secret_file(secret_file, "creeper0809@hotmail.com", credential)

    runtime = authorize._runtime_secrets()
    values = runtime.load(secret_file)
    assert values["WEBCOMPILER_SECRET_KEY"] == "preserve-existing-secret"
    assert values["WEBCOMPILER_ADMIN_PASSWORD"] == "preserve-existing-admin"
    assert values["SMTP_HOST"] == authorize.SMTP_HOST
    assert values["SMTP_USERNAME"] == values["SMTP_FROM"] == "creeper0809@hotmail.com"
    assert values["SMTP_PASSWORD"] == credential
    assert values["PASSWORD_RESET_BASE_URL"] == authorize.RESET_URL
    assert secret_file.stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(os.name != "posix", reason="Production secret update requires POSIX locks")
def test_active_deployment_lock_blocks_secret_replacement(tmp_path):
    import fcntl

    deploy = tmp_path / ".deploy"
    deploy.mkdir()
    secret_file = deploy / "runtime-secrets.env"
    secret_file.write_text("WEBCOMPILER_SECRET_KEY=preserve\n", encoding="utf-8")
    secret_file.chmod(0o600)
    lock = deploy / "deploy.lock"
    with lock.open("w") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(authorize.AuthorizationError, match="Another deployment"):
            authorize.update_secret_file(
                secret_file,
                "creeper0809@hotmail.com",
                authorize.encode_credential(CLIENT_ID, "private-refresh-token"),
            )
