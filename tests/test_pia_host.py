"""Focused checks for the PC-host Pia acquisition gate."""

import unittest
from types import SimpleNamespace

from frlgsim.crypto import PiaCrypto, PiaHeader, decompress
from frlgsim.pia_connect import (
    HOST_NET_PERIOD,
    PROTO_NET,
    PROTO_SESSION,
    ST_JOIN_RECEIVED,
    HostConnectionManager,
    build_net_request,
    build_net_response,
    build_session_join,
    parse_net,
    parse_session_join,
)
from frlgsim.reliable import parse_app
from frlgsim.sim import Sim


HOST_MAC = bytes.fromhex("a047d7b02b39")
PEER_MAC = bytes.fromhex("98415c794138")


class PiaHostTest(unittest.TestCase):
    def test_net_0x11_fixed_fields_survive_zero_variable_size(self):
        packet = build_net_request(2, 0x7620, HOST_MAC, 0x11223344)
        self.assertEqual(packet.hex(),
                         "01110000000000027620a047d7b02b390000"
                         "000000001122334401000000")
        version, msg_type, body = parse_net(packet)
        self.assertEqual((version, msg_type), (1, 0x11))
        self.assertEqual(body[:6], bytes.fromhex("000000027620"))

        # Net 0x12 also has size=0 and a fixed four-byte sequence field.
        self.assertEqual(parse_net(build_net_response(2))[2], b"\x00\x00\x00\x02")

    def test_session_join_parser_extracts_peer_identity(self):
        payload = build_session_join(
            PEER_MAC, bytes.fromhex("4a2b"), "169.254.120.2",
            HOST_MAC, bytes.fromhex("348e"), "mwl", bytes.fromhex("01020304"))
        join = parse_session_join(payload)
        self.assertIsNotNone(join)
        self.assertEqual(join["src_constant"], PEER_MAC + b"\x00\x00")
        self.assertEqual(join["src_var"], 0x4A2B)
        self.assertEqual(join["dst_var"], 0x348E)
        self.assertEqual(join["address"], "169.254.120.2")
        self.assertEqual(join["port"], 12345)
        self.assertEqual(join["names"], ["mwl"])
        self.assertEqual(join["app_ver"], 88)

    def test_host_retransmits_until_switch_join_is_captured(self):
        manager = HostConnectionManager(
            HOST_MAC, "169.254.21.1", 0x11223344, our_var=0x348E)

        manager.poll(1)
        first = manager.drain()
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0]["proto"], PROTO_NET)
        self.assertFalse(first[0]["unicast"])
        self.assertEqual((first[0]["dst"], first[0]["src"], first[0]["pktid"]),
                         (0, 0, 0))

        manager.poll(HOST_NET_PERIOD)
        self.assertEqual(manager.drain(), [])
        manager.poll(HOST_NET_PERIOD + 1)
        self.assertEqual(len(manager.drain()), 1)

        manager.on_message(PROTO_NET, build_net_response(2))
        join_payload = build_session_join(
            PEER_MAC, bytes.fromhex("4a2b"), "169.254.21.2",
            HOST_MAC, bytes.fromhex("348e"), "Switch", b"R" * 4)
        manager.on_message(PROTO_SESSION, join_payload)
        self.assertEqual(manager.state, ST_JOIN_RECEIVED)
        self.assertEqual(manager.host_var, 0x4A2B)
        self.assertEqual(manager.peer["names"], ["Switch"])
        manager.poll(10 * HOST_NET_PERIOD)
        self.assertEqual(manager.drain(), [])
        self.assertFalse(manager.connected)

    def test_sim_emits_encrypted_net_0x11_to_broadcast(self):
        class Transport:
            def __init__(self):
                self.sent = []

            def recv(self):
                return []

            def send(self, datagram, destination):
                self.sent.append((datagram, destination))

        transport = Transport()
        crypto = PiaCrypto(bytes(range(16)))
        manager = HostConnectionManager(
            HOST_MAC, "169.254.21.1", crypto.net_id, our_var=0x348E)
        sim = Sim(transport, crypto, SimpleNamespace(),
                  "169.254.21.1", "169.254.21.1", conn=manager,
                  our_var=manager.our_var)

        sim.tick()
        self.assertEqual(len(transport.sent), 1)
        datagram, destination = transport.sent[0]
        self.assertEqual(destination, "169.254.21.255")
        header = PiaHeader.unpack(datagram)
        self.assertEqual((header.dst, header.src, header.pktid), (0, 0, 0))
        self.assertEqual(header.flags & 0x0F, 2)       # establishing/skip-dst check
        plaintext = crypto.decrypt(datagram, "169.254.21.1")
        app, compressed = decompress(plaintext)
        messages, _, _ = parse_app(app)
        self.assertFalse(compressed)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].proto, PROTO_NET)
        self.assertEqual(parse_net(messages[0].payload)[1], 0x11)


if __name__ == "__main__":
    unittest.main(verbosity=2)
