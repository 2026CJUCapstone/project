"""Opt-in integration coverage for terminal transport limits in an isolated Redis namespace."""
import hashlib
import os
import uuid

import pytest
from redis import Redis

from app.core.config import settings
from app.services.terminal_broker import TerminalBroker, TerminalClosed, TerminalLimit


pytestmark = pytest.mark.skipif(not os.getenv('TEST_REDIS_URL'), reason='Isolated Redis URL required')


def sid(index: int) -> str:
    return f'{index:032x}'


def delete_prefix(client: Redis, prefix: str) -> None:
    cursor = 0
    while True:
        cursor, keys = client.scan(cursor=cursor, match=f'{prefix}:*', count=200)
        if keys:
            client.delete(*keys)
        if cursor == 0:
            return


@pytest.fixture
def redis_client(monkeypatch):
    client = Redis.from_url(os.environ['TEST_REDIS_URL'], decode_responses=True, socket_timeout=2)
    try:
        client.ping()
    except Exception:
        client.close()
        pytest.fail('Configured isolated Redis is unavailable')

    prefix = f'test-terminal-broker-{uuid.uuid4().hex}'
    monkeypatch.setattr(settings, 'REDIS_KEY_PREFIX', prefix)
    try:
        yield client
    finally:
        delete_prefix(client, prefix)
        client.close()


def test_reserve_applies_global_and_per_ip_limits_across_broker_instances(redis_client, monkeypatch):
    monkeypatch.setattr(settings, 'TERMINAL_MAX_CONNECTIONS', 2)
    monkeypatch.setattr(settings, 'TERMINAL_MAX_CONNECTIONS_PER_IDENTITY', 1)
    first, second = TerminalBroker(redis_client), TerminalBroker(redis_client)

    first.reserve(sid(1), '203.0.113.10')
    with pytest.raises(TerminalLimit):
        second.reserve(sid(2), '203.0.113.10')
    second.reserve(sid(2), '203.0.113.11')
    with pytest.raises(TerminalLimit):
        first.reserve(sid(3), '203.0.113.12')


def test_bind_user_applies_the_identity_limit_across_different_ips(redis_client, monkeypatch):
    monkeypatch.setattr(settings, 'TERMINAL_MAX_CONNECTIONS', 4)
    monkeypatch.setattr(settings, 'TERMINAL_MAX_CONNECTIONS_PER_IDENTITY', 1)
    first, second = TerminalBroker(redis_client), TerminalBroker(redis_client)
    first.reserve(sid(10), '203.0.113.20')
    second.reserve(sid(11), '203.0.113.21')

    first.bind_user(sid(10), 'user-1')
    with pytest.raises(TerminalLimit):
        second.bind_user(sid(11), 'user-1')


def test_renew_and_close_keep_connection_counters_idempotent(redis_client):
    broker = TerminalBroker(redis_client)
    session_id, ip = sid(20), '203.0.113.30'
    broker.reserve(session_id, ip)
    meta, _, _ = broker.keys(session_id)
    global_key = f'{settings.REDIS_KEY_PREFIX}:terminal:connections'
    ip_key = f'{settings.REDIS_KEY_PREFIX}:terminal:ip:{hashlib.sha256(ip.encode()).hexdigest()}'

    assert redis_client.zcard(global_key) == 1
    assert redis_client.zcard(ip_key) == 1
    assert broker.renew(session_id)
    assert redis_client.zcard(global_key) == 1
    assert redis_client.zcard(ip_key) == 1
    broker.close(session_id)
    broker.close(session_id)
    assert redis_client.zcard(global_key) == 0
    assert redis_client.zcard(ip_key) == 0
    assert redis_client.hget(meta, 'state') == 'closed'
    assert not broker.renew(session_id)
    assert not broker.active(session_id)


def test_input_and_output_byte_budgets_use_utf8_and_output_cursor_is_incremental(redis_client, monkeypatch):
    monkeypatch.setattr(settings, 'TERMINAL_INPUT_MAX_BYTES', 5)
    monkeypatch.setattr(settings, 'SANDBOX_OUTPUT_MAX_BYTES', 6)
    broker = TerminalBroker(redis_client)
    session_id = sid(30)
    broker.reserve(session_id, '203.0.113.40')

    broker.send_input(session_id, '가')
    assert broker.take_input(session_id) == '가'
    with pytest.raises(TerminalLimit):
        broker.send_input(session_id, '가')

    broker.publish(session_id, '가')
    broker.publish(session_id, '나')
    with pytest.raises(TerminalLimit):
        broker.publish(session_id, 'a')
    events = broker.read_output(session_id)
    assert [fields['text'] for _, fields in events] == ['가', '나']
    assert broker.read_output(session_id, events[-1][0]) == []


def test_unknown_or_closed_sessions_cannot_be_used_to_resurrect_terminal_state(redis_client):
    broker = TerminalBroker(redis_client)
    unknown = sid(40)
    unknown_meta, _, _ = broker.keys(unknown)

    assert not broker.active(unknown)
    assert not broker.renew(unknown)
    broker.close(unknown)
    with pytest.raises(TerminalClosed):
        broker.send_input(unknown, 'ignored')
    with pytest.raises(TerminalClosed):
        broker.publish(unknown, 'ignored')
    assert broker.read_output(unknown) == []
    assert not redis_client.exists(unknown_meta)

    closed = sid(41)
    broker.reserve(closed, '203.0.113.50')
    broker.close(closed)
    with pytest.raises(TerminalClosed):
        broker.send_input(closed, 'ignored')
    with pytest.raises(TerminalClosed):
        broker.publish(closed, 'ignored')
    assert not broker.active(closed)
