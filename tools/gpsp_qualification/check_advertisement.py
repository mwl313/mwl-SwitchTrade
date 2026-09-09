"""Offline RFU discovery check; exit 1 means an unresolved software defect.

Uses the synthetic advertisement fixture and the production converter only.
No emulator, radio, ROM, save, capture or network access. This is a necessary
packet-format check, NOT a game/physical qualification or a replacement encoder.
See GPSP_COMPATIBILITY_RESEARCH_20260909.md for the pinned source references.
"""
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[2]


def inspect_broadcast(packet: bytes) -> dict[str, bool]:
    checks = dict(frame=False, game_serial=False, game_checksum=False, trade_candidate=False)
    if len(packet) != 36:
        return checks
    magic, kind, device = struct.unpack("!III", packet[:12])
    checks["frame"] = magic == 0x52465531 and kind == 0 and 0 < device <= 0xFFFF
    # gpSP rfu.c copies these six host-order words into BCRD_FETCH's response.
    data = struct.pack("<6I", *struct.unpack("!6I", packet[12:]))
    # FRLG rfu_REQ_configGameData / rfu_STC_readParentCandidateList:
    # serial(2), gname(13), checksum(1), uname(8). Multiboot is not this profile.
    checks["game_serial"] = data[:2] == b"\x02\x00"
    checks["game_checksum"] = data[15] == (~sum(data[2:10] + data[16:24]) & 0xFF)
    checks["trade_candidate"] = (
        int.from_bytes(data[2:4], "little") in (0x1002, 0x1402)
        and not any(data[6:12]) and data[12] == 4 and data[13] <= 1
        and data[14] == 0 and data[16] != 0xFF and b"\xff" in data[16:24])
    return checks


def probe() -> dict:
    from switchtrade.endpoints.retroarch_gpsp.rfu import RfuTranslator

    fixture = json.loads((ROOT / "tests/fixtures/rfu/translator-vectors.v1.json").read_text())
    translator = RfuTranslator(attempt_id="advertisement-check", tunnel_epoch=1,
                              child_connection_id=b"\x67\x79", gpsp_device_id=0x4567)
    action, = translator.accept_advertisement(
        bytes.fromhex(fixture["vectors"]["advertisement"]), generation=1)
    checks = inspect_broadcast(action.payload)
    return {"verdict": "PASS" if all(checks.values()) else "FAIL",
            "scope": "synthetic production advertisement format only", "checks": checks}


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    result = probe()
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(0 if result["verdict"] == "PASS" else 1)
