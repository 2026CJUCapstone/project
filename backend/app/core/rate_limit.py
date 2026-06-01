from collections import defaultdict, deque
from time import monotonic
from threading import Lock

from fastapi import HTTPException, status

_attempts: dict[str, deque[float]] = defaultdict(deque)
_lock = Lock()


def check_rate_limit(key: str, max_attempts: int, window_seconds: int) -> None:
    now = monotonic()
    cutoff = now - window_seconds

    with _lock:
        bucket = _attempts[key]
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= max_attempts:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="요청이 너무 많습니다. 잠시 후 다시 시도해주세요.",
            )
        bucket.append(now)
