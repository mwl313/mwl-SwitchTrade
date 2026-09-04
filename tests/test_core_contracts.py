from __future__ import annotations

import unittest

from switchtrade.core.contracts import (
    CleanupReport,
    EndpointCapabilities,
    EndpointKind,
    GenerationRole,
    LinkPacket,
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

    def test_packet_bounds_and_cleanup_details_are_protected(self) -> None:
        packet = LinkPacket("g1", "switchtrade.fake.v1", b"opaque")
        self.assertEqual(packet.payload, b"opaque")
        report = CleanupReport(True, True, True, {"count": 1})
        with self.assertRaises(TypeError):
            report.details["count"] = 2  # type: ignore[index]


if __name__ == "__main__":
    unittest.main()
