from unittest.mock import Mock

import pytest
from httpx import ASGITransport, AsyncClient

from app import main
from app.services import runtime_health
from app.services.worker_process import ProcessIdentity


class Connection:
    def __init__(self, marker_present=True):
        self.marker_present = marker_present

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, statement, params):
        assert params["version"] == runtime_health.RUNTIME_SCHEMA_VERSION
        return Mock(first=lambda: (1,) if self.marker_present else None)


class Engine:
    def __init__(self, marker_present=True):
        self.connection = Connection(marker_present)

    def connect(self):
        return self.connection


def worker_identity(*, hostname="worker-local", epoch="a" * 32):
    return ProcessIdentity(
        epoch=epoch,
        pid=1234,
        start_token="test:1234",
        hostname=hostname,
        scope="c" * 64,
    )


def assert_epoch_keys(call, key, identity):
    assert call.args[1:4] == (2, key, key + ":owners")
    assert call.args[4:6] == (identity.hostname+'-'+identity.scope, identity.epoch)


def test_dependencies_ready_requires_schema_redis_and_live_worker(monkeypatch):
    client = Mock()
    client.ping.return_value = True
    client.eval.return_value = 1
    monkeypatch.setattr(runtime_health.settings, "RUNTIME_INSTANCE_ID", "")
    monkeypatch.setattr(runtime_health, "engine", Engine())
    monkeypatch.setattr(runtime_health, "get_redis", lambda: client)

    assert runtime_health.dependencies_ready() is True
    client.eval.assert_called_once()
    assert client.eval.call_args.args[1:4] == (
        2,
        runtime_health.worker_health_key(),
        runtime_health.worker_owners_key(),
    )

    client.eval.reset_mock()
    assert runtime_health.dependencies_ready(require_worker=False) is True
    client.eval.assert_not_called()


@pytest.mark.parametrize("marker_present, ping, eval_error", [
    (False, True, False),
    (True, False, False),
    (True, True, True),
])
def test_dependencies_ready_fails_closed_without_exposing_dependency_errors(monkeypatch, marker_present, ping, eval_error):
    client = Mock()
    client.ping.return_value = ping
    if eval_error:
        client.eval.side_effect = RuntimeError("redis-password=secret")
    monkeypatch.setattr(runtime_health, "engine", Engine(marker_present))
    monkeypatch.setattr(runtime_health, "get_redis", lambda: client)

    assert runtime_health.dependencies_ready() is False


def test_this_worker_ready_checks_the_live_process_epoch_owner(monkeypatch):
    client = Mock()
    client.eval.return_value = 1
    identity = worker_identity()
    monkeypatch.setattr(runtime_health.settings, "RUNTIME_INSTANCE_ID", "")
    monkeypatch.setattr(runtime_health, "get_redis", lambda: client)
    monkeypatch.setattr(runtime_health, "read_live_identity", lambda: identity)

    assert runtime_health.this_worker_ready() is True
    assert_epoch_keys(client.eval.call_args, runtime_health.worker_health_key(), identity)

    client.eval.side_effect = RuntimeError("redis-password=secret")
    assert runtime_health.this_worker_ready() is False


def test_epoch_readiness_heartbeat_and_withdrawal_use_exact_runtime_scope(monkeypatch):
    client = Mock()
    client.ping.return_value = True
    client.eval.return_value = 1
    identity = worker_identity()
    monkeypatch.setattr(runtime_health, "engine", Engine())
    monkeypatch.setattr(runtime_health, "get_redis", lambda: client)
    monkeypatch.setattr(runtime_health, "_process_state", object())
    monkeypatch.setattr(runtime_health, "_owned_identity", lambda: identity)
    monkeypatch.setattr(runtime_health, "read_live_identity", lambda: identity)
    monkeypatch.setattr(runtime_health.settings, "RUNTIME_INSTANCE_ID", "")
    for release in ("a" * 40, "b" * 40, ""):
        monkeypatch.setattr(runtime_health.settings, "DEPLOYMENT_SHA", release)
        keys = set()
        for pool in ("local", "webcompiler-blue", "webcompiler-green"):
            monkeypatch.setattr(runtime_health.settings, "RUNTIME_POOL_ID", pool)
            key = runtime_health.worker_health_key()
            assert key == ":".join((
                runtime_health.settings.REDIS_KEY_PREFIX,
                "health",
                "workers-v2",
                pool,
                release or "unversioned",
                "local",
            ))
            assert runtime_health.worker_owners_key() == key + ":owners"
            keys.add(key)
            assert runtime_health.dependencies_ready()
            assert client.eval.call_args.args[1:4] == (
                2,
                key,
                key + ":owners",
            )

            client.eval.reset_mock()
            runtime_health.report_worker_ready()
            assert_epoch_keys(client.eval.call_args, key, identity)
            assert client.eval.call_args.args[-1] == runtime_health.WORKER_HEALTH_SECONDS

            client.eval.reset_mock()
            assert runtime_health.this_worker_ready()
            assert_epoch_keys(client.eval.call_args, key, identity)

            client.eval.reset_mock()
            runtime_health.withdraw_worker()
            assert_epoch_keys(client.eval.call_args, key, identity)
            assert client.eval.call_args.args[6:] == ("0", runtime_health.WORKER_HEALTH_SECONDS)
        assert len(keys) == 3


@pytest.mark.asyncio
async def test_ready_is_no_store_and_safe_when_unavailable_while_health_stays_live(monkeypatch):
    monkeypatch.setattr(runtime_health, "dependencies_ready", lambda: False)
    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
        unavailable = await client.get("/ready")
        health = await client.get("/health")

    assert unavailable.status_code == 503
    assert unavailable.headers["cache-control"] == "no-store"
    assert unavailable.json() == {"status": "unavailable"}
    assert "secret" not in unavailable.text.lower()
    assert health.status_code == 200
    assert health.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_ready_returns_ok_when_dependencies_are_ready(monkeypatch):
    monkeypatch.setattr(runtime_health, "dependencies_ready", lambda: True)
    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
        response = await client.get("/ready")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"status": "ready"}
