"""Cross-check the browser auth payload contract against backend schemas/routes.

The explicit-null profile test records a current UI/API mismatch: Header sends
``null`` when a profile field is cleared, while the route currently treats
``None`` as an omitted partial-update field. The regression now guards the
root fix distinguishing explicitly cleared values from omitted fields.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.api.routes import auth as auth_routes
from app.models import schemas


ROOT = Path(__file__).resolve().parents[2]


def test_auth_response_aliases_match_frontend_field_names():
    token = schemas.Token(access_token="fixture-token", token_type="bearer")
    assert token.model_dump(by_alias=True) == {
        "accessToken": "fixture-token",
        "tokenType": "bearer",
    }

    user = schemas.UserRead(
        id="user-1",
        username="alice",
        email="alice@example.test",
        nickname="Alice",
        total_score=12,
        rating=3,
        tier="Iron V",
        solved_count=1,
        avatar_url="https://avatar.example.test/a.svg",
        role="user",
    )
    serialized = user.model_dump(by_alias=True)
    assert serialized["totalScore"] == 12
    assert serialized["solvedCount"] == 1
    assert serialized["avatarUrl"] == "https://avatar.example.test/a.svg"

    reset = schemas.PasswordResetResponse(message="fixture", debug_reset_token="token")
    assert reset.model_dump(by_alias=True) == {
        "message": "fixture",
        "debugResetToken": "token",
    }


def test_auth_request_aliases_accept_browser_payloads():
    registration = schemas.UserCreate.model_validate(
        {
            "username": "alice",
            "email": " Alice@Example.TEST ",
            "nickname": "Alice",
            "password": "password-123",
        }
    )
    assert registration.email == "alice@example.test"

    reset_request = schemas.PasswordResetRequest.model_validate(
        {"usernameOrEmail": "alice@example.test"}
    )
    assert reset_request.username_or_email == "alice@example.test"

    reset_confirm = schemas.PasswordResetConfirm.model_validate(
        {"token": "t" * 32, "newPassword": "new-password-123"}
    )
    assert reset_confirm.new_password == "new-password-123"


def test_header_sends_explicit_nulls_when_profile_fields_are_cleared():
    source = (ROOT / "frontend" / "src" / "app" / "components" / "Header.tsx").read_text(
        encoding="utf-8"
    )
    assert "email: profileEmail.trim() || null" in source
    assert "nickname: profileNickname.trim() || null" in source
    assert "avatarUrl: profileAvatar.trim() || null" in source


def test_explicit_null_profile_values_clear_fields_sent_by_header(monkeypatch: pytest.MonkeyPatch):
    payload = schemas.UserProfileUpdate.model_validate(
        {"email": None, "nickname": None, "avatarUrl": None}
    )
    assert payload.model_fields_set == {"email", "nickname", "avatar_url"}

    user = SimpleNamespace(
        id="user-1",
        email="old@example.test",
        nickname="Old name",
        avatar_url="https://avatar.example.test/old.svg",
    )

    class FakeDB:
        def __init__(self):
            self.added = []
            self.commits = 0

        def add(self, value):
            self.added.append(value)

        def commit(self):
            self.commits += 1

        def refresh(self, _value):
            return None

    db = FakeDB()
    monkeypatch.setattr(
        auth_routes,
        "_serialize_user",
        lambda current_user, _db: {
            "email": current_user.email,
            "nickname": current_user.nickname,
            "avatar_url": current_user.avatar_url,
        },
    )

    result = auth_routes.update_profile(payload, db, user)

    assert result == {"email": None, "nickname": None, "avatar_url": None}
    assert user.email is None
    assert user.nickname is None
    assert user.avatar_url is None
    assert db.added == [user]
    assert db.commits == 1
