from __future__ import annotations

import json
import logging
from time import monotonic
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

try:
    import redis
    from redis import Redis
except Exception:  # pragma: no cover - optional dependency fallback
    redis = None
    Redis = Any  # type: ignore[assignment]


_client: Redis | None = None
_next_retry_at = 0.0
_RETRY_INTERVAL_SECONDS = 5.0


def get_redis() -> Redis | None:
    global _client, _next_retry_at
    if _client is not None:
        return _client

    now = monotonic()
    if now < _next_retry_at:
        return None

    if not settings.REDIS_URL or redis is None:
        _next_retry_at = now + _RETRY_INTERVAL_SECONDS
        return None

    try:
        client = redis.Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=1.0,
            socket_timeout=2.0,
            health_check_interval=30,
        )
        client.ping()
    except Exception as exc:
        logger.warning("Redis is unavailable; falling back to local mode: %s", exc)
        _client = None
        _next_retry_at = now + _RETRY_INTERVAL_SECONDS
        return None

    _client = client
    _next_retry_at = 0.0
    return _client


def redis_key(*parts: str) -> str:
    return ":".join([settings.REDIS_KEY_PREFIX, *parts])


def cache_get_json(key: str) -> Any | None:
    client = get_redis()
    if client is None:
        return None
    try:
        value = client.get(key)
        return json.loads(value) if value else None
    except Exception:
        return None


def cache_set_json(key: str, value: Any, ttl_seconds: int | None = None) -> None:
    client = get_redis()
    if client is None:
        return
    ttl = ttl_seconds or settings.REDIS_CACHE_TTL_SECONDS
    try:
        client.setex(key, ttl, json.dumps(value, separators=(",", ":")))
    except Exception:
        return


def cache_delete_pattern(pattern: str) -> None:
    client = get_redis()
    if client is None:
        return
    try:
        cursor = 0
        while True:
            cursor, keys = client.scan(cursor=cursor, match=pattern, count=200)
            if keys:
                client.delete(*keys)
            if cursor == 0:
                break
    except Exception:
        return
