"""Two real Nginx hops, two API processes and shared Redis; audit host only.

The membership UDS is an explicit fixture, not a controller/rollout proof.
Trusted TLS-hop metadata is simulated; this does not configure production TLS.
"""
import asyncio
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
from uuid import uuid4

import docker
import httpx
import pytest
import redis
from websockets.asyncio.client import connect

from app.services.api_proxy_config import render_managed
from tests.test_edge_renderer import edge_transaction as edge
from tests.test_execution_http_live import stop

pytestmark = pytest.mark.skipif(os.getenv('RUN_LB_INTEGRATION') != '1', reason='Explicit isolated Docker/Redis host required')


def allocate_ports(count):
    sockets = [socket.socket() for _ in range(count)]
    try:
        for listener in sockets:
            listener.bind(('127.0.0.1', 0))
        return [listener.getsockname()[1] for listener in sockets]
    finally:
        for listener in sockets:
            listener.close()


@pytest.mark.asyncio
async def test_trusted_chain_preserves_distinct_clients_and_shared_http_ws_quotas():
    client = docker.from_env(timeout=15)
    parent = client.containers.get(socket.gethostname())
    assert parent.labels.get('com.docker.compose.project', '').startswith('webcompiler-audit-')
    assert parent.attrs['Config']['Image'].startswith('webcompiler-audit-tests:')
    nginx = client.images.get('nginx:1.30.4-alpine-slim@sha256:77da26c31397bf6694b4bf93275f5b40b0b120ba1b8f114264b603e592c561d6')  # Never pull or use production images.
    prefix = 'audit-ingress-'+uuid4().hex
    root = Path(os.environ['SANDBOX_WORKDIR_ROOT']).resolve()
    assert root.is_relative_to(Path(os.environ['AUDIT_ROOT']).resolve())
    # Linux AF_UNIX paths are limited to 107 bytes. The audit root is already
    # long; resource ownership uses the separate full UUID container label.
    work = Path(tempfile.mkdtemp(prefix='ing-', dir=root))
    assert len(os.fsencode(work/'proxy'/'membership.sock')) <= 107
    first, second, proxy_port, edge_port, frontend_port = allocate_ports(5)
    api_env = dict(os.environ, ENVIRONMENT='development', REDIS_URL=os.environ['TEST_REDIS_URL'],
                   REDIS_KEY_PREFIX=prefix, TRUSTED_PROXY_CIDRS='127.0.0.1/32',
                   EXECUTION_IP_RATE_LIMIT='2', EXECUTION_GLOBAL_RATE_LIMIT='100')
    processes, containers = [], []
    nginx_uid, nginx_gid = (10001, 10001) if os.getuid() == 0 else (os.getuid(), os.getgid())
    membership = None
    store = redis.Redis.from_url(os.environ['TEST_REDIS_URL'])

    def start_nginx(role, config_dir, status_dir=None):
        mounts = {str(config_dir): {'bind': '/control', 'mode': 'ro'}}
        if status_dir:
            mounts[str(status_dir)] = {'bind': '/status', 'mode': 'rw'}
        container = client.containers.run(nginx.id, name=prefix+'-'+role,
            entrypoint=['nginx'], command=['-c', '/control/nginx.conf', '-g', 'daemon off;'],
            network_mode='container:'+parent.id, user=f'{nginx_uid}:{nginx_gid}',
            read_only=True, cap_drop=['ALL'], security_opt=['no-new-privileges:true'],
            tmpfs={'/tmp': 'size=16m,mode=1777,noexec,nosuid'},
            mem_limit='96m', memswap_limit='96m', cpu_period=100000, cpu_quota=25000, pids_limit=64,
            volumes=mounts, labels={'io.webcompiler.audit.fixture': prefix}, detach=True,
            log_config=docker.types.LogConfig(type='json-file', config={'max-size':'1m','max-file':'1'}))
        containers.append(container)
        return container

    async def healthy(http, url):
        async with asyncio.timeout(25):
            while True:
                assert all(process.poll() is None for process in processes)
                for container in containers:
                    await asyncio.to_thread(container.reload)
                    assert container.attrs['State']['Running'], container.logs(tail=20).decode(errors='replace')
                try:
                    response = await http.get(url+'/audit/identity')
                    if response.status_code == 200:
                        return
                except httpx.TransportError:
                    pass
                await asyncio.sleep(.1)

    with tempfile.TemporaryFile() as log:
        try:
            for port in (first, second):
                processes.append(subprocess.Popen([sys.executable, '-m', 'uvicorn', 'tests.ingress_identity_server:app',
                    '--host', '127.0.0.1', '--port', str(port), '--no-proxy-headers', '--log-level', 'error'],
                    cwd=Path(__file__).resolve().parents[1], env=api_env, stdout=log, stderr=log))
            proxy_dir, edge_dir, status_dir = (work/'proxy', work/'edge', work/'status')
            for directory in (proxy_dir, edge_dir, status_dir):
                directory.mkdir(mode=0o700)
                if os.getuid() == 0:
                    os.chown(directory, nginx_uid, nginx_gid)
            generation = uuid4().hex
            (proxy_dir/('generation-'+generation)).write_text(generation)
            config = render_managed([f'127.0.0.1:{first}', f'127.0.0.1:{second}'], generation,
                trusted_ingress='127.0.0.1/32,127.0.0.10/32')
            assert config.count('listen 8080;') == 1
            (proxy_dir/'nginx.conf').write_text(config.replace('listen 8080;', f'listen 127.0.0.1:{proxy_port};'))

            async def membership_fixture(reader, writer):
                try:
                    async with asyncio.timeout(2):
                        raw = await reader.readuntil(b'\r\n\r\n')
                        allowed = raw.split(b'\r\n')[0] == f'GET /allow/{generation} HTTP/1.1'.encode()
                        status = '204 No Content' if allowed else '403 Forbidden'
                        writer.write(f'HTTP/1.1 {status}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n'.encode())
                        await writer.drain()
                finally:
                    writer.close()

            membership = await asyncio.start_unix_server(membership_fixture, path=str(proxy_dir/'membership.sock'), limit=4096)
            if os.getuid() == 0:
                os.chown(proxy_dir/'membership.sock', nginx_uid, nginx_gid)
            os.chmod(proxy_dir/'membership.sock', 0o600)
            layout = edge.Layout(edge_port, frontend_port, '127.0.0.10/32')
            release = edge.Release('blue', 'a'*40, proxy_port, first, uuid4().hex)
            (edge_dir/'nginx.conf').write_text(edge.render(layout, release))
            await asyncio.to_thread(start_nginx, 'proxy', proxy_dir)
            await asyncio.to_thread(start_nginx, 'edge', edge_dir, status_dir)
            url = f'http://127.0.0.1:{edge_port}'
            async with httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(local_address='127.0.0.2'), timeout=5) as a, \
                    httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(local_address='127.0.0.3'), timeout=5) as b, \
                    httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(local_address='127.0.0.10'), timeout=5) as tls:
                await healthy(a, url)
                spoof = {'X-Forwarded-For':'203.0.113.77', 'X-Forwarded-Proto':'https', 'Forwarded':'for=127.0.0.1'}
                pids = set()
                for _ in range(8):
                    response = await a.get(url+'/audit/identity', headers=spoof)
                    assert response.status_code == 200, response.text
                    assert response.json()['ip'] == '127.0.0.2' and response.json()['scheme'] == 'http'
                    pids.add(response.json()['pid'])
                assert pids == {process.pid for process in processes}
                trusted = await tls.get(url+'/audit/identity', headers={'X-Forwarded-For':'203.0.113.20','X-Forwarded-Proto':'https'})
                assert trusted.json()['ip'] == '203.0.113.20' and trusted.json()['scheme'] == 'https'
                # realip must not turn a non-control peer into loopback for ACLs.
                denied = await tls.get(f'http://127.0.0.1:{proxy_port}/_proxy_generation',
                    headers={'X-Forwarded-For':'127.0.0.1','X-Forwarded-Proto':'http'})
                assert denied.status_code == 403
                direct = await a.get(f'http://127.0.0.1:{first}/audit/identity', headers=spoof)
                assert direct.json()['ip'] == '127.0.0.2'
                assert (await a.get(url+'/api/audit/limited', headers=spoof)).status_code == 200
                async with connect(f'ws://127.0.0.1:{edge_port}/ws/terminal', local_addr=('127.0.0.2',0),
                                   additional_headers=spoof) as ws:
                    message = json.loads(await ws.recv())
                    assert message['ip'] == '127.0.0.2' and message['scheme'] == 'ws'
                rejected = await a.get(url+'/api/audit/limited', headers={**spoof, 'X-Forwarded-For':'203.0.113.88'})
                assert rejected.status_code == 429 and 'retry-after' in rejected.headers
                distinct = await b.get(url+'/api/audit/limited', headers=spoof)
                assert distinct.status_code == 200 and distinct.json()['ip'] == '127.0.0.3'
        except Exception:
            # Only disposable test fixtures log here; retain bounded startup
            # evidence before cleanup so a timeout isn't an opaque failure.
            for container in containers:
                print(container.name, container.logs(tail=20).decode(errors='replace')[-4000:])
            log.seek(0)
            print(log.read(4000).decode(errors='replace'))
            raise
        finally:
            for container in reversed(containers):
                assert container.labels.get('io.webcompiler.audit.fixture') == prefix
                await asyncio.to_thread(container.remove, force=True)
            for process in processes:
                await asyncio.to_thread(stop, process)
            if membership:
                membership.close()
                await membership.wait_closed()
            keys = list(store.scan_iter(prefix+':*'))
            if keys:
                store.delete(*keys)
            store.close()
            assert work.parent == root and work.name.startswith('ing-')
            shutil.rmtree(work)
            client.close()
