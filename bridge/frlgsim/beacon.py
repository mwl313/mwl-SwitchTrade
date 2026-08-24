"""Host-mode RFU search beacon (LDN CreateNetworkParam.application_data) builder.

transport.py only DECODES the host's advertisement (``_dump_beacon`` + ``_b85_decode``) for
diagnostics; this module is its inverse, so a host-mode EMU room can ADVERTISE the same shape of
beacon via ldn's ``create_network()``. The application_data layout is:

    [0x5C bytes Pia 6.16-6.41 LDN system header][custom-base85-encoded 24-byte RFU record]

The RFU record mirrors ``_dump_beacon``'s offsets exactly:

    [0:2]   trainer_id      u16 LE
    [2:10]  in-game name    FRLG charset (A-Z/a-z/0-9), terminated + padded with 0xFF
    [10:12] rfu_session_id  u16 LE
    [12:20] partner_info    opaque (zeros by default)
    [20:24] tradeSpecies    u32 LE, species in the UPPER 16 bits (_dump_beacon logs >> 16)

The custom base85 and the Pia system header are parameterised so newly observed values from real
Switch advertisements can replace the defaults without touching transport.py.
"""

import struct

from frlgsim.transport import _PIA_HDR

RECORD_SIZE = 24                 # _b85-decoded RFU record length (_dump_beacon requires >= 24)
NAME_WIDTH = 8                   # record[2:10]
PARTNER_INFO_OFF = 12            # record[12:20]
PARTNER_INFO_SIZE = 8
TRADE_SPECIES_OFF = 20           # record[20:24]


# --- custom base85 (exact inverse of transport._b85_decode) ---------------------------------
def _digit_char(d):
    """base85 digit -> alphabet byte. Alphabet = 0x23..0x78 skipping 0x5C ('\\'), i.e. digits
    0..56 map to 0x23..0x5B and digits 57..84 to 0x5D..0x78."""
    c = d + 0x23
    return c + 1 if c >= 0x5C else c


def _b85_encode(data):
    """4-byte little-endian groups -> 5 alphabet chars, FIRST char = LEAST-significant digit
    (mirrors _b85_decode, which folds chars in reversed order into v*85+digit). The decoder
    truncates input length to a multiple of 5 and masks to 32 bits; every 4-byte group encodes
    losslessly (max 0xFFFFFFFF < 85^5), so decode(encode(x)) == x always holds."""
    data = bytes(data)
    if len(data) % 4:
        raise ValueError(f"base85 payload must be a multiple of 4 bytes, got {len(data)}")
    out = bytearray()
    for i in range(0, len(data), 4):
        v = int.from_bytes(data[i:i + 4], "little")
        for _ in range(5):                      # low digit first: first char is the LSB
            out.append(_digit_char(v % 85))
            v //= 85
    return bytes(out)


# --- FRLG name field (inverse of transport._frlg_name) --------------------------------------
_NAME_ENC = {}
for _i in range(26):
    _NAME_ENC[chr(ord("A") + _i)] = 0xBB + _i   # A..Z = 0xBB..0xD4
    _NAME_ENC[chr(ord("a") + _i)] = 0xD5 + _i   # a..z = 0xD5..0xEE
for _i in range(10):
    _NAME_ENC[str(_i)] = 0xA1 + _i              # 0..9 = 0xA1..0xAA


def encode_frlg_name(name, width=NAME_WIDTH):
    """str -> FRLG name bytes: letters/digits per _frlg_name's table, unknown characters dropped,
    0xFF terminator then 0xFF padding to exactly `width` bytes (_frlg_name stops at the first
    0xFF, so the padding is invisible to it)."""
    out = bytearray()
    for ch in name:
        b = _NAME_ENC.get(ch)
        if b is not None:
            out.append(b)
    del out[max(0, width - 1):]                 # keep room for the terminator
    out.append(0xFF)
    while len(out) < width:
        out.append(0xFF)
    return bytes(out)


# --- Pia 6.16-6.41 LDN system header --------------------------------------------------------
# https://github.com/kinnay/NintendoClients/wiki/LDN-Application-Data-(Pia)
# Pia 6.x fields are big-endian. This is a fixed 0x5C-byte structure, not a TLV:
#   0x00 u16 property size, 0x02 u8 system communication version,
#   0x03 u16 application communication version, 0x15/0x16 player-limit fields,
#   0x17 u32 player-name byte length, 0x1B encoding, 0x1C..0x5B name bytes.
_OBSERVED_HEADER_FIELDS = {
    0x00: struct.pack(">H", _PIA_HDR),
    0x02: b"\x16",                  # system communication version 22 (Pia 6.39-6.41)
    0x03: struct.pack(">H", 0x58),  # application communication version (captured FRLG value)
    0x15: b"\x01",                  # player limit enabled
    0x16: b"\x01",                  # current/advertised player count in captured FRLG room
}


def build_pia_header(overrides=None, size=_PIA_HDR, *, player_name=None):
    """Build the documented Pia 6.16-6.41 system-property header.

    ``player_name`` is UTF-8, with its byte length at 0x17 and encoding marker 1 at 0x1B.
    ``overrides`` remains available for captured game-specific variants and is applied last.
    """
    out = bytearray(size)
    fields = dict(_OBSERVED_HEADER_FIELDS)
    if player_name is not None:
        name = str(player_name).encode("utf-8")[:64]
        fields[0x17] = struct.pack(">I", len(name))
        fields[0x1B] = b"\x01"       # UTF-8
        fields[0x1C] = name
    fields.update(overrides or {})
    for off, val in fields.items():
        val = bytes(val)
        if not 0 <= off <= size - len(val):
            raise ValueError(f"header override at offset {off} (len {len(val)}) out of range "
                             f"for a {size:#x}-byte header")
        out[off:off + len(val)] = val
    return bytes(out)


# --- RFU record + full application_data -----------------------------------------------------
def build_rfu_record(trainer_id, name, rfu_session_id, partner_data=b"", trade_species=0):
    """The 24-byte RFU record that sits base85-encoded after the Pia header. Offsets are the ones
    _dump_beacon decodes: TID [0:2], name [2:10], RFU session id [10:12], partner info [12:20],
    tradeSpecies [20:24]. tradeSpecies lives in the upper 16 bits (the dump logs value >> 16);
    partner_data is zero-padded/truncated to PARTNER_INFO_SIZE."""
    if not 0 <= trainer_id <= 0xFFFF:
        raise ValueError(f"trainer_id {trainer_id:#x} does not fit u16")
    if not 0 <= rfu_session_id <= 0xFFFF:
        raise ValueError(f"rfu_session_id {rfu_session_id:#x} does not fit u16")
    if not 0 <= trade_species <= 0xFFFF:
        raise ValueError(f"trade_species {trade_species} does not fit u16")
    partner = (bytes(partner_data) + b"\x00" * PARTNER_INFO_SIZE)[:PARTNER_INFO_SIZE]
    return (struct.pack("<H", trainer_id)
            + encode_frlg_name(name)
            + struct.pack("<H", rfu_session_id)
            + partner
            + struct.pack("<I", trade_species << 16))


def build_application_data(trainer_id, name, rfu_session_id, partner_data=b"", *,
                           trade_species=0, header=None):
    """Full LDN CreateNetworkParam.application_data for a host-mode EMU room:
    [Pia system header][_b85_encode(build_rfu_record(...))]. `header` replaces the default
    (observed-fields) Pia header wholesale; it must stay 0x5C bytes because _dump_beacon and the
    console both slice the game payload at that fixed offset."""
    hdr = build_pia_header() if header is None else bytes(header)
    if len(hdr) != _PIA_HDR:
        raise ValueError(f"Pia system header must be {_PIA_HDR:#x} bytes, got {len(hdr)}")
    return hdr + _b85_encode(build_rfu_record(trainer_id, name, rfu_session_id,
                                              partner_data, trade_species))
