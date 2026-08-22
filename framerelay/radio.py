"""Monitor-mode radio: capture and inject raw 802.11 frames (Track B, docs/07 section 6).

Measured premises (docs/07 section 3, 8/21 field test):
- CAPTURE works via an AF_PACKET raw socket bound to a monitor interface; every packet
  arrives prefixed with a radiotap header that must be stripped before relaying.
- INJECTION only works WITH a radiotap header: the measured 8-byte
  ``00 00 08 00 00 00 00 00`` (version=0, pad=0, header_len=8, present=0). Without it the
  driver silently drops the frame - no error, just nothing on air.
- The bridge must relay ONLY its own Switch's traffic, so captures are filtered by host
  MAC (= the LDN soft-AP BSSID) across addr1/addr2/addr3, which covers every frame
  direction of the host/guest exchange.

Linux-only at runtime (AF_PACKET); the module imports cleanly anywhere so offline tests
can exercise the codec/filter helpers with stub sockets.
"""

import errno
import socket
import struct
import time
from collections import namedtuple

# radiotap TX header actually verified on the Realtek cards (8/21): version 0, pad 0,
# length 8, present-bitmap 0. struct.pack("<BBHI", 0, 0, 8, 0) reproduces it exactly.
RADIOTAP_TX_HEADER = struct.pack("<BBHI", 0, 0, 8, 0)

ETH_P_ALL = 0x0003
_AF_PACKET = getattr(socket, "AF_PACKET", None)
_SOL_PACKET = getattr(socket, "SOL_PACKET", 263)
_PACKET_IGNORE_OUTGOING = getattr(socket, "PACKET_IGNORE_OUTGOING", 20)

# 802.11 frame control (docs/07: the bridge never interprets frames - these constants
# exist only for beacon classification and the BSSID filter).
TYPE_MANAGEMENT = 0
TYPE_CONTROL = 1
TYPE_DATA = 2
SUBTYPE_BEACON = 8

Dot11 = namedtuple("Dot11", "type subtype to_ds from_ds addr1 addr2 addr3")


def parse_mac(text):
    """'aa:bb:cc:dd:ee:ff' / 'AA-BB-CC-DD-EE-FF' -> 6 raw bytes. Raises ValueError on
    anything else so a CLI typo dies at startup instead of silently filtering nothing."""
    if isinstance(text, (bytes, bytearray)):
        if len(text) != 6:
            raise ValueError(f"MAC must be 6 bytes, got {len(text)}")
        return bytes(text)
    parts = str(text).strip().replace("-", ":").split(":")
    if len(parts) != 6:
        raise ValueError(f"invalid MAC {text!r} (expected e.g. 00:ad:a7:11:73:09)")
    try:
        mac = bytes(int(p, 16) for p in parts)
    except ValueError:
        raise ValueError(f"invalid MAC {text!r} (non-hex octet)") from None
    return mac


def mac_str(mac):
    """6 raw bytes -> lowercase 'aa:bb:cc:dd:ee:ff' (log form)."""
    return ":".join(f"{b:02x}" for b in mac)


def strip_radiotap(data):
    """Drop the leading radiotap header (length is the LE u16 at offset 2). Returns the
    bare 802.11 frame, or None when the capture is too short / declares a bogus or empty
    header - callers skip those instead of crashing on malformed monitor output."""
    if not isinstance(data, (bytes, bytearray, memoryview)) or len(data) < 4:
        return None
    data = bytes(data)
    rtap_len = struct.unpack_from("<H", data, 2)[0]
    if rtap_len < len(RADIOTAP_TX_HEADER) or rtap_len > len(data):
        return None
    frame = data[rtap_len:]
    return frame or None


def wrap_radiotap(frame):
    """Prepend the measured TX header - the injection precondition (docs/07 section 3)."""
    return RADIOTAP_TX_HEADER + bytes(frame)


def parse_80211(frame):
    """Minimal 802.11 header decode for filtering/classification -> Dot11, or None when
    the frame is shorter than an address field. Control frames legitimately carry only
    addr1; addr2/addr3 come back None when absent."""
    if not isinstance(frame, (bytes, bytearray)) or len(frame) < 10:
        return None
    fc = frame[0] | (frame[1] << 8)
    ftype = (fc >> 2) & 0x3
    subtype = (fc >> 4) & 0xF
    to_ds = bool(frame[1] & 0x01)
    from_ds = bool(frame[1] & 0x02)
    addr1 = bytes(frame[4:10])
    addr2 = bytes(frame[10:16]) if len(frame) >= 16 else None
    addr3 = bytes(frame[16:22]) if len(frame) >= 22 else None
    return Dot11(ftype, subtype, to_ds, from_ds, addr1, addr2, addr3)


def is_beacon(info):
    """Management subtype 8 = beacon (what the replay thread keeps alive)."""
    return info is not None and info.type == TYPE_MANAGEMENT and info.subtype == SUBTYPE_BEACON


def matches_host(info, host_mac):
    """True when the host's MAC appears in any address field. Host = LDN soft AP, so its
    beacons/probe-responses carry it in addr2+addr3, guest->host data in addr1 (BSSID),
    host->guest data in addr2/addr3 - one check covers all directions without the bridge
    understanding any of the payload."""
    if info is None or host_mac is None:
        return False
    host_mac = bytes(host_mac)
    return any(a == host_mac for a in (info.addr1, info.addr2, info.addr3) if a is not None)


# Consecutive hard recv() errors (anything beyond the benign errno classes below)
# before MonitorRadio declares the interface dead (audit 10 M-2: ENODEV on USB unplug
# or a driver wedge used to look exactly like "no traffic").
MAX_RECV_ERRORS = 5


class MonitorRadio:
    """One monitor-mode interface doing both capture and injection.

    recv() strips radiotap and returns bare 802.11 frames; send() re-adds the measured TX
    header before pushing the frame out. `sock` allows tests to inject a stub socket; the
    real path needs root + Linux (AF_PACKET).
    """

    def __init__(self, iface, host_mac=None, log=print):
        self.iface = iface
        self.host_mac = parse_mac(host_mac) if isinstance(host_mac, str) else host_mac
        self.log = log
        self._sock = None
        self._recv_errors = 0

    def open(self, sock=None):
        """Bind AF_PACKET SOCK_RAW to the monitor iface. PACKET_IGNORE_OUTGOING is set
        best-effort so our own injections don't loop straight back into the capture path
        (pre-Linux-4.20 kernels lack it - bridge.EchoGuard covers those)."""
        if sock is not None:
            self._sock = sock
            return self
        if _AF_PACKET is None:
            raise RuntimeError("AF_PACKET unavailable (Linux required for live capture)")
        s = socket.socket(_AF_PACKET, socket.SOCK_RAW, socket.htons(ETH_P_ALL))
        s.bind((self.iface, 0))
        try:
            s.setsockopt(_SOL_PACKET, _PACKET_IGNORE_OUTGOING, 1)
        except OSError as e:
            self.log(f"[radio] PACKET_IGNORE_OUTGOING unsupported ({e}) - "
                     "relying on EchoGuard to suppress our own echoes")
        self._sock = s
        return self

    def close(self):
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def recv(self, timeout=0.05):
        """Next captured 802.11 frame (radiotap stripped), or None on timeout/empty.

        OSError taxonomy (audit 10 M-2): EAGAIN/EWOULDBLOCK/EINTR are benign timing
        signals - keep polling. Any other errno (ENODEV on USB unplug, driver wedge,
        ...) logs one line and returns None for this call, but after MAX_RECV_ERRORS
        consecutive hard errors raises RuntimeError so the caller can stop instead of
        capturing silence forever.
        """
        if self._sock is None:
            raise RuntimeError("MonitorRadio.recv() before open()")
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._recv_errors = 0
                return None
            self._sock.settimeout(remaining)
            try:
                data = self._sock.recv(65535)
            except (TimeoutError, socket.timeout):
                self._recv_errors = 0
                return None
            except OSError as e:
                if e.errno in (errno.EAGAIN, errno.EWOULDBLOCK, errno.EINTR):
                    continue                    # transient - poll again within the window
                self._recv_errors += 1
                if self._recv_errors >= MAX_RECV_ERRORS:
                    self._recv_errors = 0
                    raise RuntimeError(
                        f"monitor iface {self.iface}: {MAX_RECV_ERRORS} consecutive "
                        f"recv errors (interface gone? driver wedged?): {e}") from e
                self.log(f"[radio] recv error {self._recv_errors}/{MAX_RECV_ERRORS} "
                         f"({e}); will keep polling")
                return None
            self._recv_errors = 0
            frame = strip_radiotap(data)
            if frame:
                return frame

    def send(self, frame):
        """Inject one bare 802.11 frame with the mandatory radiotap TX header."""
        if self._sock is None:
            raise RuntimeError("MonitorRadio.send() before open()")
        self._sock.sendto(wrap_radiotap(frame), (self.iface, 0))

    def accepts(self, frame):
        """BSSID filter helper: keep only frames belonging to our own Switch (host MAC).
        host_mac=None disables filtering (relay everything captured)."""
        if self.host_mac is None:
            return True
        return matches_host(parse_80211(frame), self.host_mac)
