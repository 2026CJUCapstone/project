"""Dedicated worker process: python -m app.worker (no HTTP server)."""
import asyncio
import contextlib
import signal

from app.core.config import settings
from app.services.auth import validate_runtime_security
from app.services.contests import contest_maintenance
from app.services.execution_runtime import build_worker
from app.services.housekeeping import retention_maintenance
from app.services.runtime_health import dependencies_ready, report_worker_ready, withdraw_worker
from app.services.runtime_health import start_worker_process, stop_worker_process, ensure_worker_process_registered, revoke_worker_readiness
from app.services.runtime_registry import register_configured_runtime
from app.services.worker_lifecycle import owned_worker_lifecycle


async def health_loop(stop):
    import docker
    while not stop.is_set():
        try:
            await asyncio.to_thread(ensure_worker_process_registered)
            if not await asyncio.to_thread(dependencies_ready, require_worker=False):
                raise RuntimeError('Worker dependencies unavailable')
            def probe():
                client = docker.from_env(timeout=2)
                try:
                    client.ping()
                    client.images.get(settings.SANDBOX_IMAGE)
                finally:
                    client.close()
            await asyncio.to_thread(probe)
            if not stop.is_set():
                await asyncio.to_thread(report_worker_ready)
        except Exception:
            with contextlib.suppress(Exception):
                await asyncio.to_thread(withdraw_worker)
        try:
            await asyncio.wait_for(stop.wait(), timeout=5)
        except TimeoutError:
            pass


async def serve(stop=None):
    validate_runtime_security()
    await asyncio.to_thread(register_configured_runtime)
    if settings.ENVIRONMENT == 'production' and not await asyncio.to_thread(dependencies_ready, require_worker=False):
        raise RuntimeError('Worker requires initialized database and shared Redis')
    async with owned_worker_lifecycle(start_worker_process, stop_worker_process) as lifecycle:
        await serve_registered(stop, lifecycle=lifecycle)


async def serve_registered(stop=None, *, lifecycle=None):
    stop = stop or asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)
    instances = [build_worker() for _ in range(max(1, settings.COMPILER_QUEUE_CONCURRENCY))]
    workers = [asyncio.create_task(instance.run(stop)) for instance in instances]
    maintenance = [asyncio.create_task(contest_maintenance()), asyncio.create_task(retention_maintenance())]
    maintenance.append(asyncio.create_task(health_loop(stop)))
    try:
        await stop.wait()
        if lifecycle is not None:
            await asyncio.to_thread(lifecycle.begin_drain)
        await asyncio.gather(*(asyncio.to_thread(instance.begin_drain) for instance in instances))
        with contextlib.suppress(Exception):
            await asyncio.to_thread(revoke_worker_readiness)
        # No new claims after the durable drain commits. Let prior claims finish;
        # forcibly interrupted claims stay fenced until confirmed recovery.
        try:
            await asyncio.wait_for(asyncio.gather(*workers), timeout=settings.WORKER_DRAIN_SECONDS)
        except TimeoutError:
            pass
    finally:
        for task in workers + maintenance:
            task.cancel()
        await asyncio.gather(*workers, *maintenance, return_exceptions=True)
        with contextlib.suppress(Exception):
            await asyncio.to_thread(withdraw_worker)


if __name__ == '__main__':
    asyncio.run(serve())
