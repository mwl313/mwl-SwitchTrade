"""Relay rate limiting - the physical last line of defense against loop storms (docs/13 §7).

EchoGuard suppresses our own re-captured injections, but its premise (injected bytes ==
recaptured bytes) is exactly what V-1 is out to verify (docs/10 C-1). Until that lands -
and afterwards too, as belt-and-suspenders - a hard cap on frames per second bounds any
ping-pong amplification: a healthy LDN session peaks at tens of frames/s (beacon replay
alone is <=40/s, docs/10 M-4), while a hash-mismatch loop multiplies through both bridges
and reaches thousands within seconds. Anything above DEFAULT_RATE_FPS therefore cannot be
legitimate traffic and is dropped, with a warning log that is itself throttled - during a
storm an unthrottled warning per drop would be its own flood.

TokenBucket over a sliding window: O(1) memory (no timestamp deque to grow mid-storm)
and the burst budget naturally absorbs legitimate micro-bursts such as a beacon replay
tick firing several frames at once.

The bridge deliberately does NOT wire this in yet - the class ships with offline tests so
STEP 6 (D-1) only has to instantiate it once the V-1 scenario (docs/13) is confirmed.
"""

import time

# docs/13 section 7: ~5x headroom over the worst legitimate load (~40/s beacon replay +
# data exchange), still orders of magnitude below what a relay loop storm produces.
DEFAULT_RATE_FPS = 200.0
WARN_INTERVAL = 1.0           # seconds between drop warnings - see module docstring


class TokenBucket:
    """Classic token bucket with an injectable clock -> deterministic offline tests.

    Each allow() call spends one token; tokens regenerate continuously at `rate` per
    second, capped at `burst` (default: one second's worth = `rate`). `clock` must be a
    zero-argument callable returning seconds (monotonic-like); tests inject a fake clock
    and step time explicitly instead of sleeping.

    frame_len does not gate admission (the cap is per-frame) but is accumulated into byte
    counters so logs/stats can show how much traffic the cap swallowed.
    """

    def __init__(self, rate=DEFAULT_RATE_FPS, burst=None, clock=time.monotonic,
                 log=None, warn_interval=WARN_INTERVAL):
        if rate <= 0:
            raise ValueError("rate must be positive")
        if burst is None:
            burst = float(rate)
        if burst < 1:
            raise ValueError("burst must admit at least one frame")
        self.rate = float(rate)
        self.burst = float(burst)
        self.clock = clock
        self.log = log
        self.warn_interval = warn_interval
        self._tokens = float(burst)
        self._last = None          # clock() of the previous call - None = never used
        self._last_warn = None     # clock() of the previous drop warning
        self.stats = {"frames": 0, "allowed": 0, "dropped": 0,
                      "bytes_in": 0, "bytes_allowed": 0, "bytes_dropped": 0}

    def allow(self, frame_len=0):
        """True = forward this frame; False = over the cap, drop it (warn sparingly)."""
        now = self.clock()
        # Refill only on forward time movement: equal timestamps add nothing, and a
        # backward jump (a monotonic clock should never do it, but stay safe) must not
        # mint tokens out of negative elapsed time.
        if self._last is not None and now > self._last:
            self._tokens = min(self.burst, self._tokens + (now - self._last) * self.rate)
        self._last = now
        frame_len = max(0, int(frame_len))
        s = self.stats
        s["frames"] += 1
        s["bytes_in"] += frame_len
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            s["allowed"] += 1
            s["bytes_allowed"] += frame_len
            return True
        s["dropped"] += 1
        s["bytes_dropped"] += frame_len
        if self.log is not None and (
                self._last_warn is None or now - self._last_warn >= self.warn_interval):
            self._last_warn = now
            self.log(f"[rate] {self.rate:.0f}/s exceeded - dropping "
                     f"({s['dropped']} dropped / {s['frames']} seen)")
        return False
