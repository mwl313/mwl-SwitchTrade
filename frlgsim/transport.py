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

C-4 (--target-bssid): opt-in BSSID-pinned association. The ldn library's Station._connect_network
                  sends NL80211_CMD_CONNECT with ONLY SSID + channel, so with two Switches
                  advertising the same SSID+channel the kernel associated with the WRONG console
                  (dmesg-verified; docs/09-testing-audit I-7). When target_bssid is set we
                  monkeypatch ldn.wlan.Station._connect_network at runtime: for the lifetime of the
                  original connect CM the station's _wlan handle is swapped for a transparent proxy
                  that adds nl80211.NL80211_ATTR_MAC (= the scanned network's address or an explicit
                  MAC) to the CONNECT request attrs, then verifies the association really landed on
                  the pinned BSSID. target_bssid=None keeps the stock behavior 100% unchanged; any
                  patch failure falls back to the old SSID+channel association instead of crashing.
"""

import asyncio
import contextlib
import functools
import json
import queue
import socket
import struct
import subprocess
import threading
import time
import traceback
from collections.abc import Mapping

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

# --- C-4: BSSID-pinned association (opt-in --target-bssid) ----------------------------------
# docs/09-testing-audit I-7: ldn's Station._connect_network (wlan.py:1289 in the 0.0.17 snapshot)
# puts only NL80211_ATTR_SSID + NL80211_ATTR_WIPHY_FREQ into NL80211_CMD_CONNECT - no BSSID - so
# with two Switches advertising the same SSID+channel the kernel associated with the WRONG console
# (the root cause of the two-Switch mis-association incident, confirmed via dmesg). The fix pins
# the 802.11 association to the host's BSSID by adding nl80211.NL80211_ATTR_MAC at runtime. The ldn
# package is patched in place (site-packages must stay untouched) and ONLY when the user opts in;
# every failure path degrades to the stock SSID+channel association with a warning, never a crash.
#
# WP-B mechanism (verified against docs/research/ldn-0.0.17-src/wlan.py): _connect_network(self)
# takes NO arguments - it builds its attrs dict LOCALLY (wlan.py:1309) and hands it straight to
# self._wlan.request(NL80211_CMD_CONNECT, attrs) (wlan.py:1336), so an args/kwargs wrapper can
# never see it. Instead the wrapper swaps station._wlan for a transparent proxy for the lifetime
# of the original connect CM: the proxy forwards every attribute access to the real wlan object
# untouched (receive() included - _process_messages consumes it) and only rewrites CONNECT
# requests by adding ATTR_MAC = the pinned BSSID IN PLACE - the attrs dict is shared by reference
# with the real request call, so the kernel's connect command carries it.

BSSID_AUTO = "auto"          # sentinel: resolve the BSSID from the selected network's address

_LDN_TESTED_VERSION = "0.0.17"   # the only ldn flow this patch is verified against

# The BSSID the patched _connect_network injects (None = stock behavior). Set by LiveTransport
# right before the join, cleared when the join context exits; one radio, so a single slot is enough.
# WP-C (H-2): every arm/disarm goes through a generation token so a stale attempt thread's late
# finally-clear can't clobber the pin a newer attempt just armed (retry-race -> silent SSID+channel
# fallback). Access ONLY via set_assoc_target/clear_assoc_target below.
_ASSOC_TARGET = {"bssid": None, "token": None}

_ASSOC_TOKENS = iter(range(1, 1 << 62))          # monotonic generation source
_ASSOC_LOCK = threading.Lock()


def set_assoc_target(bssid):
    """Arm the association pin and return this join's generation token."""
    with _ASSOC_LOCK:
        token = next(_ASSOC_TOKENS)
        _ASSOC_TARGET["bssid"] = bssid
        _ASSOC_TARGET["token"] = token
        return token


def clear_assoc_target(token):
    """Disarm the pin only when `token` is still the live generation; stale tokens are ignored."""
    if token is None:
        return
    with _ASSOC_LOCK:
        if _ASSOC_TARGET["token"] == token:
            _ASSOC_TARGET["bssid"] = None
            _ASSOC_TARGET["token"] = None

_BSSID_PATCH = {"installed": False, "failed": False, "warned": False}


def normalize_target_bssid(value):
    """Normalize a --target-bssid value: None/'' -> None (off); 'auto'/True -> BSSID_AUTO (resolve
    from the scanned network's address); '98:41:5c:79:41:38' -> 6 raw bytes. Raises ValueError on
    anything else so the CLI rejects typos before a radio join is attempted."""
    if value is None or value == "":
        return None
    if value is True or (isinstance(value, str) and value.strip().lower() == BSSID_AUTO):
        return BSSID_AUTO
    if isinstance(value, (bytes, bytearray)):
        if len(value) != 6:
            raise ValueError(f"target BSSID must be 6 bytes, got {len(value)}")
        return bytes(value)
    if isinstance(value, str):
        parts = value.strip().replace("-", ":").split(":")
        if len(parts) == 6:
            try:
                mac = bytes(int(p, 16) for p in parts)
            except ValueError:
                mac = None
            if mac is not None:
                return mac
    raise ValueError(f"invalid target BSSID {value!r} (expected e.g. 98:41:5c:79:41:38 "
                     f"or 'auto')")


def _mac_str(bssid):
    return ":".join(f"{b:02x}" for b in bssid)


class _WlanProxy:
    """Transparent forwarding proxy around a Station's real `_wlan` handle (WP-B). Everything not
    defined here resolves through the original object via __getattr__ - receive() and friends pass
    through UNMODIFIED (_process_messages depends on them). Only `request` is intercepted: an
    NL80211_CMD_CONNECT whose attrs is a Mapping gets NL80211_ATTR_MAC = the pinned BSSID added in
    place before the original request runs."""

    def __init__(self, wlan, bssid, cmd_connect, attr_mac):
        self._mwl_wlan = wlan
        self._mwl_bssid = bytes(bssid)
        self._mwl_cmd_connect = cmd_connect
        self._mwl_attr_mac = attr_mac

    def __getattr__(self, name):
        # Only reached for attributes the proxy itself does not define -> pure passthrough.
        return getattr(self._mwl_wlan, name)

    async def request(self, cmd, *args, **kwargs):
        if cmd == self._mwl_cmd_connect:
            attrs = kwargs.get("attrs", args[0] if args else None)
            if isinstance(attrs, Mapping):
                attrs[self._mwl_attr_mac] = self._mwl_bssid      # in place: same dict object
        return await self._mwl_wlan.request(cmd, *args, **kwargs)


def install_target_bssid_patch(log=print):
    """C-4: runtime-monkeypatch ldn.wlan.Station._connect_network (site-packages untouched) so the
    NL80211_CMD_CONNECT request also carries nl80211.NL80211_ATTR_MAC = the target BSSID
    (docs/09-testing-audit I-7: SSID+channel assoc joined the WRONG Switch when two consoles
    advertised the same SSID on the same channel). Installed once per process; the actual BSSID is
    read at call time from _ASSOC_TARGET, so each join can pin a different console.

    The wrapper keeps the original asynccontextmanager CM but swaps station._wlan for _WlanProxy
    while it runs, restoring the real handle afterwards (also on failure). b-lite verification
    (plan WP-B): once the original CM has entered - i.e. the kernel reported CONNECT complete and
    ldn stored its ATTR_MAC in station._host_address (wlan.py:1348) - that address must equal the
    pin, otherwise the join raises immediately so LiveTransport.start()'s attempt loop retries.
    Any failure (ldn not installed, version drift, unexpected structure) logs ONE warning and
    leaves the library stock - the association then works exactly as before (never crashes)."""
    if _BSSID_PATCH["installed"]:
        return True
    if _BSSID_PATCH["failed"]:
        return False
    try:
        import ldn
        import ldn.wlan
        # ldn 0.0.17 imports nl80211 from the netlink package (wlan.py:16 "from netlink import
        # nl80211, route") - there is NO top-level nl80211 module. Resolve the SAME object the
        # Station's request() call sees (ldn.wlan's module global) so constants always match -
        # real netlink on Linux, and the test stubs' fake nl80211 in offline tests alike.
        nl80211 = getattr(ldn.wlan, "nl80211", None)
        if nl80211 is None:
            raise ImportError("ldn.wlan has no nl80211 reference (library version drift?)")
        # Version guard: the proxy targets the verified 0.0.17 request flow exactly; if upstream
        # ever ships its own fix or reshapes the flow, auto-invalidate instead of stacking a stale
        # patch. 0.0.17 itself carries no __version__ attribute, so absence passes the guard.
        version = getattr(ldn, "__version__", None)
        if version is not None and str(version) != _LDN_TESTED_VERSION:
            raise RuntimeError(f"ldn {version} is not the tested {_LDN_TESTED_VERSION}")
        station_cls = ldn.wlan.Station
        orig = station_cls.__dict__.get("_connect_network")
        if orig is None:
            raise AttributeError("ldn.wlan.Station._connect_network not found "
                                 "(library version drift?)")
        if getattr(orig, "_mwl_bssid_patch", False):    # already ours (re-import/restart guard)
            _BSSID_PATCH["installed"] = True
            return True
        cmd_connect = nl80211.NL80211_CMD_CONNECT
        attr_mac = nl80211.NL80211_ATTR_MAC

        @functools.wraps(orig)
        @contextlib.asynccontextmanager
        async def _connect_network_with_bssid(station):
            bssid = _ASSOC_TARGET["bssid"]
            if not bssid:                               # opt-out / outside a pinned join: stock
                async with orig(station):
                    yield
                return
            saved_wlan = station._wlan
            station._wlan = _WlanProxy(saved_wlan, bssid, cmd_connect, attr_mac)
            try:
                async with orig(station):
                    host = getattr(station, "_host_address", None)   # what we ACTUALLY got
                    if host is not None and bytes(host) != bytes(bssid):
                        raise ConnectionError(
                            f"associated with {_mac_str(bytes(host))} instead of the pinned "
                            f"BSSID {_mac_str(bytes(bssid))} (docs/09-testing-audit I-7)")
                    yield
            finally:
                station._wlan = saved_wlan              # restore even on failure/exception

        _connect_network_with_bssid._mwl_bssid_patch = True
        setattr(station_cls, "_connect_network", _connect_network_with_bssid)
        _BSSID_PATCH["installed"] = True
        log(f"[live] --target-bssid: patched ldn.wlan.Station._connect_network to add "
            f"NL80211_ATTR_MAC via a _wlan request proxy (BSSID-pinned assoc; "
            f"docs/09-testing-audit I-7)")
        return True
    except Exception as e:                              # ImportError on macOS, attr drift, ...
        _BSSID_PATCH["failed"] = True
        log(f"[live] --target-bssid: patch not installed ({type(e).__name__}: {e}) - "
            f"keeping the stock SSID+channel association (docs/09-testing-audit I-7)")
        return False


# LDN virtual interfaces to clear off the radio (ported from the bridge tooling).
LDN_VIFS = {"ldn", "ldn-mon", "ldn-tap", "ldnclient"}


# --- radio / interface cleanup (the library needs the radio free of stale vifs) -------------
def _run(cmd):
    try:
        subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        pass                      # best-effort: tool (iw/nmcli/ip) not installed


def _iw_del(iface):
    """Delete a netdev and HONESTLY report the outcome (WP-E, docs/09 MEDIUM-2): `_run` swallows
    iw's exit status/output, so a silent EBUSY/EPERM used to be logged as "removed". The only
    truthful answer is re-querying sysfs after the delete. Returns True iff the iface is gone."""
    _run(["iw", "dev", iface, "del"])
    return not _iface_exists(iface)


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
    whatever vifs they need (monitor/up/ch1, ldnclient) on the next join. Needs root.

    WP-E (docs/09 MEDIUM-2): every delete is VERIFIED by re-reading /sys/class/net afterwards -
    the log says "removed" only when the netdev is really gone, "FAILED to remove" otherwise,
    and if every attempt failed a single sudo/root hint is appended (EBUSY etc. used to hide
    behind an unconditional "removed" line)."""
    mapping = list_phy_ifaces()
    attempted = failed = 0
    for phy in {p for p in phys if p}:
        ifaces = mapping.get(phy, [])
        # Known LDN vifs first (kept from the earlier behavior), then every other netdev on this
        # phy. MWL (2026-08-22): deleting a wlx* here is intended - a udev-renamed LEAK can carry
        # the same wlx<card-MAC> name as the wrapper's own monitor vif, so leaving "wlx" alone
        # would keep the stale station associated; the wrapper re-creates its vif.
        for iface in ([i for i in ifaces if i in LDN_VIFS]
                      + [i for i in ifaces if i not in LDN_VIFS]):
            # WP-E: verify the deletion instead of assuming it - an EBUSY/EPERM failure must not
            # masquerade as success in the log.
            attempted += 1
            if _iw_del(iface):
                log(f"[live] freed radio: removed {iface} from {phy}")
            else:
                failed += 1
                log(f"[live] freed radio: FAILED to remove {iface} from {phy}")
    # Belt-and-suspenders: a failed/abandoned join LEAKS its station vif (still associated to the
    # host), and `iw dev` may not map it under the expected phy - a leftover, still-associated
    # `ldnclient` then makes the NEXT association fail with nl80211 status code 1. Delete every
    # known LDN vif by name unconditionally so each join starts from a clean radio.
    for vif in LDN_VIFS:
        if vif in {i for ifs in mapping.values() for i in ifs} or _iface_exists(vif):
            attempted += 1
            _iw_del(vif)
            _run(["ip", "link", "del", vif])        # kept: secondary attempt if iw failed
            if not _iface_exists(vif):              # verdict AFTER both attempts (WP-E)
                log(f"[live] freed radio: removed stale LDN vif {vif}")
            else:
                failed += 1
                log(f"[live] freed radio: FAILED to remove stale LDN vif {vif}")
    # WP-E: EVERY delete attempt failing is the signature of a permission problem (iw/ip link del
    # need root) - say so once instead of leaving a wall of identical FAILED lines unexplained.
    if attempted > 0 and failed == attempted:
        log(f"[live] freed radio: all {attempted} delete attempt(s) FAILED - "
            f"sudo로 실행했는지 확인 (root 권한 필요)")
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

    # WP-D (H-1): 다음 attempt 시작 전 이전 ldn 스레드를 회수하기 위한 유예 시간(초). grace
    # 내에도 is_alive()면 라디오 상태를 알 수 없으므로 남은 재시도를 포기한다 (아래 start()).
    THREAD_JOIN_GRACE = 15

    def __init__(self, password=None, nickname="EMU", keys_path="~/.switch/prod.keys",
                 local_comm_id=None, scene_id=None, app_version=None,
                 phyname="phy0", ifname="ldnclient", log=print, target_bssid=None):
        self.info = getattr(log, "info", log)   # clean milestone sink (default-mode narration)
        self.password = password if password else GBA_APP_PASSPHRASE
        self.nickname = nickname
        self.keys_path = keys_path
        self.phyname = phyname
        self.ifname = ifname
        # C-4 (docs/09-testing-audit I-7): opt-in BSSID pinning. None keeps the stock ldn join
        # 100% unchanged; BSSID_AUTO resolves to the scanned network's address at join time; a
        # 6-byte value pins that exact console (protects against same-SSID+channel neighbors).
        self.target_bssid = normalize_target_bssid(target_bssid)
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
    def start(self, timeout=45, attempts=3, settle=1.5):
        """Join the LDN network, retrying transient failures. The LDN/nl80211 layer flakes
        intermittently (radio busy, association timeout, a stale vif racing the fresh join) - the
        SAME failure the bridge hits as 'connection failed'. Rather than make the user re-run, we
        free the radio and retry up to `attempts` times, logging each attempt's FULLY-UNWRAPPED
        cause (see _format_join_error) so persistent problems are still diagnosable instead of
        hidden behind trio's opaque ExceptionGroup.

        WP-D (H-1) 예산 계층: 외부 예산(timeout=45, _ready.wait) > 내부 예산(스캔 fail_after 20)
        이 되도록 기본값을 30->45로 확대했다 - 같은 30s 예산이 겹치던 구버전은 경계 overlap 시
        늙은 스레드와 새 attempt가 충돌할 수 있었다."""
        last_err = None
        for attempt in range(1, attempts + 1):
            # WP-D (H-1): free_radio는 이전 attempt의 스레드가 완전히 join된 '후에만' 호출한다 -
            # 아직 라디오를 만지는 스레드가 살아 있는 상태에서 vif를 지우면 그 스레드의 nl80211
            # 작업과 충돌한다. 첫 attempt 전에는 살아있는 스레드가 없으므로 안전하다.
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
            # WP-D (H-1): 다음 attempt를 시작하기 전에 이전 스레드가 반드시 끝나야 한다. grace
            # 내에도 is_alive()면(커널 blocking hang으로 _stop 플래그를 못 보는 상태) 늙은 스레드와
            # 새 attempt가 같은 phy를 두고 충돌하므로, 남은 시도를 포기한다. 라디오 상태를 알 수
            # 없으므로 free_radio/light_cleanup 같은 섣부른 정리도 하지 않고 즉시 실패한다 -
            # 정리는 외부 워치독(run_trade.sh timeout 900)과 다음 실행의 pre-setup에 맡긴다.
            if self._thread is not None:
                self._thread.join(timeout=self.THREAD_JOIN_GRACE)
                if self._thread.is_alive():
                    raise RuntimeError(
                        "radio thread still alive - radio state unknown "
                        f"(join grace {self.THREAD_JOIN_GRACE}s exceeded after attempt "
                        f"{attempt}/{attempts}; 커널 blocking hang 의심 - 라디오 정리는 "
                        "외부 워치독/재실행 pre-setup에 위임)")
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
            # WP-D (H-1): ①예산 계층 — 내부 스캔 예산(20s) < 외부 start() _ready.wait(45s)로
            # 축소했다. 구버전은 양쪽 다 30s라 경계 overlap 시 늙은 스레드가 살아 있는 채 새
            # attempt가 시작될 수 있었다. ②한계 — fail_after는 trio checkpoint에서만 발동하므로
            # 커널 blocking hang(스캔이 커널 호출에서 못 빠져나오는 상태)에는 무력하다. 즉 이
            # 타임아웃은 커널 blocking hang의 근본 방어가 아님 — 외부 timeout 워치독(래퍼
            # run_trade.sh의 timeout 900, 단독 스캔용 scan_phy.py) 병행 필수.
            try:
                with trio.fail_after(20):
                    networks = await ldn.scan(keys, phyname=self.phyname)
            except trio.TooSlowError:
                self._err = "LDN scan timed out after 20s - radio/driver stuck (see docs/09 D-1)"
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
            # C-4 (docs/09-testing-audit I-7): resolve the BSSID to pin. 'auto' takes it from the
            # selected network's address (the scan result carries the host's BSSID); an explicit
            # --target-bssid wins over that. Resolution failure degrades to the stock join.
            bssid = None
            patched = False
            if self.target_bssid is not None:
                if self.target_bssid == BSSID_AUTO:
                    try:
                        addr = bytes(getattr(net, "address") or b"")
                        bssid = addr if len(addr) == 6 else None
                    except Exception:
                        bssid = None
                    if bssid is None:
                        self.log("[live] --target-bssid auto: scanned network has no usable "
                                 "address - associating by SSID+channel as before")
                else:
                    bssid = self.target_bssid
                if bssid is not None:
                    patched = install_target_bssid_patch(self.log)
            param = ldn.ConnectNetworkParam()
            param.keys = keys
            param.network = net
            param.password = self.password           # 64-byte emulator passphrase
            param.name = self.nickname.encode()
            param.app_version = self.APPLICATION_VERSION
            param.phyname = self.phyname              # wifi phy (like the bridge: phy0)
            param.ifname = self.ifname                # station iface (like the bridge: ldnclient)
            self.info("Joining the host...")
            try:
                self._pin_token = set_assoc_target(bssid)   # read by the patched _connect_network
                if bssid is not None:
                    if patched:                       # MED③: only claim pinning when it is real
                        self.log(f"[live] pinning association to BSSID {_mac_str(bssid)} "
                                 f"(docs/09-testing-audit I-7)")
                    elif not _BSSID_PATCH["warned"]:  # fallback notice ONCE, not per attempt
                        _BSSID_PATCH["warned"] = True
                        self.log(f"[live] --target-bssid: BSSID pinning unavailable - "
                                 f"associating by SSID+channel as before "
                                 f"(fallback; docs/09-testing-audit I-7)")
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
            finally:
                clear_assoc_target(getattr(self, "_pin_token", None))  # never leak the pin past this join

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

    def __init__(self, relay_url, session_id=None, role="guest", target_bssid=None,
                 *args, **kwargs):
        # target_bssid (C-4, docs/09-testing-audit I-7) is forwarded explicitly so relay-mode
        # callers get the same BSSID-pinned association as direct live mode.
        super().__init__(*args, target_bssid=target_bssid, **kwargs)
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
