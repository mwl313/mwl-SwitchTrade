"""Focused checks for the PC-host Pia acquisition gate."""

import unittest
from types import SimpleNamespace

from frlgsim.crypto import PiaCrypto, PiaHeader, decompress
from frlgsim.pia_connect import (
    HOST_NET_PERIOD,
    PROTO_NET,
    PROTO_SESSION,
    SESSION_FINALIZE,
    ST_FINALIZED,
    ST_JOIN_RECEIVED,
    HostConnectionManager,
    build_net_request,
    build_net_response,
    build_session_join,
    build_session_join_response,
    build_session_update,
    ldn_constant_id,
    parse_net,
    parse_session_join,
)
from frlgsim.reliable import parse_app
from frlgsim.sim import Sim


HOST_MAC = bytes.fromhex("a047d7b02b39")
PEER_MAC = bytes.fromhex("98415c794138")
NATIVE_HOST_MAC = bytes.fromhex("a4c1e8667325")
NATIVE_JOIN = bytes.fromhex(
    "00060100030505010a030d070f000058ab141d275c41387941980000f4690000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "e8732566c1a40000cdb0010100a9fe190230391000000000449c5d2f18fd9c5a"
    "032d8200000003016d776c")


class PiaHostTest(unittest.TestCase):
    def test_net_0x11_matches_fixed_channel_native_gold(self):
        packet = build_net_request(
            2, 0xCDB0, NATIVE_HOST_MAC, 0x55C77B2B,
            host_ip="169.254.25.1", peer_ip="169.254.25.2")
        self.assertEqual(packet.hex(),
                         "0111008400000002cdb0e8732566c1a400000000000055c77b2b0100060000000000a9fe1901000000000000000000000000303900010000a9fe1902000000000000000000000000303900ff000000000000000000000000000000000000000000ff000000000000000000000000000000000000000000ff000000000000000000000000000000000000000000ff0000000000000000000000000000000000000000")
        version, msg_type, body = parse_net(packet)
        self.assertEqual((version, msg_type), (1, 0x11))
        self.assertEqual(body[:6], bytes.fromhex("00000002cdb0"))
        self.assertEqual(ldn_constant_id(NATIVE_HOST_MAC),
                         bytes.fromhex("e8732566c1a40000"))

        # Net 0x12 has size=0 and a fixed four-byte sequence field.
        self.assertEqual(parse_net(build_net_response(2))[2], b"\x00\x00\x00\x02")

    def test_native_session_join_and_accept_are_byte_exact(self):
        join = parse_session_join(NATIVE_JOIN)
        self.assertIsNotNone(join)
        self.assertEqual(join["src_constant"], bytes.fromhex("5c41387941980000"))
        self.assertEqual(join["src_var"], 0xF469)
        self.assertEqual(join["dst_var"], 0xCDB0)
        self.assertEqual(join["address"], "169.254.25.2")
        self.assertEqual(join["port"], 12345)
        self.assertEqual(join["names"], ["mwl"])
        self.assertEqual(join["app_ver"], 88)
        self.assertEqual(join["player_ids"][0].hex(),
                         "1000000000449c5d2f18fd9c5a032d82")

        host_constant = bytes.fromhex("e8732566c1a40000")
        self.assertEqual(
            build_session_join_response(
                host_constant, 0xCDB0, join["src_constant"], 0xF469,
                bytes.fromhex("ffd3541a")).hex(),
            "020d070100000000ffd3541ae8732566c1a40000cdb0"
            "5c41387941980000f4690100010000")
        self.assertEqual(
            build_session_update(
                host_constant, 0xCDB0, "169.254.25.1",
                bytes.fromhex("1002b488ea850b8739afe6f5e6a151b6"), "Min",
                join["src_constant"], 0xF469, join["address"], join["token"],
                join["player_ids"][0], "mwl").hex(),
            "05000001000003e8732566c1a40000cdb002000001000000000000e8732566c1a40000cdb0a9fe1901303900000000000000000000000000000000000000000000000000000000000000000000000000010100001002b488ea850b8739afe6f5e6a151b600000003014d696e5c41387941980000f469a9fe1902303901000100000000000000000000000000000000000000000000000000000000000000000000010100001000000000449c5d2f18fd9c5a032d8200000003016d776c")

    def test_host_retransmits_until_switch_join_is_captured(self):
        peer = [HOST_MAC, "169.254.21.1"]
        manager = HostConnectionManager(
            HOST_MAC, "169.254.21.1", 0x11223344, our_var=0x348E,
            peer_provider=lambda: tuple(peer), player_name="CODEX",
            player_id=b"\x10" + b"H" * 15, random4=b"R" * 4)

        manager.poll(1)
        self.assertEqual(manager.drain(), [])
        peer[:] = [PEER_MAC, "169.254.21.2"]
        manager.poll(1)
        first = manager.drain()
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0]["proto"], PROTO_NET)
        self.assertFalse(first[0]["unicast"])
        self.assertTrue(first[0]["compress"])
        self.assertEqual((first[0]["dst"], first[0]["src"], first[0]["pktid"]),
                         (0, 0x348E, 0))

        manager.poll(HOST_NET_PERIOD)
        self.assertEqual(manager.drain(), [])
        manager.poll(HOST_NET_PERIOD + 1)
        self.assertEqual(len(manager.drain()), 1)

        manager.on_message(PROTO_NET, build_net_response(2))
        manager.on_message(PROTO_SESSION, NATIVE_JOIN)
        self.assertEqual(manager.state, ST_JOIN_RECEIVED)
        self.assertEqual(manager.host_var, 0xF469)
        self.assertEqual(manager.peer["names"], ["mwl"])
        accept = manager.drain()
        self.assertEqual([entry["payload"][0] for entry in accept], [2, 5])
        self.assertEqual((accept[0]["dst"], accept[0]["src"], accept[0]["unicast"]),
                         (0xF469, 0x348E, True))
        self.assertEqual((accept[1]["dst"], accept[1]["src"], accept[1]["unicast"]),
                         (1, 0x348E, False))
        manager.on_message(PROTO_SESSION, bytes([SESSION_FINALIZE]))
        self.assertEqual(manager.state, ST_FINALIZED)
        self.assertTrue(manager.pia_connected)
        manager.on_message(PROTO_SESSION, NATIVE_JOIN)  # idempotent retry
        self.assertEqual(manager.state, ST_FINALIZED)
        self.assertTrue(manager.pia_connected)
        manager.drain()
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
            HOST_MAC, "169.254.21.1", crypto.net_id, our_var=0x348E,
            peer_provider=lambda: (PEER_MAC, "169.254.21.2"))
        sim = Sim(transport, crypto, SimpleNamespace(),
                  "169.254.21.1", "169.254.21.1", conn=manager,
                  our_var=manager.our_var)

        sim.tick()
        self.assertEqual(len(transport.sent), 1)
        datagram, destination = transport.sent[0]
        self.assertEqual(destination, "169.254.21.255")
        header = PiaHeader.unpack(datagram)
        self.assertEqual((header.dst, header.src, header.pktid), (0, 0x348E, 0))
        self.assertEqual(header.flags & 0x0F, 3)       # zstd + skip-dst check
        plaintext = crypto.decrypt(datagram, "169.254.21.1")
        app, compressed = decompress(plaintext)
        messages, _, _ = parse_app(app)
        self.assertTrue(compressed)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].proto, PROTO_NET)
        self.assertEqual(parse_net(messages[0].payload)[1], 0x11)

    def test_sim_frames_native_session_accept_on_the_right_channels(self):
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
            NATIVE_HOST_MAC, "169.254.25.1", crypto.net_id, our_var=0xCDB0,
            peer_provider=lambda: (PEER_MAC, "169.254.25.2"), player_name="Min",
            player_id=bytes.fromhex("1002b488ea850b8739afe6f5e6a151b6"),
            random4=bytes.fromhex("ffd3541a"))
        sim = Sim(transport, crypto, SimpleNamespace(),
                  "169.254.25.1", "169.254.25.2", conn=manager,
                  our_var=manager.our_var)

        manager.on_message(PROTO_SESSION, NATIVE_JOIN)
        sim.tick()
        self.assertEqual(len(transport.sent), 2)

        first, second = [entry[0] for entry in transport.sent]
        h2, h5 = PiaHeader.unpack(first), PiaHeader.unpack(second)
        self.assertEqual((h2.dst, h2.src, h2.pktid, h2.footer, h2.flags & 0x0F),
                         (0xF469, 0xCDB0, 1, 2, 0))
        self.assertEqual((h5.dst, h5.src, h5.pktid, h5.footer, h5.flags & 0x0F),
                         (1, 0xCDB0, 1, 2, 1))

        plain2 = crypto.decrypt(first, "169.254.25.1")
        app2, compressed2 = decompress(plain2)
        messages2, footer2, _ = parse_app(app2)
        self.assertFalse(compressed2)
        self.assertEqual(footer2, 0xF469)
        self.assertEqual(messages2[0].payload[0], 2)

        plain5 = crypto.decrypt(second, "169.254.25.1")
        app5, compressed5 = decompress(plain5)
        messages5, _, _ = parse_app(app5)
        self.assertTrue(compressed5)
        self.assertEqual(plain5[-3:-1], bytes.fromhex("f469"))
        self.assertEqual(messages5[0].payload[0], 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
