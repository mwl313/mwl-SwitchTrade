import asyncio
import os
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
