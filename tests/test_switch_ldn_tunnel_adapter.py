from __future__ import annotations

import asyncio
import ast
from pathlib import Path
import threading
import unittest

from switchtrade.core.contracts import LinkPacket
from switchtrade.endpoints.switch_ldn import SWITCH_LDN_PROTOCOL, SwitchLdnEndpointError
from switchtrade.endpoints.switch_ldn.tunnel_adapter import CoreTunnelAdapter


ROOT = Path(__file__).resolve().parents[1]


class CoreTunnelAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_maps_opaque_rfu_payload_and_full_core_flags(self) -> None:
        adapter = CoreTunnelAdapter("generation-1", SWITCH_LDN_PROTOCOL)
        adapter.send_rfu(b"\x57opaque-local", flags=0x0100)
        self.assertEqual(
            await adapter.receive_for_core(),
            LinkPacket("generation-1", SWITCH_LDN_PROTOCOL, b"\x57opaque-local", 0x0100),
        )
        await adapter.deliver_from_core(
            LinkPacket("generation-1", SWITCH_LDN_PROTOCOL, b"\x58opaque-remote", 0xFFFF)
        )
        self.assertEqual(
            [(frame.payload, frame.flags, frame.kind.name) for frame in adapter.poll()],
            [(b"\x58opaque-remote", 0xFFFF, "RFU")],
        )

    async def test_rejects_stale_packets_and_discards_queues_on_reset(self) -> None:
        adapter = CoreTunnelAdapter("generation-1", SWITCH_LDN_PROTOCOL, capacity=1)
        await adapter.deliver_from_core(
            LinkPacket("generation-1", SWITCH_LDN_PROTOCOL, b"stale-remote", 0x01)
        )
        adapter.send_rfu(b"stale-local", flags=0x01)
        first_connection = adapter.connection_generation
        adapter.reset("generation-2")
        self.assertGreater(adapter.connection_generation, first_connection)
        self.assertEqual(adapter.poll(), [])
        with self.assertRaises(SwitchLdnEndpointError) as raised:
            await adapter.deliver_from_core(
                LinkPacket("generation-1", SWITCH_LDN_PROTOCOL, b"old-link", 0x01)
            )
        self.assertEqual(raised.exception.code, "SWITCH_ENDPOINT_GENERATION_MISMATCH")
        adapter.send_rfu(b"fresh-local", flags=0x01)
        self.assertEqual((await adapter.receive_for_core()).generation_id, "generation-2")

    async def test_bounds_apply_backpressure_before_dropping_rfu_state(self) -> None:
        adapter = CoreTunnelAdapter("generation-1", SWITCH_LDN_PROTOCOL, capacity=1)
        adapter.send_rfu(b"first", flags=0x01)
        with self.assertRaises(SwitchLdnEndpointError) as raised:
            adapter.send_rfu(b"overflow", flags=0x01)
        self.assertEqual(raised.exception.code, "SWITCH_ENDPOINT_BACKPRESSURE")
        self.assertEqual((await adapter.receive_for_core()).payload, b"first")

        await adapter.deliver_from_core(
            LinkPacket("generation-1", SWITCH_LDN_PROTOCOL, b"first-remote", 0x01)
        )
        with self.assertRaises(SwitchLdnEndpointError) as raised:
            await adapter.deliver_from_core(
                LinkPacket("generation-1", SWITCH_LDN_PROTOCOL, b"overflow-remote", 0x01)
            )
        self.assertEqual(raised.exception.code, "SWITCH_ENDPOINT_BACKPRESSURE")
        self.assertEqual([frame.payload for frame in adapter.poll()], [b"first-remote"])

    async def test_tunnelsim_thread_can_signal_the_core_event_loop(self) -> None:
        adapter = CoreTunnelAdapter("generation-1", SWITCH_LDN_PROTOCOL)
        adapter.send_rfu(b"bind-loop", flags=0x01)
        await adapter.receive_for_core()
        sender = threading.Thread(
            target=lambda: adapter.send_rfu(b"from-tunnelsim-thread", flags=0x01)
        )
        sender.start()
        await asyncio.to_thread(sender.join)
        self.assertEqual(
            (await adapter.receive_for_core()).payload, b"from-tunnelsim-thread"
        )

    def test_adapter_does_not_import_or_interpret_game_protocols(self) -> None:
        source = ROOT / "switchtrade" / "endpoints" / "switch_ldn" / "tunnel_adapter.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        imports = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        self.assertFalse(any(module.startswith("frlgsim") for module in imports))
        self.assertFalse(any("game" in name.lower() for name in imports))


if __name__ == "__main__":
    unittest.main()
