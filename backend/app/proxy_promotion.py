"""Read-only deployment gate, executed inside the scoped controller container.

Serving one healthy API is valid degraded operation, not a promotion criterion.
Never infer two replicas from Docker's running count or a single HTTP /ready.
"""
import argparse
import asyncio
import json
from pathlib import Path
import re
import time
from app.services.runtime_identity import validate_runtime_id


def validate_identity(release, pool_id):
    if not isinstance(release, str) or not re.fullmatch(r'[0-9a-f]{40}', release):
        raise ValueError('An exact release SHA is required')
    if not isinstance(pool_id, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,99}', pool_id):
        raise ValueError('An explicit pool identity is required')


def candidate(status, release, pool_id, runtime_id=''):
    if not isinstance(status, dict):
        return None
    count = status.get('readyPeers')
    generation = status.get('generation')
    if (status.get('deploymentSha') != release or status.get('poolId') != pool_id
            or (runtime_id and status.get('runtimeInstanceId') != runtime_id)
            or status.get('available') is not True or status.get('deploymentReady') is not True
            or status.get('draining') is not False or type(count) is not int or not 2 <= count <= 32
            or not isinstance(generation, str) or not re.fullmatch(r'[0-9a-f]{32}', generation)):
        return None
    # A replica count change also restarts the observation window, even if a
    # malformed/older controller were to forget to advance the generation.
    return generation, count


async def read_status(path=Path('/control/membership.sock')):
    async with asyncio.timeout(2):
        reader, writer = await asyncio.open_unix_connection(str(path), limit=8192)
        try:
            writer.write(b'GET /status HTTP/1.1\r\nHost: controller\r\nConnection: close\r\n\r\n')
            await writer.drain()
            header = await reader.readuntil(b'\r\n\r\n')
            lines = header.decode('ascii').split('\r\n')
            if lines[0].split()[:2] != ['HTTP/1.1', '200']:
                raise ValueError('Controller status unavailable')
            headers = {}
            for line in lines[1:-2]:
                key, value = line.split(':', 1)
                key = key.lower()
                if key in headers:
                    raise ValueError('Duplicate controller header')
                headers[key] = value.strip()
            length = headers.get('content-length', '')
            if 'transfer-encoding' in headers or not length.isascii() or not length.isdecimal() or not 0 < int(length) <= 4096:
                raise ValueError('Unbounded controller response')
            return json.loads(await reader.readexactly(int(length)))
        finally:
            writer.close()
            await writer.wait_closed()


async def wait_for_pool(release, pool_id, *, runtime_id='', timeout=60, stable_seconds=5,
                        read=read_status, clock=time.monotonic, sleep=asyncio.sleep):
    validate_identity(release, pool_id)
    validate_runtime_id(runtime_id, allow_empty=True)
    if not 5 <= stable_seconds <= 30 or not stable_seconds + 2 <= timeout <= 300:
        raise ValueError('Invalid bounded promotion window')
    deadline = clock() + timeout
    observed, since = None, None
    while clock() < deadline:
        try:
            async with asyncio.timeout(min(2, max(.001, deadline - clock()))):
                current = candidate(await read(), release, pool_id, runtime_id)
        except (OSError, ValueError, TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            current = None
        now = clock()
        if current is None or current != observed:
            observed, since = current, now
        elif now < deadline and now - since >= stable_seconds:
            return current
        await sleep(min(1, max(0, deadline - clock())))
    raise TimeoutError('Two same-release ready APIs did not remain stable before promotion deadline')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', required=True)
    parser.add_argument('--pool', required=True)
    parser.add_argument('--runtime', required=True)
    args = parser.parse_args()
    try:
        asyncio.run(wait_for_pool(args.release, args.pool,runtime_id=validate_runtime_id(args.runtime)))
    except (OSError, ValueError, TimeoutError):
        parser.exit(1, 'Managed API pool promotion readiness failed\n')
    print('Managed API pool has at least two stable same-release ready replicas')


if __name__ == '__main__':
    main()
