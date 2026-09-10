"""ASGI lifetimes and cancellation across an actual DB admission thread."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.services.api_admission import PendingAdmission, RuntimeAdmissionMiddleware
from tests.test_api_lifecycle import services
from tests.test_durable_queue import replicas


@pytest.fixture(autouse=True)
def managed(monkeypatch):
    monkeypatch.setattr(settings, 'RUNTIME_INSTANCE_ID', 'a'*32)


def scope(service, kind='http', path='/api/test', method='GET'):
    return {'type':kind, 'path':path, 'method':method, 'headers':[],
            'app':SimpleNamespace(state=SimpleNamespace(runtime_requests=service))}


async def receive():
    return {'type':'http.request', 'body':b'', 'more_body':False}


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['http', 'websocket'])
async def test_entire_stream_or_socket_lifetime_survives_fence_but_new_requests_do_not(replicas, kind):
    owner, registry, (a, b) = services(replicas)
    started, release = asyncio.Event(), asyncio.Event()
    messages = []
    async def send(message):
        messages.append(message)
    async def app(current, receive, send):
        if kind == 'http':
            await send({'type':'http.response.start','status':200,'headers':[]})
            await send({'type':'http.response.body','body':b'first','more_body':True})
        else:
            await send({'type':'websocket.accept'})
        started.set()
        await release.wait()
        await send({'type':'http.response.body','body':b'last'} if kind == 'http'
                   else {'type':'websocket.close','code':1000})
    middleware = RuntimeAdmissionMiddleware(app)
    task = asyncio.create_task(middleware(scope(a, kind), receive, send))
    try:
        await asyncio.wait_for(started.wait(), 5)
        field = 'active_http' if kind == 'http' else 'active_websockets'
        assert registry.status(owner)[field] == 1
        await asyncio.to_thread(registry.begin_drain, owner)
        rejected = []
        async def reject_send(message):
            rejected.append(message)
        await middleware(scope(b, kind), receive, reject_send)
        assert rejected[0].get('status', rejected[0].get('code')) == (503 if kind == 'http' else 1013)
        assert registry.status(owner)[field] == 1
        assert not task.done()
    finally:
        release.set()
        await asyncio.wait_for(task, 5)
    assert registry.status(owner)[field] == 0
    assert messages[-1].get('body', messages[-1].get('code')) == (b'last' if kind == 'http' else 1000)


@pytest.mark.parametrize('abandon_first', [False, True])
def test_cancel_racing_commit_releases_only_own_record(replicas, abandon_first):
    owner, registry, (a, b) = services(replicas)
    other = b.begin('http')
    committed, release = Event(), Event()
    def delayed_begin(kind):
        result = a.begin(kind)
        committed.set()
        assert release.wait(5)
        return result
    pending = PendingAdmission(SimpleNamespace(begin=delayed_begin, finish=a.finish), 'websocket')
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(pending.start)
        try:
            assert committed.wait(5)
            assert registry.status(owner)['active_websockets'] == 1
            if abandon_first:
                pending.abandon()
        finally:
            release.set()
        future.result(timeout=5)
        if not abandon_first:
            pending.abandon()
    pending.abandon()  # Duplicate cleanup is harmless.
    assert registry.status(owner)['active_websockets'] == 0
    assert registry.status(owner)['active_http'] == 1
    assert b.finish(other)


@pytest.mark.asyncio
async def test_task_cancellation_during_admission_is_cleaned_after_thread_returns(replicas):
    owner, registry, (a, _) = services(replicas)
    committed, release, finished = Event(), Event(), Event()
    called = []
    def begin(kind):
        result = a.begin(kind)
        committed.set()
        assert release.wait(5)
        return result
    def finish(request_id):
        try:
            return a.finish(request_id)
        finally:
            finished.set()
    async def app(*args):
        called.append(True)
    task = asyncio.create_task(RuntimeAdmissionMiddleware(app)(
        scope(SimpleNamespace(begin=begin, finish=finish)), receive, app))
    try:
        assert await asyncio.to_thread(committed.wait, 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()
    assert await asyncio.to_thread(finished.wait, 5)
    assert not called and registry.status(owner)['active_http'] == 0


@pytest.mark.asyncio
async def test_application_failure_cleans_up_but_database_failure_retains_evidence(replicas):
    owner, registry, (a, _) = services(replicas)
    async def broken_app(*args):
        raise RuntimeError('fixture application failure')
    def broken_finish(request_id):
        raise RuntimeError('fixture DB unavailable')
    for service, expected in [(a, 0), (SimpleNamespace(begin=a.begin, finish=broken_finish), 1)]:
        with pytest.raises(RuntimeError, match='fixture application failure'):
            await RuntimeAdmissionMiddleware(broken_app)(scope(service), receive, broken_app)
        assert registry.status(owner)['active_http'] == expected
    assert not a.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize('path,method,bypass', [('/health','GET',True),('/ready','HEAD',True),
    ('/health','POST',False),('/ready/','GET',False),('/api/test','GET',False)])
async def test_only_read_only_health_paths_bypass_unavailable_admission(path, method, bypass):
    called, messages = [], []
    async def app(*args):
        called.append(True)
    async def send(message):
        messages.append(message)
    await RuntimeAdmissionMiddleware(app)(scope(None, path=path, method=method), receive, send)
    assert bool(called) == bypass
    if not bypass:
        assert messages[0]['status'] == 503
        assert (b'cache-control', b'no-store') in messages[0]['headers']
