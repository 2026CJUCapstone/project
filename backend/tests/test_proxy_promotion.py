import asyncio
import os

import pytest

from app.proxy_controller import Controller
from app.proxy_membership import Config
from app.proxy_promotion import read_status, wait_for_pool


def ready():
    return dict(available=True, deploymentReady=True, draining=False, readyPeers=2,
                deploymentSha='a'*40, poolId='audit-blue', generation='b'*32,runtimeInstanceId='c'*32)


class Clock:
    def __init__(self):
        self.now = 0

    def __call__(self):
        return self.now

    async def sleep(self, seconds):
        self.now += seconds


@pytest.mark.asyncio
@pytest.mark.parametrize('interruption', ['one-peer', 'generation', 'count', 'unavailable', 'io', 'wrong-pool', 'wrong-release','wrong-runtime'])
async def test_promotion_restarts_full_stability_window_after_every_interruption(interruption):
    clock = Clock()
    async def read():
        state = ready()
        if clock.now == 4:
            if interruption == 'io':
                raise OSError('fixture controller unavailable')
            key, value = {'one-peer': ('readyPeers',1), 'generation':('generation','c'*32),
                          'count':('readyPeers',3), 'unavailable':('available',False),
                          'wrong-pool':('poolId','audit-green'), 'wrong-release':('deploymentSha','d'*40),
                          'wrong-runtime':('runtimeInstanceId','d'*32)}[interruption]
            state[key] = value
        return state
    result = await wait_for_pool('a'*40, 'audit-blue', runtime_id='c'*32,read=read, clock=clock, sleep=clock.sleep, timeout=15)
    assert result == ('b'*32, 2)
    assert clock.now == 10  # five full seconds after the recovery observation


@pytest.mark.asyncio
async def test_one_peer_serves_but_cannot_promote_and_deadline_is_not_extended():
    clock = Clock()
    async def read():
        return {**ready(), 'readyPeers':1, 'deploymentReady':False}
    with pytest.raises(TimeoutError):
        await wait_for_pool('a'*40,'audit-blue',read=read,clock=clock,sleep=clock.sleep,timeout=8)
    assert clock.now == 8


@pytest.mark.asyncio
async def test_reply_arriving_at_deadline_cannot_promote():
    clock = Clock()
    async def read():
        if clock.now == 5:
            clock.now = 8
        return ready()
    with pytest.raises(TimeoutError):
        await wait_for_pool('a'*40,'audit-blue',read=read,clock=clock,sleep=clock.sleep,timeout=8)
    assert clock.now == 8


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != 'posix',reason='Real Unix socket required')
async def test_actual_controller_uds_reports_pool_generation_and_freshness(tmp_path):
    managed = Controller(Config('backend',8000,'a'*40,('127.0.0.0/24',),runtime_id='c'*32),tmp_path,pool_id='audit-blue')
    managed.state.observe(['127.0.0.2','127.0.0.3'])
    managed.state.confirmed = True
    managed.generation = 'b'*32
    path = tmp_path/'membership.sock'
    server = await asyncio.start_unix_server(managed.serve,path=str(path),limit=4096)
    try:
        assert await read_status(path) == ready()
        managed.state.draining = True
        state = await read_status(path)
        assert state['draining'] is True and state['deploymentReady'] is False
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != 'posix',reason='Real Unix socket required')
@pytest.mark.parametrize('reply', [
    b'HTTP/1.1 302 Found\r\nContent-Length: 2\r\n\r\n{}',
    b'HTTP/1.1 200 OK\r\nContent-Length: 5000\r\n\r\n',
    b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\nContent-Length: 2\r\n\r\n{}',
    b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nContent-Length: 2\r\n\r\n{}',
    b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nx',
])
async def test_actual_uds_rejects_ambiguous_oversized_redirect_or_truncated_response(tmp_path,reply):
    async def serve(reader,writer):
        await reader.readuntil(b'\r\n\r\n')
        writer.write(reply)
        await writer.drain()
        writer.close()
        await writer.wait_closed()
    path = tmp_path/'membership.sock'
    server = await asyncio.start_unix_server(serve,path=str(path))
    try:
        with pytest.raises((ValueError,asyncio.IncompleteReadError)):
            await read_status(path)
    finally:
        server.close()
        await server.wait_closed()
