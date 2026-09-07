"""Owned console child: actual Core CLI cancellation, with virtual Linux OS."""

import asyncio
from contextlib import ExitStack, nullcontext
import os
from pathlib import Path
import socket
import sys
import threading
from types import SimpleNamespace
from unittest.mock import patch

import uvicorn

from tests.virtual_ldn_os import VirtualLdnOS
from relay.core_server import create_app
from switchtrade import core_cli


def main():
    ready, stopped = map(Path, sys.argv[1:])
    kernel = VirtualLdnOS()
    with ExitStack() as stack:
        kernel.install(stack)
        stack.enter_context(patch.dict(os.environ, {
            "SWITCHTRADE_USB_ID": "0bda:818b", "SWITCHTRADE_PHY": "phy0",
            "SWITCHTRADE_IFACE": "proven0", "SWITCHTRADE_P0_TARGET_CHANNEL": "6",
            "SWITCHTRADE_PARENT_STDIN": os.environ.get("SWITCHTRADE_PARENT_STDIN", "0"),
            "SWITCHTRADE_P0_RX_PASSED": "1", "SWITCHTRADE_KEYS": "/synthetic-test.keys"}))

        async def run():
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
            server = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=port,
                log_level="critical", access_log=False))
            # The real deployment's relay is a separate process. Its fixture
            # must not steal the actual CLI process's Windows Ctrl+C handler.
            server.capture_signals = nullcontext
            serving = asyncio.create_task(server.serve())
            while not server.started:
                await asyncio.sleep(.01)

            async def announce():
                while not kernel.links:
                    await asyncio.sleep(.01)
                ready.write_text(str(os.getpid()), encoding="ascii")

            announcing = asyncio.create_task(announce())
            try:
                async with asyncio.timeout(20):
                    await core_cli.run(SimpleNamespace(command="host", relay=f"http://127.0.0.1:{port}",
                        usb_id="0bda:818b", channel=6, verbose=False, log_dir=None))
            finally:
                announcing.cancel()
                await asyncio.gather(announcing, return_exceptions=True)
                server.should_exit = True
                await serving

        try:
            asyncio.run(run())
        except KeyboardInterrupt:
            pass
        kernel.assert_clean()
        assert not any(t.name.startswith("switchtrade-") for t in threading.enumerate())
        stopped.write_text("CTRL_C_CLI_CLEAN", encoding="ascii")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
