from __future__ import annotations

import unittest

from switchtrade.core.contracts import (
    CleanupReport,
    EndpointCapabilities,
    EndpointKind,
    GenerationOffer,
    GenerationRole,
    LinkPacket,
    MAX_PACKET_BYTES,
    MAX_SETUP_BYTES,
    PairSeat,
    RuntimeKind,
    validate_protocol_id,
)


class CoreContractTests(unittest.TestCase):
    def test_role_axes_are_distinct_and_capabilities_are_immutable(self) -> None:
        capabilities = EndpointCapabilities(
            EndpointKind.FAKE,
            RuntimeKind.IN_PROCESS,
            ("switchtrade.fake.v1",),
            (GenerationRole.ORIGIN,),
        )
        self.assertEqual(capabilities.generation_roles, (GenerationRole.ORIGIN,))
        with self.assertRaises(ValueError):
            EndpointCapabilities(EndpointKind.FAKE, RuntimeKind.IN_PROCESS, ("switchtrade.fake.v1",) * 2, (GenerationRole.ORIGIN,))
        with self.assertRaises(ValueError):
            validate_protocol_id("switchtrade.fake.v0")
        self.assertNotEqual(PairSeat.HOST.value, GenerationRole.ORIGIN.value)
        self.assertEqual(EndpointKind.SWITCH_LDN.value, "switch_ldn")
        self.assertEqual(RuntimeKind.MANAGED_WSL.value, "managed_wsl")

    def test_packet_bounds_and_cleanup_details_are_protected(self) -> None:
        packet = LinkPacket("g1", "switchtrade.fake.v1", b"opaque")
        self.assertEqual(packet.payload, b"opaque")
        report = CleanupReport(True, True, True, {"count": 1})
        with self.assertRaises(TypeError):
            report.details["count"] = 2  # type: ignore[index]
        for flags in (-1, 1 << 16):
            with self.assertRaises(ValueError):
                LinkPacket("g1", "switchtrade.fake.v1", b"", flags)
        with self.assertRaises(ValueError):
            LinkPacket("g1", "switchtrade.fake.v1", b"x" * (MAX_PACKET_BYTES + 1))
        with self.assertRaises(ValueError):
            GenerationOffer("g1", "switchtrade.fake.v1", EndpointKind.FAKE, b"x" * (MAX_SETUP_BYTES + 1))


if __name__ == "__main__":
    unittest.main()
