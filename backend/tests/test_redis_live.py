"""Only the explicitly configured isolated audit Redis is used."""
import multiprocessing
import os
import time
import uuid

import pytest
from fastapi import HTTPException
from redis import Redis

from app.core import rate_limit
from app.services.redis_client import redis_key

pytestmark = pytest.mark.skipif(not os.getenv('TEST_REDIS_URL'), reason='Isolated Redis URL required')


def consume(url, key, gate, output):
    client = Redis.from_url(url, decode_responses=True, socket_timeout=1, socket_connect_timeout=1)
    rate_limit.get_redis = lambda: client
    gate.wait(timeout=10)
    statuses = []
    for _ in range(6):
        try:
            rate_limit.check_rate_limit(key, 3, 30)
            statuses.append(200)
        except HTTPException as error:
            statuses.append(error.status_code)
    output.put(statuses)
    client.close()


def test_shared_limit_across_two_actual_processes():
    url = os.environ['TEST_REDIS_URL']
    key = f'audit:{uuid.uuid4().hex}'
    context = multiprocessing.get_context('spawn')
    gate, output = context.Barrier(2), context.Queue()
    processes = [context.Process(target=consume, args=(url, key, gate, output)) for _ in range(2)]
    try:
        for process in processes:
            process.start()
        statuses = output.get(timeout=20) + output.get(timeout=20)
        for process in processes:
            process.join(timeout=5)
            assert process.exitcode == 0
        assert statuses.count(200) == 3
        assert statuses.count(429) == 9
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        with Redis.from_url(url) as client:
            client.delete(redis_key('rate_limit', key))


def test_real_redis_expiration_allows_new_request(monkeypatch):
    client = Redis.from_url(os.environ['TEST_REDIS_URL'], decode_responses=True)
    monkeypatch.setattr(rate_limit, 'get_redis', lambda: client)
    key = f'audit:{uuid.uuid4().hex}'
    try:
        rate_limit.check_rate_limit(key, 1, 1)
        with pytest.raises(HTTPException) as error:
            rate_limit.check_rate_limit(key, 1, 1)
        assert error.value.status_code == 429
        time.sleep(1.05)
        rate_limit.check_rate_limit(key, 1, 1)
    finally:
        client.delete(redis_key('rate_limit', key))
        client.close()
