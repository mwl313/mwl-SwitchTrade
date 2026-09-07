import asyncio
import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from switchtrade import parent_lifetime


def test_actual_pipe_eof_cancels_and_awaits_child_cleanup_without_helpers():
    async def exercise():
        read_fd, write_fd = os.pipe()
        released = asyncio.Event()
        with os.fdopen(read_fd, "rb") as stream:
            with patch.object(parent_lifetime, "sys", SimpleNamespace(stdin=stream)):
                async def child():
                    try:
                        await asyncio.Event().wait()
                    finally:
                        await asyncio.sleep(.01)
                        released.set()
                task = asyncio.create_task(parent_lifetime.run_with_parent(child()))
                await asyncio.sleep(.03)
                assert not task.done()
                os.close(write_fd)
                await asyncio.wait_for(task, 1)
        assert released.is_set()
        assert asyncio.all_tasks() == {asyncio.current_task()}
    asyncio.run(exercise())


@pytest.mark.skipif(os.name != "posix", reason="actual Linux process-group/WSL boundary primitive")
@pytest.mark.parametrize("stalled", [False, True])
def test_linux_parent_exit_interrupts_the_owned_gate_before_cli(stalled, tmp_path):
    async def exercise():
        ready, clean = tmp_path / "ready", tmp_path / "clean"
        script = tmp_path / "gate.py"
        script.write_text(
            "import os,signal,time\nfrom pathlib import Path\n"
            + ("signal.signal(signal.SIGINT, signal.SIG_IGN)\n" if stalled else "")
            + f"Path({str(ready)!r}).write_text(str(os.getpid()))\n"
            + "try:\n time.sleep(20)\nexcept KeyboardInterrupt:\n"
            + f" Path({str(clean)!r}).write_text('owned gate cleaned')\n", encoding="utf-8")
        eof = asyncio.Event()
        with patch.object(parent_lifetime, "wait_parent_exit", eof.wait):
            guarding = asyncio.create_task(parent_lifetime.guard_command(
                [sys.executable, str(script)], stop_timeout=.1 if stalled else 2))
            async with asyncio.timeout(3):
                while not ready.exists():
                    await asyncio.sleep(.005)
            pid = int(ready.read_text())
            eof.set()
            result = await asyncio.wait_for(guarding, 3)
        assert result == (1 if stalled else 0)
        assert clean.exists() is not stalled
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
        assert asyncio.all_tasks() == {asyncio.current_task()}
    asyncio.run(exercise())


@pytest.mark.skipif(os.name != "posix", reason="actual Linux group -> real CLI/StageSession")
def test_linux_guardian_eof_cleans_actual_cli_and_stage(tmp_path):
    async def exercise():
        ready, stopped = tmp_path / "ready", tmp_path / "stopped"
        eof = asyncio.Event()
        with patch.object(parent_lifetime, "wait_parent_exit", eof.wait):
            guarding = asyncio.create_task(parent_lifetime.guard_command([
                sys.executable, "-m", "tests.cli_signal_child", str(ready), str(stopped)]))
            async with asyncio.timeout(10):
                while not ready.exists():
                    if guarding.done():
                        pytest.fail(f"CLI exited early: {guarding.result()}")
                    await asyncio.sleep(.01)
            pid = int(ready.read_text())
            eof.set()
            assert await asyncio.wait_for(guarding, 10) == 0
        assert stopped.read_text() == "CTRL_C_CLI_CLEAN"
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
    asyncio.run(exercise())


@pytest.mark.parametrize("external_cancel", [False, True])
def test_cleanup_failure_is_not_a_successful_parent_cancellation(external_cancel):
    async def exercise():
        eof = asyncio.Event()
        entered = asyncio.Event()

        async def child():
            try:
                entered.set()
                await asyncio.Event().wait()
            finally:
                raise RuntimeError("owned cleanup failed")

        with patch.object(parent_lifetime, "wait_parent_exit", eof.wait):
            task = asyncio.create_task(parent_lifetime.run_with_parent(child()))
            await entered.wait()
            if external_cancel:
                task.cancel()
            else:
                eof.set()
            with pytest.raises(RuntimeError, match="owned cleanup failed"):
                await task
        assert asyncio.all_tasks() == {asyncio.current_task()}
    asyncio.run(exercise())


def test_functional_failure_does_not_wait_for_parent_pipe_close():
    async def exercise():
        first = ValueError("first functional failure")

        async def child():
            raise first

        with patch.object(parent_lifetime, "wait_parent_exit", asyncio.Event().wait):
            with pytest.raises(ValueError) as caught:
                await asyncio.wait_for(parent_lifetime.run_with_parent(child()), 1)
        assert caught.value is first
        assert asyncio.all_tasks() == {asyncio.current_task()}
    asyncio.run(exercise())
