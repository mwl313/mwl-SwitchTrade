from __future__ import annotations

import asyncio
import unittest

from switchtrade.core.contracts import LinkPacket
from switchtrade.endpoints.fake import FAKE_PROTOCOL, FakeEndpointDriver, FakeEndpointHub


class FakeEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_discover_accept_and_opaque_exchange(self) -> None:
        hub = FakeEndpointHub()
        origin = FakeEndpointDriver(hub)
        mirror = FakeEndpointDriver(hub)
        await origin.prepare()
        await mirror.prepare()
        local_origin = await origin.discover(asyncio.Event())
        local_mirror = await mirror.accept(local_origin.offer, asyncio.Event())
        packet = LinkPacket(local_origin.offer.generation_id, FAKE_PROTOCOL, b"hello")
        await local_origin.send(packet)
        self.assertEqual(await local_mirror.receive(), packet)
        reply = LinkPacket(local_origin.offer.generation_id, FAKE_PROTOCOL, b"world")
        await local_mirror.send(reply)
        self.assertEqual(await local_origin.receive(), reply)
        self.assertTrue((await local_origin.close("done")).endpoint_stopped)
        self.assertTrue((await local_mirror.close("done")).local_resources_released)

    async def test_cancellation_and_injected_failure_stop_admission(self) -> None:
        cancel = asyncio.Event()
        cancel.set()
        driver = FakeEndpointDriver(FakeEndpointHub(), fail_prepare=True)
        with self.assertRaises(RuntimeError):
            await driver.prepare()
        healthy = FakeEndpointDriver(FakeEndpointHub())
        await healthy.prepare()
        with self.assertRaises(asyncio.CancelledError):
            await healthy.discover(cancel)


if __name__ == "__main__":
    unittest.main()
