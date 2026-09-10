from collections import defaultdict, deque
from time import monotonic
from threading import Lock
from uuid import uuid4

from fastapi import HTTPException, status

from app.services.redis_client import get_redis, redis_key
from app.core.config import settings

_attempts: dict[str, deque[float]] = defaultdict(deque)
_expirations: dict[str, float] = {}
_lock = Lock()
_next_cleanup = 0.0
_MAX_LOCAL_BUCKETS = 10000


def check_rate_limit(key: str, max_attempts: int, window_seconds: int) -> None:
    global _next_cleanup
    if _check_redis_rate_limit(key, max_attempts, window_seconds):
        return

    now = monotonic()
    cutoff = now - window_seconds

    with _lock:
        if now >= _next_cleanup:
            for old_key in list(_attempts):
                if not _attempts[old_key] or _expirations.get(old_key, 0) <= now:
                    del _attempts[old_key]
                    _expirations.pop(old_key, None)
            _next_cleanup = now + min(window_seconds, 10)
        if key not in _attempts and len(_attempts) >= _MAX_LOCAL_BUCKETS:
            raise HTTPException(
                429,
                "요청이 너무 많습니다. 잠시 후 다시 시도해주세요.",
                headers={"Retry-After": str(window_seconds)},
            )
        bucket = _attempts[key]
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= max_attempts:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="요청이 너무 많습니다. 잠시 후 다시 시도해주세요.",
                headers={"Retry-After": str(window_seconds)},
            )
        bucket.append(now)
        _expirations[key] = now + window_seconds


def _check_redis_rate_limit(key: str, max_attempts: int, window_seconds: int) -> bool:
    client = get_redis()
    if client is None:
        if settings.REDIS_URL or settings.ENVIRONMENT.lower() == "production":
            raise HTTPException(
                503,
                "요청 제한 서비스를 사용할 수 없습니다. 잠시 후 다시 시도해주세요.",
                headers={"Retry-After": "5"},
            )
        return False

    redis_bucket = redis_key("rate_limit", key)
    member = uuid4().hex

    try:
        script = """
local clock = redis.call('TIME')
local now = tonumber(clock[1]) * 1000 + math.floor(tonumber(clock[2]) / 1000)
redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, now - tonumber(ARGV[2]) * 1000)
local count = redis.call('ZCARD', KEYS[1])
if count >= tonumber(ARGV[1]) then
  return 0
end
redis.call('ZADD', KEYS[1], now, ARGV[3])
redis.call('EXPIRE', KEYS[1], ARGV[2])
return 1
"""
        allowed = client.eval(
            script,
            1,
            redis_bucket,
            str(max_attempts),
            str(window_seconds),
            member,
        )
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="요청이 너무 많습니다. 잠시 후 다시 시도해주세요.",
                headers={"Retry-After": str(window_seconds)},
            )
        return True
    except HTTPException:
        raise
    except Exception as exc:
        # Falling back to one local budget per API replica bypasses the shared
        # limit exactly when Redis is unhealthy. Reject admission instead.
        raise HTTPException(
            503,
            "요청 제한 서비스를 사용할 수 없습니다. 잠시 후 다시 시도해주세요.",
            headers={"Retry-After": "5"},
        ) from exc
