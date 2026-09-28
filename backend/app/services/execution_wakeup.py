"""Best-effort work hints, never job storage, admission or lease authority.

One expiring byte wakes one idle worker after a committed IDE receipt. A lost,
duplicate, stale or wrong-pool hint only causes an ordinary database claim.
Periodic polling is retained for other producers, restarts and Redis outages.
Separate short-timeout clients do not alter the shared admission Redis policy.
"""
import asyncio
from functools import lru_cache
import time

from app.core.config import settings

try:
    import redis
    from redis.backoff import NoBackoff
    from redis.retry import Retry
except ImportError:  # Redis is optional in local single-process configurations.
    redis = None


_PUBLISH = """
redis.call('LPUSH', KEYS[1], '1')
redis.call('LTRIM', KEYS[1], 0, 0)
redis.call('EXPIRE', KEYS[1], 1)
return 1
"""


@lru_cache(maxsize=2)
def _client(url, blocking):
    return redis.Redis.from_url(
        url, socket_connect_timeout=0.05,
        socket_timeout=0.30 if blocking else 0.05,
        max_connections=8, retry=Retry(NoBackoff(), 0),
    )


def _configured_client(blocking):
    if redis is None or not settings.REDIS_URL:
        return None
    return _client(settings.REDIS_URL, blocking)


def _key():
    return settings.REDIS_KEY_PREFIX + ':execution:wakeup'


def notify_execution_work():
    """Call only after commit; failure cannot turn an accepted job into error."""
    try:
        client = _configured_client(False)
        if client is not None:
            client.eval(_PUBLISH, 1, _key())
    except Exception:
        # Never log connection strings/credentials or modify admission policy.
        pass


async def wait_for_execution_work():
    started = time.monotonic()
    try:
        client = _configured_client(True)
        if client is not None:
            hint = await asyncio.wait_for(
                asyncio.to_thread(client.blpop, _key(), timeout=0.20), timeout=0.30,
            )
            if hint is not None:
                return
    except Exception:
        pass
    # Preserve the existing polling cadence, also when Redis fails immediately.
    await asyncio.sleep(max(0, 0.25 - (time.monotonic() - started)))
