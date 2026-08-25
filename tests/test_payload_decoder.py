import json
import math
from pathlib import Path
import struct
import tempfile
import unittest

from tools import payload_decoder as decoder


ROOT = Path(__file__).resolve().parents[1]
SALAMENCE = ROOT / "archive" / "pokemon" / "fixtures" / "0373_SALAMENCE.pk3"


class RepositoryLayoutTests(unittest.TestCase):
    def test_extractor_uses_tracked_bridge_by_default(self):
        from tools import extract_pokemon_payload

        self.assertEqual(extract_pokemon_payload.EMU_ROOT, ROOT / "bridge")
        self.assertTrue((extract_pokemon_payload.EMU_ROOT / "frlgsim" / "crypto.py").is_file())


def _gba(frame_type, body):
    return b"\x57" + bytes([frame_type]) + len(body).to_bytes(2, "little") + body


def _parent_t(command, timestamp=1):
    # Parent LLSF: state=UNI(4), payload is one 14-byte command.
    slot = ((4 << 14) | (3 + 14)).to_bytes(3, "little") + command
    body = timestamp.to_bytes(4, "little") + bytes([len(slot), 0, 0, 0]) + slot
    return _gba(0x54, body)


def _init_command(count, owner=1):
    return struct.pack("<7H", 0x8800, count, owner | 0x80, 0, 0, 0, 0)


def _fragment_command(index, fragment):
    fragment = fragment[:12].ljust(12, b"\x00")
    words = [0x8900 | index]
    words.extend(int.from_bytes(fragment[i:i + 2], "little") for i in range(0, 12, 2))
    return struct.pack("<7H", *words)


class PayloadSchemaTests(unittest.TestCase):
    def test_valid_record_round_trip(self):
        obj = {
            "capture_id": "gold",
            "room_id": "room-1",
            "timestamp_ns": 123,
            "direction": "host_to_peer",
            "payload_hex": "57410100aa",
            "source_frames": [10, 11],
            "complete": True,
            "src_mac": "AA:BB:CC:DD:EE:FF",
            "dst_mac": "00:11:22:33:44:55",
            "retransmit": False,
        }
        record = decoder.PayloadRecord.from_dict(obj)
        self.assertEqual(record.payload, bytes.fromhex("57410100aa"))
        self.assertEqual(record.src_mac, "aa:bb:cc:dd:ee:ff")
        self.assertEqual(record.to_dict()["payload_hex"], "57410100aa")

    def test_invalid_record_is_rejected(self):
        with self.assertRaises(decoder.PayloadSchemaError):
            decoder.PayloadRecord.from_dict({"capture_id": "x"})

        bad = {
            "capture_id": "gold", "room_id": "r", "timestamp_ns": 1,
            "direction": "sideways", "payload_hex": "00", "source_frames": [],
            "complete": True,
        }
        with self.assertRaises(decoder.PayloadSchemaError):
            decoder.PayloadRecord.from_dict(bad)

    def test_jsonl_loader_reports_line_number(self):
        obj = {
            "capture_id": "gold", "room_id": "r", "timestamp_ns": 1,
            "direction": "peer_to_host", "payload_hex": "00", "source_frames": [1],
            "complete": True,
        }
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "stream.jsonl"
            path.write_text(json.dumps(obj) + "\n{bad json}\n", encoding="utf-8")
            with self.assertRaisesRegex(decoder.PayloadSchemaError, r":2:"):
                decoder.load_payload_stream(path)


class CarrierTests(unittest.TestCase):
    def test_gba_parser_preserves_unexpected_prefix_and_frames(self):
        result = decoder.parse_gba_frames(b"\x4a\x01" + _gba(0x43, b"abc") + _gba(0x41, b"d"))
        self.assertEqual([frame.type_name for frame in result.frames], ["C", "A"])
        self.assertEqual(result.issues[0].code, "unexpected_prefix")

    def test_gba_parser_marks_truncation(self):
        result = decoder.parse_gba_frames(_gba(0x54, b"1234")[:-1])
        self.assertEqual(result.frames, ())
        self.assertEqual(result.issues[0].code, "truncated_body")

    def test_parent_t_carrier_decodes_rfu_command(self):
        command = _init_command(9)
        result = decoder.parse_gba_frames(_parent_t(command))
        carrier = decoder.parse_t_carrier(result.frames[0], role="parent", timestamp_ns=99)
        self.assertIsNotNone(carrier.slot)
        self.assertEqual(carrier.slot.state, decoder.RFU_UNI)
        self.assertEqual(carrier.slot.commands[0].name, "SEND_BLOCK_INIT")
        self.assertEqual(carrier.slot.commands[0].block_count, 9)
        self.assertEqual(carrier.timestamp_ns, 99)


class BlockTests(unittest.TestCase):
    def test_reassembles_complete_block_and_reports_padding(self):
        mon = SALAMENCE.read_bytes()
        count = math.ceil(len(mon) / 12)
        assembler = decoder.RfuBlockAssembler()
        init = decoder._parse_command(_init_command(count))
        block = assembler.feed(init, direction="host_to_peer", source_offset=4)
        self.assertIsNotNone(block)
        for index in range(count):
            command = decoder._parse_command(
                _fragment_command(index, mon[index * 12:(index + 1) * 12])
            )
            block = assembler.feed(command, direction="host_to_peer", source_offset=10 + index)
        self.assertTrue(block.complete)
        self.assertEqual(block.missing_indices, [])
        self.assertEqual(block.payload[:100], mon)
        self.assertEqual(len(block.payload), count * 12)
        self.assertEqual(len(assembler.completed), 1)

    def test_missing_fragment_is_not_pretended_complete(self):
        assembler = decoder.RfuBlockAssembler()
        block = assembler.feed(
            decoder._parse_command(_init_command(2)), direction="peer_to_host"
        )
        assembler.feed(
            decoder._parse_command(_fragment_command(0, b"partial")), direction="peer_to_host"
        )
        assembler.finalize()
        self.assertFalse(block.complete)
        self.assertEqual(block.missing_indices, [1])
        self.assertTrue(any(issue.code == "incomplete_block" for issue in assembler.issues))

    def test_duplicate_init_preserves_partial_block(self):
        assembler = decoder.RfuBlockAssembler()
        block = assembler.feed(
            decoder._parse_command(_init_command(2)), direction="peer_to_host"
        )
        assembler.feed(
            decoder._parse_command(_fragment_command(0, b"first")), direction="peer_to_host"
        )
        same = assembler.feed(
            decoder._parse_command(_init_command(2)), direction="peer_to_host"
        )
        self.assertIs(same, block)
        self.assertEqual(block.fragments[0][:5], b"first")
        assembler.feed(
            decoder._parse_command(_fragment_command(1, b"second")), direction="peer_to_host"
        )
        self.assertTrue(block.complete)
        self.assertEqual(len(assembler.completed), 1)

    def test_parent_rows_keep_independent_block_state(self):
        assembler = decoder.RfuBlockAssembler()
        blocks = []
        for mpid, value in ((0, b"zero"), (1, b"one")):
            blocks.append(assembler.feed(
                decoder._parse_command(_init_command(1), multiplayer_id=mpid),
                direction="host_to_peer",
            ))
            assembler.feed(
                decoder._parse_command(_fragment_command(0, value), multiplayer_id=mpid),
                direction="host_to_peer",
            )
        self.assertTrue(all(block.complete for block in blocks))
        self.assertEqual([block.multiplayer_id for block in blocks], [0, 1])
        self.assertEqual(len(assembler.completed), 2)

    def test_invalid_fragment_index_is_reported(self):
        assembler = decoder.RfuBlockAssembler()
        block = assembler.feed(
            decoder._parse_command(_init_command(1)), direction="peer_to_host", source_offset=7
        )
        assembler.feed(
            decoder._parse_command(_fragment_command(1, b"bad")),
            direction="peer_to_host",
            source_offset=8,
        )
        self.assertFalse(block.complete)
        self.assertEqual(assembler.issues[-1].code, "invalid_fragment_index")


class PokemonCandidateTests(unittest.TestCase):
    def test_scans_canonical_party_record(self):
        mon = SALAMENCE.read_bytes()
        candidates = decoder.scan_pokemon_candidates(b"noise" + mon + b"tail", source_id="fixture")
        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertTrue(candidate.valid)
        self.assertEqual(candidate.offset, 5)
        self.assertEqual(candidate.size, 100)
        self.assertEqual(candidate.form, "decrypted/.pk3")
        self.assertEqual(candidate.decoded["species_name"], "SALAMENCE")
        self.assertEqual(candidate.decoded["ivs"], [30, 30, 30, 31, 30, 30])

    def test_scans_wire_form(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("pk3_tool_test", ROOT / "tools" / "pk3-tool.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        wire = module.to_encrypted(SALAMENCE.read_bytes())
        candidates = decoder.scan_pokemon_candidates(wire, source_id="wire")
        self.assertEqual(len(candidates), 1)
        self.assertTrue(candidates[0].valid)
        self.assertEqual(candidates[0].form, "wire/.ek3")

    def test_rejects_zero_and_truncated_records(self):
        self.assertEqual(decoder.scan_pokemon_candidates(bytes(100)), [])
        self.assertEqual(decoder.scan_pokemon_candidates(SALAMENCE.read_bytes()[:79]), [])

    def test_rejects_raw_capture_sized_input(self):
        with self.assertRaises(ValueError):
            decoder.scan_pokemon_candidates(b"\x00" * 101, max_bytes=100)

    def test_candidate_from_reassembled_block(self):
        mon = SALAMENCE.read_bytes()
        candidates = decoder.scan_pokemon_candidates(mon, source_id="block", complete=True)
        self.assertTrue(candidates[0].valid)
        incomplete = decoder.scan_pokemon_candidates(mon, source_id="gap", complete=False)
        self.assertFalse(incomplete[0].valid)


if __name__ == "__main__":
    unittest.main()
