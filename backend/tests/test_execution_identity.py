from http.cookies import SimpleCookie
from types import SimpleNamespace

from fastapi import Response
from starlette.requests import Request

from app.services.execution_identity import COOKIE, execution_owner, execution_quota
from app.services.durable_queue import DurableQueue, QueueFull
from tests.test_durable_queue import replicas
import pytest


def request(cookie=''):
    return Request({'type':'http', 'client':('192.0.2.1',123), 'headers':[(b'cookie',f'{COOKIE}={cookie}'.encode())]})


def test_anonymous_result_owners_are_distinct_on_same_ip_and_signed():
    response_a, response_b = Response(), Response()
    a = execution_owner(request(), response=response_a)
    b = execution_owner(request(), response=response_b)
    assert a != b
    jar = SimpleCookie(response_a.headers['set-cookie'])
    cookie = jar[COOKIE].value
    assert execution_owner(request(cookie)) == a
    assert execution_owner(request(cookie[:-1] + ('0' if cookie[-1] != '0' else '1'))) is None
    assert 'HttpOnly' in response_a.headers['set-cookie'] and 'SameSite=strict' in response_a.headers['set-cookie']
    assert execution_owner(request(cookie), SimpleNamespace(id='user')) == 'account:user'


def test_rotating_anonymous_session_does_not_expand_ip_pending_capacity(replicas):
    queue = DurableQueue(replicas[0], per_owner=1)
    key = execution_quota(request())
    job_id = queue.enqueue(owner_key='guest:a', quota_key=key, request_id='one', kind='run', payload={'code':'print(1)'})
    with pytest.raises(QueueFull):
        queue.enqueue(owner_key='guest:b', quota_key=key, request_id='two', kind='run', payload={'code':'print(2)'})
    assert queue.read(job_id, owner_key='guest:b') is None
