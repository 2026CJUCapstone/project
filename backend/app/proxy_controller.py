"""Manage a same-color Nginx pool without access to the Docker socket.

Runs as the proxy UID in ONLY its network/PID namespaces. /control is a scoped
shared writable directory, not the application source or host workspace.
"""
import asyncio
import json
import os
from pathlib import Path
import re
import signal
import stat
import time
from uuid import uuid4

from app.proxy_membership import Config, Membership, Resolver, discover, http_get
from app.services.api_proxy_config import render_managed
from app.services.runtime_identity import validate_runtime_id


class Controller:
    def __init__(self, config, directory=Path('/control'), *, pool_id='development'):
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,99}',pool_id):
            raise ValueError('Explicit proxy pool identity required')
        self.pool_id = pool_id
        self.state = Membership(config)
        self.directory = directory
        self.generation = None
        self.applied = None
        self.applied_config = None
        self.last_reload = float('-inf')
        self.connections = 0
        self.resolver = Resolver()

    def atomic_write(self, name, data):
        # Callers supply fixed basenames or generated UUIDs, never user input.
        temporary = self.directory / ('.write-'+uuid4().hex)
        try:
            with temporary.open('x',encoding='utf-8') as output:
                os.chmod(temporary,0o600)
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            temporary.replace(self.directory/name)
        finally:
            temporary.unlink(missing_ok=True)

    async def apply(self):
        # Bound old-worker generations: at most one reload/5s, with a 150s
        # graceful shutdown ceiling in managed configs. No per-request reload.
        if time.monotonic() - self.last_reload < 5:
            return
        self.state.confirmed = False
        generation = uuid4().hex
        try:
            await self.apply_generation(generation)
        except (OSError, ValueError, RuntimeError, TimeoutError):
            # A HUP might have reached nginx even when acknowledgment failed.
            # Restore a verified config on disk (or an empty pool at startup)
            # so a subsequent proxy restart cannot adopt an unverified file.
            if self.applied_config is not None:
                self.atomic_write('nginx.conf',self.applied_config)
            else:
                closed_generation = '0'*32
                self.atomic_write('generation-'+closed_generation,closed_generation)
                self.atomic_write('nginx.conf',render_managed([],closed_generation,
                    trusted_ingress=self.state.config.trusted_ingress))
            if Path('/proc/1/comm').read_text().strip() == 'nginx':
                os.kill(1,signal.SIGHUP)
            raise
        finally:
            if self.generation != generation:
                (self.directory/('generation-'+generation)).unlink(missing_ok=True)

    async def apply_generation(self, generation):
        if Path('/proc/1/comm').read_text().strip() != 'nginx':
            raise RuntimeError('Controller is not in the Nginx PID namespace')
        self.atomic_write('generation-'+generation,generation)
        config = render_managed([f'{ip}:{self.state.config.port}' for ip in self.state.peers],generation,
            trusted_ingress=self.state.config.trusted_ingress)
        config = config.replace('worker_processes 1;', 'worker_processes 1;\nworker_shutdown_timeout 150s;')
        self.atomic_write('nginx.conf',config)
        # In the proxy's PID namespace nginx must be PID 1. Never signal an
        # unverified host process or trust a writable pid file from a peer.
        os.kill(1,signal.SIGHUP)
        self.last_reload = time.monotonic()
        deadline = time.monotonic()+2
        while time.monotonic() < deadline:
            try:
                actual = await http_get('127.0.0.1',8080,'/_proxy_generation')
                if actual.decode('ascii') == generation:
                    self.generation, self.applied = generation, self.state.peers
                    self.applied_config = config
                    self.state.confirmed = True
                    for marker in self.directory.glob('generation-*'):
                        if (marker.name != 'generation-'+generation
                                and re.fullmatch(r'generation-[0-9a-f]{32}',marker.name)
                                and not marker.is_symlink() and marker.is_file()
                                and marker.stat().st_uid == os.getuid()):
                            marker.unlink()
                    return
            except (OSError, ValueError, KeyError, TimeoutError, asyncio.IncompleteReadError):
                pass
            await asyncio.sleep(.1)
        raise RuntimeError('Nginx did not acknowledge the ready pool')

    async def cycle(self):
        while not self.state.draining:
            self.state.observe(await discover(self.state.config,self.resolver))
            if self.applied != self.state.peers or not self.state.confirmed:
                try:
                    await self.apply()
                except (OSError, ValueError, RuntimeError, TimeoutError):
                    self.state.confirmed = False
            await asyncio.sleep(1)

    async def serve(self, reader, writer):
        self.connections += 1
        try:
            if self.connections > 64:
                return
            async with asyncio.timeout(1):
                request = await reader.readuntil(b'\r\n\r\n')
                first = request.split(b'\r\n',1)[0]
                if first.startswith(b'GET /allow/'):
                    expected = f'GET /allow/{self.generation} HTTP/1.1'.encode()
                    code, body = (204,b'') if first == expected and self.state.available() else (403,b'')
                elif first == b'GET /status HTTP/1.1':
                    code, body = 200,json.dumps({**self.state.status(),
                        'poolId':self.pool_id,'generation':self.generation,
                        'runtimeInstanceId':self.state.config.runtime_id}).encode()
                else:
                    code, body = 404,b''
                writer.write(f'HTTP/1.1 {code} Result\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n'.encode()+body)
                await writer.drain()
        except (OSError, ValueError, TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            pass
        finally:
            self.connections -= 1
            writer.close()

    async def run(self):
        import fcntl
        info = self.directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise RuntimeError('Private controller-owned directory required')
        owner = json.loads((self.directory/'owner.json').read_text())
        expected = {'deploymentSha':self.state.config.release,'poolId':self.pool_id,
                    'runtimeInstanceId':self.state.config.runtime_id,'uid':os.getuid(),'gid':os.getgid()}
        if self.state.config.trusted_ingress:
            expected['trustedIngress'] = self.state.config.trusted_ingress
        if owner != expected:
            raise RuntimeError('Control directory belongs to another release')
        descriptor = os.open(self.directory/'controller.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        # Hold until process exit: a second controller must not unlink the live
        # socket or overwrite the first controller's in-flight configuration.
        self.lock = os.fdopen(descriptor,'w')
        fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        sock = self.directory/'membership.sock'
        if sock.exists():
            info = sock.lstat()
            if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
                raise RuntimeError('Refusing unknown control socket')
            sock.unlink()
        server = await asyncio.start_unix_server(self.serve,path=str(sock),limit=4096,backlog=64)
        os.chmod(sock,0o600)
        loop = asyncio.get_running_loop()
        stopped = asyncio.Event()
        def stop():
            self.state.draining = True
            stopped.set()
        for sig in (signal.SIGTERM,signal.SIGINT):
            loop.add_signal_handler(sig,stop)
        updater = asyncio.create_task(self.cycle())
        updater.add_done_callback(lambda task: stopped.set())
        try:
            await stopped.wait()
        finally:
            self.state.draining = True
            updater.cancel()
            await asyncio.gather(updater,return_exceptions=True)
            server.close()
            await server.wait_closed()
            sock.unlink(missing_ok=True)
            self.lock.close()


def main():
    config = Config(service=os.getenv('PROXY_DISCOVERY_SERVICE','backend'),
        port=int(os.getenv('PROXY_DISCOVERY_PORT','8000')),release=os.environ['DEPLOYMENT_SHA'],
        networks=tuple(os.environ['PROXY_ALLOWED_CIDRS'].split(',')),
        runtime_id=validate_runtime_id(os.environ['RUNTIME_INSTANCE_ID']),
        trusted_ingress=os.getenv('PROXY_TRUSTED_INGRESS_CIDRS',''))
    asyncio.run(Controller(config,pool_id=os.environ['PROXY_POOL_ID']).run())


if __name__ == '__main__':
    main()
