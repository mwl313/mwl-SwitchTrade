"""Pia connection layer (S0) - Net + Session(new) + RTT, the handshake the host must complete
before it registers the sim as a peer (no "OK" prompt until then).

Decoded from the kinnay NintendoClients wiki (Pia 6.32+ numbering: 1=Net, 3=RTT, 10=Reliable,
13=Session-new) and the reference capture. KEY FACTS:
  * The 2-byte station "variable id" is ASSIGNED per session, NOT derived from the MAC. Each
    side LEARNS the other's from the packet header: Pia header is [dst_var(2)][src_var(2)], and
    the message footer is the DESTINATION var id. So the sim reads its own var id (= IN header
    dst) and the host's (= IN header src) off the first incoming packet.
  * The 8-byte LDN "constant id" is a documented permutation of the station's
    six-byte MAC followed by 0x0000; it is not the display-order MAC bytes.
  * Net (proto 1): header [ver=1][type][size:u16 BE]; type 0x11 = connection request (host->us),
    0x12 = our response. Session (proto 13): join request (type 0) below. RTT (proto 3): type 0
    request -> type 1 response.

Verified: build_session_join() reproduces the reference capture's message #3 byte-for-byte
(except the random nonce). The Session join's exact PlayerInfo/version constants are templated
from the reference capture and may need live tuning against the real host.
"""

import os

# Proto ids (Pia 6.32+)
PROTO_NET = 1
PROTO_RTT = 3
PROTO_RELIABLE = 10
PROTO_SESSION = 13

# The reserved session pseudo-station var-id. RTT (proto 3) + session-control ride header dst=0x0001
# (NOT the peer var); the footer recipient stays the host var. (observed: RTT dst=0x0001 both ways)
SESSION_VAR = 0x0001
RTT_ORIGINATE_PERIOD = 10    # VBlanks between guest-originated RTT requests (~6/s; reference capture ~5.9/s)

# Net message types
NET_CONN_REQUEST = 0x11      # host -> joiner
NET_CONN_RESPONSE = 0x12     # joiner -> host
NET_UPDATE_PROPERTY = 0x50   # host -> joiner (mid-session "update network property", retransmit-until-acked)
NET_UPDATE_PROPERTY_ACK = 0x51   # joiner -> host

# Session(new) message types
SESSION_JOIN_REQUEST = 0
SESSION_JOIN_RESPONSE = 2
SESSION_UPDATE = 5
SESSION_FINALIZE = 6
SESSION_LEFT_SYNC = 7

# Session join templated constants (from the reference capture's message #3 - confirm/tune live).
DEFAULT_PROTOCOLS = [(1, 0), (3, 5), (5, 1), (10, 3), (13, 7), (15, 0)]
DEFAULT_APP_VER = bytes.fromhex("0058")
DEFAULT_PLAYER_ID = bytes.fromhex("00000000000000010000000000000000")


def _ip4(ip):
    return bytes(int(x) for x in ip.split("."))


# --- Net protocol (proto 1) -----------------------------------------------------------------
def parse_net(payload):
    """-> (version, type, body) for a Net message.

    The inner size is the trailing variable-payload size, not the size of the
    fixed fields that follow the four-byte header. Net 0x12 therefore carries
    ``size == 0`` while still containing its fixed sequence field.
    """
    if len(payload) < 4:
        return None
    return payload[0], payload[1], payload[4:]


def ldn_constant_id(mac):
    """Return Pia 6.x's 8-byte LDN constant id for a six-byte MAC."""
    mac = bytes(mac)
    if len(mac) != 6:
        raise ValueError("MAC must be 6 bytes")
    return bytes((mac[2], mac[4], mac[5], mac[3], mac[1], mac[0])) + b"\x00\x00"


def _net_station(ranking, ip=None, port=12345):
    address = _ip4(ip) + b"\x00" * 12 if ip else b"\x00" * 16
    return b"\x00" + bytes([ranking]) + b"\x00\x00" + address + \
        (port if ip else 0).to_bytes(2, "big")


def build_net_request(seqid, host_var, host_mac, network_id, *, host_ip,
                      peer_ip, max_stations=6):
    """Build the fixed-channel-gold Pia 6.x Net 0x11 connection status."""
    if max_stations < 2 or max_stations > 0xFFFF:
        raise ValueError("max_stations must include host and peer")
    records = [_net_station(0, host_ip), _net_station(1, peer_ip)]
    records.extend(_net_station(0xFF, None) for _ in range(max_stations - 2))
    payload = b"".join(records)
    body = bytearray()
    body += (seqid & 0xFFFFFFFF).to_bytes(4, "big")
    body += (_vid(host_var) & 0xFFFF).to_bytes(2, "big")
    body += ldn_constant_id(host_mac)
    body += (network_id & 0xFFFFFFFFFFFFFFFF).to_bytes(8, "big")
    body += b"\x01"                              # network is open
    body += max_stations.to_bytes(2, "big")
    body += b"\x00"                              # not migrating host
    return bytes([0x01, NET_CONN_REQUEST]) + len(payload).to_bytes(2, "big") + \
        bytes(body) + payload


def build_net_response(seqid=2):
    """The joiner's Net connection response (the reference capture, message #2: 01 12 00 00 | <seqid:u32 BE>).
    The seqid ECHOES the host's 0x11 connection-request seqid (its body[0:4]); hardcoding 2 deadlocks the
    moment the host's network-status seqid differs (endless 500ms 0x11 retransmits -> host send-buffer fill)."""
    return bytes([0x01, NET_CONN_RESPONSE, 0x00, 0x00]) + (seqid & 0xFFFFFFFF).to_bytes(4, "big")


def build_net_property_ack(seqid):
    """Net 0x51 'Update network property' ACK (observed: 01 51 00 00 | <seqid:u32 BE>), echoing
    the host's 0x50 seqid. The host retransmits its 0x50 every 500ms until it sees this ack."""
    return bytes([0x01, NET_UPDATE_PROPERTY_ACK, 0x00, 0x00]) + (seqid & 0xFFFFFFFF).to_bytes(4, "big")


def parse_net_conn_request(payload):
    """Pull the host's identity out of a Net 0x11 connection request. The Net body is
    `[u32 ?][host var-id u16][host constant id u64]...`; returns the variable id,
    six-byte constant-id prefix, and sequence id. The Session join must echo the
    constant id from this packet rather than re-deriving it from unrelated state."""
    n = parse_net(payload)
    if not n or n[1] != NET_CONN_REQUEST or len(n[2]) < 12:
        return None
    body = n[2]
    # body[0:4] = the connection-request seqid (echoed in our 0x12); body[4:6]=host var; body[6:12]=host MAC.
    return int.from_bytes(body[4:6], "big"), bytes(body[6:12]), int.from_bytes(body[0:4], "big")


# --- RTT protocol (proto 3) -----------------------------------------------------------------
def parse_rtt(payload):
    """RTT message [wiki RTT-Protocol]: type is at BYTE 0x0 (0=request, 1=response); [0x4:0x8] padding,
    [0x8:0x10] system time, then (this title) [0x13:0x15] = subject var-id (21B total).
    CRITICAL: byte 0x3 is the RTT PROTOCOL VERSION (3 for Pia 5.29-5.44), NOT part of the
    type. The old code read the type as a u32-LE over [0:4] -> on this title that yields 0x03000000
    (version<<24), never 0/1, so we treated every host RTT REQUEST as 'not a request' and NEVER
    responded (0 RTT out vs native's ~1000). It only worked on the reference capture because there the
    version byte was 0. The host pings us for liveness; a station that never answers gets degraded/dropped."""
    if len(payload) < 16:
        return None
    return {"type": payload[0],                          # 0=request, 1=response (single byte)
            "version": payload[3],                       # RTT proto version (3 here); MUST be preserved
            "systime": payload[8:16],
            "subject": payload[19:21] if len(payload) >= 21 else b""}


def build_rtt_response(request):
    """Turn a host RTT request (type 0) into our response: type u32 = 1 LITTLE-ENDIAN (observed:
    01 00 00 00), echoing the rest of the request VERBATIM - the 12-byte timestamp so the host can
    compute the round-trip, and the subject [19:21] = host var 0x7620 (NOT our var). (The old code
    wrote type BE + subject=our_var, both wrong vs the reference capture.)"""
    b = bytearray(request[:21].ljust(21, b"\x00"))
    b[0] = 1                                          # type = response (BYTE 0); preserve [1:4] incl the
    return bytes(b)                                   # version byte [3]=3 and the host's timestamp (it
    # uses the echoed timestamp to compute the round-trip). Native does exactly this: OUT response bytes
    # are 01 00 00 03 (type 1 + version 3), i.e. the request with only byte 0 flipped.


def build_rtt_request(template, systime):
    """Originate a guest type-0 RTT request (~5.9/s on dst=0x0001). Clone the host's last request
    `template` (so the layout/subject are byte-faithful) and set type=0 (LE) with a fresh incrementing
    `systime`. The host echoes it in a type-1 response; matching the echoed systime to the send tick
    gives the round-trip that drives the reliable RTO (and keeps our slot live in the host's RTT layer)."""
    b = bytearray(template[:21].ljust(21, b"\x00"))
    b[0] = 0                                          # type = request (BYTE 0); preserve the template's
    b[8:16] = (systime & ((1 << 64) - 1)).to_bytes(8, "little")   # version byte [3] + layout, fresh systime
    return bytes(b)


# --- Session protocol (proto 13) ------------------------------------------------------------
def build_session_join(src_mac, src_var, src_ip, dst_mac, dst_var, player_name,
                       random4, *, src_port=12345, app_ver=DEFAULT_APP_VER,
                       protocols=DEFAULT_PROTOCOLS, player_id=DEFAULT_PLAYER_ID):
    """Build a Session(new) join request. src = the sim (joiner), dst = the host. var ids are
    2-byte BE; macs are 6 bytes. Reproduces the reference capture's message #3 exactly given its values."""
    out = bytearray([SESSION_JOIN_REQUEST, len(protocols)])
    for pid, ver in protocols:
        out += bytes([pid, ver])
    out += app_ver
    out += random4                                   # 4-byte random nonce
    out += bytes(src_mac) + b"\x00\x00"              # source constant id (8)
    out += bytes(src_var)                            # source variable id (2)
    out += bytes([0, 0])                             # NAT mapping, is-private-IPv6
    out += b"\x00" * 32                              # identification token
    out += bytes(dst_mac) + b"\x00\x00"             # dest constant id (8)
    out += bytes(dst_var)                            # dest variable id (2)
    out += bytes([1, 1])                             # num players, num participants
    out += bytes([0]) + _ip4(src_ip) + src_port.to_bytes(2, "big")   # StationAddress (IPv4)
    nm = player_name.encode()[:20]                   # PlayerInfo
    out += player_id + len(nm).to_bytes(4, "big") + bytes([1]) + nm
    return bytes(out)


def _player_info(player_id, name):
    player_id = bytes(player_id)
    if len(player_id) != 16:
        raise ValueError("player id must be 16 bytes")
    encoded = name.encode()[:20]
    return player_id + len(encoded).to_bytes(4, "big") + b"\x01" + encoded


def build_session_join_response(host_constant, host_var, peer_constant, peer_var,
                                random4):
    """Build native Session type 2, byte-locked to the 2026-08-24 CH1 gold."""
    if len(random4) != 4:
        raise ValueError("random4 must be 4 bytes")
    return (b"\x02\x0d\x07\x01" + b"\x00" * 4 + bytes(random4)
            + bytes(host_constant) + _vid(host_var).to_bytes(2, "big")
            + bytes(peer_constant) + _vid(peer_var).to_bytes(2, "big")
            + b"\x01\x00\x01\x00\x00")


def _session_station(constant, variable, ip, index, join_order, token,
                     player_id, player_name):
    token = bytes(token)
    if len(token) != 32:
        raise ValueError("identification token must be 32 bytes")
    return (bytes(constant) + _vid(variable).to_bytes(2, "big")
            + _ip4(ip) + (12345).to_bytes(2, "big")
            + bytes([index]) + join_order.to_bytes(2, "big") + b"\x00" * 2
            + token + b"\x01\x01\x00\x00"
            + _player_info(player_id, player_name))


def build_session_update(host_constant, host_var, host_ip, host_player_id,
                         host_name, peer_constant, peer_var, peer_ip,
                         peer_token, peer_player_id, peer_name):
    """Build the native two-station Session type-5 accept/update."""
    header = (b"\x05\x00\x00\x01\x00\x00\x03" + bytes(host_constant)
              + _vid(host_var).to_bytes(2, "big") + b"\x02\x00\x00\x01"
              + b"\x00" * 6)
    return (header
            + _session_station(host_constant, host_var, host_ip, 0, 0,
                               b"\x00" * 32, host_player_id, host_name)
            + _session_station(peer_constant, peer_var, peer_ip, 1, 1,
                               peer_token, peer_player_id, peer_name))


def parse_session(payload):
    """Light parse: surface the message type (and station count for a join response/update)."""
    if not payload:
        return None
    t = payload[0]
    rec = {"type": t}
    if t in (SESSION_JOIN_REQUEST, SESSION_UPDATE) and len(payload) > 2:
        rec["count"] = payload[1]
    return rec


def parse_session_join(payload):
    """Parse the identity/address fields needed by a Pia 6.x session host."""
    if len(payload) < 2 or payload[0] != SESSION_JOIN_REQUEST:
        return None
    nproto = payload[1]
    pos = 2
    if len(payload) < pos + 2 * nproto + 2 + 4 + 8 + 2 + 2 + 32 + 8 + 2 + 2 + 1:
        return None
    protocols = [(payload[pos + i], payload[pos + i + 1])
                 for i in range(0, 2 * nproto, 2)]
    pos += 2 * nproto
    app_ver = int.from_bytes(payload[pos:pos + 2], "big"); pos += 2
    random4 = payload[pos:pos + 4]; pos += 4
    src_constant = payload[pos:pos + 8]; pos += 8
    src_var = int.from_bytes(payload[pos:pos + 2], "big"); pos += 2
    nat_mapping, private_ipv6 = payload[pos:pos + 2]; pos += 2
    token = payload[pos:pos + 32]; pos += 32
    dst_constant = payload[pos:pos + 8]; pos += 8
    dst_var = int.from_bytes(payload[pos:pos + 2], "big"); pos += 2
    players, participants = payload[pos:pos + 2]; pos += 2
    family = payload[pos]; pos += 1
    address_size = 4 if family == 0 else 16 if family == 1 else 0
    if not address_size or len(payload) < pos + address_size + 2:
        return None
    address = payload[pos:pos + address_size]; pos += address_size
    port = int.from_bytes(payload[pos:pos + 2], "big"); pos += 2
    names = []
    player_ids = []
    for _ in range(players):
        if len(payload) < pos + 21:
            return None
        player_ids.append(payload[pos:pos + 16]); pos += 16
        name_size = int.from_bytes(payload[pos:pos + 4], "big"); pos += 4
        encoding = payload[pos]; pos += 1
        if len(payload) < pos + name_size:
            return None
        raw_name = payload[pos:pos + name_size]; pos += name_size
        codec = "utf-16-be" if encoding == 2 else "utf-8"
        names.append(raw_name.decode(codec, errors="replace"))
    return {"protocols": protocols, "app_ver": app_ver, "random4": random4,
            "src_constant": src_constant, "src_var": src_var,
            "nat_mapping": nat_mapping, "private_ipv6": private_ipv6,
            "token": token, "dst_constant": dst_constant, "dst_var": dst_var,
            "players": players, "participants": participants,
            "address": ".".join(str(x) for x in address) if family == 0 else address.hex(),
            "port": port, "names": names, "player_ids": player_ids}


# --- connection state machine (HOST-ACK-GATED; loss-tolerant) -------------------------------
# Header var-id (dst,src) progression observed in the reference capture:
#   net 0x12 -> (0, 0)   |   session join -> (0, our_var)   |   finalize/reliable -> (host_var, our_var)
# We never advance on our own send; we advance when the HOST acknowledges - it retransmits 0x11
# until it accepts our join, then sends a Session msg (-> we finalize), then RTT/Reliable (-> up).
# Because the host retransmits every stage and we answer each, a dropped OUT packet is simply
# re-sent on the host's next retransmit. Outbox entries carry their own (dst_var, src_var).
ST_NET, ST_FINALIZE, ST_CONNECTED = "net", "finalize", "connected"
# back-compat aliases
NET_WAIT, SESSION_WAIT, CONNECTED = ST_NET, ST_FINALIZE, ST_CONNECTED


def build_session_finalize(our_mac):
    """Session(13) type 6 - the joiner's finalize referencing ITS OWN constant id (the reference
    capture, message #14: 06 <our_mac:6> 0000 0000000000 01). The capture embeds the joiner's MAC here, not the host's."""
    return bytes([6]) + ldn_constant_id(our_mac) + b"\x00" * 5 + bytes([1])


def _vid(x):
    return x if isinstance(x, int) else int.from_bytes(x, "big")


class ConnectionManager:
    """The S0 Pia connection as a host-ack-gated state machine. Outbox entries are
    (proto, payload, unicast, dst_var, src_var) - the var-ids change per stage."""

    def __init__(self, our_mac, host_mac, our_ip, host_ip, our_var=0xc493,
                 player_name="EMU", random4=b"\x00\x00\x00\x00", log=lambda *a: None):
        self.our_mac = bytes(our_mac)
        self.host_mac = bytes(host_mac)
        self.our_ip = our_ip
        self.host_ip = host_ip
        self.our_var = _vid(our_var)
        self.host_var = None
        self.player_name = player_name
        self.random4 = random4
        self.log = log
        self.info = getattr(log, "info", log)   # clean milestone sink (default-mode narration)
        self.state = ST_NET
        self._outbox = []
        # RTT origination: clone the host's last type-0 request as our template, bump a
        # systime per originated probe. _rtt_orig_tick gates the ~6/s cadence.
        self._last_host_rtt = None
        self._rtt_systime = 0x10000
        self._rtt_orig_tick = -10 ** 9
        # RTT measurement: each originated request's systime -> the tick it was sent, so the matching
        # type-1 response yields a round-trip. Completed round-trips (in ticks) accumulate in rtt_samples
        # for the caller to drain and feed into the reliable layer's RTO; the reliable RTO is RTT-driven.
        self._rtt_pending = {}
        self.rtt_samples = []

    def maybe_originate_rtt(self, tick):
        """Once connected, ORIGINATE a type-0 RTT request every RTT_ORIGINATE_PERIOD VBlanks (a liveness
        probe the host expects to see from us; it responds type-1, which we ignore). No-op
        until we have seen a host request to clone the layout from."""
        if not self.connected or self._last_host_rtt is None or self.host_var is None:
            return
        if tick - self._rtt_orig_tick < RTT_ORIGINATE_PERIOD:
            return
        self._rtt_orig_tick = tick
        self._rtt_systime = (self._rtt_systime + 1) & ((1 << 64) - 1)
        # remember when we sent this systime so the host's type-1 echo gives us the round-trip
        self._rtt_pending[self._rtt_systime] = tick
        if len(self._rtt_pending) > 64:                     # bound it if responses are being lost
            for k in sorted(self._rtt_pending, key=self._rtt_pending.get)[:32]:
                del self._rtt_pending[k]
        self._q(PROTO_RTT, build_rtt_request(self._last_host_rtt, self._rtt_systime),
                SESSION_VAR, self.our_var, False, True, False, footer_var=self.host_var)

    @property
    def connected(self):
        return self.state == ST_CONNECTED

    def learn_ids(self, our_var, host_var):
        if our_var is not None:
            self.our_var = _vid(our_var)
        if host_var is not None:
            self.host_var = _vid(host_var)

    def _join(self):
        return build_session_join(ldn_constant_id(self.our_mac)[:6],
                                  self.our_var.to_bytes(2, "big"), self.our_ip,
                                  self.host_mac, (self.host_var or 0).to_bytes(2, "big"),
                                  self.player_name, self.random4)

    def _q(self, proto, payload, dst, src, compress, footer, establishing, pktid=None, footer_var=None):
        """Queue one outbox entry (a dict the sim frames per the wire rules). `pktid` overrides the
        sim's per-channel counter (the establishing connection-exchange frames force pktid=0).
        `footer_var` overrides the footer recipient when it differs from the header dst (RTT: header
        dst=0x0001 session channel, footer recipient=host var 0x7620)."""
        self._outbox.append({"proto": proto, "payload": payload, "dst": dst, "src": src,
                             "compress": compress, "footer": footer, "establishing": establishing,
                             "unicast": True, "pktid": pktid, "footer_var": footer_var})

    def on_message(self, proto, payload, tick=None):
        """React to a decoded IN Pia message; queue the ack-gated reply. The exact framing per stage:
          * Net 0x12   -> hdr(dst=0, src=0),                 establishing (pktid 0, flag 0x02), no footer, uncompressed.
          * Session join -> hdr(dst=0, src=OUR_var),         establishing, no footer, zstd-COMPRESSED.
          * Session finalize -> hdr(dst=host_var, src=our_var), established, footer=host_var, uncompressed.
          * RTT response -> hdr(dst=host_var, src=our_var),  established, footer=host_var, uncompressed."""
        if proto == PROTO_NET:
            n = parse_net(payload)
            if n and n[1] == NET_CONN_REQUEST and self.state == ST_NET:
                # The host's Net 0x11 carries its TRUE Pia constant id (emulator virtual MAC) + var
                # id; learn both from the wire (the participant-list MAC is a DIFFERENT identifier
                # and addressing it makes the host ignore our join). [parse_net_conn_request]
                req = parse_net_conn_request(payload)
                seqid = 2
                if req:
                    host_var, host_mac, seqid = req
                    self.host_mac = host_mac
                    if self.host_var is None:
                        self.host_var = host_var
                # answer EVERY host 0x11: Net 0x12 (ECHOING the 0x11 seqid) then the Session
                # join. Both are the establishing exchange -> pktid 0 on the dst=0x0000 channel (per the reference capture).
                self._q(PROTO_NET, build_net_response(seqid), 0, 0, False, False, True, pktid=0)
                if self.host_var is not None:
                    self._q(PROTO_SESSION, self._join(), 0, self.our_var, True, False, True, pktid=0)
            elif n and n[1] == NET_UPDATE_PROPERTY:
                # Mid-session 'Update network property' (in the reference capture: at the lobby->trade
                # transition). The host RETRANSMITS it every 500ms until it sees our Net 0x51 ack -> an
                # unanswered 0x50 keeps the host's reliable SEND buffer full (a leading BufferIsFull cause).
                # Echo the 0x50's seqid (its body[0:4]) in a Net 0x51 on dst=0x0000, establishing flag set.
                # NOTE: the reference capture used a "running" establishing pktid (173); we send a non-zero
                # per-channel pktid (unverified - confirm the host accepts it / stops retransmitting 0x50).
                body = n[2]
                seqid = int.from_bytes(body[0:4], "big") if len(body) >= 4 else 1
                self._q(PROTO_NET, build_net_property_ack(seqid), 0, self.our_var, False, False, True)
        elif proto == PROTO_SESSION:
            # host ACKED our join -> finalize (Session 6, dst=host, src=ours). Finalize ONLY on the
            # host's join-accept (Session type 5 / SESSION_UPDATE), NOT on every session message: the host
            # sends a type-5 accept (192B) AND a type-2 follow-up (37B), and we were finalizing on both (2
            # total) vs native's exactly ONE. Guarding on type 5 re-emits on a re-sent accept (loss
            # recovery) but never on the type-2, matching native. STOP once CONNECTED.
            s = parse_session(payload)
            if (s and s["type"] == SESSION_UPDATE
                    and self.host_var is not None and self.state != ST_CONNECTED):
                self._q(PROTO_SESSION, build_session_finalize(self.our_mac),
                        self.host_var, self.our_var, False, True, False)
            if self.state == ST_NET:
                self.state = ST_FINALIZE
                self.log("host acked join (Session) -> FINALIZE")
                self.info("Host acknowledged our join.")
        elif proto in (PROTO_RTT, PROTO_RELIABLE):
            if self.state == ST_FINALIZE:
                self.state = ST_CONNECTED
                self.log("host live (RTT/Reliable) -> CONNECTED")
                self.info("Connection established.")
            # Answer the host's RTT requests once we are past ST_NET (have finalized). The native does NOT
            # answer RTT during the pre-finalize window (byte-checked vs frlg2: zero RTT responses across the
            # whole 0.3-2.1s join), so we don't either - the pre-OK deadlock was NOT a liveness drop; it was
            # the connect-phase J/C reliable frames being sent once and never retransmitted (fixed via the
            # reliable layer's connect bootstrap RTO, sim.py RTO_BOOTSTRAP_MS).
            if proto == PROTO_RTT and self.state != ST_NET and self.host_var is not None:
                r = parse_rtt(payload)
                if r and r["type"] == 0:                  # host request -> respond
                    self._last_host_rtt = bytes(payload[:21])   # template for our own origination
                    self._q(PROTO_RTT, build_rtt_response(payload),
                            SESSION_VAR, self.our_var, False, True, False, footer_var=self.host_var)
                elif r and r["type"] == 1 and tick is not None:
                    # type-1 = the host echoing one of OUR originated requests. Match its systime to the
                    # tick we sent it and record the round-trip; this feeds the reliable RTO.
                    systime = int.from_bytes(r["systime"], "little")
                    sent = self._rtt_pending.pop(systime, None)
                    if sent is not None and tick >= sent:
                        self.rtt_samples.append(tick - sent)

    def drain(self):
        out, self._outbox = self._outbox, []
        return out


ST_ANNOUNCE, ST_JOIN_RECEIVED, ST_FINALIZED = "announce", "join_received", "finalized"
HOST_NET_PERIOD = 30             # ~502 ms at the title's 59.727 Hz VBlank


class HostConnectionManager:
    """PC-host Pia acquisition gate.

    It emits the byte-verified native Net 0x11 and Session type-2/type-5
    exchange.  Game traffic stays gated after the guest's type-6 finalize;
    the existing Sim reliable/RFU implementation is a joiner, not a host.
    """

    def __init__(self, our_mac, our_ip, network_id, our_var=0x7620, seqid=2,
                 peer_provider=None, player_name="EMU", player_id=None,
                 random4=None, log=lambda *a: None):
        self.our_mac = bytes(our_mac)
        self.our_ip = our_ip
        self.network_id = network_id
        self.our_var = _vid(our_var)
        self.host_var = None                         # peer var; Sim-compatible name
        self.seqid = seqid & 0xFFFFFFFF
        self.peer_provider = peer_provider
        self.peer_ip = None
        self.player_name = player_name
        self.player_id = bytes(player_id) if player_id is not None else \
            b"\x10" + os.urandom(15)
        self.random4 = bytes(random4) if random4 is not None else os.urandom(4)
        if len(self.player_id) != 16 or len(self.random4) != 4:
            raise ValueError("player_id/random4 must be 16/4 bytes")
        self.log = log
        self.info = getattr(log, "info", log)
        self.state = ST_ANNOUNCE
        self.peer = None
        self._last_net_tick = -HOST_NET_PERIOD
        self._outbox = []
        self.rtt_samples = []

    @property
    def connected(self):
        return False                                 # host RFU path is not implemented yet

    @property
    def pia_connected(self):
        return self.state == ST_FINALIZED

    def learn_ids(self, our_var, peer_var):
        if our_var is not None:
            self.our_var = _vid(our_var)
        if peer_var is not None:
            self.host_var = _vid(peer_var)

    def poll(self, tick):
        if self.state != ST_ANNOUNCE or tick - self._last_net_tick < HOST_NET_PERIOD:
            return
        if self.peer_provider is not None:
            peer_mac, peer_ip = self.peer_provider()
            if (not peer_mac or bytes(peer_mac) == self.our_mac
                    or not peer_ip or peer_ip == self.our_ip):
                return
            self.peer_ip = peer_ip
        if self.peer_ip is None:
            return
        self._last_net_tick = tick
        self._outbox.append({
            "proto": PROTO_NET,
            "payload": build_net_request(
                self.seqid, self.our_var, self.our_mac, self.network_id,
                host_ip=self.our_ip, peer_ip=self.peer_ip),
            "dst": 0, "src": self.our_var, "compress": True, "footer": False,
            "establishing": True, "unicast": False, "pktid": 0,
            "footer_var": None,
        })

    def on_message(self, proto, payload, tick=None):
        if proto == PROTO_NET:
            net = parse_net(payload)
            if (net and net[1] == NET_CONN_RESPONSE and len(net[2]) >= 4
                    and int.from_bytes(net[2][:4], "big") == self.seqid):
                self.log("Switch acked host Net 0x11; awaiting Session join")
                self.info("Switch acknowledged the PC host.")
        elif proto == PROTO_SESSION:
            join = parse_session_join(payload)
            if join is not None:
                self.peer = join
                self.host_var = join["src_var"]
                self.peer_ip = join["address"]
                if self.state != ST_FINALIZED:
                    self.state = ST_JOIN_RECEIVED
                host_constant = ldn_constant_id(self.our_mac)
                peer_name = join["names"][0] if join["names"] else "Switch"
                peer_player = join["player_ids"][0] if join["player_ids"] else b"\x10" + b"\x00" * 15
                self._outbox.extend((
                    {"proto": PROTO_SESSION,
                     "payload": build_session_join_response(
                         host_constant, self.our_var, join["src_constant"],
                         self.host_var, self.random4),
                     "dst": self.host_var, "src": self.our_var,
                     "compress": False, "footer": True, "establishing": False,
                     "unicast": True, "pktid": None, "footer_var": self.host_var},
                    {"proto": PROTO_SESSION,
                     "payload": build_session_update(
                         host_constant, self.our_var, self.our_ip, self.player_id,
                         self.player_name, join["src_constant"], self.host_var,
                         join["address"], join["token"], peer_player, peer_name),
                     "dst": SESSION_VAR, "src": self.our_var,
                     "compress": True, "footer": True, "establishing": False,
                     "unicast": False, "pktid": None, "footer_var": self.host_var},
                ))
                self.log(f"Switch Session join captured: var=0x{self.host_var:04x} "
                         f"constant={join['src_constant'].hex()} ip={join['address']}:"
                         f"{join['port']} name={join['names'][:1]}; native accept queued")
                self.info("Switch Session join captured; native host accept sent.")
            else:
                session = parse_session(payload)
                if session and session["type"] == SESSION_FINALIZE and self.state == ST_JOIN_RECEIVED:
                    self.state = ST_FINALIZED
                    self.log("Switch finalized the Pia session; host RFU remains gated")
                    self.info("Switch finalized the Pia session.")

    def drain(self):
        out, self._outbox = self._outbox, []
        return out
