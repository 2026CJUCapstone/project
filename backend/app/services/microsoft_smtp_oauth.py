"""Bounded Microsoft consumer OAuth2 support for SMTP AUTH.

The long-lived refresh credential is stored as a versioned opaque value in the
existing private SMTP password field. Access tokens are fetched only when a
mail connection is opened and are never persisted or included in diagnostics.
"""

from __future__ import annotations

import base64
import json
import re
import ssl
from urllib.parse import urlencode
import urllib.request


CREDENTIAL_PREFIX = "ms-oauth2-v1."
TOKEN_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"
SMTP_SCOPE = "https://outlook.office.com/SMTP.Send offline_access"
MAX_RESPONSE_BYTES = 64 * 1024
MAX_REFRESH_TOKEN_BYTES = 16 * 1024


class MicrosoftOAuthError(RuntimeError):
    pass


def _validate(client_id: object, refresh_token: object) -> tuple[str, str]:
    if not isinstance(client_id, str) or re.fullmatch(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
        client_id,
    ) is None:
        raise MicrosoftOAuthError("Microsoft OAuth credential is invalid.")
    if (
        not isinstance(refresh_token, str)
        or not refresh_token
        or len(refresh_token.encode("utf-8")) > MAX_REFRESH_TOKEN_BYTES
        or any(character in refresh_token for character in "\r\n\0")
    ):
        raise MicrosoftOAuthError("Microsoft OAuth credential is invalid.")
    return client_id.lower(), refresh_token


def encode_credential(client_id: str, refresh_token: str) -> str:
    client_id, refresh_token = _validate(client_id, refresh_token)
    raw = json.dumps(
        {"client_id": client_id, "refresh_token": refresh_token},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    return CREDENTIAL_PREFIX + encoded


def is_credential(value: object) -> bool:
    return isinstance(value, str) and value.startswith(CREDENTIAL_PREFIX)


def decode_credential(value: str) -> tuple[str, str]:
    if not is_credential(value):
        raise MicrosoftOAuthError("Microsoft OAuth credential is invalid.")
    encoded = value[len(CREDENTIAL_PREFIX) :]
    try:
        padding = "=" * (-len(encoded) % 4)
        raw = base64.b64decode(encoded + padding, altchars=b"-_", validate=True)
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError, json.JSONDecodeError) as error:
        raise MicrosoftOAuthError("Microsoft OAuth credential is invalid.") from error
    if not isinstance(payload, dict) or set(payload) != {"client_id", "refresh_token"}:
        raise MicrosoftOAuthError("Microsoft OAuth credential is invalid.")
    return _validate(payload["client_id"], payload["refresh_token"])


def access_token(credential: str) -> str:
    client_id, refresh_token = decode_credential(credential)
    body = urlencode(
        {
            "client_id": client_id,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
            "scope": SMTP_SCOPE,
        }
    ).encode("ascii")
    request = urllib.request.Request(
        TOKEN_URL,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ssl.create_default_context())
    )
    try:
        with opener.open(request, timeout=10) as response:
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_RESPONSE_BYTES:
                raise MicrosoftOAuthError("Microsoft OAuth response is invalid.")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except MicrosoftOAuthError:
        raise
    except (OSError, ValueError) as error:
        raise MicrosoftOAuthError("Microsoft OAuth token refresh failed.") from error
    if len(raw) > MAX_RESPONSE_BYTES:
        raise MicrosoftOAuthError("Microsoft OAuth response is invalid.")
    try:
        payload = json.loads(raw.decode("utf-8"))
        token = payload["access_token"]
    except (KeyError, TypeError, ValueError, UnicodeError, json.JSONDecodeError) as error:
        raise MicrosoftOAuthError("Microsoft OAuth response is invalid.") from error
    if (
        not isinstance(payload, dict)
        or payload.get("token_type", "Bearer").lower() != "bearer"
        or not isinstance(token, str)
        or not token
        or len(token.encode("utf-8")) > 32 * 1024
        or any(character in token for character in "\r\n\0\x01")
    ):
        raise MicrosoftOAuthError("Microsoft OAuth response is invalid.")
    return token
