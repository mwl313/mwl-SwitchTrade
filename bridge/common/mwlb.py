"""MWLB frame codec - the shared wire format for the relay tunnel (Track A + Track B).

Wire format ([PHASE2_DESIGN.md S4]; byte-identical to frlgsim.transport.RemoteTransport
_build_frame/_parse_frame - do not diverge):

    [4B magic b"MWLB"][1B msg_type][2B payload length BE][payload]

The relay (relay/server.py) is a dumb bytes pipe: it never inspects frames, so every
message type rides the same session. Track A carries game-semantic state messages
(0x01..0x04, 0x10, owned by frlgsim.transport); Track B (framerelay/) tunnels whole raw
802.11 frames as MSG_FRAME_RELAY (0x20) so two Switches trade through the relay exactly
as if they shared one radio cell (docs/07-framerelay-design.md).
"""

import struct

MWLB_MAGIC = b"MWLB"

# Message-type registry. 0x01..0x10 are Track A game semantics (defined here for the
# shared heartbeat only; their meaning lives in frlgsim.transport.RemoteTransport).
MSG_TRADE_SELECT = 0x01
MSG_TRADE_CONFIRM = 0x02
MSG_TRADE_CANCEL = 0x03
MSG_HEARTBEAT = 0x04
MSG_STATE_SYNC = 0x10

# Track B: transparent 802.11 frame tunnel. payload = one raw 802.11 frame WITHOUT its
# radiotap header; the receiving bridge re-adds a fresh radiotap TX header locally
# (docs/07 section 3: injection REQUIRES the measured 8-byte header or the driver
# silently drops the frame).
MSG_FRAME_RELAY = 0x20

HEADER_LEN = 7            # magic(4) + type(1) + len(2)
MAX_PAYLOAD = 0xFFFF      # bounded by the 2-byte length field


def build_frame(msg_type, payload=b""):
    """Frame `payload` as [b"MWLB"][type][len BE][payload]. Raises ValueError when the
    payload cannot fit the 2-byte length field: failing loudly beats emitting a frame a
    peer would silently drop mid-stream."""
    payload = bytes(payload)
    if len(payload) > MAX_PAYLOAD:
        raise ValueError(f"payload too large for MWLB framing: {len(payload)} > {MAX_PAYLOAD}")
    return MWLB_MAGIC + bytes([msg_type & 0xFF]) + struct.pack("!H", len(payload)) + payload


def parse_frame(data):
    """Parse one MWLB frame -> (msg_type, payload), or None when `data` is not a complete
    valid frame (wrong magic / truncated header / length field exceeding the buffer).
    Mirrors RemoteTransport._parse_frame: callers treat None as "skip", so short reads or
    garbage on the WS never crash the pump. Trailing bytes after the declared payload are
    ignored (the next frame in a batch starts there)."""
    if not isinstance(data, (bytes, bytearray, memoryview)) or len(data) < HEADER_LEN:
        return None
    data = bytes(data)
    if data[:4] != MWLB_MAGIC:
        return None
    (length,) = struct.unpack_from("!H", data, 5)
    if length > len(data) - HEADER_LEN:
        return None
    return data[4], data[HEADER_LEN:HEADER_LEN + length]
