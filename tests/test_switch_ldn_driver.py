from __future__ import annotations

import asyncio
import ast
from pathlib import Path
import subprocess
import sys
import unittest

from switchtrade.composition import create_switch_ldn_driver
from switchtrade.connection.stage_session import StageResources, StageSessionError
from switchtrade.core.contracts import EndpointKind, GenerationOffer, GenerationRole, RuntimeKind
from switchtrade.endpoints.switch_ldn import (
    SWITCH_LDN_PROTOCOL,
    SwitchLdnEndpointDriver,
    SwitchLdnEndpointError,
    SwitchLdnPolicy,
)


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
            policy(), stage_factory=stage_factory, session_factory=session_factory
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

    async def test_generation_methods_are_reserved_for_later_phase_packets(self) -> None:
        driver = create_switch_ldn_driver(policy())
        await driver.prepare()
        with self.assertRaises(NotImplementedError):
            await driver.accept(
                GenerationOffer("pending", SWITCH_LDN_PROTOCOL, EndpointKind.SWITCH_LDN, b""),
                asyncio.Event(),
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

    async def test_cleanup_failure_is_preserved_and_blocks_next_generation(self) -> None:
        resources = StageResources(object(), object(), b"advertisement")

        def session_factory(_stage: object, **_kwargs: object) -> FailingStopSession:
            return FailingStopSession(resources)

        driver = SwitchLdnEndpointDriver(
            policy(), stage_factory=lambda _policy: object(), session_factory=session_factory
        )
        await driver.prepare()
        generation = await driver.discover(asyncio.Event())
        first = await generation.close("done")
        second = await generation.close("done")
        self.assertFalse(first.local_resources_released)
        self.assertIs(first, second)
        with self.assertRaisesRegex(SwitchLdnEndpointError, "unverified"):
            await driver.prepare()

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
