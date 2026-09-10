"""Explicit proxy trust, shared by HTTP/WS admission and proxy rendering.

Each trusted hop must overwrite forwarding headers with one normalized client
address. Never accept a client-supplied chain or infer trust from private IPs.
"""
import ipaddress


def trusted_networks(value):
    if isinstance(value, str):
        value = value.split(',') if value else ()
    if not isinstance(value, (list, tuple)) or len(value) > 16:
        raise ValueError('At most 16 explicit trusted proxy networks required')
    networks = []
    for raw in value:
        if not isinstance(raw, str) or raw != raw.strip() or '%' in raw:
            raise ValueError('Canonical trusted proxy IP/CIDR required')
        network = ipaddress.ip_network(raw, strict=True)
        if (network.prefixlen < (16 if network.version == 4 else 64)
                or network.network_address.is_multicast or network.network_address.is_unspecified
                or (network.version == 6 and network.network_address.ipv4_mapped)):
            raise ValueError('Narrow unicast trusted proxy network required')
        if network in networks:
            raise ValueError('Duplicate trusted proxy network')
        networks.append(network)
    return tuple(networks)


def client_address(value):
    if not isinstance(value, str) or '%' in value or len(value) > 45:
        raise ValueError('Single client IP required')
    address = ipaddress.ip_address(value)
    if address.is_multicast or address.is_unspecified:
        raise ValueError('Unicast client IP required')
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return address


_FORWARDING = frozenset((b'forwarded', b'x-forwarded-for', b'x-forwarded-proto',
                         b'x-forwarded-host', b'x-forwarded-port', b'x-real-ip'))


class TrustedIngressMiddleware:
    """Requires Uvicorn --no-proxy-headers: trust the original transport peer."""
    def __init__(self, app, *, networks=()):
        self.app = app
        self.networks = trusted_networks(networks)

    async def __call__(self, scope, receive, send):
        if scope['type'] not in ('http', 'websocket'):
            return await self.app(scope, receive, send)
        peer = scope.get('client')
        try:
            address = client_address(peer[0]) if peer else None
            trusted = address is not None and any(address in network for network in self.networks)
        except (ValueError, TypeError, IndexError):
            trusted = False
        headers = scope.get('headers', ())
        forwarded = [value for name, value in headers if name.lower() == b'x-forwarded-for']
        protocols = [value for name, value in headers if name.lower() == b'x-forwarded-proto']
        resolved = scope.copy()
        resolved['headers'] = [(name, value) for name, value in headers if name.lower() not in _FORWARDING]
        if trusted and (forwarded or protocols):
            try:
                if len(forwarded) != 1 or len(protocols) != 1:
                    raise ValueError('One forwarding address and protocol required')
                original = client_address(forwarded[0].decode('ascii'))
                protocol = protocols[0].decode('ascii')
                if protocol not in ('http', 'https'):
                    raise ValueError('Invalid forwarded protocol')
            except (ValueError, UnicodeError):
                if scope['type'] == 'websocket':
                    await send({'type': 'websocket.close', 'code': 1008})
                else:
                    await send({'type': 'http.response.start', 'status': 400,
                                'headers': [(b'cache-control', b'no-store'), (b'content-length', b'0')]})
                    await send({'type': 'http.response.body', 'body': b''})
                return
            resolved['client'] = (str(original), 0)  # The proxy cannot attest a client source port.
            resolved['scheme'] = ('wss' if protocol == 'https' else 'ws') if scope['type'] == 'websocket' else protocol
        return await self.app(resolved, receive, send)


def nginx_ingress(value):
    """HTTP-context directives. Preserve peer identity for local control ACLs."""
    networks = trusted_networks(value)
    if not networks:
        return '', '$scheme'
    trusted = '\n'.join(f'    set_real_ip_from {network};' for network in networks)
    peers = '\n'.join(f'        {network} 1;' for network in networks)
    return f'''{trusted}
    real_ip_header X-Forwarded-For;
    real_ip_recursive off;
    geo $realip_remote_addr $webcompiler_trusted_peer {{
        default 0;
{peers}
    }}
    map "$webcompiler_trusted_peer:$http_x_forwarded_proto" $webcompiler_client_scheme {{
        default $scheme;
        "1:http" http;
        "1:https" https;
    }}
''', '$webcompiler_client_scheme'
