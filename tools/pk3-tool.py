#!/usr/bin/env python3
"""pk3-tool — Gen-3 .pk3/.ek3 읽기·편집·변환 CLI for MWL-SwitchTrade.

Parsing/encryption logic inlined from frlgsim/mon.py (tornadus/frlg-ldn-trade),
which itself mirrors the canonical PKHeX .pk3 layout — so a file this tool reads
is guaranteed to be understood by the trade simulator.

Usage:
  pk3-tool.py info <file>                 # full dump: PID/TID/SID/OT/nick/species/level/checksum
  pk3-tool.py check <file>                # checksum validation only
  pk3-tool.py set <file> -o <out> [options]
      --tid N   --sid N   --ot NAME   --nick NAME   --level N
      --species N  --item N  --exp N
  pk3-tool.py convert <file> -o <out> --to ek3|pk3
"""

import argparse
import os
import sys

from species_map import SPECIES
from stats import build_party_tail
from charmap_jp import G3_JP, G3_JP_REV

# ── Gen-3 mon constants ───────────────────────────────────────────────────────
PARTY_MON_SIZE = 100
BOX_SIZE = 80
SECURE_OFF = 32
SECURE_END = 80

SUBSTRUCT_ORDER = [
    "GAEM", "GAME", "GEAM", "GEMA", "GMAE", "GMEA",
    "AGEM", "AGME", "AEGM", "AEMG", "AMGE", "AMEG",
    "EGAM", "EGMA", "EAGM", "EAMG", "EMGA", "EMAG",
    "MGAE", "MGEA", "MAGE", "MAEG", "MEGA", "MEAG",
]

_CHARS = {0x00: " ", 0xAB: "!", 0xAC: "?", 0xAD: ".", 0xAE: "-", 0xAF: "·", 0xB0: "…",
          0xB1: "“", 0xB2: "”", 0xB3: "‘", 0xB4: "’", 0xB5: "♂", 0xB6: "♀", 0xB7: "¥",
          0xB8: ",", 0xB9: "×", 0xBA: "/", 0xFF: ""}
for _i in range(10):
    _CHARS[0xA1 + _i] = "0123456789"[_i]
for _i in range(26):
    _CHARS[0xBB + _i] = chr(ord("A") + _i)
    _CHARS[0xD5 + _i] = chr(ord("a") + _i)
_CHAR_TO_BYTE = {v: k for k, v in _CHARS.items() if v}


def gba_str(b):
    """Decode a Gen-3 name field (0xFF terminator). Uses the EN charmap, falling back to
    the JP charmap when the bytes are not representable in EN (Japanese-named mons)."""
    out = []
    jp_hint = False
    for x in b:
        if x == 0xFF:
            break
        if x in _CHARS:
            out.append(_CHARS[x])
        else:
            jp_hint = True
            out.append("?")
    if not jp_hint:
        return "".join(out)
    out = []
    for x in b:
        if x == 0xFF:
            break
        out.append(G3_JP.get(x, "."))
    return "".join(out)


def gba_encode(s, length, jp=False):
    """Encode a display string into a Gen-3 name field (0xFF-padded). Use jp=True for
    Japanese names (uses the JP charmap)."""
    table = G3_JP_REV if jp else _CHAR_TO_BYTE
    raw = bytearray()
    for ch in s:
        if ch not in table:
            raise ValueError(f"cannot encode char {ch!r} (use --lang jp for Japanese names)")
        raw.append(table[ch])
        if len(raw) >= length:
            break
    raw += b"\xFF" * (length - len(raw))
    return bytes(raw)


def to_decrypted(wire):
    """encrypted+shuffled (.ek3 / wire) -> decrypted canonical (.pk3)."""
    pid = int.from_bytes(wire[0:4], "little")
    key = pid ^ int.from_bytes(wire[4:8], "little")
    dec = bytearray(wire)
    for i in range(12):
        o = SECURE_OFF + i * 4
        v = (int.from_bytes(dec[o:o + 4], "little") ^ key) & 0xFFFFFFFF
        dec[o:o + 4] = v.to_bytes(4, "little")
    order = SUBSTRUCT_ORDER[pid % 24]
    sec = dec[SECURE_OFF:SECURE_END]
    canon = bytearray(48)
    for ci, letter in enumerate("GAEM"):
        p = order.index(letter)
        canon[ci * 12:ci * 12 + 12] = sec[p * 12:p * 12 + 12]
    dec[SECURE_OFF:SECURE_END] = canon
    return bytes(dec)


def to_encrypted(pk3):
    """decrypted canonical (.pk3) -> encrypted+shuffled (.ek3 / wire)."""
    pid = int.from_bytes(pk3[0:4], "little")
    key = pid ^ int.from_bytes(pk3[4:8], "little")
    order = SUBSTRUCT_ORDER[pid % 24]
    canon = pk3[SECURE_OFF:SECURE_END]
    shuf = bytearray(48)
    for p in range(4):
        ci = "GAEM".index(order[p])
        shuf[p * 12:p * 12 + 12] = canon[ci * 12:ci * 12 + 12]
    out = bytearray(pk3)
    out[SECURE_OFF:SECURE_END] = shuf
    for i in range(12):
        o = SECURE_OFF + i * 4
        v = (int.from_bytes(out[o:o + 4], "little") ^ key) & 0xFFFFFFFF
        out[o:o + 4] = v.to_bytes(4, "little")
    return bytes(out)


def checksum(decrypted):
    """16-bit sum over the decrypted 48-byte secure region."""
    return sum(int.from_bytes(decrypted[i * 2:i * 2 + 2], "little") for i in range(24)) & 0xFFFF


def recompute_checksum(pk3_dec):
    """Set the stored checksum (offset 28, plaintext header) from decrypted bytes."""
    out = bytearray(pk3_dec)
    out[28:30] = checksum(out[SECURE_OFF:SECURE_END]).to_bytes(2, "little")
    return bytes(out)


def canonical_view(mon):
    """Return (decrypted-canonical bytes, form) — auto-detects wire (.ek3) vs decrypted (.pk3).

    A wire-form mon checksum-validates AFTER decrypting the secure region; a decrypted
    .pk3 does NOT (it would be double-decrypted). Header + party tail are plaintext in both."""
    if len(mon) >= 80:
        dec = to_decrypted(mon[:100])
        stored = int.from_bytes(mon[28:30], "little")
        if checksum(dec[SECURE_OFF:SECURE_END]) == stored:
            return bytes(dec), "wire/.ek3"
    return bytes(mon[:100]), "decrypted/.pk3"


def decode(mon):
    """Decode a 100B party mon (auto-detects wire vs decrypted)."""
    if len(mon) < 80:
        return None
    canon, form = canonical_view(mon)
    pid = int.from_bytes(canon[0:4], "little")
    otid = int.from_bytes(canon[4:8], "little")
    stored = int.from_bytes(canon[28:30], "little")
    growth = canon[32:44]
    attacks = canon[44:56]
    evs = canon[56:68]
    misc = canon[68:80]
    iv_word = int.from_bytes(misc[4:8], "little")
    ivs = [(iv_word >> (5 * i)) & 0x1F for i in range(6)]
    nature = pid % 25
    # party tail is plaintext in both forms; box exports carry a zero tail
    tail = mon[80:100] if len(mon) >= 100 else b""
    level = tail[4] if len(tail) >= 20 else None
    stats_tup = tuple(int.from_bytes(tail[o:o + 2], "little") for o in (6, 8, 10, 12, 14, 16, 18)) if len(tail) >= 20 else None
    tail_src = "file"
    if level == 0 and len(tail) >= 20:
        rebuilt = build_party_tail(canon)
        if rebuilt:
            level = rebuilt[4]
            stats_tup = tuple(int.from_bytes(rebuilt[o:o + 2], "little") for o in (6, 8, 10, 12, 14, 16, 18))
            tail_src = "rebuilt(exp)"
    return {
        "form": form,
        "pid": pid,
        "tid": otid & 0xFFFF,
        "sid": otid >> 16,
        "otid": otid,
        "nickname": gba_str(mon[8:18]),
        "language": mon[18],
        "otName": gba_str(mon[20:27]),
        "checksum_ok": checksum(canon[SECURE_OFF:SECURE_END]) == stored,
        "stored": stored,
        "calc": checksum(canon[SECURE_OFF:SECURE_END]),
        "species": int.from_bytes(growth[0:2], "little"),
        "species_name": SPECIES.get(int.from_bytes(growth[0:2], "little"), "?"),
        "heldItem": int.from_bytes(growth[2:4], "little"),
        "exp": int.from_bytes(growth[4:8], "little"),
        "moves": [int.from_bytes(attacks[i * 2:i * 2 + 2], "little") for i in range(4)],
        "evs": list(evs[:6]),
        "ivs": ivs,
        "nature": nature,
        "level": level,
        "stats": stats_tup,
        "tail_src": tail_src,
    }


def load(path):
    with open(path, "rb") as f:
        data = f.read()
    if len(data) not in (BOX_SIZE, PARTY_MON_SIZE):
        sys.exit(f"error: {path}: must be {BOX_SIZE} or {PARTY_MON_SIZE} bytes, got {len(data)}")
    return data


def cmd_info(args):
    mon = load(args.file)
    d = decode(mon)
    if not d:
        sys.exit("error: undecodable")
    ck = "OK" if d["checksum_ok"] else f"BAD (calc {d['calc']:04x} != stored {d['stored']:04x})"
    print(f"file          : {args.file} ({len(mon)}B, {d['form']})")
    print(f"species       : {d['species_name']} (#{d['species']})")
    print(f"PID           : {d['pid']:08X}")
    print(f"nature        : {d['nature']}")
    print(f"TID           : {d['tid']:05d} (0x{d['tid']:04X})")
    print(f"SID           : {d['sid']:05d} (0x{d['sid']:04X})")
    print(f"OT ID (u32)   : 0x{d['otid']:08X}")
    print(f"OT name       : {d['otName']!r}")
    print(f"nickname      : {d['nickname']!r}")
    print(f"language      : {d['language']}")
    print(f"held item     : {d['heldItem']}")
    print(f"exp           : {d['exp']}")
    print(f"level         : {d['level']} ({d['tail_src']})")
    print(f"moves         : {[f'{m:04X}' for m in d['moves']]}")
    print(f"IVs (hp/a/d/sa/sd/sp): {d['ivs']}")
    print(f"EVs (hp/a/d/sa/sd/sp): {d['evs']}")
    print(f"stats (hp/maxhp/a/d/sp/sa/sd): {d['stats']}")
    print(f"checksum      : {ck}")


def cmd_check(args):
    mon = load(args.file)
    d = decode(mon)
    if not d:
        sys.exit("error: undecodable")
    if d["checksum_ok"]:
        print(f"{args.file}: checksum OK (0x{d['calc']:04x}) — wire form (.ek3)")
    else:
        print(f"{args.file}: checksum BAD — decrypted form (.pk3)? calc=0x{d['calc']:04x} stored=0x{d['stored']:04x}")
    sys.exit(0 if d["checksum_ok"] else 1)


def cmd_set(args):
    mon = load(args.file)
    canon, form = canonical_view(mon)
    dec = bytearray(canon)
    changes = []

    if args.tid is not None or args.sid is not None:
        d = decode(mon)
        assert d, "undecodable mon"
        tid = args.tid if args.tid is not None else d["tid"]
        sid = args.sid if args.sid is not None else d["sid"]
        if not (0 <= tid <= 0xFFFF and 0 <= sid <= 0xFFFF):
            sys.exit("error: TID/SID must be 0..65535")
        dec[4:8] = (sid << 16 | tid).to_bytes(4, "little")
        changes.append(f"TID={tid} SID={sid}")

    if args.nick is not None:
        dec[8:18] = gba_encode(args.nick, 10)
        changes.append(f"nick={args.nick!r}")

    if args.ot is not None:
        dec[20:27] = gba_encode(args.ot, 7)
        changes.append(f"OT={args.ot!r}")

    if args.species is not None:
        dec[32:34] = int(args.species).to_bytes(2, "little")
        changes.append(f"species={args.species}")

    if args.item is not None:
        dec[34:36] = int(args.item).to_bytes(2, "little")
        changes.append(f"item={args.item}")

    if args.exp is not None:
        dec[36:40] = int(args.exp).to_bytes(4, "little")
        changes.append(f"exp={args.exp}")

    # level lives in the plaintext party tail; if the source had none, rebuild it from exp
    tail = bytearray(mon[80:100] if len(mon) >= 100 else b"\x00" * 20)
    if args.level is not None:
        if not (0 <= args.level <= 100):
            sys.exit("error: level must be 0..100")
        tail[4] = args.level
        changes.append(f"level={args.level}")

    dec = recompute_checksum(bytes(dec))
    wire = to_encrypted(bytes(dec))

    # keep the (possibly modified) party tail; write back in the SOURCE form
    out = (wire if form == "wire/.ek3" else bytes(dec))[:80] + bytes(tail)
    with open(args.out, "wb") as f:
        f.write(out)
    print(f"wrote {args.out} ({len(out)}B, {form})")
    print("changes:", ", ".join(changes) if changes else "(none)")
    d2 = decode(out)
    ck = "OK" if d2 and d2["checksum_ok"] else "BAD"
    print(f"verify: checksum {ck}, species={d2['species_name'] if d2 else '?'}, "
          f"level={d2['level'] if d2 else '?'} ({d2['tail_src'] if d2 else '?'})")


def cmd_convert(args):
    mon = load(args.file)
    canon, form = canonical_view(mon)
    if args.to == "ek3":
        out = to_encrypted(canon)
        desc = "wire (.ek3)"
    else:
        out = canon
        desc = "decrypted (.pk3)"
    with open(args.out, "wb") as f:
        f.write(out)
    print(f"wrote {args.out} ({len(out)}B, {desc}, source was {form})")


def main():
    p = argparse.ArgumentParser(description="Gen-3 .pk3/.ek3 tool")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("info", help="dump full info")
    pi.add_argument("file")
    pi.set_defaults(fn=cmd_info)

    pc = sub.add_parser("check", help="validate checksum")
    pc.add_argument("file")
    pc.set_defaults(fn=cmd_check)

    ps = sub.add_parser("set", help="edit fields (recomputes checksum)")
    ps.add_argument("file")
    ps.add_argument("-o", "--out", required=True)
    ps.add_argument("--tid", type=int)
    ps.add_argument("--sid", type=int)
    ps.add_argument("--ot", type=str)
    ps.add_argument("--nick", type=str)
    ps.add_argument("--level", type=int)
    ps.add_argument("--species", type=int)
    ps.add_argument("--item", type=int)
    ps.add_argument("--exp", type=int)
    ps.set_defaults(fn=cmd_set)

    pv = sub.add_parser("convert", help="convert between .pk3 and .ek3")
    pv.add_argument("file")
    pv.add_argument("-o", "--out", required=True)
    pv.add_argument("--to", choices=["ek3", "pk3"], required=True)
    pv.set_defaults(fn=cmd_convert)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
