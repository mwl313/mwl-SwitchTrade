"""RFU beacon encoder unit tests (host-mode application_data, STEP 2).

Verifies frlgsim.beacon against the DECODER side in transport.py (which stays untouched):
the encoder must produce application_data that _dump_beacon's own decoding path
(_b85_decode + _frlg_name + fixed offsets) reads back identically.

  1. Roundtrip: build_application_data(0x9ca7, "DESTROY", 0x1efd) -> decode -> TID/name/session.
  2. FRLG name encoding: exact inverse of _frlg_name for A-Z/a-z/0-9 (plus drop/pad edges).
  3. Custom base85 encode/decode roundtrip (alphabet 0x23..0x78 skipping 0x5C, LSB first).
  4. Pia system header: exactly 0x5C bytes, observed prefix, override parameterisation.
  5. partner_info / tradeSpecies field placement (species in the UPPER 16 bits).

Run:  .venv/bin/python tests/test_beacon_encoder.py
"""

import os
import random
import sys
import unittest

EMU_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, EMU_ROOT)

from frlgsim import beacon as bmod                                    # noqa: E402
from frlgsim.beacon import (build_application_data, build_pia_header,  # noqa: E402
                            build_rfu_record, encode_frlg_name)
from frlgsim.transport import (HostTransport, _PIA_HDR, _b85_decode,  # noqa: E402
                               _dump_beacon, _frlg_name)


class BeaconRoundtripTest(unittest.TestCase):
    """The required acceptance case: build -> decode with transport's decoder -> fields match."""

    def test_roundtrip_tid_name_session(self):
        app = build_application_data(0x9CA7, "DESTROY", 0x1EFD)
        self.assertEqual(len(app), _PIA_HDR + 30)       # header + 6 base85 groups of a 24B record
        d = _b85_decode(app[_PIA_HDR:])
        self.assertEqual(len(d), 24)
        self.assertEqual(int.from_bytes(d[0:2], "little"), 0x9CA7)
        self.assertEqual(_frlg_name(d[2:10]), "DESTROY")
        self.assertEqual(int.from_bytes(d[10:12], "little"), 0x1EFD)

    def test_feeds_dump_beacon_decoder(self):
        lines = []
        app = build_application_data(0x9CA7, "DESTROY", 0x1EFD)
        ret = _dump_beacon(app, lines.append)
        self.assertEqual(ret, app)                      # pass-through unchanged
        decoded = [ln for ln in lines if "beacon decoded" in ln]
        self.assertEqual(len(decoded), 1)
        self.assertIn("host name='DESTROY'", decoded[0])
        self.assertIn("TID=0x9ca7", decoded[0])
        self.assertIn("RFU-session-id=0x1efd", decoded[0])


class FrlgNameEncodingTest(unittest.TestCase):
    def test_upper_lower_digits_mapping(self):
        for i in range(26):
            self.assertEqual(encode_frlg_name(chr(ord("A") + i)), bytes([0xBB + i]) + b"\xff" * 7)
            self.assertEqual(encode_frlg_name(chr(ord("a") + i)), bytes([0xD5 + i]) + b"\xff" * 7)
        for i in range(10):
            self.assertEqual(encode_frlg_name(str(i)), bytes([0xA1 + i]) + b"\xff" * 7)

    def test_inverse_of_frlg_name_full_alphabet(self):
        alnum = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
        encoded = encode_frlg_name(alnum)               # >8 chars: truncated to 7 + terminator
        self.assertEqual(len(encoded), 8)
        self.assertEqual(encoded[7], 0xFF)
        self.assertEqual(_frlg_name(encoded), alnum[:7])

    def test_padding_and_empty(self):
        self.assertEqual(encode_frlg_name(""), b"\xff" * 8)
        self.assertEqual(_frlg_name(b"\xff" * 8), "")
        self.assertEqual(encode_frlg_name("A"), b"\xbb" + b"\xff" * 7)

    def test_unknown_chars_dropped(self):
        self.assertEqual(encode_frlg_name("DE-STROY!"), encode_frlg_name("DESTROY"))


class Base85Test(unittest.TestCase):
    def test_known_vectors(self):
        # v=1: first char carries the low digit 1 -> '$' (0x24), then four zero digits '#'.
        self.assertEqual(bmod._b85_encode(b"\x01\x00\x00\x00"), b"$####")
        # digit 53 -> 0x58; digit 56 -> 0x5B (last char before the skipped 0x5C);
        # digit 57 must skip 0x5C ('\\') and lands on 0x5D.
        self.assertEqual(bmod._b85_encode(b"\x35\x00\x00\x00")[0], 0x58)
        self.assertEqual(bmod._b85_encode(b"\x38\x00\x00\x00")[0], 0x5B)
        self.assertEqual(bmod._b85_encode(b"\x39\x00\x00\x00")[0], 0x5D)
        # max u32 encodes without overflow (85^5 > 0xFFFFFFFF).
        self.assertEqual(_b85_decode(bmod._b85_encode(b"\xff\xff\xff\xff")), b"\xff\xff\xff\xff")

    def test_alphabet_skips_backslash(self):
        out = bmod._b85_encode(random.Random(2026).randbytes(40))
        self.assertNotIn(0x5C, out)
        self.assertTrue(all(0x23 <= c <= 0x78 for c in out))

    def test_roundtrip_random(self):
        rng = random.Random(20260822)
        for size in (4, 8, 12, 24, 100):
            data = rng.randbytes(size)
            self.assertEqual(_b85_decode(bmod._b85_encode(data)), data)

    def test_rejects_non_multiple_of_four(self):
        with self.assertRaises(ValueError):
            bmod._b85_encode(b"\x01\x02\x03")


class PiaHeaderTest(unittest.TestCase):
    def test_header_length(self):
        app = build_application_data(0x9CA7, "DESTROY", 0x1EFD)
        self.assertEqual(_PIA_HDR, 0x5C)
        self.assertEqual(len(build_pia_header()), 0x5C)
        self.assertEqual(app[:_PIA_HDR], build_pia_header())

    def test_observed_default_prefix(self):
        self.assertTrue(build_pia_header().startswith(bytes.fromhex("005c160058")))
        hdr = build_pia_header()
        self.assertEqual(int.from_bytes(hdr[0:2], "big"), 0x5C)
        self.assertEqual(hdr[2], 22)                       # system communication version
        self.assertEqual(int.from_bytes(hdr[3:5], "big"), 0x58)
        self.assertEqual(hdr[0x15:0x17], b"\x01\x01")

    def test_player_name_uses_documented_fixed_fields(self):
        hdr = build_pia_header(player_name="EMU")
        self.assertEqual(int.from_bytes(hdr[0x17:0x1B], "big"), 3)
        self.assertEqual(hdr[0x1B], 1)                    # UTF-8
        self.assertEqual(hdr[0x1C:0x1F], b"EMU")
        self.assertEqual(hdr[0x1F:], b"\x00" * (0x5C - 0x1F))

    def test_overrides(self):
        hdr = build_pia_header({0x50: b"\xab\xcd"})
        self.assertEqual(hdr[0x50:0x52], b"\xab\xcd")
        self.assertTrue(hdr.startswith(bytes.fromhex("005c16")))
        with self.assertRaises(ValueError):
            build_pia_header({0x5B: b"\x01\x02"})       # runs past the header end


class RecordFieldsTest(unittest.TestCase):
    def test_partner_info_placed_at_12_20(self):
        rec = build_rfu_record(0x1234, "AB", 0x5678, b"\x11\x22")
        self.assertEqual(rec[12:14], b"\x11\x22")
        self.assertEqual(rec[14:20], b"\x00" * 6)
        self.assertEqual(len(rec), 24)

    def test_trade_species_in_upper_16_bits(self):
        rec = build_rfu_record(1, "X", 2, trade_species=133)
        raw = int.from_bytes(rec[20:24], "little")
        self.assertEqual(raw >> 16, 133)                # what _dump_beacon logs
        self.assertEqual(raw & 0xFFFF, 0)

    def test_range_validation(self):
        with self.assertRaises(ValueError):
            build_rfu_record(0x10000, "X", 1)
        with self.assertRaises(ValueError):
            build_rfu_record(1, "X", 0x10000)
        with self.assertRaises(ValueError):
            build_rfu_record(1, "X", 1, trade_species=0x10000)


class HostIdentityTest(unittest.TestCase):
    def test_advertised_capacity_matches_captured_frlg_rooms(self):
        self.assertEqual(HostTransport.MAX_PARTICIPANTS, 6)


if __name__ == "__main__":
    unittest.main()
