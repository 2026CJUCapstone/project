"""Settle a non-cancellable acquisition thread before releasing its resource."""
import asyncio
from contextlib import asynccontextmanager

_cleanup_tasks = set()


async def _cleanup(coroutine):
    task = asyncio.create_task(coroutine)
    _cleanup_tasks.add(task)  # Repeated cancellation must not orphan cleanup.
    def completed(done):
        _cleanup_tasks.discard(done)
        if not done.cancelled():
            done.exception()  # Retrieve failure without logging sensitive values.
    task.add_done_callback(completed)
    cancelled = False
    while True:
        try:
            result = await asyncio.shield(task)
            break
        except asyncio.CancelledError:
            if task.cancelled():
                raise
            cancelled = True
            # Do not let repeated parent cancellation end the event loop while
            # the acquisition thread can still create an owned resource.
    if cancelled:
        raise asyncio.CancelledError
    return result


@asynccontextmanager
async def acquired_in_thread(acquire, release):
    """acquire must unwind partial acquisition if it raises synchronously."""
    acquisition = asyncio.create_task(asyncio.to_thread(acquire))
    try:
        resource = await asyncio.shield(acquisition)
    except asyncio.CancelledError:
        async def after_acquisition():
            try:
                resource = await acquisition
            except BaseException:
                return  # acquire owns partial-failure cleanup.
            await asyncio.to_thread(release, resource)
        try:
            await _cleanup(after_acquisition())
        except asyncio.CancelledError:
            pass  # Repeated cancellation is re-raised only after cleanup settles.
        raise
    else:
        try:
            yield resource
        finally:
            await _cleanup(asyncio.to_thread(release, resource))
