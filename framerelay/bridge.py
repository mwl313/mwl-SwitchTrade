"""Track B relay bridge: a transparent 802.11 <-> relay-WebSocket pipe (docs/07).

The two bridges make one radio cell out of two:

    Switch A(leader) <--air--> Bridge A <--WS--> relay <--WS--> Bridge B <--air--> Switch B(guest)

The bridge NEVER interprets frames (docs/07 section 2 "투명 중계"): every capture that
passes the host-BSSID filter is wrapped as MWLB MSG_FRAME_RELAY (0x20) and shipped to the
peer, and every 0x20 received from the peer is injected back on air with a fresh radiotap
TX header. That is the whole protocol - which is exactly why both consoles see each
other's real nicknames and run the trade 100% like a local session.

Loop safety: packet sockets can hear our own injections (PACKET_IGNORE_OUTGOING is
best-effort), and an echoed frame relayed back would ping-pong forever. EchoGuard
remembers the hashes of recently injected frames and drops matching captures for a short
window; real retries from the Switch are unaffected because only locally-injected bytes
are ever recorded.

Beacon replay: a scanning guest only sees the room while beacons arrive, but across the
relay a missed beacon is gone. The cache keeps the latest host beacons and a thread
re-injects them every BEACON_INTERVAL (docs/07: "100ms 주기 실측 후 조정") so Switch B's
scan always finds Switch A's room.
"""

import asyncio
import hashlib
import queue
import struct
import threading
import time

from common import mwlb
from framerelay.radio import is_beacon, mac_str, parse_80211, wrap_radiotap
from framerelay.rate_limit import TokenBucket

HEARTBEAT_INTERVAL = 10.0     # relay/server.py HEARTBEAT_TIMEOUT is 30.0s - sending at
                              # exactly the timeout let silent gaps exceed it and the
                              # relay closed us with 4408 in a loop; 1/3 of the budget
                              # keeps a missed beat recoverable (audit 10 H-1)
RADIO_POLL = 0.05             # capture poll quantum
BEACON_INTERVAL = 0.1         # beacon replay period (docs/07 section 6: 100ms)
BEACON_TTL = 1.5              # cached beacons older than this are never replayed again -
                              # a closed room must not haunt the peer's scan list
                              # indefinitely (audit 10 H-4)
ECHO_WINDOW = 2.0             # seconds a re-injected hash stays suppressed on capture
OUTBOX_MAXSIZE = 200          # WS backlog cap: ~10fps beacons during an outage would
                              # otherwise grow without bound and dump minutes-stale
                              # frames on reconnect (audit 10 H-2)
RECONNECT_BACKOFF = 1.0       # seconds before the first reconnect retry...
RECONNECT_BACKOFF_MAX = 60.0  # ...doubling every failure up to this cap, forever
                              # (audit 10 H-3: giving up after 3 tries left a zombie)


def compose_relay_url(base, session_id, role):
    """Build the relay WS endpoint from --relay-url/--session-id/--role. A bare base gets
    the server's path appended; an explicit /session/... URL passes through untouched so
    operators can pin exotic deployments. http(s):// bases are rewritten to ws(s):// -
    operators naturally copy the same URL the relay advertises over HTTP (STEP 9 finding:
    websockets.connect rejects an http scheme outright)."""
    base = str(base).rstrip("/")
    if base.startswith("http://"):
        base = "ws://" + base[len("http://"):]
    elif base.startswith("https://"):
        base = "wss://" + base[len("https://"):]
    if "/session/" in base:
        return base
    return f"{base}/session/{session_id}/ws?role={role}"


class BeaconCache:
    """Latest unique host beacons, oldest first, capped. Deduped by content hash so the
    100ms replay doesn't stack copies of the same beacon captured repeatedly.

    Entries carry the time they were cached and expire after `ttl` seconds (audit 10
    H-4): once a Switch closes its room the last beacons must stop replaying, otherwise
    the peer keeps seeing a ghost room forever.
    """

    def __init__(self, capacity=4, ttl=BEACON_TTL):
        self.capacity = capacity
        self.ttl = ttl
        self._frames = []            # [(hash, frame, monotonic-added)] oldest -> newest
        self._lock = threading.Lock()

    def add(self, frame):
        frame = bytes(frame)
        digest = hashlib.sha1(frame).digest()
        now = time.monotonic()
        with self._lock:
            self._frames = [e for e in self._frames if e[0] != digest]
            self._frames.append((digest, frame, now))
            while len(self._frames) > self.capacity:
                self._frames.pop(0)

    def snapshot(self):
        now = time.monotonic()
        with self._lock:
            self._frames = [e for e in self._frames if now - e[2] <= self.ttl]
            return [frame for _h, frame, _t in self._frames]

    def __len__(self):
        with self._lock:
            return len(self._frames)


class EchoGuard:
    """Suppress relaying frames we ourselves injected within ECHO_WINDOW (loopback echo).
    record() on injection, duplicate() on capture - True means "drop, it's ours"."""

    def __init__(self, window=ECHO_WINDOW):
        self.window = window
        self._seen = {}              # hash -> monotonic time of last injection
        self._lock = threading.Lock()

    def _prune_locked(self, now):
        """Drop entries past the window. Caller must hold the lock (audit 10 M-1:
        record()/duplicate() prune as they go so _seen cannot grow without bound)."""
        cutoff = now - self.window
        self._seen = {h: t for h, t in self._seen.items() if t >= cutoff}

    def prune(self):
        with self._lock:
            self._prune_locked(time.monotonic())

    def record(self, frame):
        digest = hashlib.sha1(bytes(frame)).digest()
        now = time.monotonic()
        with self._lock:
            self._prune_locked(now)
            self._seen[digest] = now

    def duplicate(self, frame):
        digest = hashlib.sha1(bytes(frame)).digest()
        now = time.monotonic()
        with self._lock:
            self._prune_locked(now)
            stamp = self._seen.get(digest)
            return stamp is not None and now - stamp <= self.window


class BeaconReplayer(threading.Thread):
    """Re-inject cached beacons at BEACON_INTERVAL so the remote guest's scan never sees
    the room disappear between real (relayed) beacon arrivals."""

    def __init__(self, cache, sender, interval=BEACON_INTERVAL, log=print):
        super().__init__(name="framerelay-beacons", daemon=True)
        self.cache = cache
        self.sender = sender          # callable(bare_frame) - exceptions must not kill us
        self.interval = interval
        self.log = log
        # NOT named _stop: threading.Thread already owns a _stop() method internally and
        # shadowing it breaks join() ('Event' object is not callable).
        self._halt = threading.Event()

    def stop(self):
        self._halt.set()

    def run(self):
        while not self._halt.wait(self.interval):
            try:
                for frame in self.cache.snapshot():
                    self.sender(frame)
            except Exception as e:   # noqa: BLE001 - a dead radio must not kill the thread
                self.log(f"[bridge] beacon replay error: {e}")
                if self._halt.wait(self.interval):
                    break


class RelayBridge:
    """Owns one MonitorRadio + one relay WebSocket; moves 802.11 frames between them.

    The data-plane entry points (on_radio_capture / on_ws_message) are deliberately
    synchronous and side-effect-light so offline tests can drive both directions without
    threads, sockets or a relay server.
    """

    def __init__(self, radio, relay_url, session_id, role="host", log=print, verbose=False,
                 rate_fps=None):
        self.radio = radio
        self.relay_url = compose_relay_url(relay_url, session_id, role)
        self.session_id = session_id
        self.role = role
        self.log = log
        self.verbose = verbose
        self.beacon_cache = BeaconCache()
        self.echo_guard = EchoGuard()
        # STEP 6 (docs/12): TokenBucket wired in as the physical last line of defense
        # against loop storms (docs/13 section 7). V-1 confirmed the EchoGuard byte-equality
        # premise (scenario A), so this is belt-and-suspenders - but a storm would multiply
        # through BOTH bridges, so the cap stays on by default. rate_fps=None -> default.
        if rate_fps is None:
            self.rate_limiter = TokenBucket(log=self._rate_warn)
        else:
            self.rate_limiter = TokenBucket(rate=float(rate_fps), log=self._rate_warn)
        self.stats = {"captured": 0, "relayed_out": 0, "injected": 0,
                      "dropped_filter": 0, "dropped_echo": 0, "dropped_backlog": 0,
                      "dropped_rate": 0}
        self._outbox = queue.Queue(maxsize=OUTBOX_MAXSIZE)  # MWLB frames for the WS thread
        self._ws = None                    # live websockets connection (async thread only)
        self._ws_thread = None
        self._beacon_thread = None
        self._radio_thread = None
        self._stop = threading.Event()

    def _rate_warn(self, message):
        """Throttled drop warning from the rate limiter (TokenBucket handles the 1/s cap)."""
        self.log(message)

    # -- data plane: radio -> relay -------------------------------------------
    def on_radio_capture(self, frame):
        """One bare 802.11 frame off the air. Filter (our Switch only), suppress our own
        echoes, cache beacons, then hand the frame to the relay unmodified inside 0x20."""
        self.stats["captured"] += 1
        if not self.radio.accepts(frame):
            self.stats["dropped_filter"] += 1
            return False
        if self.echo_guard.duplicate(frame):
            self.stats["dropped_echo"] += 1
            return False
        # STEP 6: physical loop-storm cap (docs/13 section 7). Checked AFTER filter/echo
        # so legitimate traffic accounting stays clean; a storm that defeats EchoGuard
        # still cannot multiply through here.
        if not self.rate_limiter.allow(len(frame)):
            self.stats["dropped_rate"] += 1
            return False
        info = parse_80211(frame)
        if is_beacon(info):
            self.beacon_cache.add(frame)
            if self.verbose:
                self.log(f"[bridge] beacon cached ({len(self.beacon_cache)} in queue)")
        # Audit 10 H-2: the queue is capped; on overflow evict the OLDEST queued frame
        # and keep this fresh capture ("newest wins") - a reconnect must replay what
        # the Switch just sent, not minutes-stale ACKs that piled up mid-outage.
        mwlb_frame = mwlb.build_frame(mwlb.MSG_FRAME_RELAY, frame)
        try:
            self._outbox.put_nowait(mwlb_frame)
        except queue.Full:
            self.stats["dropped_backlog"] += 1      # counts the evicted head-of-line
            try:
                self._outbox.get_nowait()
            except queue.Empty:
                pass                                # WS thread drained it in between
            try:
                self._outbox.put_nowait(mwlb_frame)
            except queue.Full:
                self.stats["dropped_backlog"] += 1  # raced again - count the loss
        self.stats["relayed_out"] += 1
        if self.verbose:
            self.log(f"[bridge] TX relay {len(frame)}B {frame[:16].hex()}...")
        return True

    # -- data plane: relay -> radio -------------------------------------------
    def on_ws_message(self, data):
        """One raw message from the relay socket. Only complete MSG_FRAME_RELAY frames do
        anything; heartbeats and garbage are swallowed (the relay is a byte pipe, so this
        is the only place inbound sanity is checked)."""
        parsed = mwlb.parse_frame(data)
        if parsed is None:
            return False
        msg_type, payload = parsed
        if msg_type == mwlb.MSG_HEARTBEAT:
            return True                     # consumed, never injected
        if msg_type != mwlb.MSG_FRAME_RELAY:
            return False
        # STEP 6: inbound side of the loop-storm cap - a peer bridge that lost its own
        # limiter must not turn US into an amplifier either.
        if not self.rate_limiter.allow(len(payload)):
            self.stats["dropped_rate"] += 1
            return False
        self.echo_guard.record(payload)     # mark BEFORE the air copy can echo back
        if is_beacon(parse_80211(payload)):
            self.beacon_cache.add(payload)  # keep the remote room alive between relays
        try:
            self.radio.send(wrap_radiotap(payload))
        except OSError as e:
            self.log(f"[bridge] inject failed: {e}")
            return False
        self.stats["injected"] += 1
        if self.verbose:
            self.log(f"[bridge] RX inject {len(payload)}B {payload[:16].hex()}...")
        return True

    def drain_outbox(self):
        """MWLB frames queued for the relay (test/debug convenience)."""
        out = []
        while True:
            try:
                out.append(self._outbox.get_nowait())
            except queue.Empty:
                return out

    # -- lifecycle --------------------------------------------------------------
    def start(self):
        self._stop.clear()
        self.radio.open()
        self._radio_thread = threading.Thread(target=self._run_radio_loop,
                                              name="framerelay-radio", daemon=True)
        # Replays go through the guard too: each 100ms re-injection refreshes its echo
        # suppression, otherwise echoes past ECHO_WINDOW would ping-pong back to the peer.
        self._beacon_thread = BeaconReplayer(self.beacon_cache, self._inject_guarded,
                                             log=self.log)
        self._radio_thread.start()
        self._beacon_thread.start()
        self._ws_thread = threading.Thread(target=self._run_ws_thread,
                                           name="framerelay-ws", daemon=True)
        self._ws_thread.start()
        self.log(f"[bridge] up: iface={getattr(self.radio, 'iface', '?')} "
                 f"role={self.role} session={self.session_id} relay={self.relay_url} "
                 f"host_mac={mac_str(self.radio.host_mac) if self.radio.host_mac is not None else 'filter-off'}")
        return self

    def stop(self):
        self._stop.set()
        for t in (self._beacon_thread, self._radio_thread, self._ws_thread):
            if t is not None:
                t.join(timeout=2)
        self.radio.close()
        rl = self.rate_limiter.stats
        self.log(f"[bridge] down: {self.stats} rate_limiter={rl}")

    # -- threads ----------------------------------------------------------------
    def _run_radio_loop(self):
        while not self._stop.is_set():
            try:
                frame = self.radio.recv(RADIO_POLL)
            except RuntimeError as e:
                # Shutdown close underneath us, or MonitorRadio's consecutive-error
                # tripwire (audit 10 M-2) - either way the loop must end loudly, not
                # as another silent zombie.
                if not self._stop.is_set():
                    self.log(f"[bridge] radio loop aborting: {e}")
                break
            if frame is not None:
                try:
                    self.on_radio_capture(frame)
                except Exception as e:      # noqa: BLE001 - one bad frame must not die
                    self.log(f"[bridge] capture handling error: {e}")

    def _run_ws_thread(self):
        try:
            asyncio.run(self._ws_main())
        except Exception as e:              # pragma: no cover - defensive
            self.log(f"[bridge] websocket thread crashed: {e}")

    async def _ws_main(self):
        try:
            import websockets
        except ImportError as e:            # pragma: no cover
            self.log(f"[bridge] missing dep for relay mode: {e}")
            return
        attempt = 0                         # consecutive failures, for the log only
        backoff = RECONNECT_BACKOFF
        while not self._stop.is_set():
            try:
                async with websockets.connect(self.relay_url) as ws:
                    attempt = 0             # reset once a connect succeeds
                    backoff = RECONNECT_BACKOFF
                    self._ws = ws
                    self.log(f"[bridge] websocket connected: {self.relay_url}")
                    await self._ws_session(ws)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self._ws = None
                if self._stop.is_set():
                    break
                attempt += 1
                # Audit 10 H-3: retry forever with exponential backoff (1s, 2s, 4s ...
                # capped at RECONNECT_BACKOFF_MAX). The old "3 attempts then quit"
                # budget left a silent zombie: WS thread dead, main loop alive, queue
                # filling up - exactly the state field debugging hates most.
                self.log(f"[bridge] connection lost ({e}); reconnect attempt "
                         f"{attempt} in {backoff:.0f}s (retrying indefinitely)")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2.0, RECONNECT_BACKOFF_MAX)

    async def _ws_session(self, ws):
        last_hb = time.monotonic()
        while not self._stop.is_set():
            while not self._outbox.empty():         # flush frames queued by captures
                await ws.send(self._outbox.get_nowait())
            if time.monotonic() - last_hb >= HEARTBEAT_INTERVAL:
                ts = int(time.time()) & 0xFFFFFFFF
                await ws.send(mwlb.build_frame(mwlb.MSG_HEARTBEAT, struct.pack("!I", ts)))
                last_hb = time.monotonic()
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=0.1)
            except asyncio.TimeoutError:
                continue
            self.on_ws_message(msg)

    def _inject_guarded(self, frame):
        """Inject + echo-guard bookkeeping in one step (used by the beacon replayer)."""
        self.echo_guard.record(frame)
        self.radio.send(wrap_radiotap(frame))
