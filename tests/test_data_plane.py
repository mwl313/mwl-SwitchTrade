import socket
import struct
import unittest

from switchtrade.connection.data_plane import ETH_P_IP, LdnDataPlane, PIA_PORT


def udp_frame(payload=b"pia", *, protocol=17, port=PIA_PORT):
    source = socket.inet_aton("169.254.21.1")
    destination = socket.inet_aton("169.254.21.2")
    ip = bytearray(20)
    ip[0] = 0x45
    ip[9] = protocol
    ip[12:16] = source
    ip[16:20] = destination
    udp = struct.pack("!HHHH", PIA_PORT, port, len(payload) + 8, 0) + payload
    return bytes(12) + struct.pack("!H", ETH_P_IP) + bytes(ip) + udp


class LdnDataPlaneTests(unittest.TestCase):
    def test_parses_only_ipv4_udp_and_preserves_payload(self):
        parsed = LdnDataPlane._parse_udp(udp_frame(b"opaque-rfu"))
        self.assertEqual(parsed, (
            "169.254.21.1", "169.254.21.2", PIA_PORT, b"opaque-rfu"))
        self.assertIsNone(LdnDataPlane._parse_udp(udp_frame(protocol=6)))
        self.assertIsNone(LdnDataPlane._parse_udp(udp_frame()[:30]))

    def test_udp_length_bounds_payload_without_exposing_frame_metadata(self):
        frame = udp_frame(b"abc") + b"padding"
        parsed = LdnDataPlane._parse_udp(frame)
        self.assertEqual(parsed[-1], b"abc")


if __name__ == "__main__":
    unittest.main()
