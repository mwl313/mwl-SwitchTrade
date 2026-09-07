"""Read-only parent-lifetime pipe. No console signal or orphan reader thread."""

import asyncio
import os
import select
import signal
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


async def guard_command(arguments, *, stop_timeout=20):
    """Own the entire Linux radio-gate -> CLI process group, from first exec.

    Closing the Windows wrapper while radio preparation is pending must not
    leave that preparation running until a future CLI happens to read EOF.
    """
    if os.name != "posix" or not arguments:
        raise RuntimeError("PARENT_COMMAND_REQUIRES_LINUX")
    child = await asyncio.create_subprocess_exec(
        *arguments, start_new_session=True, stdin=asyncio.subprocess.DEVNULL,
        env={**os.environ, "SWITCHTRADE_PARENT_STDIN": "0"})
    exited = asyncio.create_task(child.wait())
    parent = asyncio.create_task(wait_parent_exit())
    forced = False
    try:
        done, _ = await asyncio.wait((exited, parent), return_when=asyncio.FIRST_COMPLETED)
        if exited not in done:
            parent.result()
    finally:
        parent.cancel()
        await asyncio.gather(parent, return_exceptions=True)
        if child.returncode is None:
            # start_new_session makes this exact child the group owner. No
            # process-name search, user process group or ambient shell is used.
            try:
                os.killpg(child.pid, signal.SIGINT)
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(asyncio.shield(exited), stop_timeout)
            except TimeoutError:
                print("DEV_CHILD_CLEANUP_UNVERIFIED: owned Linux group did not stop; do not retry", file=sys.stderr)
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await exited
                forced = True
        else:
            await exited
    if forced:
        return 1  # Forced process exit is never local-radio cleanup proof.
    return child.returncode if child.returncode >= 0 else 128 - child.returncode


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["--"]:
        arguments.pop(0)
    try:
        return asyncio.run(guard_command(arguments))
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        print(f"DEV_PARENT_CONTROL_FAILED: {type(error).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
