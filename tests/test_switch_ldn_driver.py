from __future__ import annotations

import asyncio
import ast
from pathlib import Path
import subprocess
import sys
import unittest

from switchtrade.composition import create_switch_ldn_driver
from switchtrade.core.contracts import EndpointKind, GenerationOffer, GenerationRole, RuntimeKind
from switchtrade.endpoints.switch_ldn import SWITCH_LDN_PROTOCOL, SwitchLdnEndpointDriver


ROOT = Path(__file__).resolve().parents[1]


class SwitchLdnDriverBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_driver_exposes_phase_b_capabilities_and_empty_cleanup(self) -> None:
        driver = SwitchLdnEndpointDriver()
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
        driver = create_switch_ldn_driver()
        with self.assertRaises(NotImplementedError):
            await driver.discover(asyncio.Event())
        offer = GenerationOffer("pending", SWITCH_LDN_PROTOCOL, EndpointKind.SWITCH_LDN, b"")
        with self.assertRaises(NotImplementedError):
            await driver.accept(offer, asyncio.Event())

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
