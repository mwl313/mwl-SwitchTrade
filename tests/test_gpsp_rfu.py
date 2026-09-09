import json
import hashlib
from pathlib import Path
import struct
import unittest
import pytest

from bridge.frlgsim.beacon import build_application_data, build_rfu_record
from switchtrade.endpoints.retroarch_gpsp.rfu import (
    CHILD_TIMESTAMP_SEED, FLAGS_GBA, FLAGS_METADATA, GBA_ACCEPT, GBA_ACK,
    GBA_CONNECT, GBA_DISCONNECT, GBA_GROUP, GBA_TRANSFER, MAX_PENDING,
    METADATA_FRAME, RFU1_BROADCAST, RFU1_CLIENT_ACK, RFU1_CLIENT_SEND,
    RFU1_CONNECT_ACK, RFU1_CONNECT_REQ, RFU1_DISCONNECT, RFU1_HOST_SEND,
    RFU1_MAGIC, RfuTranslator, TranslatorError,
    _native_game_broadcast,
)


HOST_SESSION = 0x1234
CHILD_CONNECTION = bytes.fromhex("6779")
GPSP_DEVICE = 0x4567
ASSIGNMENT = GPSP_DEVICE
VECTORS = json.loads(
    (Path(__file__).parent / "fixtures" / "rfu" / "translator-vectors.v1.json")
    .read_text(encoding="utf-8"))


def gba(frame_type: int, body: bytes) -> bytes:
    return bytes((0x57, frame_type)) + len(body).to_bytes(2, "little") + body


def rfu1(packet_type: int, header: int, body: bytes = b"", *, size: int = 16) -> bytes:
    value = struct.pack("!III", RFU1_MAGIC, packet_type, header) + body
    return value + b"\0" * (size - len(value))


def parent_t(timestamp: int, slot: bytes | None) -> bytes:
    if slot is None:
        body = timestamp.to_bytes(4, "little") + b"\x01\0\0\0"
    else:
        padded = slot + b"\0" * ((-len(slot)) & 3)
        body = timestamp.to_bytes(4, "little") + bytes((len(slot), 0, 0, 0)) + padded
    return gba(GBA_TRANSFER, body)


def accept() -> bytes:
    return gba(
        GBA_ACCEPT,
        HOST_SESSION.to_bytes(2, "little") + CHILD_CONNECTION + b"\0\0")


def advertisement(*, session: int = HOST_SESSION, partner: bytes = b"\0\0\0\0\x04\x14") -> bytes:
    return build_application_data(0x2211, "HOST", session, partner)


@pytest.mark.parametrize("version,gender", [(4, 0), (4, 1), (5, 0), (5, 1)])
@pytest.mark.parametrize("name", [b"\xbb\xff" + bytes(6), b"\xbb" * 7 + b"\xff"])
def test_search_record_translates_fields_not_identity_or_session(version, gender, name):
    record = (b"\x11\x22" + name + b"\x34\x12" + bytes(4)
              + bytes((4 | gender << 7, version | 2 << 3)) + bytes(6))
    native = _native_game_broadcast(record)
    assert len(native) == 24
    assert native[:2] == b"\x02\0"
    assert int.from_bytes(native[2:4], "little") == 2 | version << 10
    assert native[4:6] == record[:2]
    assert native[6:15] == bytes(6) + bytes((4, gender, 0))
    assert native[16:] == name
    assert native[15] == (~sum(native[2:10] + name)) & 255
    changed_session = record[:10] + b"\x78\x56" + record[12:]
    assert _native_game_broadcast(changed_session) == native


@pytest.mark.parametrize("offset,value", [(12, 1), (15, 1), (16, 1), (16, 2),
    (16, 3), (17, 0x0C), (17, 0x16), (17, 0x54), (17, 0x94), (18, 1), (23, 1)])
def test_unmapped_discovery_fields_fail_closed(offset, value):
    record = bytearray(b"\x11\x22" + b"\xbb\xff" + bytes(6) + b"\x34\x12"
                       + bytes(4) + b"\x04\x14" + bytes(6))
    record[offset] = value
    with pytest.raises(TranslatorError) as failure:
        _native_game_broadcast(bytes(record))
    assert failure.value.code == "TRANSLATOR_ADVERTISEMENT_UNSUPPORTED"


def test_unsupported_advertisement_failure_is_sticky_without_state_advance():
    translator = TranslatorFixture.create()
    with pytest.raises(TranslatorError) as first:
        translator.accept_advertisement(advertisement(partner=b"\0" * 4 + b"\x01\x14"), generation=1)
    assert first.value.code == "TRANSLATOR_ADVERTISEMENT_UNSUPPORTED"
    assert translator._host_session_id is None and translator._advertisement_hash is None
    with pytest.raises(TranslatorError) as repeated:
        translator.accept_advertisement(advertisement(), generation=1)
    assert repeated.value is first.value


class TranslatorFixture:
    @staticmethod
    def create() -> RfuTranslator:
        return RfuTranslator(
            attempt_id="attempt-1", tunnel_epoch=1,
            child_connection_id=CHILD_CONNECTION, gpsp_device_id=GPSP_DEVICE)

    @classmethod
    def connecting(cls) -> RfuTranslator:
        value = cls.create()
        value.start()
        value.accept_advertisement(advertisement(), generation=1)
        value.from_switch(METADATA_FRAME, flags=FLAGS_METADATA, generation=1, sequence=1)
        value.from_core(
            rfu1(RFU1_CONNECT_REQ, HOST_SESSION), peer_id=1, sequence=1)
        return value

    @classmethod
    def connected(cls) -> RfuTranslator:
        value = cls.connecting()
        value.from_switch(accept(), flags=FLAGS_METADATA, generation=1, sequence=2)
        return value


class RfuTranslatorGoldenTests(unittest.TestCase):
    def test_frozen_vector_identity_table(self):
        self.assertEqual(VECTORS["contract_version"], "frlg-wireless-adapter.v1")
        self.assertEqual(VECTORS["direction"],
                         "nintendo-switch-creator-to-stock-gpsp-finder")
        self.assertEqual(VECTORS["identities"], {
            "attempt_id": "attempt-1", "tunnel_epoch": 1,
            "host_session_id": HOST_SESSION,
            "child_connection_id": CHILD_CONNECTION.hex(),
            "gpsp_device_id": GPSP_DEVICE, "gpsp_slot": 0,
            "core_peer_id": 1, "switch_peer_id": 0,
        })

    def test_advertisement_maps_to_stock_gpsp_broadcast(self):
        translator = TranslatorFixture.create()
        opened = translator.start()
        self.assertEqual(opened[0].payload, METADATA_FRAME)
        self.assertEqual(opened[0].payload.hex(), VECTORS["vectors"]["metadata"])
        self.assertEqual(opened[0].flags, FLAGS_METADATA)

        application_data = advertisement()
        self.assertEqual(application_data.hex(), VECTORS["vectors"]["advertisement"])
        action = translator.accept_advertisement(application_data, generation=1)[0]
        self.assertEqual(action.payload.hex(), VECTORS["vectors"]["broadcast"])
        magic, packet_type, device_id = struct.unpack("!III", action.payload[:12])
        self.assertEqual((magic, packet_type, device_id), (
            RFU1_MAGIC, RFU1_BROADCAST, HOST_SESSION))
        words = b"".join(
            struct.unpack("!I", action.payload[offset:offset + 4])[0].to_bytes(4, "little")
            for offset in range(12, 36, 4))
        self.assertEqual(words[:15], bytes.fromhex("020002101122000000000000040000"))
        self.assertEqual(words[16:], build_rfu_record(0x2211, "HOST", HOST_SESSION)[2:10])
        self.assertEqual(words[15], (~sum(words[2:10] + words[16:])) & 0xFF)

    def test_connect_accept_and_child_transfer_golden_vectors(self):
        translator = TranslatorFixture.connecting()
        duplicate = translator.from_core(
            rfu1(RFU1_CONNECT_REQ, HOST_SESSION), peer_id=1, sequence=1)
        self.assertEqual(
            rfu1(RFU1_CONNECT_REQ, HOST_SESSION).hex(),
            VECTORS["vectors"]["core_connect_request"])
        self.assertEqual(
            duplicate[0].payload.hex(), VECTORS["vectors"]["switch_connect_request"])

        accept_frame = accept()
        self.assertEqual(accept_frame.hex(), VECTORS["vectors"]["switch_accept"])
        action = translator.from_switch(
            accept_frame, flags=FLAGS_METADATA, generation=1, sequence=2)[0]
        self.assertEqual(action.payload.hex(), VECTORS["vectors"]["core_connect_ack"])
        self.assertEqual(
            struct.unpack("!III", action.payload[:12]),
            (RFU1_MAGIC, RFU1_CONNECT_ACK, ASSIGNMENT))
        self.assertEqual(translator.state, "connected")

        slot = bytes.fromhex("0e10") + bytes(range(14))
        header = (len(slot) << 24) | GPSP_DEVICE
        core_frame = rfu1(RFU1_CLIENT_SEND, header, slot, size=104)
        self.assertEqual(core_frame.hex(), VECTORS["vectors"]["core_client_send"])
        transfer = translator.from_core(core_frame, peer_id=1, sequence=2)[0]
        expected_body = (
            CHILD_TIMESTAMP_SEED.to_bytes(4, "little") + bytes((0, len(slot), 0, 0)) + slot)
        self.assertEqual(transfer.payload, gba(GBA_TRANSFER, expected_body))
        self.assertEqual(
            transfer.payload.hex(), VECTORS["vectors"]["switch_child_transfer"])
        self.assertEqual(transfer.flags, FLAGS_GBA)

    def test_parent_transfer_core_ack_and_switch_k_golden_vectors(self):
        translator = TranslatorFixture.connected()
        slot = bytes.fromhex("110001") + bytes(range(14))
        frame = parent_t(0x4B7B, slot)
        self.assertEqual(frame.hex(), VECTORS["vectors"]["switch_parent_transfer"])
        action = translator.from_switch(
            frame, flags=FLAGS_GBA, generation=1, sequence=3)[0]
        self.assertEqual(action.payload.hex(), VECTORS["vectors"]["core_host_send"])
        self.assertEqual(
            struct.unpack("!III", action.payload[:12]),
            (RFU1_MAGIC, RFU1_HOST_SEND, len(slot)))
        self.assertEqual(action.payload[12:12 + len(slot)], slot)

        core_ack = rfu1(RFU1_CLIENT_ACK, ASSIGNMENT)
        self.assertEqual(core_ack.hex(), VECTORS["vectors"]["core_client_ack"])
        ack = translator.from_core(core_ack, peer_id=1, sequence=2)[0]
        self.assertEqual(
            ack.payload,
            gba(GBA_ACK, (1).to_bytes(4, "little") + (1).to_bytes(4, "little")
                + (0x4B7B).to_bytes(4, "little")))
        self.assertEqual(ack.payload.hex(), VECTORS["vectors"]["switch_ack"])

    def test_idle_parent_poll_is_acked_without_fake_core_data(self):
        translator = TranslatorFixture.connected()
        actions = translator.from_switch(
            parent_t(100, None), flags=FLAGS_GBA, generation=1, sequence=3)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].destination, "tunnel")
        self.assertEqual(actions[0].classification, "parent_ack")
        self.assertEqual(translator.snapshot()["pending_core_acks"], 0)

    def test_group_states_and_disconnects_are_classified(self):
        translator = TranslatorFixture.connected()
        self.assertEqual(translator.from_switch(
            gba(GBA_GROUP, (0).to_bytes(4, "little")), flags=FLAGS_GBA,
            generation=1, sequence=3), ())
        self.assertEqual(translator.from_switch(
            gba(GBA_GROUP, (1).to_bytes(4, "little")), flags=FLAGS_GBA,
            generation=1, sequence=4), ())
        self.assertEqual(
            gba(GBA_GROUP, (1).to_bytes(4, "little")).hex(),
            VECTORS["vectors"]["switch_group"])
        action = translator.from_core(
            rfu1(RFU1_DISCONNECT, ASSIGNMENT), peer_id=1, sequence=2)[0]
        self.assertEqual(
            rfu1(RFU1_DISCONNECT, ASSIGNMENT).hex(),
            VECTORS["vectors"]["core_disconnect"])
        self.assertEqual(action.payload, gba(GBA_DISCONNECT, CHILD_CONNECTION))
        self.assertEqual(action.payload.hex(), VECTORS["vectors"]["switch_disconnect"])
        self.assertEqual(translator.state, "closed")

        remote_close = TranslatorFixture.connected()
        action = remote_close.from_switch(
            gba(GBA_DISCONNECT, CHILD_CONNECTION), flags=FLAGS_GBA,
            generation=1, sequence=3)[0]
        self.assertEqual(
            struct.unpack("!III", action.payload[:12]),
            (RFU1_MAGIC, RFU1_DISCONNECT, ASSIGNMENT))
        self.assertEqual(remote_close.state, "closed")


class RfuTranslatorFailureTests(unittest.TestCase):
    def assert_code(self, code: str, call) -> None:
        with self.assertRaises(TranslatorError) as raised:
            call()
        self.assertEqual(raised.exception.code, code)

    def test_native_init_accept_does_not_relax_other_opcode_or_identity_validation(self):
        translator = TranslatorFixture.connecting()
        first = translator.from_switch(accept(), flags=FLAGS_METADATA, generation=1, sequence=2)
        self.assertEqual(translator.from_switch(accept(), flags=FLAGS_METADATA, generation=1, sequence=2), first)
        self.assertEqual(translator.state, "connected")
        self.assert_code("TRANSLATOR_RELIABLE_FLAGS", lambda: translator.from_switch(
            accept(), flags=0x010F, generation=1, sequence=2))
        translator = TranslatorFixture.connected()
        self.assert_code("TRANSLATOR_METADATA", lambda: translator.from_switch(
            parent_t(1, b"hello"), flags=FLAGS_METADATA, generation=1, sequence=3))
        translator = TranslatorFixture.connecting()
        bad = gba(GBA_ACCEPT, b"\0" * 6)
        self.assert_code("TRANSLATOR_ACCEPT", lambda: translator.from_switch(
            bad, flags=FLAGS_METADATA, generation=1, sequence=2))

    def test_sequence_duplicate_gap_reorder_and_generation(self):
        translator = TranslatorFixture.connecting()
        packet = rfu1(RFU1_CONNECT_REQ, HOST_SESSION)
        self.assertEqual(
            translator.from_core(packet, peer_id=1, sequence=1),
            translator.from_core(packet, peer_id=1, sequence=1))

        changed = TranslatorFixture.create()
        changed.accept_advertisement(advertisement(), generation=1)
        changed.from_core(packet, peer_id=1, sequence=1)
        self.assert_code("TRANSLATOR_DUPLICATE_CHANGED", lambda: changed.from_core(
            rfu1(RFU1_CONNECT_REQ, HOST_SESSION + 1), peer_id=1, sequence=1))

        gap = TranslatorFixture.create()
        gap.accept_advertisement(advertisement(), generation=1)
        self.assert_code("TRANSLATOR_SEQUENCE_GAP", lambda: gap.from_core(
            packet, peer_id=1, sequence=2))

        reconnect = TranslatorFixture.create()
        reconnect.from_switch(METADATA_FRAME, flags=FLAGS_METADATA, generation=1, sequence=1)
        self.assert_code("TRANSLATOR_GENERATION_STALE", lambda: reconnect.from_switch(
            METADATA_FRAME, flags=FLAGS_METADATA, generation=2, sequence=1))

        # A new Generation gets a new converter, including ACK/timestamp state.
        fresh = RfuTranslator(attempt_id="generation-2", tunnel_epoch=2,
                              child_connection_id=CHILD_CONNECTION, gpsp_device_id=GPSP_DEVICE)
        self.assertEqual(fresh.from_switch(
            METADATA_FRAME, flags=FLAGS_METADATA, generation=2, sequence=1), ())
        self.assertEqual(fresh._child_timestamp, CHILD_TIMESTAMP_SEED)
        self.assertEqual(fresh.snapshot()["pending_core_acks"], 0)

    def test_parent_timestamp_duplicates_reorder_and_change(self):
        translator = TranslatorFixture.connected()
        first = parent_t(100, b"\x01\x02")
        self.assertEqual(len(translator.from_switch(
            first, flags=FLAGS_GBA, generation=1, sequence=3)), 1)
        self.assertEqual(translator.from_switch(
            first, flags=FLAGS_GBA, generation=1, sequence=4), ())

        changed = TranslatorFixture.connected()
        changed.from_switch(first, flags=FLAGS_GBA, generation=1, sequence=3)
        self.assert_code("TRANSLATOR_TIMESTAMP_CHANGED", lambda: changed.from_switch(
            parent_t(100, b"\x02\x03"), flags=FLAGS_GBA, generation=1, sequence=4))

        reordered = TranslatorFixture.connected()
        reordered.from_switch(first, flags=FLAGS_GBA, generation=1, sequence=3)
        self.assert_code("TRANSLATOR_TIMESTAMP_REORDERED", lambda: reordered.from_switch(
            parent_t(99, b"\x01\x02"), flags=FLAGS_GBA, generation=1, sequence=4))

    def test_unknown_direction_length_flags_metadata_and_ack_fail_closed(self):
        invalid_core_types = (
            (RFU1_BROADCAST, 36), (RFU1_CONNECT_ACK, 16),
            (3, 16), (RFU1_HOST_SEND, 104),
        )
        for packet_type, size in invalid_core_types:
            translator = TranslatorFixture.connected()
            self.assert_code("TRANSLATOR_CORE_DIRECTION", lambda t=translator, p=packet_type, s=size:
                t.from_core(rfu1(p, 0, size=s), peer_id=1, sequence=2))

        for frame_type in (GBA_CONNECT, GBA_ACK, 0x7F):
            translator = TranslatorFixture.connected()
            self.assert_code("TRANSLATOR_SWITCH_DIRECTION", lambda t=translator, f=frame_type:
                t.from_switch(gba(f, b"\0\0"), flags=FLAGS_GBA,
                              generation=1, sequence=3))

        translator = TranslatorFixture.connected()
        self.assert_code("TRANSLATOR_RELIABLE_FLAGS", lambda: translator.from_switch(
            accept(), flags=1, generation=1, sequence=3))
        translator = TranslatorFixture.create()
        self.assert_code("TRANSLATOR_METADATA", lambda: translator.from_switch(
            b"invalid", flags=FLAGS_METADATA, generation=1, sequence=1))
        translator = TranslatorFixture.connected()
        self.assert_code("TRANSLATOR_ACK_UNCORRELATED", lambda: translator.from_core(
            rfu1(RFU1_CLIENT_ACK, ASSIGNMENT), peer_id=1, sequence=2))

    def test_malformed_lengths_ids_padding_and_group_regression_fail(self):
        translator = TranslatorFixture.create()
        translator.accept_advertisement(advertisement(), generation=1)
        self.assert_code("TRANSLATOR_RFU1_LENGTH", lambda: translator.from_core(
            rfu1(RFU1_CONNECT_REQ, HOST_SESSION)[:-1], peer_id=1, sequence=1))

        translator = TranslatorFixture.connected()
        slot = b"\x01\x02"
        header = (len(slot) << 24) | (GPSP_DEVICE + 1)
        self.assert_code("TRANSLATOR_CLIENT_DATA", lambda: translator.from_core(
            rfu1(RFU1_CLIENT_SEND, header, slot, size=104), peer_id=1, sequence=2))

        translator = TranslatorFixture.connected()
        translator.from_switch(
            gba(GBA_GROUP, (1).to_bytes(4, "little")), flags=FLAGS_GBA,
            generation=1, sequence=3)
        self.assert_code("TRANSLATOR_GROUP_STATE", lambda: translator.from_switch(
            gba(GBA_GROUP, (0).to_bytes(4, "little")), flags=FLAGS_GBA,
            generation=1, sequence=4))

    def test_parent_ack_queue_is_bounded(self):
        translator = TranslatorFixture.connected()
        for index in range(MAX_PENDING):
            translator.from_switch(
                parent_t(index + 1, b"\x01\x02"), flags=FLAGS_GBA,
                generation=1, sequence=index + 3)
        self.assert_code("TRANSLATOR_QUEUE_FULL", lambda: translator.from_switch(
            parent_t(MAX_PENDING + 1, b"\x01\x02"), flags=FLAGS_GBA,
            generation=1, sequence=MAX_PENDING + 3))

    def test_snapshot_is_role_limited_and_redacted(self):
        translator = TranslatorFixture.connected()
        snapshot = translator.snapshot()
        self.assertEqual(snapshot["role_capabilities"], ["finder"])
        self.assertNotIn("attempt_id", snapshot)
        self.assertNotIn("child_connection_id", snapshot)
        self.assertNotIn("gpsp_device_id", snapshot)


class RfuTranslatorStressTests(unittest.TestCase):
    @staticmethod
    def _run_10000_messages() -> tuple[str, dict, tuple[int, int, int]]:
        translator = TranslatorFixture.connected()
        digest = hashlib.sha256()
        child = rfu1(
            RFU1_CLIENT_SEND, (1 << 24) | GPSP_DEVICE, b"\x5a", size=104)
        for index in range(5_000):
            core_action = translator.from_core(
                child, peer_id=1, sequence=index + 2)[0]
            switch_action = translator.from_switch(
                parent_t(index + 1, None), flags=FLAGS_GBA,
                generation=1, sequence=index + 3)[0]
            for action in (core_action, switch_action):
                digest.update(action.destination.encode("ascii"))
                digest.update(action.classification.encode("ascii"))
                digest.update(action.payload)
        bounds = (
            len(translator._sequence_cache["core"]),  # noqa: SLF001
            len(translator._sequence_cache["remote"]),  # noqa: SLF001
            len(translator._parent_timestamps),  # noqa: SLF001
        )
        return digest.hexdigest(), translator.snapshot(), bounds

    def test_exact_10000_message_stress_is_deterministic_and_bounded(self):
        first = self._run_10000_messages()
        second = self._run_10000_messages()

        self.assertEqual(first, second)
        self.assertEqual(first[1]["state"], "connected")
        self.assertEqual(first[1]["pending_core_acks"], 0)
        self.assertEqual(first[2], (MAX_PENDING, MAX_PENDING, MAX_PENDING))


@pytest.mark.parametrize("flags", [0x107, 0x10F, 0xFFFF, -1, True, 0x10007])
def test_duplicate_cannot_bypass_full_width_flags_validation(flags):
    translator = TranslatorFixture.connected()
    frame = parent_t(100, None)
    translator.from_switch(frame, flags=FLAGS_GBA, generation=1, sequence=3)
    with pytest.raises(TranslatorError) as first:
        translator.from_switch(frame, flags=flags, generation=1, sequence=3)
    assert first.value.code == "TRANSLATOR_RELIABLE_FLAGS"
    with pytest.raises(TranslatorError) as second:
        translator.start()
    assert second.value is first.value


def test_parse_failure_is_sticky_and_does_not_advance_sequence():
    translator = TranslatorFixture.connected()
    with pytest.raises(TranslatorError) as first:
        translator.from_core(b"invalid", peer_id=1, sequence=2)
    assert first.value.code == "TRANSLATOR_RFU1_LENGTH"
    assert translator._sequence_last["core"] == 1
    with pytest.raises(TranslatorError) as second:
        translator.from_core(rfu1(RFU1_CLIENT_ACK, ASSIGNMENT), peer_id=1, sequence=2)
    assert first.value is second.value


def test_reserved_rfu_client_header_bits_are_rejected():
    translator = TranslatorFixture.connected()
    with pytest.raises(TranslatorError, match="gpSP child data"):
        translator.from_core(rfu1(RFU1_CLIENT_SEND, (1 << 24) | 0x40000 | GPSP_DEVICE,
                                   b"a", size=104), peer_id=1, sequence=2)


if __name__ == "__main__":
    unittest.main()
