"""Actual isolated Redis + independent SQLite/PostgreSQL scoreboard readers."""
import os
from uuid import uuid4

import pytest
from redis import Redis
from sqlalchemy import event

from app.core.config import settings
from app.models import database as m
from app.services import redis_client, scoreboard_cache
from tests.test_durable_queue import replicas
from tests.test_scoreboard_cache_concurrency import seeded, board, wrong

@pytest.mark.skipif(not os.getenv('TEST_REDIS_URL'), reason='Explicit isolated Redis URL required')
def test_shared_revision_cache_hit_invalidation_ttl_and_corruption_rebuild(seeded, monkeypatch):
    prefix = 'audit-scoreboard-' + uuid4().hex
    client = Redis.from_url(os.environ['TEST_REDIS_URL'], decode_responses=True,
        socket_timeout=2, socket_connect_timeout=1)
    monkeypatch.setattr(settings, 'REDIS_KEY_PREFIX', prefix)
    monkeypatch.setattr(redis_client, '_client', client)
    keys = [scoreboard_cache.cache_key('contest', revision) for revision in (0, 1)]
    assert all(key.startswith(prefix + ':') for key in keys)
    try:
        with seeded[0]() as reader:
            first = board(reader, reader.get(m.Contest, 'contest'))
            assert first['rows'][0]['penaltySeconds'] == 20
        assert client.exists(keys[0])
        assert 0 < client.ttl(keys[0]) <= scoreboard_cache.SCOREBOARD_CACHE_TTL_SECONDS
        cached = client.get(keys[0])
        assert 'private' not in cached and 'username' not in cached
        statements = []
        engine = seeded[1].kw['bind']
        def capture(_connection, _cursor, sql, *_args):
            statements.append(sql.lower())
        event.listen(engine, 'before_cursor_execute', capture)
        try:
            with seeded[1]() as peer:
                assert board(peer, peer.get(m.Contest, 'contest'))['rows'][0]['penaltySeconds'] == 20
        finally:
            event.remove(engine, 'before_cursor_execute', capture)
        assert not any('contest_submissions' in sql for sql in statements)
        with seeded[1]() as writer:
            wrong(writer)
            writer.commit()
        with seeded[0]() as reader:
            assert board(reader, reader.get(m.Contest, 'contest'))['rows'][0]['penaltySeconds'] == 320
        assert client.exists(keys[1])
        client.set(keys[1], '{corrupt fixture json', ex=15)
        with seeded[1]() as reader:
            assert board(reader, reader.get(m.Contest, 'contest'))['rows'][0]['penaltySeconds'] == 320
        assert client.get(keys[1]).startswith('{"rows":')
    finally:
        client.delete(*keys)  # Only this test's two unique-prefix disposable keys.
        client.close()


def test_cache_set_json_uses_redis_set_expiration_option(monkeypatch):
    calls = []

    class FakeRedis:
        def set(self, *args, **kwargs):
            calls.append((args, kwargs))

    monkeypatch.setattr(redis_client, '_client', FakeRedis())
    redis_client.cache_set_json('scoreboard:key', {'rows': []}, ttl_seconds=23)

    assert calls == [(('scoreboard:key', '{"rows":[]}',), {'ex': 23})]
