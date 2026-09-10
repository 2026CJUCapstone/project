import asyncio
import json

import pytest

from app.proxy_membership import Config, Membership, http_get, ready_peer
from app.services.api_proxy_config import render_managed


def config(**kwargs):
    return Config(**dict(service='backend',port=8000,release='a'*40,
                         networks=('127.0.0.0/24',),**kwargs))


def test_membership_generation_freshness_drain_and_single_survivor():
    now = [0.0]
    state = Membership(config(),clock=lambda:now[0])
    assert not state.available()
    state.observe(['127.0.0.2','127.0.0.3'])
    assert not state.available()
    state.confirmed = True
    assert state.status()['deploymentReady']
    now[0] = 6
    assert not state.available()
    state.observe(['127.0.0.2'])
    assert not state.confirmed
    state.confirmed = True
    assert state.available() and not state.status()['deploymentReady']
    now[0] = 5
    assert not state.available()
    now[0] = 6
    state.draining = True
    assert not state.available()


@pytest.mark.parametrize('field,value',[
    ('service','backend; evil'),('release','main'),('release','A'*40),
    ('networks',()),('networks',('0.0.0.0/0',)),('networks',('::/64',)),
    ('port',0),('max_peers',33),('fresh_seconds',60),
])
def test_config_rejects_unsafe_discovery(field,value):
    values = dict(service='backend',port=8000,release='a'*40,networks=('127.0.0.0/24',))
    values[field] = value
    with pytest.raises(ValueError):
        Config(**values)


def test_discovery_addresses_are_bounded_and_inside_explicit_network():
    assert config().peers(['127.0.0.2']*4) == ('127.0.0.2',)
    for addresses in ([], ['192.168.1.1'],['127.0.0.1:8000'],[f'127.0.0.{n}' for n in range(33)]):
        with pytest.raises(ValueError):
            config().peers(addresses)


def test_managed_config_is_closed_and_generation_has_access_phase_checks():
    rendered = render_managed([], 'b'*32)
    assert 'server 127.0.0.1:1 ' in rendered
    assert rendered.count('auth_request /_proxy_membership;') == 2
    assert 'proxy_pass_request_body off;' in rendered
    assert 'proxy_pass_request_headers off;' in rendered
    assert ':/allow/'+'b'*32+';' in rendered
    assert 'location @membership_unavailable { return 503; }' in rendered
    generation = rendered.split('location = /_proxy_generation {')[1].split('}',1)[0]
    assert 'allow 127.0.0.1;' in generation and 'deny all;' in generation
    assert 'return 200' not in generation
    assert 'X-Audit-Upstream' not in rendered
    with pytest.raises(ValueError):
        render_managed(['127.0.0.2:8000'],'injection;')


@pytest.mark.asyncio
@pytest.mark.parametrize('ready,release,expected', [('ready','a'*40,True),('unavailable','a'*40,False),('ready','b'*40,False)])
async def test_actual_http_probe_checks_readiness_and_release(ready,release,expected):
    async def serve(reader,writer):
        request = await reader.readuntil(b'\r\n\r\n')
        body = json.dumps({'status':ready} if b'GET /ready ' in request else {'status':'ok','deploymentSha':release}).encode()
        writer.write(f'HTTP/1.1 200 OK\r\nContent-Length: {len(body)}\r\n\r\n'.encode()+body)
        await writer.drain()
        writer.close()
    server = await asyncio.start_server(serve,'127.0.0.1',0)
    try:
        cfg = Config('backend',server.sockets[0].getsockname()[1],'a'*40,('127.0.0.0/24',))
        assert await ready_peer(cfg,'127.0.0.1') is expected
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
@pytest.mark.parametrize('headers',[
    'HTTP/1.1 302 Redirect\r\nLocation: http://evil.invalid\r\nContent-Length: 0',
    'HTTP/1.1 200 OK\r\nContent-Length: 999999',
    'HTTP/1.1 200 OK\r\nContent-Length: 0\r\nContent-Length: 1',
    'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nContent-Length: 0',
])
async def test_actual_http_probe_refuses_ambiguous_or_unbounded_responses(headers):
    async def serve(reader,writer):
        await reader.readuntil(b'\r\n\r\n')
        writer.write((headers+'\r\n\r\n').encode())
        await writer.drain()
        writer.close()
    server = await asyncio.start_server(serve,'127.0.0.1',0)
    try:
        with pytest.raises(ValueError):
            await http_get('127.0.0.1',server.sockets[0].getsockname()[1],'/ready')
    finally:
        server.close()
        await server.wait_closed()
