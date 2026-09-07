"""Read-only parent-lifetime pipe. No console signal or orphan reader thread."""

import asyncio
import os
import select
import sys


async def wait_parent_exit():
    """The dev wrapper holds stdin open; its close/exit is cancellation, not UI."""
    fd = sys.stdin.fileno()
    while True:
        if os.name == "nt":
            import _winapi
            import msvcrt

            try:
                available, _remaining = _winapi.PeekNamedPipe(msvcrt.get_osfhandle(fd), 0)
            except BrokenPipeError:
                return
            readable = available > 0
        else:
            readable = bool(select.select([fd], [], [], 0)[0])
        if readable:
            if not os.read(fd, 1):
                return
            raise RuntimeError("PARENT_CONTROL_INVALID: lifetime pipe must contain no input")
        await asyncio.sleep(.05)


async def run_with_parent(operation):
    """Keep the first operation failure, and await owned cancellation cleanup."""
    running = asyncio.create_task(operation)
    parent = asyncio.create_task(wait_parent_exit())
    primary = None
    try:
        done, _ = await asyncio.wait((running, parent), return_when=asyncio.FIRST_COMPLETED)
        if running in done:
            return await running
        try:
            parent.result()
        finally:
            running.cancel()
        try:
            return await running
        except asyncio.CancelledError:
            return None
    except BaseException as error:
        primary = error
        raise
    finally:
        for task in (running, parent):
            if not task.done():
                task.cancel()
        result, _ = await asyncio.gather(running, parent, return_exceptions=True)
        if (isinstance(primary, asyncio.CancelledError) and isinstance(result, BaseException)
                and not isinstance(result, asyncio.CancelledError)):
            # Ctrl+C is normal only when the CLI's owned cleanup succeeded.
            raise result
        if primary is not None and isinstance(result, Exception) and result is not primary:
            primary.add_note("child cleanup failed: " + type(result).__name__)
