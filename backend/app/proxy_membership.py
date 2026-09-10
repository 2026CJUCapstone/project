"""Bounded, socket-free readiness discovery for one immutable API release."""
import asyncio
from dataclasses import dataclass
import ipaddress
import json
import re
import socket
import time
from app.services.runtime_identity import validate_runtime_id
from app.services.trusted_ingress import trusted_networks


@dataclass(frozen=True)
class Config:
    service: str
    port: int
    release: str
    networks: tuple[str, ...]
    max_peers: int = 32
    fresh_seconds: float = 6
    runtime_id: str = ''
    trusted_ingress: str = ''

    def __post_init__(self):
        validate_runtime_id(self.runtime_id, allow_empty=True)
        object.__setattr__(self, 'trusted_ingress', ','.join(str(n) for n in trusted_networks(self.trusted_ingress)))
        if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9.-]{0,99}', self.service):
            raise ValueError('Invalid discovery service')
        if not 1 <= self.port <= 65535 or not 1 <= self.max_peers <= 32:
            raise ValueError('Invalid discovery limits')
        if not re.fullmatch(r'[0-9a-f]{40}', self.release):
            raise ValueError('Exact release SHA required')
        if not 4 <= self.fresh_seconds <= 10 or not 1 <= len(self.networks) <= 4:
            raise ValueError('Explicit bounded discovery network required')
        for raw in self.networks:
            network = ipaddress.ip_network(raw, strict=True)
            if network.version != 4 or network.prefixlen < 16:
                raise ValueError('Narrow IPv4 discovery networks required')

    def peers(self, addresses):
        peers = sorted(set(addresses))
        if not 1 <= len(peers) <= self.max_peers:
            raise ValueError('Invalid discovery peer count')
        networks = [ipaddress.ip_network(n) for n in self.networks]
        for address in peers:
            ip = ipaddress.ip_address(address)
            if not isinstance(ip, ipaddress.IPv4Address) or not any(ip in n for n in networks):
                raise ValueError('Discovered peer is outside the approved network')
        return tuple(peers)


async def http_get(host, port, path):
    """One HTTP/1.1 probe. Never redirect, proxy, retry, or read unbounded data."""
    writer = None
    try:
        async with asyncio.timeout(1):
            reader, writer = await asyncio.open_connection(host, port, limit=8192)
            writer.write(f'GET {path} HTTP/1.1\r\nHost: readiness.internal\r\nConnection: close\r\n\r\n'.encode('ascii'))
            await writer.drain()
            headers = (await reader.readuntil(b'\r\n\r\n')).decode('ascii')
            lines = headers.split('\r\n')
            if lines[0].split()[:2] != ['HTTP/1.1','200']:
                raise ValueError('Probe refused')
            fields = {}
            for line in lines[1:]:
                if not line:
                    continue
                key, value = line.split(':',1)
                key = key.lower()
                if key in fields:
                    raise ValueError('Duplicate probe header')
                fields[key] = value.strip()
            length = int(fields['content-length'])
            if 'transfer-encoding' in fields or not 0 <= length <= 4096:
                raise ValueError('Invalid probe body size')
            return await reader.readexactly(length)
    finally:
        if writer is not None:
            writer.close()
            # Do not extend the probe deadline waiting for a malicious peer.


async def ready_peer(config, address):
    try:
        async with asyncio.timeout(2):
            ready = json.loads(await http_get(address, config.port, '/ready'))
            health = json.loads(await http_get(address, config.port, '/health'))
            return (ready.get('status') == 'ready' and health.get('status') == 'ok'
                    and health.get('deploymentSha') == config.release
                    and (not config.runtime_id or health.get('runtimeInstanceId') == config.runtime_id))
    except (OSError, ValueError, KeyError, AttributeError, asyncio.IncompleteReadError,
            asyncio.LimitOverrunError, TimeoutError):
        return False


class Resolver:
    """Keep at most one OS DNS lookup outstanding, even if it stalls."""
    def __init__(self):
        self.pending = None

    async def resolve(self, config):
        if self.pending is None:
            self.pending = asyncio.create_task(asyncio.get_running_loop().getaddrinfo(
                config.service,config.port,family=socket.AF_INET,type=socket.SOCK_STREAM))
        try:
            return await asyncio.shield(self.pending)
        finally:
            if self.pending.done():
                self.pending = None


async def discover(config, resolver=None):
    try:
        async with asyncio.timeout(1):
            records = await (resolver or Resolver()).resolve(config)
        addresses = config.peers(record[4][0] for record in records)
        ready = await asyncio.gather(*(ready_peer(config,address) for address in addresses))
        return tuple(address for address, valid in zip(addresses,ready) if valid)
    except (OSError, ValueError, TimeoutError):
        # DNS failure or an untrusted answer withdraws the entire old pool.
        return ()


class Membership:
    def __init__(self, config, *, clock=time.monotonic):
        self.config, self.clock = config, clock
        self.peers = ()
        self.confirmed = False
        self.checked_at = float('-inf')
        self.draining = False

    def observe(self, peers):
        peers = self.config.peers(peers) if peers else ()
        if peers != self.peers:
            self.confirmed = False
        self.peers = peers
        self.checked_at = self.clock()

    def available(self):
        age = self.clock() - self.checked_at
        return bool(self.peers and self.confirmed and not self.draining and 0 <= age < self.config.fresh_seconds)

    def status(self):
        return {'available':self.available(), 'readyPeers':len(self.peers),
                'deploymentReady':self.available() and len(self.peers) >= 2,
                'deploymentSha':self.config.release, 'draining':self.draining}
