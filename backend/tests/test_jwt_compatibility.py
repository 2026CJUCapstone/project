"""Library-independent HS256 compatibility and token rejection regressions."""
import base64
import hashlib
import hmac
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app.api.routes.auth import get_current_user
from app.core.config import settings


SECRET = 'jwt-compatibility-test-secret-at-least-32-bytes'


def token(payload, *, key=SECRET, algorithm='HS256'):
    def encode(value):
        return base64.urlsafe_b64encode(json.dumps(value, separators=(',', ':')).encode()).rstrip(b'=')
    signing_input = encode({'alg':algorithm, 'typ':'JWT'}) + b'.' + encode(payload)
    signature = hmac.new(key.encode(), signing_input, hashlib.sha256).digest()
    return (signing_input + b'.' + base64.urlsafe_b64encode(signature).rstrip(b'=')).decode()


@pytest.fixture
def account(monkeypatch):
    monkeypatch.setattr(settings, 'SECRET_KEY', SECRET)
    user = SimpleNamespace(username='legacy-user', auth_version=0)
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = user
    return user, db


def test_existing_standard_hs256_token_without_version_remains_valid(account):
    user, db = account
    old = token({'sub':'legacy-user', 'exp':4102444800})
    assert get_current_user(old, db) is user
    user.auth_version = 1
    with pytest.raises(HTTPException) as failure:
        get_current_user(old, db)
    assert failure.value.status_code == 401


@pytest.mark.parametrize('payload,key,algorithm', [
    ({'sub':'legacy-user','exp':4102444800}, 'attacker-key', 'HS256'),
    ({'sub':'legacy-user','exp':4102444800}, SECRET, 'none'),
    ({'sub':'legacy-user'}, SECRET, 'HS256'),
    ({'exp':4102444800}, SECRET, 'HS256'),
    ({'sub':'legacy-user','exp':1}, SECRET, 'HS256'),
    ({'sub':123,'exp':4102444800}, SECRET, 'HS256'),
    ({'sub':'legacy-user','exp':4102444800, 'ver':True}, SECRET, 'HS256'),
])
def test_invalid_tokens_are_401_not_authenticated_or_500(account, payload, key, algorithm):
    _, db = account
    with pytest.raises(HTTPException) as failure:
        get_current_user(token(payload, key=key, algorithm=algorithm), db)
    assert failure.value.status_code == 401
