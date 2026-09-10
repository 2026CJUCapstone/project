import pytest
from starlette.requests import Request
from starlette.websockets import WebSocket

from app.services.execution_admission import execution_ip
from app.services.trusted_ingress import TrustedIngressMiddleware, trusted_networks


async def invoke(*, kind='http', peer='172.20.0.3', headers=(), networks=('172.20.0.0/24',)):
    observed, messages = [], []
    original = {'type': kind, 'client': (peer, 1234), 'scheme': 'ws' if kind == 'websocket' else 'http',
                'headers': list(headers), 'path': '/', 'method': 'GET'}
    async def app(scope, receive, send):
        observed.append(scope)
    async def receive():
        raise AssertionError('Identity middleware must not read request bodies')
    async def send(message):
        messages.append(message)
    await TrustedIngressMiddleware(app, networks=networks)(original, receive, send)
    return original, observed, messages


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['http', 'websocket'])
async def test_only_configured_peer_can_supply_one_client_address_and_scheme(kind):
    headers = [(b'x-forwarded-for', b'203.0.113.20'), (b'x-forwarded-proto', b'https'),
               (b'forwarded', b'for=127.0.0.1'), (b'x-real-ip', b'127.0.0.1'), (b'authorization', b'unchanged')]
    original, scopes, messages = await invoke(kind=kind, headers=headers)
    assert not messages
    assert original['client'] == ('172.20.0.3', 1234)
    assert scopes[0]['client'] == ('203.0.113.20', 0)
    assert scopes[0]['scheme'] == ('wss' if kind == 'websocket' else 'https')
    assert scopes[0]['headers'] == [(b'authorization', b'unchanged')]
    connection = Request(scopes[0]) if kind == 'http' else WebSocket(scopes[0], None, None)
    assert execution_ip(connection) == '203.0.113.20'
    for networks, peer in (((), '172.20.0.3'), (('172.20.0.0/24',), '192.0.2.20')):
        _, untrusted, _ = await invoke(kind=kind, peer=peer, headers=headers, networks=networks)
        assert untrusted[0]['client'] == (peer, 1234)
        assert untrusted[0]['scheme'] == ('ws' if kind == 'websocket' else 'http')
        assert untrusted[0]['headers'] == [(b'authorization', b'unchanged')]


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['http', 'websocket'])
@pytest.mark.parametrize('headers', [
    [(b'x-forwarded-for', b'203.0.113.1')],
    [(b'x-forwarded-proto', b'https')],
    [(b'x-forwarded-for', b'1.1.1.1'), (b'x-forwarded-for', b'2.2.2.2'), (b'x-forwarded-proto', b'https')],
    [(b'x-forwarded-for', b'1.1.1.1'), (b'x-forwarded-proto', b'https'), (b'x-forwarded-proto', b'http')],
] + [[(b'x-forwarded-for', value), (b'x-forwarded-proto', b'https')] for value in
     (b'1.1.1.1, 2.2.2.2', b'unknown', b'fe80::1%eth0', b'0.0.0.0', b'[::1]:80', b'\xff', b'224.0.0.1')])
async def test_ambiguous_or_malformed_trusted_forwarding_is_rejected_before_admission(kind, headers):
    _, scopes, messages = await invoke(kind=kind, headers=headers)
    assert not scopes
    if kind == 'http':
        assert messages[0]['status'] == 400
        assert (b'cache-control', b'no-store') in messages[0]['headers']
    else:
        assert messages == [{'type': 'websocket.close', 'code': 1008}]


@pytest.mark.asyncio
async def test_ipv6_addresses_keep_existing_prefix_quota_and_mapped_ipv4_normalization():
    _, scopes, _ = await invoke(headers=[(b'x-forwarded-for', b'2001:db8:1::123'), (b'x-forwarded-proto', b'http')])
    assert execution_ip(Request(scopes[0])) == '2001:db8:1::/64'
    _, scopes, _ = await invoke(peer='::ffff:172.20.0.3',
        headers=[(b'x-forwarded-for', b'::ffff:203.0.113.1'), (b'x-forwarded-proto', b'https')])
    assert execution_ip(Request(scopes[0])) == '203.0.113.1'


@pytest.mark.parametrize('value', ['*', '0.0.0.0/0', '10.0.0.0/8', '::/0', '2001:db8::/32',
    'localhost', 'unix:', '127.0.0.1\n', '127.0.0.1; deny all;', '172.20.0.1/24',
    '127.0.0.1,127.0.0.1', '::ffff:127.0.0.1', True, ['127.0.0.1'] * 17])
def test_proxy_trust_requires_explicit_bounded_noninjectable_networks(value):
    with pytest.raises(ValueError):
        trusted_networks(value)


@pytest.mark.asyncio
async def test_readiness_without_forwarding_and_lifespan_are_passed_through():
    original, scopes, messages = await invoke()
    assert scopes[0] == original and not messages
    received = []
    async def app(scope, *_):
        received.append(scope)
    scope = {'type': 'lifespan'}
    await TrustedIngressMiddleware(app)(scope, None, None)
    assert received == [scope]
