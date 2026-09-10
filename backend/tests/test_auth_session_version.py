"""Session revocation and reset single-use regression tests (isolated DB only)."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
import uuid

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from app.api.routes import auth as routes
from app.core.database import SessionLocal
from app.main import app
from app.models import database as m, schemas
from app.services import auth


@pytest.fixture
def reset_account():
    suffix = uuid.uuid4().hex
    token = f"reset-{suffix}"
    with SessionLocal() as db:
        user = m.User(username=f"revoke_{suffix}", email=f"{suffix}@example.test",
                      hashed_password=auth.get_password_hash("before-reset-password"))
        db.add(user)
        db.flush()
        db.add(m.PasswordResetToken(user_id=user.id, token_hash=routes._hash_reset_token(token),
                                    expires_at=routes._utc_now() + timedelta(minutes=30)))
        db.commit()
        account = (user.id, user.username, token)
    yield account
    with SessionLocal() as db:
        db.query(m.PasswordResetToken).filter_by(user_id=account[0]).delete()
        db.query(m.User).filter_by(id=account[0]).delete()
        db.commit()


@pytest.mark.asyncio
async def test_reset_revokes_existing_token_and_new_login_works(reset_account):
    _, username, token = reset_account
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://isolated") as client:
        login = await client.post('/api/v1/auth/login', json={"username":username,"password":"before-reset-password"})
        old_headers = {"Authorization": f"Bearer {login.json()['accessToken']}"}
        assert (await client.get('/api/v1/auth/me', headers=old_headers)).status_code == 200
        reset = await client.post('/api/v1/auth/password-reset/confirm', json={"token":token,"newPassword":"after-reset-password"})
        assert reset.status_code == 200
        assert (await client.get('/api/v1/auth/me', headers=old_headers)).status_code == 401
        # Optional authentication must not preserve the revoked identity either.
        with SessionLocal() as db:
            assert routes.get_optional_current_user(old_headers['Authorization'][7:], db) is None
        new_login = await client.post('/api/v1/auth/login', json={"username":username,"password":"after-reset-password"})
        assert new_login.status_code == 200
        new_headers = {"Authorization": f"Bearer {new_login.json()['accessToken']}"}
        assert (await client.get('/api/v1/auth/me', headers=new_headers)).status_code == 200


def test_reset_expiration_boundary_is_rejected(reset_account, monkeypatch):
    uid, _, token = reset_account
    at = routes._utc_now()
    with SessionLocal() as db:
        db.query(m.PasswordResetToken).filter_by(user_id=uid).update({"expires_at":at})
        db.commit()
    monkeypatch.setattr(routes, '_utc_now', lambda: at)
    with SessionLocal() as db, pytest.raises(HTTPException) as exc:
        routes.confirm_password_reset(schemas.PasswordResetConfirm(token=token,new_password="after-reset-password"), db)
    assert exc.value.status_code == 400


def test_two_reset_confirmations_only_one_can_change_password(reset_account, monkeypatch):
    uid, _, token = reset_account
    barrier = Barrier(2)
    real_hash = auth.get_password_hash
    def synchronized_hash(password):
        result = real_hash(password)
        barrier.wait(timeout=10)
        return result
    monkeypatch.setattr(auth, 'get_password_hash', synchronized_hash)
    def confirm(password):
        with SessionLocal() as db:
            try:
                routes.confirm_password_reset(schemas.PasswordResetConfirm(token=token,new_password=password), db)
                return (200,password)
            except HTTPException as exc:
                return (exc.status_code,password)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(confirm,['concurrent-password-a','concurrent-password-b']))
    assert sorted(status for status,_ in results) == [200,400]
    winning_password = next(password for status,password in results if status == 200)
    with SessionLocal() as db:
        user = db.get(m.User,uid)
        assert auth.verify_password(winning_password,user.hashed_password)
        assert user.auth_version == 1
