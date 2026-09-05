from __future__ import annotations

import asyncio
import ast
from pathlib import Path
import subprocess
import sys
import threading
import unittest

from switchtrade.connection.stage_session import StageResources, StageSessionError
from switchtrade.core.contracts import EndpointKind, GenerationOffer, GenerationRole, LinkPacket, RuntimeKind
from switchtrade.endpoints.switch_ldn import (
    SWITCH_LDN_PROTOCOL,
    SwitchLdnEndpointDriver,
    SwitchLdnEndpointError,
    SwitchLdnPolicy,
)
from switchtrade.endpoints.switch_ldn.generation import build_tunnelsim
from switchtrade.endpoints.switch_ldn.tunnel_adapter import CoreTunnelAdapter


ROOT = Path(__file__).resolve().parents[1]


def policy(**changes: object) -> SwitchLdnPolicy:
    values: dict[str, object] = {
        "run_id": "c2-test",
        "release": "test-release",
        "usb_id": "0bda:818b",
        "hardware_profile": "rtl8192eu",
        "phy": "phy7",
        "ifname": "sta-c2-test",
        "keys_path": "/runtime/config/prod.keys",
    }
    values.update(changes)
    return SwitchLdnPolicy(**values)


class FakeSession:
    def __init__(self, outcome: StageResources | BaseException) -> None:
        self.outcome = outcome
        self.started = False
        self.stopped = False

    def start(self) -> "FakeSession":
        self.started = True
        return self

    def wait_ready(self) -> StageResources:
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome

    def stop(self) -> None:
        self.stopped = True


class FailingStopSession(FakeSession):
    def stop(self) -> None:
        self.stopped = True
        raise RuntimeError("cleanup failed")


class BlockingSession(FakeSession):
    def __init__(self) -> None:
        super().__init__(StageResources(object(), object(), b"late"))
        self.waiting = threading.Event()
        self.released = threading.Event()

    def wait_ready(self) -> StageResources:
        self.waiting.set()
        self.released.wait()
        return super().wait_ready()

    def stop(self) -> None:
        self.stopped = True
        self.released.set()


class FakeSimulation:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakePiaTransport:
    ssid = b"0123456789abcdef"
    our_mac = b"\x01\x02\x03\x04\x05\x06"
    host_mac = b"\x06\x05\x04\x03\x02\x01"
    our_ip = "169.254.1.2"
    host_ip = "169.254.1.1"


def simulation_factory(
    _resources: StageResources, _tunnel: object, _parent: bool
) -> FakeSimulation:
    return FakeSimulation()


def driver_with_outcomes(*outcomes: StageResources | BaseException) -> tuple[SwitchLdnEndpointDriver, list[object], list[FakeSession]]:
    stages: list[object] = []
    sessions: list[FakeSession] = []
    pending = iter(outcomes)

    def stage_factory(_policy: SwitchLdnPolicy) -> object:
        stage = object()
        stages.append(stage)
        return stage

    def session_factory(_stage: object, **_kwargs: object) -> FakeSession:
        session = FakeSession(next(pending))
        sessions.append(session)
        return session

    return (
        SwitchLdnEndpointDriver(
            policy(), stage_factory=stage_factory, session_factory=session_factory,
            simulation_factory=simulation_factory,
        ),
        stages,
        sessions,
    )


class SwitchLdnDriverBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_driver_exposes_phase_b_capabilities_and_empty_cleanup(self) -> None:
        driver = SwitchLdnEndpointDriver(policy())
        self.assertEqual(driver.capabilities.endpoint_kind, EndpointKind.SWITCH_LDN)
        self.assertEqual(driver.capabilities.runtime_kind, RuntimeKind.MANAGED_WSL)
        self.assertEqual(driver.capabilities.protocols, (SWITCH_LDN_PROTOCOL,))
        self.assertEqual(
            driver.capabilities.generation_roles,
            (GenerationRole.ORIGIN, GenerationRole.MIRROR),
        )
        await driver.prepare()
        report = await driver.close()
        self.assertTrue(
            report.endpoint_stopped
            and report.local_resources_released
            and report.transport_drained
        )

    async def test_leader_retries_with_fresh_stage_after_no_room(self) -> None:
        resources = StageResources(object(), object(), b"advertisement")
        driver, stages, sessions = driver_with_outcomes(
            StageSessionError("A_ROOM_NOT_OBSERVED", "A1_RADIO_SCAN", "no room"), resources
        )
        await driver.prepare()
        generation = await driver.discover(asyncio.Event())
        self.assertEqual(len(stages), 2)
        self.assertTrue(sessions[0].stopped)
        self.assertIs(generation.offer.origin_endpoint_kind, EndpointKind.SWITCH_LDN)
        self.assertEqual(generation.offer.protocol_id, SWITCH_LDN_PROTOCOL)
        self.assertEqual(generation.offer.setup_payload, b"advertisement")
        self.assertFalse(sessions[1].stopped)
        self.assertTrue((await generation.close("done")).local_resources_released)
        self.assertTrue(sessions[1].stopped)

    async def test_leader_preserves_fatal_error_after_cleanup(self) -> None:
        failure = StageSessionError("A_ROOM_AMBIGUOUS", "A2_ROOM_IDENTIFICATION", "ambiguous")
        driver, stages, sessions = driver_with_outcomes(failure)
        await driver.prepare()
        with self.assertRaisesRegex(StageSessionError, "ambiguous") as caught:
            await driver.discover(asyncio.Event())
        self.assertIs(caught.exception, failure)
        self.assertEqual(len(stages), 1)
        self.assertTrue(sessions[0].stopped)

    async def test_cancellation_and_invalid_policy_do_not_start_a_stage(self) -> None:
        driver, stages, _sessions = driver_with_outcomes()
        await driver.prepare()
        cancel = asyncio.Event()
        cancel.set()
        with self.assertRaises(asyncio.CancelledError):
            await driver.discover(cancel)
        self.assertEqual(stages, [])
        invalid = SwitchLdnEndpointDriver(policy(usb_id="invalid"))
        with self.assertRaisesRegex(SwitchLdnEndpointError, "policy"):
            await invalid.prepare()

    async def test_cancellation_while_waiting_stops_session_without_generation(self) -> None:
        session = BlockingSession()
        driver = SwitchLdnEndpointDriver(
            policy(), stage_factory=lambda _policy: object(), session_factory=lambda *_args, **_kwargs: session,
            simulation_factory=simulation_factory,
        )
        await driver.prepare()
        cancel = asyncio.Event()
        discovery = asyncio.create_task(driver.discover(cancel))
        await asyncio.wait_for(asyncio.to_thread(session.waiting.wait), timeout=1)
        cancel.set()
        with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(discovery, timeout=1)
        self.assertTrue(session.stopped)
        report = await driver.close()
        self.assertTrue(report.endpoint_stopped)
        self.assertTrue(report.local_resources_released)

    async def test_cleanup_failure_is_preserved_and_blocks_next_generation(self) -> None:
        resources = StageResources(object(), object(), b"advertisement")

        def session_factory(_stage: object, **_kwargs: object) -> FailingStopSession:
            return FailingStopSession(resources)

        driver = SwitchLdnEndpointDriver(
            policy(), stage_factory=lambda _policy: object(), session_factory=session_factory,
            simulation_factory=simulation_factory,
        )
        await driver.prepare()
        generation = await driver.discover(asyncio.Event())
        first = await generation.close("done")
        second = await generation.close("done")
        self.assertFalse(first.local_resources_released)
        self.assertIs(first, second)
        with self.assertRaisesRegex(SwitchLdnEndpointError, "unverified"):
            await driver.prepare()

    async def test_failed_attempt_cleanup_blocks_discover_and_empty_close(self) -> None:
        failure = StageSessionError("A_ROOM_NOT_OBSERVED", "A1_RADIO_SCAN", "no room")
        stages: list[object] = []

        def stage_factory(_policy: SwitchLdnPolicy) -> object:
            stage = object()
            stages.append(stage)
            return stage

        driver = SwitchLdnEndpointDriver(
            policy(), stage_factory=stage_factory, session_factory=lambda *_args, **_kwargs: FailingStopSession(failure),
            simulation_factory=simulation_factory,
        )
        await driver.prepare()
        with self.assertRaisesRegex(StageSessionError, "no room"):
            await driver.discover(asyncio.Event())
        with self.assertRaisesRegex(SwitchLdnEndpointError, "unverified"):
            await driver.discover(asyncio.Event())
        self.assertEqual(len(stages), 1)
        report = await driver.close()
        self.assertFalse(report.endpoint_stopped)
        self.assertFalse(report.local_resources_released)

    async def test_mirror_starts_direct_b_only_after_a_supported_offer(self) -> None:
        resources = StageResources(object(), object(), b"ignored")
        stages: list[tuple[SwitchLdnPolicy, GenerationOffer]] = []
        sessions: list[FakeSession] = []
        simulations: list[tuple[object, bool, FakeSimulation]] = []

        def mirror_factory(value: SwitchLdnPolicy, offer: GenerationOffer) -> object:
            stages.append((value, offer))
            return object()

        def session_factory(_stage: object, **_kwargs: object) -> FakeSession:
            session = FakeSession(resources)
            sessions.append(session)
            return session

        def make_simulation(_resources: StageResources, tunnel: object, parent: bool) -> FakeSimulation:
            simulation = FakeSimulation()
            simulations.append((tunnel, parent, simulation))
            return simulation

        driver = SwitchLdnEndpointDriver(
            policy(), mirror_stage_factory=mirror_factory, session_factory=session_factory,
            simulation_factory=make_simulation,
        )
        await driver.prepare()
        unsupported = GenerationOffer("bad", "switchtrade.fake.v1", EndpointKind.FAKE, b"no-ap")
        with self.assertRaises(SwitchLdnEndpointError) as raised:
            await driver.accept(unsupported, asyncio.Event())
        self.assertEqual(raised.exception.code, "SWITCH_ENDPOINT_PROTOCOL_MISMATCH")
        self.assertEqual(stages, [])

        offer = GenerationOffer("mirror-1", SWITCH_LDN_PROTOCOL, EndpointKind.SWITCH_LDN, b"opaque-ad")
        generation = await driver.accept(offer, asyncio.Event())
        self.assertEqual(stages, [(driver._policy, offer)])
        self.assertEqual(len(sessions), 1)
        self.assertTrue(generation.parent)
        self.assertTrue(simulations[0][1])

        generation.tunnel.send_rfu(b"local-rfu", flags=0x0100)
        self.assertEqual(
            await generation.receive(),
            LinkPacket("mirror-1", SWITCH_LDN_PROTOCOL, b"local-rfu", 0x0100),
        )
        await generation.send(LinkPacket("mirror-1", SWITCH_LDN_PROTOCOL, b"remote-rfu", 0xFFFF))
        self.assertEqual(
            [(frame.payload, frame.flags) for frame in generation.tunnel.poll()],
            [(b"remote-rfu", 0xFFFF)],
        )
        report = await generation.close("done")
        self.assertTrue(report.local_resources_released)
        self.assertTrue(sessions[0].stopped)
        self.assertTrue(simulations[0][2].closed)

    async def test_mirror_preserves_direct_b_failure_after_cleanup(self) -> None:
        failure = StageSessionError("B_SWITCH_ASSOCIATION_TIMEOUT", "B6_SWITCH_ASSOCIATION", "join timed out")
        session = FakeSession(failure)
        driver = SwitchLdnEndpointDriver(
            policy(), mirror_stage_factory=lambda *_args: object(),
            session_factory=lambda *_args, **_kwargs: session,
            simulation_factory=simulation_factory,
        )
        await driver.prepare()
        offer = GenerationOffer("mirror-error", SWITCH_LDN_PROTOCOL, EndpointKind.SWITCH_LDN, b"opaque-ad")
        with self.assertRaisesRegex(StageSessionError, "join timed out") as raised:
            await driver.accept(offer, asyncio.Event())
        self.assertIs(raised.exception, failure)
        self.assertTrue(session.stopped)

    async def test_mirror_simulation_setup_failure_releases_ready_direct_b_session(self) -> None:
        session = FakeSession(StageResources(object(), object(), b"ignored"))

        def fail_simulation(*_args: object) -> FakeSimulation:
            raise RuntimeError("TunnelSim unavailable")

        driver = SwitchLdnEndpointDriver(
            policy(), mirror_stage_factory=lambda *_args: object(),
            session_factory=lambda *_args, **_kwargs: session,
            simulation_factory=fail_simulation,
        )
        await driver.prepare()
        offer = GenerationOffer("mirror-sim-error", SWITCH_LDN_PROTOCOL, EndpointKind.SWITCH_LDN, b"opaque-ad")
        with self.assertRaisesRegex(RuntimeError, "TunnelSim unavailable"):
            await driver.accept(offer, asyncio.Event())
        self.assertTrue(session.stopped)

    def test_default_tunnelsim_maps_leader_and_mirror_to_the_existing_pia_roles(self) -> None:
        resources = StageResources(object(), FakePiaTransport(), b"opaque-ad")
        leader = build_tunnelsim(
            resources, CoreTunnelAdapter("leader", SWITCH_LDN_PROTOCOL), parent=False
        )
        mirror = build_tunnelsim(
            resources, CoreTunnelAdapter("mirror", SWITCH_LDN_PROTOCOL), parent=True
        )
        self.assertFalse(leader.parent)
        self.assertTrue(mirror.parent)
        self.assertEqual(type(leader.conn).__name__, "ConnectionManager")
        self.assertEqual(type(mirror.conn).__name__, "HostConnectionManager")
        leader.close()
        mirror.close()

    def test_fake_endpoint_import_does_not_load_switch_driver(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; import switchtrade.endpoints.fake; "
                "assert 'switchtrade.endpoints.switch_ldn' not in sys.modules",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_core_and_relay_do_not_import_the_switch_driver(self) -> None:
        for directory in (ROOT / "switchtrade" / "core", ROOT / "relay"):
            for source in directory.rglob("*.py"):
                tree = ast.parse(source.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        modules = (item.name for item in node.names)
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        modules = (node.module,)
                    else:
                        continue
                    self.assertFalse(
                        any(
                            module == "switchtrade.endpoints.switch_ldn"
                            or module.startswith("switchtrade.endpoints.switch_ldn.")
                            for module in modules
                        ),
                        source,
                    )


if __name__ == "__main__":
    unittest.main()
