from __future__ import annotations

import asyncio
import unittest

from switchtrade.core.contracts import LinkPacket
from switchtrade.endpoints.fake import FAKE_PROTOCOL, FakeEndpointDriver, FakeEndpointHub


class FakeEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_discover_accept_and_local_boundary_exchange(self) -> None:
        hub = FakeEndpointHub()
        origin = FakeEndpointDriver(hub)
        mirror = FakeEndpointDriver(hub)
        await origin.prepare()
        await mirror.prepare()
        local_origin = await origin.discover(asyncio.Event())
        local_mirror = await mirror.accept(local_origin.offer, asyncio.Event())
        packet = LinkPacket(local_origin.offer.generation_id, FAKE_PROTOCOL, b"hello")
        await local_origin.inject_local(packet)
        self.assertEqual(await local_origin.receive(), packet)
        reply = LinkPacket(local_origin.offer.generation_id, FAKE_PROTOCOL, b"world")
        await local_mirror.send(reply)
        self.assertEqual(await local_mirror.receive_delivered(), reply)
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

    async def test_protocol_generation_and_close_boundaries(self) -> None:
        hub = FakeEndpointHub()
        origin = FakeEndpointDriver(hub)
        mirror = FakeEndpointDriver(hub)
        await origin.prepare()
        await mirror.prepare()
        local_origin = await origin.discover(asyncio.Event())
        with self.assertRaises(RuntimeError):
            await mirror.accept(type(local_origin.offer)(local_origin.offer.generation_id, "other.fake.v1", local_origin.offer.origin_endpoint_kind, b""), asyncio.Event())
        local_mirror = await mirror.accept(local_origin.offer, asyncio.Event())
        with self.assertRaises(ValueError):
            await local_origin.send(LinkPacket("wrong", FAKE_PROTOCOL, b"x"))
        for _ in range(32):
            await local_origin.send(LinkPacket(local_origin.offer.generation_id, FAKE_PROTOCOL, b"queued"))
        first = await local_origin.close("full")
        second = await local_origin.close("again")
        self.assertTrue(first.transport_drained)
        self.assertEqual(first.details["discarded_packets"], 32)
        self.assertEqual(second.details["discarded_packets"], 0)
        with self.assertRaises(RuntimeError):
            await local_origin.receive()
        await local_mirror.close("peer_done")

    async def test_discover_and_accept_failures(self) -> None:
        hub = FakeEndpointHub()
        discover = FakeEndpointDriver(hub, fail_discover=True)
        await discover.prepare()
        with self.assertRaises(RuntimeError):
            await discover.discover(asyncio.Event())
        origin = FakeEndpointDriver(hub)
        rejecting = FakeEndpointDriver(hub, fail_accept=True)
        await origin.prepare()
        await rejecting.prepare()
        with self.assertRaises(RuntimeError):
            await rejecting.accept((await origin.discover(asyncio.Event())).offer, asyncio.Event())


if __name__ == "__main__":
    unittest.main()
