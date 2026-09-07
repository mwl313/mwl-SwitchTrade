import socket
import struct
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from switchtrade.connection.data_plane import ETH_P_IP, LdnDataPlane, PIA_PORT


def udp_frame(payload=b"pia", *, protocol=17, port=PIA_PORT):
    source = socket.inet_aton("169.254.21.1")
    destination = socket.inet_aton("169.254.21.2")
    ip = bytearray(20)
    ip[0] = 0x45
    struct.pack_into("!H", ip, 2, 28 + len(payload))
    ip[9] = protocol
    ip[12:16] = source
    ip[16:20] = destination
    udp = struct.pack("!HHHH", PIA_PORT, port, len(payload) + 8, 0) + payload
    return bytes(12) + struct.pack("!H", ETH_P_IP) + bytes(ip) + udp


class LdnDataPlaneTests(unittest.TestCase):
    def test_local_plane_opens_before_peer_and_binds_only_after_association(self):
        local = SimpleNamespace(ip_address="169.254.21.1", mac_address=b"\x02\0\0\0\0\x01", connected=True)
        peer = SimpleNamespace(ip_address="169.254.21.2", mac_address=b"\x02\0\0\0\0\x02", connected=True)
        network = SimpleNamespace(
            participant=lambda: local,
            info=lambda: SimpleNamespace(ssid=b"switchtrade", participants=[local], num_participants=1),
        )
        socket_object = SimpleNamespace(setsockopt=lambda *_: None, bind=lambda *_: None, setblocking=lambda *_: None, close=lambda: None)
        with patch.object(socket, "AF_PACKET", 17, create=True), patch(
            "switchtrade.connection.data_plane.socket.socket", side_effect=[socket_object, socket_object]
        ):
            plane = LdnDataPlane(network, "tap-test", {"tap_ready": True})
            with self.assertRaisesRegex(RuntimeError, "peer is unavailable"):
                plane.bind_peer()
            # LDN may return a copy of the local participant; identity is MAC,
            # not Python object identity.
            local_copy = SimpleNamespace(**vars(local))
            network.info = lambda: SimpleNamespace(ssid=b"switchtrade", participants=[local_copy, peer], num_participants=2)
            plane.bind_peer()
        self.assertEqual((plane.host_ip, plane.host_mac), ("169.254.21.2", peer.mac_address))

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

    def test_malformed_ip_udp_lengths_and_fragments_are_dropped(self):
        for offset, value in ((14, b"\x44"), (16, b"\x00\x00"), (16, b"\xff\xff"),
                              (20, b"\x20\x00"), (20, b"\x00\x01"),
                              (38, b"\x00\x07"), (38, b"\xff\xff"), (34, b"\x00\x01")):
            frame = bytearray(udp_frame())
            frame[offset:offset + len(value)] = value
            self.assertIsNone(LdnDataPlane._parse_udp(bytes(frame)), (offset, value))

    def test_rx_and_tx_remain_bound_to_the_admitted_peer(self):
        plane = LdnDataPlane.__new__(LdnDataPlane)
        plane.our_ip, plane.host_ip, plane.broadcast = "169.254.21.2", "169.254.21.1", "169.254.21.255"
        valid = udp_frame()
        wrong_source = bytearray(valid)
        wrong_source[26:30] = socket.inet_aton("169.254.21.3")
        wrong_broadcast = bytearray(valid)
        wrong_broadcast[30:34] = socket.inet_aton("169.254.22.255")
        from unittest.mock import Mock
        plane._rx = SimpleNamespace(recv=Mock(side_effect=[bytes(wrong_source), bytes(wrong_broadcast), valid, BlockingIOError]))
        plane._tx = SimpleNamespace(sendto=Mock())
        self.assertEqual(plane.recv(), [(b"pia", plane.host_ip)])
        with self.assertRaisesRegex(RuntimeError, "DESTINATION_INVALID"):
            plane.send(b"pia", "169.254.21.3")
        plane._tx.sendto.assert_not_called()


if __name__ == "__main__":
    unittest.main()
