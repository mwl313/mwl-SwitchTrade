"""Core/real StageSession lifecycle checks; not final RFU qualification."""

import asyncio
import contextlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import threading
import unittest

import trio

from switchtrade.connection.stage_session import StageSession
from switchtrade.core.contracts import GenerationEnded, PairCredentials, PairSeat
from switchtrade.core.supervisor import CoreSupervisor, SupervisorError, SupervisorState
from switchtrade.endpoints.switch_ldn.driver import SwitchLdnEndpointDriver
from switchtrade.transport import WireClient
from tests.test_core_supervisor import MemorySocket, TestDriver, TestGeneration, credentials
from tests.test_direct_a_stage import FakeLdn, FakeSTANetwork, _NoopSimulation
from tests.test_direct_b_stage import FakeNetwork, make_stage
from tests import test_direct_a_stage as a_helpers, test_direct_b_stage as b_helpers
from tests.test_direct_resource_ownership import stage_for


class LocalLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_during_clean_retry_stop_awaits_the_actual_stage_owner(self):
        # Exceed the helper policy's old one-second readiness ceiling on purpose.
        await self._exercise_stop_race(scan_delay=1.1)

    async def test_cancel_during_retry_stop_retains_actual_cleanup_failure(self):
        await self._exercise_stop_race(dirty=True)

    async def test_cancel_during_fatal_stage_stop_preserves_primary(self):
        await self._exercise_stop_race(fatal=True)

    async def test_cancel_during_fatal_stage_stop_preserves_primary_and_cleanup(self):
        await self._exercise_stop_race(fatal=True, dirty=True)

    async def _exercise_stop_race(self, *, fatal=False, dirty=False, scan_delay=0):
        entered, release = threading.Event(), threading.Event()
        sessions = []

        class Ldn(FakeLdn):
            rooms = []

            @classmethod
            async def scan(cls, *_args):
                await trio.sleep(scan_delay)
                return []

            @staticmethod
            def load_keys(path):
                return {} if fatal else FakeLdn.load_keys(path)

        class PausedStopSession(StageSession):
            def stop(self):
                sessions.append(self)
                entered.set()
                if not release.wait(10):
                    raise RuntimeError("test did not release stop owner")
                result = super().stop()
                if dirty:
                    raise OSError("injected stop failure")
                return result

        driver = SwitchLdnEndpointDriver(
            replace(a_helpers.DirectADriverLifecycleTests()._policy(), session_timeout=None),
            stage_factory=lambda _: stage_for(Ldn), session_factory=PausedStopSession,
            simulation_factory=lambda *_: _NoopSimulation())
        await driver.prepare()
        discovery = asyncio.create_task(driver.discover(asyncio.Event()))
        try:
            self.assertTrue(await asyncio.to_thread(entered.wait, 10))
            self.assertEqual(len(sessions), 1)
            self.assertIsNone(sessions[0].timeout)  # Production human-wait policy.
            self.assertEqual(sessions[0].report["failure"]["code"],
                             "A_KEYS_INVALID" if fatal else "A_ROOM_NOT_OBSERVED")
            discovery.cancel()
            await asyncio.sleep(.02)
            self.assertFalse(discovery.done(), "cancellation orphaned the stop owner")
            discovery.cancel()  # Repeated cancellation still cannot orphan cleanup.
            await asyncio.sleep(.02)
            self.assertFalse(discovery.done())
            release.set()
            with self.assertRaises(Exception if fatal else asyncio.CancelledError) as failed:
                await asyncio.wait_for(discovery, 5)
            if fatal:
                self.assertEqual(failed.exception.code, "A_KEYS_INVALID")
        finally:
            release.set()
            await asyncio.gather(discovery, return_exceptions=True)
            report = await driver.close()
        self.assertEqual(report.local_resources_released, not dirty, report.details)
        if dirty:
            with self.assertRaisesRegex(Exception, "prior Switch LDN cleanup is unverified"):
                await driver.prepare()

    async def test_invite_expiry_is_not_confused_with_an_already_consumed_pair(self):
        for joined in (False, True):
            wire = WireClient(PairSeat.HOST)
            socket = MemorySocket()
            socket.peer = MemorySocket()
            await wire.connect(socket)

            class Ldn(FakeLdn):
                rooms = []

            driver = SwitchLdnEndpointDriver(
                a_helpers.DirectADriverLifecycleTests()._policy(),
                stage_factory=lambda _: stage_for(Ldn), session_factory=StageSession,
                simulation_factory=lambda *_: _NoopSimulation())

            async def confirm_joined():
                return joined

            host = CoreSupervisor(credentials(PairSeat.HOST), driver, wire,
                invite_expires_at=(datetime.now(UTC) + timedelta(seconds=.03)).isoformat(),
                confirm_peer_joined=confirm_joined)
            pending = asyncio.create_task(host.discover_local())
            try:
                if joined:
                    await asyncio.sleep(.08)
                    self.assertFalse(pending.done())
                else:
                    with self.assertRaisesRegex(SupervisorError, "S_PAIR_CODE_EXPIRED"):
                        await asyncio.wait_for(pending, 1)
            finally:
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
                await host.stop()
            self.assertTrue((await driver.close()).local_resources_released)

    async def asyncSetUp(self):
        self.left, self.right = MemorySocket(), MemorySocket()
        self.left.peer, self.right.peer = self.right, self.left
        self.host_wire, self.guest_wire = WireClient(PairSeat.HOST), WireClient(PairSeat.GUEST)
        await self.host_wire.connect(self.left)
        await self.guest_wire.connect(self.right)
        self.owners = []

    async def asyncTearDown(self):
        await asyncio.gather(*(owner.stop() for owner in self.owners), return_exceptions=True)
        await asyncio.gather(self.host_wire.close(), self.guest_wire.close())
        self.assertFalse(any(t.name == "switchtrade-direct-stage" for t in threading.enumerate()))

    async def wait_state(self, supervisor, state):
        async with asyncio.timeout(2):
            while supervisor.state != state:
                await asyncio.sleep(.001)

    def host_driver(self, ended):
        class Network(FakeSTANetwork):
            async def next_event(self):
                while not ended.is_set():
                    await trio.sleep(.001)
                return FakeLdn.DisconnectEvent()

        class Ldn(FakeLdn):
            STANetwork = Network

        return SwitchLdnEndpointDriver(
            a_helpers.DirectADriverLifecycleTests()._policy(), stage_factory=lambda _: stage_for(Ldn),
            session_factory=StageSession, simulation_factory=lambda *_: _NoopSimulation())

    async def test_room_end_closes_actual_stage_and_same_pair_can_admit_again(self):
        ended = threading.Event()
        driver = self.host_driver(ended)
        host = CoreSupervisor(credentials(PairSeat.HOST), driver, self.host_wire)
        first_offer = await host.discover_local()
        guest_driver = TestDriver(TestGeneration(first_offer))
        guest = CoreSupervisor(credentials(PairSeat.GUEST), guest_driver, self.guest_wire)
        self.owners.extend((host, guest))
        await asyncio.wait_for(asyncio.gather(host.offer_generation(), guest.accept_next_offer()), 2)
        ended.set()  # Physical local LDN DisconnectEvent, not close_generation().
        await asyncio.wait_for(asyncio.gather(host.wait_generation_end(), guest.wait_generation_end()), 2)
        self.assertEqual((host.state, guest.state), (SupervisorState.PAIRED, SupervisorState.PAIRED))
        self.assertIsNone(host.generation_id)
        self.assertIsNone(guest.generation_id)
        ended.clear()
        second_offer = await host.discover_local()
        self.assertNotEqual(second_offer.generation_id, first_offer.generation_id)
        await asyncio.wait_for(asyncio.gather(host.offer_generation(), guest.accept_next_offer()), 2)
        self.assertEqual(host.credentials.pair_id, guest.credentials.pair_id)
        ended.set()
        await asyncio.wait_for(asyncio.gather(host.wait_generation_end(), guest.wait_generation_end()), 2)

    async def test_room_end_while_negotiating_aborts_offer_without_stale_accept(self):
        ended = threading.Event()
        host = CoreSupervisor(credentials(PairSeat.HOST), self.host_driver(ended), self.host_wire)
        self.owners.append(host)
        offering = asyncio.create_task(host.offer_generation())
        frame = await self.guest_wire.receive(timeout=2)
        ended.set()
        with self.assertRaises(GenerationEnded):
            await asyncio.wait_for(offering, 2)
        closed = await self.guest_wire.receive(timeout=2)
        self.assertEqual(frame.generation_id, closed.generation_id)
        self.assertEqual(closed.kind.name, "GENERATION_CLOSE")
        self.assertIsNone(host.failure)

    async def test_opening_direct_b_is_interrupted_by_transport_or_lease(self):
        for cause in ("transport", "lease"):
            with self.subTest(cause=cause):
                waiting = threading.Event()
                stages = []

                class Network(FakeNetwork):
                    async def next_event(self):
                        waiting.set()
                        await trio.sleep_forever()

                def factory(_policy, _offer):
                    stage = make_stage(association_timeout=None)

                    @contextlib.asynccontextmanager
                    async def network_factory(_param):
                        stage.compatibility = dict.fromkeys(stage.compatibility, True)
                        yield Network((stage.ap_ifname, stage.monitor_ifname, stage.tap_ifname)), trio.Event()

                    stage.network_factory = network_factory
                    stages.append(stage)
                    return stage

                driver = SwitchLdnEndpointDriver(
                    b_helpers.DirectBDriverCancellationTests()._policy(session_timeout=None),
                    mirror_stage_factory=factory, session_factory=StageSession,
                    simulation_factory=lambda *_: _NoopSimulation())
                creds = credentials(PairSeat.GUEST)
                if cause == "lease":
                    creds = PairCredentials(creds.pair_id, creds.seat, creds.access_token,
                        (datetime.now(UTC) + timedelta(seconds=.3)).isoformat())
                guest = CoreSupervisor(creds, driver, self.guest_wire)
                self.owners.append(guest)
                accepting = asyncio.create_task(guest.accept_next_offer())
                await self.host_wire.wait_ready()
                from switchtrade.core.supervisor import _offer_payload
                from switchtrade.transport import FrameKind
                offer = b_helpers.DirectBDriverCancellationTests()._offer()
                await self.host_wire.send(FrameKind.GENERATION_OFFER, offer.generation_id, _offer_payload(offer))
                self.assertTrue(await asyncio.to_thread(waiting.wait, 2))
                if cause == "lease":
                    await asyncio.sleep(.4)
                    self.assertFalse(accepting.done(), "a reconnect lease is not an active-stream TTL")
                await self.right.incoming.put(ConnectionError("lost while opening"))
                with self.assertRaises(SupervisorError) as caught:
                    await asyncio.wait_for(accepting, 2)
                self.assertEqual(caught.exception.code, "S_TRANSPORT_FAILED" if cause == "transport" else "S_PAIR_LEASE_EXPIRED")
                self.assertTrue(stages[0].cleanup["ldn_context_released"])
                self.assertTrue((await driver.close()).local_resources_released)
                await guest.stop()
                self.owners.remove(guest)
                await self.host_wire.close()
                await self.guest_wire.close()
                self.left, self.right = MemorySocket(), MemorySocket()
                self.left.peer, self.right.peer = self.right, self.left
                await self.host_wire.connect(self.left)
                await self.guest_wire.connect(self.right)
