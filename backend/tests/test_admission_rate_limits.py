from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import Mock
import uuid

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api.routes import auth as routes
from app.core import rate_limit
from app.core.config import settings
from app.core.database import SessionLocal
from app.main import app
from app.models import database as m, schemas


@pytest.fixture(autouse=True)
def isolated_limits(monkeypatch):
    monkeypatch.setattr(rate_limit, '_attempts', defaultdict(deque))
    monkeypatch.setattr(rate_limit, '_expirations', {})
    monkeypatch.setattr(rate_limit, '_next_cleanup', 0)
    monkeypatch.setattr(rate_limit, 'get_redis', lambda: None)
    monkeypatch.setattr(settings, 'REDIS_URL', '')
    monkeypatch.setattr(settings, 'ENVIRONMENT', 'development')


def request(ip='127.0.0.1'):
    return Request({'type':'http', 'client':(ip,1234), 'headers':[]})


def test_rotating_identity_still_hits_ip_budget(monkeypatch):
    monkeypatch.setattr(settings, 'AUTH_IP_RATE_LIMIT_MAX_ATTEMPTS', 2)
    routes._check_auth_rate_limit(request(), 'login', 'a')
    routes._check_auth_rate_limit(request(), 'login', 'b')
    with pytest.raises(HTTPException) as failure:
        routes._check_auth_rate_limit(request(), 'login', 'c')
    assert failure.value.status_code == 429
    assert failure.value.headers == {'Retry-After': str(settings.AUTH_RATE_LIMIT_WINDOW_SECONDS)}


def test_rotating_ip_still_hits_identity_budget(monkeypatch):
    monkeypatch.setattr(settings, 'AUTH_RATE_LIMIT_MAX_ATTEMPTS', 2)
    routes._check_auth_rate_limit(request('ip1'), 'login', 'victim')
    routes._check_auth_rate_limit(request('ip2'), 'login', 'victim')
    with pytest.raises(HTTPException) as failure:
        routes._check_auth_rate_limit(request('ip3'), 'login', 'VICTIM')
    assert failure.value.status_code == 429
    assert failure.value.headers == {'Retry-After': str(settings.AUTH_RATE_LIMIT_WINDOW_SECONDS)}


@pytest.mark.parametrize('mode', ['missing-config', 'disconnected', 'eval-error'])
def test_production_shared_limiter_failure_never_falls_back(monkeypatch, mode):
    monkeypatch.setattr(settings, 'ENVIRONMENT', 'production')
    if mode != 'missing-config':
        monkeypatch.setattr(settings, 'REDIS_URL', 'redis://isolated.invalid')
    if mode == 'eval-error':
        client = Mock()
        client.eval.side_effect = ConnectionError('offline')
        monkeypatch.setattr(rate_limit, 'get_redis', lambda: client)
    with pytest.raises(HTTPException) as failure:
        rate_limit.check_rate_limit('key', 3, 60)
    assert failure.value.status_code == 503
    assert failure.value.headers == {'Retry-After': '5'}
    assert not rate_limit._attempts


def test_redis_rate_limit_rejection_includes_retry_after(monkeypatch):
    client = Mock()
    client.eval.return_value = 0
    monkeypatch.setattr(rate_limit, 'get_redis', lambda: client)

    with pytest.raises(HTTPException) as failure:
        rate_limit.check_rate_limit('key', 3, 45)

    assert failure.value.status_code == 429
    assert failure.value.headers == {'Retry-After': '45'}


def test_local_buckets_are_bounded_and_long_windows_survive_cleanup(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(rate_limit, 'monotonic', lambda: now[0])
    monkeypatch.setattr(rate_limit, '_MAX_LOCAL_BUCKETS', 2)
    rate_limit.check_rate_limit('long', 1, 100)
    rate_limit.check_rate_limit('short', 1, 10)
    with pytest.raises(HTTPException) as full_bucket:
        rate_limit.check_rate_limit('third', 1, 10)
    assert full_bucket.value.headers == {'Retry-After': '10'}
    now[0] = 111
    rate_limit.check_rate_limit('third', 1, 10)
    with pytest.raises(HTTPException) as long_bucket:
        rate_limit.check_rate_limit('long', 1, 100)
    assert long_bucket.value.headers == {'Retry-After': '100'}
    assert len(rate_limit._attempts) == 2


def test_concurrent_duplicate_registration_returns_conflict_not_500(monkeypatch):
    barrier = Barrier(2)
    username = f'concurrent_{uuid.uuid4().hex[:12]}'
    payload = schemas.UserCreate(username=username, email=f'{username}@example.test', password='password1234')

    def hash_password(_password):
        barrier.wait(timeout=5)
        return 'test-hash'

    monkeypatch.setattr(routes.auth, 'get_password_hash', hash_password)

    def register(_):
        with SessionLocal() as db:
            try:
                routes.register(payload, request(), db)
                return 200
            except HTTPException as error:
                return error.status_code

    try:
        with ThreadPoolExecutor(2) as pool:
            assert sorted(pool.map(register, range(2))) == [200, 409]
    finally:
        with SessionLocal() as db:
            assert db.query(m.User).filter_by(username=username).count() == 1
            db.query(m.User).filter_by(username=username).delete()
            db.commit()
