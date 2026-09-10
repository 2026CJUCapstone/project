import asyncio
from pathlib import Path

import pytest

from app.proxy_controller import Controller
from app.proxy_membership import Config, Resolver


def controller(tmp_path):
    return Controller(Config('backend',8000,'a'*40,('127.0.0.0/24',)),tmp_path)


@pytest.mark.asyncio
async def test_admission_is_fenced_by_confirmed_nginx_generation(tmp_path):
    managed = controller(tmp_path)
    managed.state.observe(['127.0.0.2','127.0.0.3'])
    managed.state.confirmed = True
    managed.generation = 'a'*32
    server = await asyncio.start_server(managed.serve,'127.0.0.1',0)
    async def request(generation):
        reader, writer = await asyncio.open_connection('127.0.0.1',server.sockets[0].getsockname()[1])
        try:
            writer.write(f'GET /allow/{generation} HTTP/1.1\r\nHost: fixture\r\n\r\n'.encode())
            await writer.drain()
            return (await reader.readuntil(b'\r\n')).split()[1]
        finally:
            writer.close()
            await writer.wait_closed()
    try:
        assert await request('a'*32) == b'204'
        managed.generation = 'b'*32
        # Even if an old nginx worker retains a keepalive connection, its old
        # static /allow/<generation> subrequest cannot admit another request.
        assert await request('a'*32) == b'403'
        assert await request('b'*32) == b'204'
        managed.state.draining = True
        assert await request('b'*32) == b'403'
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_unacknowledged_generation_restores_verified_disk_config(tmp_path,monkeypatch):
    managed = controller(tmp_path)
    managed.state.observe(['127.0.0.2'])
    managed.state.confirmed = True
    managed.generation = 'a'*32
    managed.applied_config = 'last verified configuration'
    async def fail(generation):
        managed.atomic_write('generation-'+generation,generation)
        managed.atomic_write('nginx.conf','unverified candidate')
        raise RuntimeError('reload acknowledgment failed')
    monkeypatch.setattr(managed,'apply_generation',fail)
    original_read = Path.read_text
    monkeypatch.setattr(Path,'read_text',lambda path,*a,**k: 'fixture-not-nginx' if path.as_posix()=='/proc/1/comm' else original_read(path,*a,**k))
    for _ in range(3):
        with pytest.raises(RuntimeError,match='acknowledgment'):
            await managed.apply()
        assert (tmp_path/'nginx.conf').read_text() == 'last verified configuration'
        assert not list(tmp_path.glob('generation-*'))
        assert not list(tmp_path.glob('.write-*'))
        assert not managed.state.available()


@pytest.mark.asyncio
async def test_dns_timeouts_reuse_one_outstanding_lookup(monkeypatch):
    resolver = Resolver()
    cfg = Config('backend',8000,'a'*40,('127.0.0.0/24',))
    finish = asyncio.Event()
    calls = []
    async def slow(*args,**kwargs):
        calls.append(args)
        await finish.wait()
        return ['resolved']
    monkeypatch.setattr(asyncio.get_running_loop(),'getaddrinfo',slow)
    for _ in range(3):
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(resolver.resolve(cfg),.01)
    assert len(calls) == 1
    finish.set()
    assert await resolver.resolve(cfg) == ['resolved']
    assert resolver.pending is None
