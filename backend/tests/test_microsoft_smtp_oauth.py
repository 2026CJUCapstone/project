import base64
import json
from types import SimpleNamespace
from urllib.parse import parse_qs

import pytest

from app.services import email as email_service
from app.services import microsoft_smtp_oauth as oauth


CLIENT_ID = "12345678-1234-4234-8234-123456789abc"


def credential(refresh_token="fixture-refresh-token"):
    return oauth.encode_credential(CLIENT_ID, refresh_token)


def settings(password):
    return SimpleNamespace(
        SMTP_HOST="smtp-mail.outlook.com",
        SMTP_PORT=587,
        SMTP_FROM="creeper0809@hotmail.com",
        SMTP_STARTTLS=True,
        SMTP_USERNAME="creeper0809@hotmail.com",
        SMTP_PASSWORD=password,
        PASSWORD_RESET_BASE_URL="https://cuha.cju.ac.kr/webcompiler/reset-password",
        PASSWORD_RESET_TOKEN_EXPIRE_MINUTES=30,
    )


def test_versioned_credential_round_trip_and_strict_shape():
    value = credential()
    assert value.startswith(oauth.CREDENTIAL_PREFIX)
    assert oauth.decode_credential(value) == (CLIENT_ID, "fixture-refresh-token")
    malformed = oauth.CREDENTIAL_PREFIX + base64.urlsafe_b64encode(
        json.dumps({"client_id": CLIENT_ID, "refresh_token": "token", "extra": True}).encode()
    ).decode().rstrip("=")
    with pytest.raises(oauth.MicrosoftOAuthError, match="credential"):
        oauth.decode_credential(malformed)


def test_token_refresh_uses_fixed_microsoft_endpoint_and_bounded_request(monkeypatch):
    calls = []

    class Response:
        headers = {"Content-Length": "60"}
        def __enter__(self): return self
        def __exit__(self, *_args): pass
        def read(self, limit):
            assert limit == oauth.MAX_RESPONSE_BYTES + 1
            return json.dumps({"token_type": "Bearer", "access_token": "access-token"}).encode()

    class Opener:
        def open(self, request, *, timeout):
            calls.append((request, timeout))
            return Response()

    monkeypatch.setattr(oauth.urllib.request, "build_opener", lambda *_handlers: Opener())
    assert oauth.access_token(credential("private-refresh-token")) == "access-token"
    request, timeout = calls[0]
    assert request.full_url == oauth.TOKEN_URL
    assert timeout == 10
    fields = parse_qs(request.data.decode())
    assert fields == {
        "client_id": [CLIENT_ID],
        "refresh_token": ["private-refresh-token"],
        "grant_type": ["refresh_token"],
        "scope": [oauth.SMTP_SCOPE],
    }


def test_refresh_failure_never_includes_refresh_token(monkeypatch):
    class Opener:
        def open(self, *_args, **_kwargs):
            raise OSError("transport details")

    monkeypatch.setattr(oauth.urllib.request, "build_opener", lambda *_handlers: Opener())
    secret = "private-refresh-token-never-log"
    with pytest.raises(oauth.MicrosoftOAuthError) as error:
        oauth.access_token(credential(secret))
    assert secret not in str(error.value)


def test_email_uses_xoauth2_and_cuha_sender_without_password_login(monkeypatch):
    events = []
    messages = []

    class SMTP:
        def __init__(self, host, port, *, timeout):
            assert (host, port, timeout) == ("smtp-mail.outlook.com", 587, 10)
        def __enter__(self): return self
        def __exit__(self, *_args): pass
        def starttls(self, *, context): events.append("tls")
        def login(self, *_args): pytest.fail("OAuth credentials must not use password login")
        def docmd(self, command, argument):
            assert command == "AUTH"
            assert argument.startswith("XOAUTH2 ")
            decoded = base64.b64decode(argument.removeprefix("XOAUTH2 ")).decode()
            assert decoded == (
                "user=creeper0809@hotmail.com\x01auth=Bearer access-token\x01\x01"
            )
            events.append("oauth")
            return 235, b"authenticated"
        def send_message(self, message): messages.append(message)

    monkeypatch.setattr(email_service, "settings", settings(credential()))
    monkeypatch.setattr(email_service.smtplib, "SMTP", SMTP)
    monkeypatch.setattr(email_service.microsoft_smtp_oauth, "access_token", lambda _value: "access-token")
    email_service.send_password_reset_email("recipient@example.test", "token")
    assert events == ["tls", "oauth"]
    assert messages[0]["From"] == "CUHA <creeper0809@hotmail.com>"


def test_rejected_xoauth2_authentication_stops_before_send(monkeypatch):
    class SMTP:
        def __init__(self, *_args, **_kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *_args): pass
        def starttls(self, *, context): pass
        def docmd(self, *_args): return 535, b"authentication rejected"
        def send_message(self, *_args): pytest.fail("Rejected authentication must not send")

    monkeypatch.setattr(email_service, "settings", settings(credential()))
    monkeypatch.setattr(email_service.smtplib, "SMTP", SMTP)
    monkeypatch.setattr(email_service.microsoft_smtp_oauth, "access_token", lambda _value: "access-token")
    with pytest.raises(email_service.smtplib.SMTPAuthenticationError):
        email_service.send_password_reset_email("recipient@example.test", "token")
