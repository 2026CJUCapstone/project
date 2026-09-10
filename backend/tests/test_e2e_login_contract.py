"""The E2E login helper consumes the public CamelModel token contract."""

import importlib.util
from pathlib import Path

import pytest

from app.models.schemas import Token


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "e2e_stack_test.py"
TOKEN_VALUE = "fixture-access-token-must-not-leak"
PASSWORD = "fixture-login-password-must-not-leak"
WIRE_TOKEN = Token(access_token=TOKEN_VALUE, token_type="bearer").model_dump(by_alias=True)


def load_script():
    spec = importlib.util.spec_from_file_location("e2e_login_contract_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_login_accepts_actual_camel_model_wire_shape(monkeypatch):
    script = load_script()
    calls = []

    def post_json(url, payload):
        calls.append((url, payload))
        return 200, WIRE_TOKEN

    monkeypatch.setattr(script, "post_json", post_json)

    assert script.login("fixture-user", PASSWORD) == {
        "Authorization": f"Bearer {TOKEN_VALUE}"
    }
    assert calls == [(
        f"{script.FRONTEND_BASE_URL}/api/v1/auth/login",
        {"username": "fixture-user", "password": PASSWORD},
    )]


@pytest.mark.parametrize(
    ("status", "payload"),
    [
        (201, WIRE_TOKEN),
        (200, {}),
        (200, {"accessToken": "" , "tokenType": "bearer"}),
        (200, {"accessToken": "   ", "tokenType": "bearer"}),
        (200, {"accessToken": None, "tokenType": "bearer"}),
        (200, {"accessToken": TOKEN_VALUE, "tokenType": ""}),
        (200, {"accessToken": TOKEN_VALUE, "tokenType": "Bearer"}),
        (200, {"accessToken": TOKEN_VALUE, "tokenType": "token"}),
        (200, {"access_token": TOKEN_VALUE, "token_type": "bearer"}),
    ],
)
def test_login_rejects_malformed_or_non_success_responses_without_leaking_secrets(
    monkeypatch, status, payload
):
    script = load_script()
    monkeypatch.setattr(script, "post_json", lambda url, body: (status, payload))

    with pytest.raises(RuntimeError) as failure:
        script.login("fixture-user", PASSWORD)

    message = str(failure.value)
    assert TOKEN_VALUE not in message
    assert PASSWORD not in message
