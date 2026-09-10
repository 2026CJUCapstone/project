"""Worker-only interactive sandbox. API replicas never receive Docker handles."""
import asyncio
import codecs
import contextlib
import shutil
import socket
import tempfile
import uuid
from pathlib import Path

from docker.types import LogConfig, Ulimit

from app.core.config import settings
from app.services.terminal_broker import TerminalClosed
from app.services.execution_phase import ExecutionPhaseDecoder


async def run_terminal(runner, broker, payload):
    sid, language, code = payload['terminal_session'], payload['language'], payload['code']
    if not await asyncio.to_thread(broker.active, sid):
        raise TerminalClosed()
    root = Path(settings.SANDBOX_WORKDIR_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    prefix = f"job-{runner.labels['webcompiler.job']}-{runner.labels['webcompiler.lease']}-"
    directory = Path(tempfile.mkdtemp(prefix=prefix, dir=root))
    container, raw_socket = None, None
    tasks = []
    phase_token = uuid.uuid4().hex
    phase = ExecutionPhaseDecoder(phase_token, terminal=True)
    try:
        directory.chmod(0o755)
        source = directory / runner._resolve_filename(language, code)
        source.write_text(code, encoding='utf-8')
        source.chmod(0o644)
        client = runner._get_client()
        container = await runner._allocate_container(client.containers.create,
            image=settings.SANDBOX_IMAGE, command=['run',language,f'/workspace/{source.name}'],
            detach=True, name='compiler-terminal-'+uuid.uuid4().hex[:12], labels=runner.labels,
            stdin_open=True, tty=True, network_disabled=True, read_only=True,
            tmpfs={'/tmp':f'rw,exec,nosuid,size={settings.SANDBOX_MEMORY_MB}m'},
            mem_limit=f'{settings.SANDBOX_MEMORY_MB}m', memswap_limit=f'{settings.SANDBOX_MEMORY_MB}m',
            nano_cpus=max(1,int(settings.SANDBOX_CPU_LIMIT*1_000_000_000)), pids_limit=settings.SANDBOX_PIDS_LIMIT,
            ulimits=[Ulimit(name='nofile',soft=settings.SANDBOX_NOFILE_LIMIT,hard=settings.SANDBOX_NOFILE_LIMIT)],
            cap_drop=['ALL'], security_opt=['no-new-privileges'], log_config=LogConfig(type='none'),
            volumes={str(directory):{'bind':'/workspace','mode':'ro'}},
            environment={'COMPILER_OPTIMIZE':'1' if payload.get('optimize') else '0',
                'COMPILER_PHASE_TOKEN':phase_token, 'HOME':'/tmp'})
        attach = asyncio.create_task(asyncio.to_thread(container.attach_socket,
            params={'stdin':1,'stdout':1,'stderr':1,'stream':1}))
        try:
            connected = await asyncio.shield(attach)
        except asyncio.CancelledError:
            with contextlib.suppress(Exception):
                connected = await attach
                getattr(connected,'_sock',connected).close()
            raise
        raw_socket = getattr(connected,'_sock',connected)
        raw_socket.settimeout(.5)
        if not await asyncio.to_thread(broker.active, sid):
            raise TerminalClosed()
        await runner._start_container(container)

        async def read():
            decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
            while True:
                try:
                    chunk = await asyncio.to_thread(raw_socket.recv,4096)
                except (TimeoutError,socket.timeout):
                    continue
                if not chunk:
                    tail = decoder.decode(phase.finish(),final=True)
                    if tail:
                        await asyncio.to_thread(broker.publish,sid,tail)
                    return
                value = decoder.decode(phase.feed(chunk))
                if value:
                    await asyncio.to_thread(broker.publish,sid,value)

        async def write():
            while True:
                value = await asyncio.to_thread(broker.take_input,sid)
                if value:
                    await asyncio.to_thread(raw_socket.sendall,value.encode('utf-8'))
                else:
                    await asyncio.sleep(.05)

        async def exited():
            while True:
                await asyncio.to_thread(container.reload)
                if container.status in ('exited','dead'):
                    return int(container.attrs.get('State',{}).get('ExitCode',1))
                await asyncio.sleep(.1)

        reader, writer, exit_task = [asyncio.create_task(coro) for coro in (read(),write(),exited())]
        tasks = [reader,writer,exit_task]
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        if reader in done:
            reader.result()  # Propagate output/Redis failures immediately.
            done, _ = await asyncio.wait([writer,exit_task], return_when=asyncio.FIRST_COMPLETED)
        if writer in done:
            writer.result()
            raise TerminalClosed()
        code = exit_task.result()
        await asyncio.wait_for(asyncio.shield(reader), timeout=2)
        return {'exit_code':code, 'execution_phase':phase.phase,
            'failure_reason':'memory_limit_exceeded' if container.attrs.get('State',{}).get('OOMKilled') is True else None}
    finally:
        if raw_socket is not None:
            with contextlib.suppress(Exception):
                raw_socket.close()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if container is not None:
            await runner._remove_container(container)
        await runner._remove_workdir(directory)
