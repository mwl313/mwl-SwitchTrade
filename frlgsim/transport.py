"""Transport adapters: where Pia datagrams come from / go to.

ReplayTransport - OFFLINE. Replays a capture's IN datagrams (so the sim's whole RX stack runs
                  against the real host stream) and records the sim's OUT datagrams. Used by the
                  test harness; needs no hardware.

LiveTransport   - LIVE. Joins the FRLG console's LDN session with kinnay's `ldn` library (like
                  the bridge tooling), then moves UDP :12345 payloads on the 169.254.x interface
                  exactly as the bridge does: a bound UDP socket for TX (SO_BROADCAST)
                  and an AF_PACKET raw socket for RX (so subnet-directed broadcasts aren't dropped).
                   Requires root + the `netlink`/`ldn`/`trio` deps and the real Switch; it cannot be
                   exercised offline, so it is written to mirror the proven bridge code path.

RemoteTransport - LIVE + REMOTE PEER. A LiveTransport that also keeps a relay WebSocket open for
                  game-semantic state messages (MWLB frames) between two sims behind different
                  bridges. Inbound frames land only in an inbox queue (remote_poll) - never the
                  local UDP plane - so remote traffic can't loop back into the broadcast path.
"""

import asyncio
import json
import queue
import socket
import struct
import subprocess
import threading
import time
import traceback

ETH_P_IP = 0x0800
PROTO_UDP = 17
PIA_PORT = 12345


_PIA_HDR = 0x5C     # Pia 6.16-6.41 LDN system header (sysCommVer 21/22); the game payload follows it


def _b85_decode(s):
    """Decode the custom base85 used for the RFU beacon payload: alphabet 0x23..0x78 skipping 0x5c
    ('\\'), first char = least-significant digit, 4-byte little-endian groups. len(s) is truncated to
    a multiple of 5."""
    out = bytearray()
    for i in range(0, len(s) - len(s) % 5, 5):
        v = 0
        for c in reversed(s[i:i + 5]):                  # reversed: first char is the LOW digit
            v = v * 85 + ((c - 0x23) if c < 0x5C else (c - 0x24))
        out += (v & 0xFFFFFFFF).to_bytes(4, "little")
    return bytes(out)


def _frlg_name(b):
    """Render a name from the FRLG character set (letters/digits) for the beacon dump."""
    out = []
    for x in b:
        if x == 0xFF:
            break
        if 0xBB <= x <= 0xD4:
            out.append(chr(ord("A") + x - 0xBB))
        elif 0xD5 <= x <= 0xEE:
            out.append(chr(ord("a") + x - 0xD5))
        elif 0xA1 <= x <= 0xAA:
            out.append(chr(ord("0") + x - 0xA1))
        else:
            out.append(" " if x == 0 else "?")
    return "".join(out).rstrip()


def _dump_beacon(app_data, log):
    """Dump the host's LDN advertisement application data (the RFU search beacon). It is a Pia
    6.16-6.41 system header (0x5C bytes: Switch nickname etc.) followed by the game payload, a
    custom-base85-encoded 24-byte RFU record (player trainer id, in-game name, RFU session id, partner
    info, game data). Diagnostics only - the connect id is not taken from here; it is a random nonzero
    value."""
    if not app_data:
        log("[live] beacon: NO application_data on the advertisement")
        return None
    app_data = bytes(app_data)
    log(f"[live] beacon application_data ({len(app_data)} B): {app_data.hex()}")
    if len(app_data) >= _PIA_HDR:
        gba = app_data[_PIA_HDR:]
        log(f"[live] beacon RFU payload (after the 0x5C Pia header, {len(gba)} B): {gba.hex()}")
        try:                                            # never let an odd beacon abort the join
            d = _b85_decode(gba)
            if len(d) >= 24:
                log(f"[live] beacon decoded: host name={_frlg_name(d[2:10])!r} "
                    f"TID=0x{int.from_bytes(d[0:2], 'little'):04x} "
                    f"RFU-session-id=0x{int.from_bytes(d[10:12], 'little'):04x} "
                    f"tradeSpecies={int.from_bytes(d[20:24], 'little') >> 16}")
        except Exception as e:
            log(f"[live] beacon decode skipped ({type(e).__name__}: {e})")
    return app_data


def _flatten_exc(e, depth=0):
    """Recursively flatten a (Base)ExceptionGroup - which is how trio reports failures from inside
    its nursery ('Exceptions from Trio nursery (N sub-exceptions)') - into the LEAF exceptions, so
    the real cause (e.g. a netlink/nl80211 EBUSY, an association timeout) is visible instead of the
    opaque group wrapper. Returns a list of (depth, exception) leaves."""
    subs = getattr(e, "exceptions", None)           # ExceptionGroup / trio.MultiError
    if subs:
        out = []
        for sub in subs:
            out.extend(_flatten_exc(sub, depth + 1))
        return out
    return [(depth, e)]


def _format_join_error(e):
    """Human-readable, fully-unwrapped description of an LDN-join failure, with the leaf exceptions'
    types, messages, and tracebacks (the opaque trio ExceptionGroup hides all of these)."""
    leaves = _flatten_exc(e)
    if len(leaves) == 1 and leaves[0][1] is e:      # not a group: report it directly
        leaf = e
        body = "".join(traceback.format_exception(type(leaf), leaf, leaf.__traceback__))
        return f"{type(leaf).__name__}: {leaf}\n{body}"
    parts = [f"{type(e).__name__} with {len(leaves)} underlying error(s):"]
    for i, (_d, leaf) in enumerate(leaves, 1):
        body = "".join(traceback.format_exception(type(leaf), leaf, leaf.__traceback__))
        parts.append(f"  [{i}] {type(leaf).__name__}: {leaf}\n{body}")
    return "\n".join(parts)

# LDN virtual interfaces to clear off the radio (ported from the bridge tooling).
LDN_VIFS = {"ldn", "ldn-mon", "ldn-tap", "ldnclient"}


# --- radio / interface cleanup (the library needs the radio free of stale vifs) -------------
def _run(cmd):
    try:
        subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        pass                      # best-effort: tool (iw/nmcli/ip) not installed


def _iw_del(iface):
    _run(["iw", "dev", iface, "del"])


def _sysctl(key, val):
    _run(["sysctl", "-wq", f"{key}={val}"])


def list_phy_ifaces():
    """Map phyName -> [netdev names] by parsing `iw dev`."""
    mapping, current = {}, None
    try:
        out = subprocess.check_output(["iw", "dev"], text=True, stderr=subprocess.DEVNULL)
    except Exception:
        return mapping
    for raw in out.splitlines():
        s = raw.strip()
        if s.startswith("phy#"):
            current = "phy" + s[4:]
            mapping[current] = []
        elif s.startswith("Interface ") and current is not None:
            mapping[current].append(s.split()[1])
    return mapping


def free_radio(phys, log=print):
    """Give the target phys a clean MONOPOLY: delete EVERY netdev that lives on them (C-1), not
    just the known LDN vif names. A failed/crashed/pkill'd run leaks its station vif on the phy,
    and after a card reset udev renames leaked vifs to wlx<MAC> - which can collide with the
    wrapper's own monitor vif name - so name-based cleanup cannot catch them; the stale vif then
    monopolizes the phy and the next join dies with EBUSY / Match already configured / assoc
    status 1 (docs/09-testing-audit I-1, C-1; the verified manual fix is exactly this "empty the
    phy" sweep). Scope is strictly the phys passed in: other adapters (built-in Wi-Fi etc.) are
    NEVER touched. Premise: the run_trade.sh wrapper's pre-setup and the ldn library recreate
    whatever vifs they need (monitor/up/ch1, ldnclient) on the next join. Needs root."""
    mapping = list_phy_ifaces()
    for phy in {p for p in phys if p}:
        ifaces = mapping.get(phy, [])
        # Known LDN vifs first (kept from the earlier behavior), then every other netdev on this
        # phy. MWL (2026-08-22): deleting a wlx* here is intended - a udev-renamed LEAK can carry
        # the same wlx<card-MAC> name as the wrapper's own monitor vif, so leaving "wlx" alone
        # would keep the stale station associated; the wrapper re-creates its vif.
        for iface in ([i for i in ifaces if i in LDN_VIFS]
                      + [i for i in ifaces if i not in LDN_VIFS]):
            _iw_del(iface)
            log(f"[live] freed radio: removed {iface} from {phy}")
    # Belt-and-suspenders: a failed/abandoned join LEAKS its station vif (still associated to the
    # host), and `iw dev` may not map it under the expected phy - a leftover, still-associated
    # `ldnclient` then makes the NEXT association fail with nl80211 status code 1. Delete every
    # known LDN vif by name unconditionally so each join starts from a clean radio.
    for vif in LDN_VIFS:
        if vif in {i for ifs in mapping.values() for i in ifs} or _iface_exists(vif):
            _iw_del(vif)
            _run(["ip", "link", "del", vif])
            log(f"[live] freed radio: removed stale LDN vif {vif}")
    _run(["pkill", "-x", "wpa_supplicant"])
    time.sleep(0.3)


def _iface_exists(iface):
    import os
    return os.path.exists(f"/sys/class/net/{iface}")


def light_cleanup(log=print):
    """Delete the LDN virtual interfaces (teardown)."""
    for iface in sorted(LDN_VIFS):
        _iw_del(iface)
    time.sleep(0.3)


def tune_iface(iface, keep_ip, broadcast_ip, log=print):
    """Make the LDN interface deliver the host's link-local subnet broadcasts: relax rp_filter,
    force the 169.254.X.255 broadcast route into the local table, and drop stray zeroconf
    addresses that would shadow it (ported from the bridge tooling). Needs root."""
    _run(["nmcli", "device", "set", iface, "managed", "no"])
    _run(["pkill", "-f", f"avahi-autoipd.*{iface}"])
    for key in (f"net.ipv4.conf.{iface}.rp_filter", "net.ipv4.conf.all.rp_filter",
                "net.ipv4.conf.default.rp_filter"):
        _sysctl(key, "0")
    _sysctl(f"net.ipv4.conf.{iface}.accept_local", "1")
    _run(["ip", "route", "replace", "table", "local", "broadcast", broadcast_ip,
          "dev", iface, "proto", "static", "scope", "link", "src", keep_ip])
    try:
        out = subprocess.check_output(["ip", "-4", "addr", "show", "dev", iface],
                                      text=True, stderr=subprocess.DEVNULL)
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("inet "):
                cidr = line.split()[1]
                ip, _, prefix = cidr.partition("/")
                if ip != keep_ip and prefix != "24":
                    _run(["ip", "addr", "del", cidr, "dev", iface])
                    log(f"[live] removed stray address {cidr} from {iface}")
    except Exception as e:
        log(f"[live] stray-address cleanup skipped: {e}")

# The emulator's LDN passphrase (NintendoClients wiki "LDN Passphrases"). It belongs to the
# GBA emulator container, not the ROM, so it is SHARED across its titles: FRLG today, and
# Ruby/Sapphire/Emerald when they are re-released. It is ONE 64-byte value (the two 32-byte halves
# concatenate - earlier code mislabeled the second half as an "alternate"). Hardcoded as the
# default so no --password is needed.
GBA_APP_PASSPHRASE = bytes.fromhex(
    "fcb6f6adb9dfea66aca9c326149d2b3b08a781895cbf78f720d78b85a57584a9"
    "9665d237797b2a41ddef14063ec28d259143af7832fb3cbcf2759cbfbdc81d8c")
assert len(GBA_APP_PASSPHRASE) == 64


# ---------------------------------------------------------------------------
class ReplayTransport:
    """Offline: dispense capture IN datagrams; collect OUT datagrams the sim sends."""

    def __init__(self, in_datagrams, our_ip="169.254.21.2", host_ip="169.254.21.1"):
        # in_datagrams: list of (payload_bytes, src_ip_str), in capture order
        self._in = list(in_datagrams)
        self._i = 0
        self.our_ip = our_ip
        self.host_ip = host_ip
        self.sent = []                  # [(datagram, dst_ip)]
        self.batch = 4                  # IN datagrams handed out per recv() (coalescing model)

    def recv(self):
        out = []
        for _ in range(self.batch):
            if self._i >= len(self._in):
                break
            out.append(self._in[self._i])
            self._i += 1
        return out

    def send(self, datagram, dst_ip):
        self.sent.append((datagram, dst_ip))

    @property
    def drained(self):
        return self._i >= len(self._in)

    @classmethod
    def from_capture(cls, raw_path):
        """Load a raw capture: IN datagrams + session ssid/ips."""
        metas, ins = [], []
        sess = {}
        for line in open(raw_path, errors="replace"):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("rec") == "meta":
                if r.get("event") == "session":
                    sess = r
                continue
            if r.get("rec") == "pkt" and r.get("dir") == "in":
                ins.append((bytes.fromhex(r["hex"]), r["src"].rsplit(":", 1)[0]))
        t = cls(ins, our_ip=sess.get("ip", "169.254.21.2"),
                host_ip=sess.get("ip", "169.254.21.1").rsplit(".", 1)[0] + ".1")
        t.ssid = bytes.fromhex(sess["ssid_hex"]) if sess.get("ssid_hex") else None
        return t


# ---------------------------------------------------------------------------
class LiveTransport:
    """Join the console's LDN session and exchange UDP :12345 datagrams. Mirrors the bridge
    (scan/connect + UDP TX socket + AF_PACKET RX). Untested offline."""

    # FRLG LDN identity (the same the bridge/console use).
    LOCAL_COMMUNICATION_ID = 0x0100610011000000     # FireRed/LeafGreen emulator title id
    SCENE_ID = 0
    APPLICATION_VERSION = 1

    def __init__(self, password=None, nickname="EMU", keys_path="~/.switch/prod.keys",
                 local_comm_id=None, scene_id=None, app_version=None,
                 phyname="phy0", ifname="ldnclient", log=print):
        self.info = getattr(log, "info", log)   # clean milestone sink (default-mode narration)
        self.password = password if password else GBA_APP_PASSPHRASE
        self.nickname = nickname
        self.keys_path = keys_path
        self.phyname = phyname
        self.ifname = ifname
        if local_comm_id is not None:
            self.LOCAL_COMMUNICATION_ID = local_comm_id
        if scene_id is not None:
            self.SCENE_ID = scene_id
        if app_version is not None:
            self.APPLICATION_VERSION = app_version
        self.log = log
        self.ssid = None
        self.our_ip = None
        self.host_ip = None
        self.our_mac = None        # our 6-byte LDN MAC = our Pia connection GUID (constant id)
        self.host_mac = None       # the host's 6-byte LDN MAC = its Pia connection GUID
        self.app_data = None       # the host's LDN advertisement beacon (emulator RFU search data)
        self.iface = None
        self.broadcast = None
        self._tx = None
        self._rx = None
        self._rx_seen = 0
        self._thread = None
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._err = None

    # -- LDN join runs in a trio thread that keeps the connection alive -------
    def start(self, timeout=30, attempts=3, settle=1.5):
        """Join the LDN network, retrying transient failures. The LDN/nl80211 layer flakes
        intermittently (radio busy, association timeout, a stale vif racing the fresh join) - the
        SAME failure the bridge hits as 'connection failed'. Rather than make the user re-run, we
        free the radio and retry up to `attempts` times, logging each attempt's FULLY-UNWRAPPED
        cause (see _format_join_error) so persistent problems are still diagnosable instead of
        hidden behind trio's opaque ExceptionGroup."""
        last_err = None
        for attempt in range(1, attempts + 1):
            free_radio({self.phyname}, self.log)        # clear the radio before each join attempt
            self._err = None
            self._ready.clear()
            self._stop.clear()
            self._thread = threading.Thread(target=self._run_ldn, daemon=True)
            self._thread.start()
            if not self._ready.wait(timeout):
                last_err = f"LDN join timed out after {timeout}s (attempt {attempt}/{attempts})"
                self.log(f"[live] {last_err}")
                self._stop.set()                        # ask the (stuck) attempt to unwind
            elif self._err:
                last_err = self._err                    # already unwrapped + logged in _run_ldn
            else:
                tune_iface(self.iface, self.our_ip, self.broadcast, self.log)  # host broadcasts
                self._setup_sockets()
                if attempt > 1:
                    self.log(f"[live] LDN join succeeded on attempt {attempt}/{attempts}.")
                return self
            self._stop.set()
            if self._thread is not None:
                self._thread.join(timeout=2)            # let an abandoned attempt unwind/disconnect
            if attempt < attempts:
                self.log(f"[live] retrying LDN join in {settle}s "
                         f"(attempt {attempt + 1}/{attempts})...")
                time.sleep(settle)                      # let the radio settle before retrying
        light_cleanup(self.log)                         # remove any vif a failed attempt leaked
        raise RuntimeError(f"LDN join failed after {attempts} attempt(s):\n{last_err}")

    def _run_ldn(self):
        try:
            import trio
            import ldn
        except ImportError as e:                     # pragma: no cover
            self._err = f"missing dep for live mode: {e}"
            self._ready.set()
            return

        async def main():
            keys = ldn.load_keys(self.keys_path)
            self.info("Scanning for the FRLG network...")
            # D-1 (2026-08-22): ldn.scan은 커널 레벨 blocking으로 VM 전체 hang을 유발한
            # 전례 3회 (handoff/HANDOFF-20260821-stabilize.md 5.1, docs/09-testing-audit D-1).
            # with_timeout은 deprecated라 fail_after 사용. TooSlowError 시 _err을 남기고
            # _ready.set() 후 return 하면 start()의 재시도(attempts=3)가 자동으로 이어진다.
            try:
                with trio.fail_after(30):
                    networks = await ldn.scan(keys, phyname=self.phyname)
            except trio.TooSlowError:
                self._err = "LDN scan timed out after 30s - radio/driver stuck (see docs/09 D-1)"
                self.log(f"[live] {self._err}")
                self._ready.set()
                return
            joinable = [n for n in networks
                        if n.accept_policy != ldn.ACCEPT_NONE
                        and n.num_participants < n.max_participants]
            for n in networks:
                # also log accept_policy: a blacklist/whitelist host (policy != ACCEPT_ALL) passes the
                # joinable filter but then rejects our auth, surfacing as an opaque trio timeout - logging
                # it makes "this Switch isn't accepting this MAC" diagnosable.
                self.log(f"[live] saw network comm_id=0x{n.local_communication_id:016x} "
                         f"scene={n.scene_id} {n.num_participants}/{n.max_participants} "
                         f"accept_policy={getattr(n, 'accept_policy', '?')}")
            # Prefer an exact FRLG comm-id match; else fall back to the only joinable network.
            net = next((n for n in joinable
                        if n.local_communication_id == self.LOCAL_COMMUNICATION_ID), None)
            if net is None and len(joinable) == 1:
                net = joinable[0]
                self.log(f"[live] no comm-id match; using the only joinable network "
                         f"(comm_id=0x{net.local_communication_id:016x})")
            elif net is not None and len(joinable) > 1:
                # MWL (2026-08-21): two Switch ads share the same comm-id; join the room
                # with the FEWEST participants so a guest targets the idle console
                # (leader-leader EMU bridge), not the one already hosting a peer.
                least = min(joinable, key=lambda n: n.num_participants)
                if least is not net:
                    self.log(f"[live] {len(joinable)} joinable with same comm-id; "
                             f"choosing {least.num_participants}/{least.max_participants} "
                             f"participants over {net.num_participants}/{net.max_participants}")
                    net = least
            if net is None:
                self._err = (f"no joinable FRLG network (saw {len(networks)}, "
                             f"{len(joinable)} joinable) - set --comm-id from the list above")
                self._ready.set()
                return
            self.LOCAL_COMMUNICATION_ID = net.local_communication_id
            # The advertisement's application data is the RFU search beacon (dumped + decoded for
            # diagnostics). The connect id is not taken from here: any nonzero value works, so it is a
            # random nonzero value chosen locally.
            self.app_data = _dump_beacon(getattr(net, "application_data", b"") or b"", self.log)
            param = ldn.ConnectNetworkParam()
            param.keys = keys
            param.network = net
            param.password = self.password           # 64-byte emulator passphrase
            param.name = self.nickname.encode()
            param.app_version = self.APPLICATION_VERSION
            param.phyname = self.phyname              # wifi phy (like the bridge: phy0)
            param.ifname = self.ifname                # station iface (like the bridge: ldnclient)
            self.info("Joining the host...")
            async with ldn.connect(param) as network:
                info = network.info()
                self.ssid = info.ssid
                self.iface = self.ifname
                # MWL (2026-08-21): systemd-udev renames our station vif on this distro
                # (ldnclient -> wlx<MAC>); sockets bind by NAME, so resolve the live
                # interface on this phy after a successful join.
                try:
                    import glob
                    for p in glob.glob(f"/sys/class/ieee80211/{self.phyname}/device/net/*"):
                        name = p.rsplit("/", 1)[-1]
                        if name != self.ifname:
                            self.iface = name
                            self.log(f"[live] udev renamed vif: {self.ifname} -> {name}")
                            break
                except Exception:
                    pass
                # The host is participant 0 (the network creator); its IP fixes the 169.254.X subnet
                # [ldn/__init__.py NetworkInfo.participants; the bridge's network_nodes]. Each
                # ParticipantInfo carries ip_address + mac_address (the 6-byte LDN MAC = the Pia
                # connection GUID). We are the participant whose name matches our nickname (we set
                # param.name); fall back to the first connected non-host, then to subnet .2.
                parts = list(getattr(info, "participants", []) or [])
                host = parts[0] if parts else None
                self.host_ip = host.ip_address if host else "169.254.21.1"
                self.host_mac = bytes(host.mac_address) if host else b"\x00" * 6
                ours = next((p for p in parts if p is not host and self._pname(p) == self.nickname),
                            None) or next((p for p in parts if p is not host
                                           and getattr(p, "connected", False)), None)
                # our IP: prefer the address the ldn lib actually assigned to the iface (ground
                # truth) over the participant list; broadcast is OUR subnet's .255 (= where the host
                # broadcasts its Net 0x11). [the reference capture seq 1: host -> 169.254.X.255]
                self.our_ip = (self._iface_ip() or (ours.ip_address if ours else None)
                               or self.host_ip.rsplit(".", 1)[0] + ".2")
                self.our_mac = ((bytes(ours.mac_address) if ours else None)
                                or self._iface_mac() or b"\x00" * 6)
                self.broadcast = self.our_ip.rsplit(".", 1)[0] + ".255"
                self.log(f"[live] joined ssid={self.ssid.hex()} "
                         f"us={self.our_ip}/{self.our_mac.hex()} "
                         f"host={self.host_ip}/{self.host_mac.hex()}")
                self.info("Joined.")
                self._ready.set()
                while not self._stop.is_set():
                    await trio.sleep(0.2)

        try:
            trio.run(main)
        except BaseException as e:                     # pragma: no cover
            # trio wraps nursery failures in a (Base)ExceptionGroup whose str() is the useless
            # "Exceptions from Trio nursery (N sub-exceptions)"; unwrap to the real leaf cause(s).
            self._err = _format_join_error(e)
            self.log(f"[live] LDN join FAILED:\n{self._err}")
            self._ready.set()

    @staticmethod
    def _pname(p):
        try:
            return p.name.decode("utf-8", "replace").rstrip("\0")
        except Exception:
            return ""

    def _iface_mac(self):
        """Read the station interface's MAC as a last-resort fallback for our connection GUID."""
        try:
            with open(f"/sys/class/net/{self.ifname}/address") as f:
                return bytes.fromhex(f.read().strip().replace(":", ""))
        except OSError:
            return None

    def _iface_ip(self):
        """Read the IPv4 the ldn lib actually assigned to the station iface (ground truth)."""
        try:
            out = subprocess.check_output(["ip", "-4", "-o", "addr", "show", "dev", self.ifname],
                                          text=True, stderr=subprocess.DEVNULL)
            for line in out.splitlines():
                parts = line.split()
                if "inet" in parts:
                    ip = parts[parts.index("inet") + 1].split("/")[0]
                    if ip.startswith("169.254."):
                        return ip
        except Exception:
            pass
        return None

    def _setup_sockets(self):
        tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        tx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        tx.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        tx.bind(("0.0.0.0", PIA_PORT))
        self._tx = tx
        rx = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(ETH_P_IP))
        rx.bind((self.iface, 0))
        rx.setblocking(False)
        # Grow the kernel receive buffer so a burst of host frames between our ~60Hz recv() drains is
        # not dropped at the OS level (AF_PACKET ring overflow shows up as silent gaps in the reliable
        # stream -> recovery work; cutting OS drops cuts the recovery we depend on). Best-effort: the
        # kernel clamps to net.core.rmem_max, so log what we actually got. 8 MiB request.
        try:
            rx.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 * 1024 * 1024)
            got = rx.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF)
            self.log(f"[live] rx socket SO_RCVBUF = {got} bytes "
                     f"(raise net.core.rmem_max if lower than requested 8 MiB)")
        except OSError as e:
            self.log(f"[live] could not enlarge rx SO_RCVBUF: {e}")
        self._rx = rx

    # -- data plane ----------------------------------------------------------
    def send(self, datagram, dst_ip):
        dst = self.broadcast if dst_ip in (self.broadcast, "255.255.255.255") else dst_ip
        try:
            self._tx.sendto(datagram, (dst, PIA_PORT))
        except OSError as e:
            self.log(f"[live] sendto failed: {e}")

    def _accept_dst(self, dst_ip):
        """The host INITIATES by BROADCASTING its Net 0x11 to the subnet .255 (the reference capture seq 1 ->
        169.254.X.255), then unicasts to us. Accept our own IP, ANY 169.254.*.255 link-local
        broadcast (robust to imperfect subnet resolution), and the global broadcasts - so we never
        miss the host's broadcast outreach."""
        return (dst_ip == self.our_ip
                or (dst_ip.startswith("169.254.") and dst_ip.endswith(".255"))
                or dst_ip in ("255.255.255.255",))

    def recv(self):
        out = []
        if self._rx is None:
            return out
        while True:
            try:
                data = self._rx.recv(65535)
            except (BlockingIOError, OSError):
                break
            parsed = self._parse_udp(data)
            if parsed is None:
                continue
            src_ip, src_port, dst_ip, dst_port, payload = parsed
            if src_ip == self.our_ip or dst_port != PIA_PORT or not self._accept_dst(dst_ip):
                continue
            self._rx_seen += 1
            if self._rx_seen <= 10:
                self.log(f"[live] RX #{self._rx_seen}: {src_ip} -> {dst_ip}:{dst_port} "
                         f"len={len(payload)} {payload[:4].hex()}")
            out.append((payload, src_ip))
        return out

    @staticmethod
    def _parse_udp(frame):
        if len(frame) < 14 + 20 + 8 or struct.unpack_from("!H", frame, 12)[0] != ETH_P_IP:
            return None
        ip = frame[14:]
        if (ip[0] >> 4) != 4 or ip[9] != PROTO_UDP:
            return None
        ihl = (ip[0] & 0x0F) * 4
        src_ip = socket.inet_ntoa(ip[12:16])
        dst_ip = socket.inet_ntoa(ip[16:20])
        udp = ip[ihl:]
        if len(udp) < 8:
            return None
        src_port, dst_port, ulen = struct.unpack_from("!HHH", udp, 0)
        payload = udp[8:][:max(0, ulen - 8)] if ulen >= 8 else udp[8:]
        return src_ip, src_port, dst_ip, dst_port, payload

    def stop(self):
        self._stop.set()
        for s in (self._tx, self._rx):
            try:
                if s:
                    s.close()
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2)
        light_cleanup(self.log)                         # delete the LDN vifs on teardown


# ---------------------------------------------------------------------------
class RemoteTransport(LiveTransport):
    """LiveTransport + a remote peer tunnel over a relay WebSocket.

    Adds a state channel alongside the local UDP :12345 data plane (the LDN join is inherited
    unchanged): game-semantic messages are framed as [4B magic b"MWLB"][1B msg_type][2B len BE]
    [payload] and shipped to a relay that pipes bytes between the two peers' sockets
    (PHASE2_DESIGN.md S4). Inbound frames land ONLY in an inbox queue (drained by remote_poll) -
    they are never re-injected onto the local data plane, so a relay message can never loop back
    into the broadcast path (S4.3).

    The WebSocket runs in its own asyncio thread: remote_send() frames queue thread-safely, the
    loop sends a HEARTBEAT every 30s, and a dropped socket is reconnected up to 3 times.
    """

    MWLB_MAGIC = b"MWLB"
    MSG_TRADE_SELECT = 0x01
    MSG_TRADE_CONFIRM = 0x02
    MSG_TRADE_CANCEL = 0x03
    MSG_HEARTBEAT = 0x04
    MSG_STATE_SYNC = 0x10

    HEARTBEAT_INTERVAL = 30.0
    RECONNECT_ATTEMPTS = 3

    def __init__(self, relay_url, session_id=None, role="guest", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.relay_url = relay_url
        self.session_id = session_id
        self.role = role
        self._inbox = queue.Queue()          # inbound remote frames: (msg_type, payload)
        self._outbox = queue.Queue()         # outbound frames queued from the sim thread
        self._ws = None                      # live websockets connection (async thread only)
        self._ws_thread = None
        self._ws_stop = threading.Event()

    # -- MWLB framing --------------------------------------------------------
    @classmethod
    def _build_frame(cls, msg_type, payload=b""):
        payload = bytes(payload)
        return (cls.MWLB_MAGIC + bytes([msg_type & 0xFF])
                + struct.pack("!H", len(payload)) + payload)

    @staticmethod
    def _parse_frame(data):
        if not isinstance(data, (bytes, bytearray)) or len(data) < 7:
            return None
        if bytes(data[:4]) != b"MWLB":
            return None
        msg_type = data[4]
        length = struct.unpack("!H", data[5:7])[0]
        if length > len(data) - 7:
            return None
        return msg_type, bytes(data[7:7 + length])

    # -- remote channel (sim thread) -----------------------------------------
    def start_remote(self):
        """Launch the relay WebSocket thread (independent of the inherited LDN start())."""
        if self._ws_thread is not None and self._ws_thread.is_alive():
            return self
        self._ws_stop.clear()
        self._ws_thread = threading.Thread(target=self._run_ws_thread,
                                           name="mwlb-remote-ws", daemon=True)
        self._ws_thread.start()
        return self

    def remote_send(self, msg, msg_type):
        """Frame a game-semantic message and hand it to the relay thread (thread-safe)."""
        self._outbox.put(self._build_frame(msg_type, msg))

    def remote_poll(self):
        """Drain the inbox: yields (msg_type, payload) tuples for the sim FSM."""
        while True:
            try:
                yield self._inbox.get_nowait()
            except queue.Empty:
                return

    # -- relay WebSocket thread ----------------------------------------------
    def _run_ws_thread(self):
        try:
            asyncio.run(self._ws_main())
        except Exception as e:
            self.log(f"[remote] websocket thread crashed: {e}")

    async def _ws_main(self):
        try:
            import websockets
        except ImportError as e:                     # pragma: no cover
            self.log(f"[remote] missing dep for remote mode: {e}")
            return
        attempt = 0
        while not self._ws_stop.is_set():
            try:
                async with websockets.connect(self.relay_url) as ws:
                    attempt = 0                      # reset once a connect succeeds
                    self._ws = ws
                    self.log(f"[remote] websocket connected: {self.relay_url}")
                    await self._ws_session(ws)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self._ws = None
                if self._ws_stop.is_set():
                    break
                attempt += 1
                if attempt > self.RECONNECT_ATTEMPTS:
                    self.log(f"[remote] gave up after {self.RECONNECT_ATTEMPTS} reconnect "
                             f"attempt(s): {e}")
                    break
                self.log(f"[remote] connection lost ({e}); reconnecting "
                         f"{attempt}/{self.RECONNECT_ATTEMPTS} ...")
                await asyncio.sleep(1.0)

    async def _ws_session(self, ws):
        last_hb = time.monotonic()
        while not self._ws_stop.is_set():
            while not self._outbox.empty():          # flush frames queued by remote_send()
                await ws.send(self._outbox.get_nowait())
            if time.monotonic() - last_hb >= self.HEARTBEAT_INTERVAL:
                ts = int(time.time()) & 0xFFFFFFFF
                await ws.send(self._build_frame(self.MSG_HEARTBEAT, struct.pack("!I", ts)))
                last_hb = time.monotonic()
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=0.1)
            except asyncio.TimeoutError:
                continue
            parsed = self._parse_frame(msg)
            if parsed is None:
                continue
            msg_type, payload = parsed
            if msg_type == self.MSG_HEARTBEAT:
                continue
            self._inbox.put((msg_type, payload))     # inbox ONLY - never the UDP plane

    def stop(self):
        self._ws_stop.set()
        super().stop()
        if self._ws_thread is not None:
            self._ws_thread.join(timeout=2)
