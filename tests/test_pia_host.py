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
from frlgsim import gbaframe, linkplayer, mon, ni, reliable, rfu, trade
from frlgsim.sim import PARENT_SEAT_IDLE_FRAMES, Sim, TS_SEED


HOST_MAC = bytes.fromhex("a047d7b02b39")
PEER_MAC = bytes.fromhex("98415c794138")
NATIVE_HOST_MAC = bytes.fromhex("a4c1e8667325")
NATIVE_JOIN = bytes.fromhex(
    "00060100030505010a030d070f000058ab141d275c41387941980000f4690000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "e8732566c1a40000cdb0010100a9fe190230391000000000449c5d2f18fd9c5a"
    "032d8200000003016d776c")
NATIVE_GUEST_METADATA = bytes.fromhex(
    "4a002a00580100466972655265645f6500000000000000000000000000000000"
    "0000000000000000000000000000")


def pia_reliable_datagram(crypto, src_ip, dst_var, src_var, pktid,
                          seq, window, flags_a, inner):
    """Build one uncompressed, established Pia Reliable test datagram."""
    frame = reliable.build_reliable(seq, window, inner, flagsA=flags_a)
    body = reliable.build_message(reliable.PROTO_RELIABLE, frame)
    body += dst_var.to_bytes(2, "big")
    pad = (-len(body)) % 16
    body += b"\xff" * pad
    header = PiaHeader(dst=dst_var, src=src_var, pktid=pktid,
                       nonce8=bytes([pktid]) * 8, flags=pad << 4, footer=2)
    return crypto.encrypt(body, src_ip, header)


def decode_reliable_messages(crypto, datagram, src_ip):
    plaintext = crypto.decrypt(datagram, src_ip)
    app, compressed = decompress(plaintext)
    messages, _, _ = reliable.parse_app(app)
    return compressed, [(message, reliable.parse_reliable(message.payload))
                        for message in messages]


class PiaHostTest(unittest.TestCase):
    def test_parent_rfu_ni_frames_match_native_gold(self):
        self.assertEqual(
            gbaframe.wrap_parent_t(None, 0x49F7).hex(),
            "57540800f749000001000000")
        self.assertEqual(
            gbaframe.wrap_parent_t(
                ni.parent_recv_ack_slot(rfu.LCOM_NI_START, 1, 0), 0x49F9).hex(),
            "57540c00f94900000300000000680400")
        self.assertEqual(gbaframe.build_group_state(0).hex(), "5747040000000000")
        self.assertEqual(gbaframe.build_group_state(1).hex(), "5747040001000000")

        slots = ni.parent_join_status_slots()
        timestamps = (0x4B2B, 0x4B2D, 0x4B2F, 0x4B32, 0x4B33)
        expected = (
            "575410002b4b0000080000000548040005000100",
            "575410002d4b0000050000000250040000000000",
            "57540c002f4b00000400000001880405",
            "57540c00324b00000300000000c00400",
            "57540c00334b00000300000000080400",
        )
        self.assertEqual(
            tuple(gbaframe.wrap_parent_t(slot, ts).hex()
                  for slot, ts in zip(slots, timestamps)), expected)

        uni = rfu.parent_uni_slot((rfu.idle_slot(), rfu.idle_slot()))
        self.assertEqual((len(uni), uni[:3].hex()), (73, "460005"))
        parsed = gbaframe.parse_in(gbaframe.wrap_parent_t(uni, 0x4B7B))
        self.assertEqual(parsed["llsf_state"], rfu.LCOM_UNI)
        self.assertEqual(parsed["slots"], [(i, rfu.idle_slot()) for i in range(5)])

    def test_parent_uni_opens_with_native_player_and_link_bootstrap(self):
        class Engine:
            def __init__(self):
                self.sender = None
                self.requests = []
                self.frames = []
                self.established = False
                self.in_seat_phase = True

            def _on_req(self, reqtype):
                self.requests.append(reqtype)
                self.sender = SimpleNamespace(owner=1, trust_pia=False)

            def feed_in_frame(self, frame):
                self.frames.append(frame)

            def tick(self):
                return [0] * 7

        engine = Engine()
        sim = Sim(SimpleNamespace(), PiaCrypto(bytes(range(16))), engine,
                  "169.254.25.1", "169.254.25.2",
                  parent_session_id=bytes.fromhex("fcc3"))
        sim._parent_accept_acked = True
        sim._parent_poll_sent = True
        sim._parent_child_ni_complete = True
        sim._parent_group_zero_sent = True
        sim._parent_status_index = len(sim._parent_status_slots)
        sim._parent_group_one_sent = True
        sim._parent_ni_complete = True
        batches = []
        sim._tx_reliable_batch = lambda batch: batches.append(list(batch))

        def drive_row_zero():
            batches.clear()
            sim._drive_parent_reliable()
            frames = [entry[2] for entry in batches[-1]
                      if entry[1] != reliable.FLAGSA_CTRL]
            sim.rel.on_ack(sim.rel.out_seq)
            return gbaframe.parse_in(frames[-1])["slots"][0][1]

        self.assertEqual(drive_row_zero(), rfu.idle_slot())
        self.assertEqual(drive_row_zero(), rfu.idle_slot())
        self.assertEqual(drive_row_zero(), rfu.serialize([rfu.SEND_PLAYER_IDS, 2, 1]))
        self.assertEqual(drive_row_zero(), rfu.idle_slot())
        self.assertEqual(drive_row_zero(), rfu.idle_slot())
        self.assertEqual(drive_row_zero(), rfu.serialize([rfu.SEND_BLOCK_REQ, 0]))
        self.assertEqual(engine.requests, [0])
        self.assertEqual((engine.sender.owner, engine.sender.trust_pia), (0, True))

        tagged = bytearray(rfu.serialize(rfu.send_block_words(0, b"GameFreak in")))
        tagged[0] |= 0xA0
        sim._on_gba_in(gbaframe.wrap_t(rfu.uni_slot(tagged), 0x31352))
        self.assertEqual(engine.frames[-1]["positional"][0],
                         (0, rfu.serialize(rfu.send_block_words(0, b"GameFreak in"))))

        engine.sender = None
        engine.established = True
        engine.tick = lambda: rfu.exit_standby_words(0)
        self.assertEqual(drive_row_zero(), rfu.idle_slot())
        standby0 = rfu.serialize(rfu.exit_standby_words(0))
        sim._on_gba_in(gbaframe.wrap_t(rfu.uni_slot(standby0), 0x31353))
        self.assertEqual(drive_row_zero(), standby0)
        self.assertEqual(drive_row_zero(), standby0)
        self.assertEqual(drive_row_zero(), rfu.idle_slot())
        self.assertEqual(drive_row_zero(), rfu.idle_slot())
        self.assertEqual(drive_row_zero(), rfu.serialize([rfu.SEND_BLOCK_REQ, 2]))
        self.assertEqual(engine.requests, [0, 2])
        self.assertEqual((engine.sender.owner, engine.sender.trust_pia), (0, True))

        engine.sender = None
        standby1 = rfu.serialize(rfu.exit_standby_words(1))
        sim._on_gba_in(gbaframe.wrap_t(rfu.uni_slot(standby1), 0x31354))
        self.assertEqual(drive_row_zero(), standby1)
        self.assertEqual(drive_row_zero(), standby1)
        for _ in range(PARENT_SEAT_IDLE_FRAMES):
            self.assertEqual(drive_row_zero(), rfu.idle_slot())
        self.assertFalse(sim._parent_seat_ready)
        drive_row_zero()
        self.assertTrue(sim._parent_seat_ready)

    def test_parent_uni_drives_real_trade_engine_to_card_gate(self):
        engine = trade.TradeEngine(
            [mon.Mon.empty(), mon.Mon.empty()], trade_slot=1,
            link_player=linkplayer.LinkPlayer(name="CODEX"), log=lambda *args: None)
        sim = Sim(SimpleNamespace(), PiaCrypto(bytes(range(16))), engine,
                  "169.254.25.1", "169.254.25.2",
                  parent_session_id=bytes.fromhex("fcc3"))
        sim._parent_accept_acked = sim._parent_poll_sent = True
        sim._parent_child_ni_complete = sim._parent_group_zero_sent = True
        sim._parent_status_index = len(sim._parent_status_slots)
        sim._parent_group_one_sent = sim._parent_ni_complete = True
        sim._tx_reliable_batch = lambda batch: None

        def drive():
            sim._drive_parent_reliable()
            sim.rel.on_ack(sim.rel.out_seq)

        for _ in range(6):
            drive()
        self.assertEqual((engine.sender.owner, engine.sender.trust_pia), (0, True))

        child = linkplayer.build_block(linkplayer.LinkPlayer(name="MWL")).ljust(200, b"\0")
        slots = rfu.SlotBuilder()
        commands = [rfu.init_words(17, owner=1)] + [
            rfu.send_block_words(i, child[i * 12:(i + 1) * 12]) for i in range(17)]
        for words in commands:
            sim._on_gba_in(gbaframe.wrap_t(rfu.uni_slot(slots.build(words)), 0x4000))
            drive()
        self.assertEqual(engine.host_link_player.name, "MWL")
        self.assertTrue(engine.established)

        while engine.sender is not None:
            drive()
        sim._on_gba_in(gbaframe.wrap_t(
            rfu.uni_slot(slots.build(rfu.exit_standby_words(0))), 0x4001))
        for _ in range(5):
            drive()
        self.assertTrue(sim._parent_card_request_sent)
        self.assertEqual((engine.sender.owner, engine.sender.trust_pia), (0, True))

    def test_parent_join_status_advances_only_on_matching_child_acks(self):
        sim = Sim(SimpleNamespace(), PiaCrypto(bytes(range(16))), SimpleNamespace(),
                  "169.254.25.1", "169.254.25.2",
                  parent_session_id=bytes.fromhex("fcc3"))
        batches = []
        sim._tx_reliable_batch = lambda batch: batches.append(list(batch))
        sim._parent_accept_acked = True
        sim._parent_poll_sent = True
        sim._parent_child_ni_complete = True

        def drive():
            batches.clear()
            sim._drive_parent_reliable()
            inner = [entry[2] for entry in batches[-1]
                     if entry[1] != reliable.FLAGSA_CTRL]
            sim.rel.on_ack(sim.rel.out_seq)
            return inner

        self.assertEqual(drive(), [gbaframe.build_group_state(0)])
        for i, slot in enumerate(ni.parent_join_status_slots()):
            self.assertEqual(drive(), [gbaframe.wrap_parent_t(slot, TS_SEED + i)])
            fields = rfu.parse_llsf_parent(slot)
            if fields["state"] != rfu.LCOM_NULL:
                child_ack = rfu.child_ni_llsf(
                    fields["state"], fields["n"], fields["phase"], 1, 0)
                sim._on_gba_in(gbaframe.wrap_t(child_ack, 0x4000 + i))
        self.assertEqual(drive(), [gbaframe.build_group_state(1)])
        self.assertTrue(sim.parent_ni_complete)

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
        messages, _, _ = reliable.parse_app(app)
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
        messages2, footer2, _ = reliable.parse_app(app2)
        self.assertFalse(compressed2)
        self.assertEqual(footer2, 0xF469)
        self.assertEqual(messages2[0].payload[0], 2)

        plain5 = crypto.decrypt(second, "169.254.25.1")
        app5, compressed5 = decompress(plain5)
        messages5, _, _ = reliable.parse_app(app5)
        self.assertTrue(compressed5)
        self.assertEqual(plain5[-3:-1], bytes.fromhex("f469"))
        self.assertEqual(messages5[0].payload[0], 5)

    def test_parent_reliable_bootstrap_matches_native_gold(self):
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
            peer_provider=lambda: (PEER_MAC, "169.254.25.2"))
        manager.state = ST_FINALIZED
        manager.host_var = 0xF469
        sim = Sim(transport, crypto, SimpleNamespace(),
                  "169.254.25.1", "169.254.25.2", conn=manager,
                  our_var=manager.our_var,
                  parent_session_id=bytes.fromhex("fcc3"))

        # Native frame 1264: guest INIT fff0 (FireRed metadata).  The host's
        # only response is the native cumulative ACK fff1.
        init = pia_reliable_datagram(
            crypto, "169.254.25.2", 0xCDB0, 0xF469, 2,
            0xFFF0, 0xFFF0, reliable.FLAGSA_INIT, NATIVE_GUEST_METADATA)
        self.assertTrue(sim.process_datagram(init, "169.254.25.2"))
        sim.tick()
        self.assertEqual(len(transport.sent), 1)
        first, destination = transport.sent.pop(0)
        self.assertEqual(destination, "169.254.25.2")
        compressed, decoded = decode_reliable_messages(
            crypto, first, "169.254.25.1")
        self.assertFalse(compressed)
        self.assertEqual(len(decoded), 1)
        message, ack = decoded[0]
        self.assertEqual(message.msgflags, 0x40)
        self.assertEqual((ack.flagsA, ack.seq, ack.ack, ack.payload.hex()),
                         (reliable.FLAGSA_CTRL, 0xFFF0, 0xFFF0,
                          "0001fff100000000000000000000000000000000"))

        # Native frame 1266: guest WC fff1 with connect id 1a51.  Native
        # frame 1269 answers with host INIT/WA fff0 followed by ACK fff2 in
        # the same Pia datagram.
        wc = pia_reliable_datagram(
            crypto, "169.254.25.2", 0xCDB0, 0xF469, 3,
            0xFFF1, 0xFFF0, reliable.FLAGSA_GBA,
            bytes.fromhex("574302001a51"))
        self.assertTrue(sim.process_datagram(wc, "169.254.25.2"))
        sim.tick()
        self.assertEqual(len(transport.sent), 1)
        second, destination = transport.sent.pop(0)
        self.assertEqual(destination, "169.254.25.2")
        compressed, decoded = decode_reliable_messages(
            crypto, second, "169.254.25.1")
        self.assertFalse(compressed)
        self.assertEqual(len(decoded), 2)
        wa_message, wa = decoded[0]
        ack_message, ack = decoded[1]
        self.assertEqual(wa_message.msgflags, 0)
        self.assertEqual((wa.flagsA, wa.seq, wa.ack, wa.payload.hex()),
                         (reliable.FLAGSA_INIT, 0xFFF0, 0xFFF0,
                          "57410600fcc31a510000"))
        self.assertEqual(ack_message.msgflags, 0x40)
        self.assertEqual((ack.flagsA, ack.seq, ack.ack, ack.payload.hex()),
                         (reliable.FLAGSA_CTRL, 0xFFF0, 0xFFF0,
                          "0001fff200000000000000000000000000000000"))

        # Native frame 1271: the guest ACKs host WA with next-expected fff1.
        guest_ack = pia_reliable_datagram(
            crypto, "169.254.25.2", 0xCDB0, 0xF469, 4,
            0xFFF0, 0xFFF2, reliable.FLAGSA_CTRL,
            reliable.build_bulk_ack(0xFFF1))
        self.assertTrue(sim.process_datagram(guest_ack, "169.254.25.2"))
        sim.tick()
        self.assertTrue(sim.parent_link_accepted)
        self.assertFalse(sim.connected)  # parent slot/NI engine is still deliberately gated
        self.assertEqual(len(transport.sent), 1)
        poll, destination = transport.sent[0]
        self.assertEqual(destination, "169.254.25.2")
        _, decoded = decode_reliable_messages(crypto, poll, "169.254.25.1")
        self.assertEqual(len(decoded), 1)
        _, parent_t = decoded[0]
        self.assertEqual((parent_t.flagsA, parent_t.seq, parent_t.payload),
                         (reliable.FLAGSA_GBA, 0xFFF1,
                          gbaframe.wrap_parent_t(None, TS_SEED)))

        # The next native gate: a child NI_START is answered with the matching
        # three-byte parent LLSF ACK, then child NULL releases WG=0.
        sim.rel.on_ack(sim.rel.out_seq)
        transport.sent.clear()
        child_start = (rfu.child_ni_llsf(rfu.LCOM_NI_START, 1, 0, 0, 7)
                       + bytes.fromhex("010c001a000000"))
        sim._on_gba_in(gbaframe.wrap_t(child_start, 0x311CE))
        sim.tick()
        _, decoded = decode_reliable_messages(
            crypto, transport.sent[-1][0], "169.254.25.1")
        parent_ack = decoded[0][1]
        self.assertEqual(
            parent_ack.payload,
            gbaframe.wrap_parent_t(
                ni.parent_recv_ack_slot(rfu.LCOM_NI_START, 1, 0), TS_SEED + 1))

        sim.rel.on_ack(sim.rel.out_seq)
        transport.sent.clear()
        child_null = rfu.child_ni_llsf(rfu.LCOM_NULL, 1, 0, 0, 0)
        sim._on_gba_in(gbaframe.wrap_t(child_null, 0x311D6))
        sim.tick()
        _, decoded = decode_reliable_messages(
            crypto, transport.sent[-1][0], "169.254.25.1")
        self.assertEqual(decoded[0][1].payload, gbaframe.build_group_state(0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
