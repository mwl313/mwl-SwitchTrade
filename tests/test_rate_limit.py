"""Unit tests for framerelay.rate_limit.TokenBucket - fully offline and deterministic.

Time is injected (docs/13 §7): a FakeClock stands in for time.monotonic so refill,
burst capping and warning cadence are asserted exactly, with no sleeps and no flakiness.
The bridge is not wired to the bucket yet (STEP 6, after V-1) - these tests pin the
contract it will be wired against.

Run:  .venv/bin/python tests/test_rate_limit.py
"""

import os
import sys
import unittest

EMU_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, EMU_ROOT)

from framerelay.rate_limit import DEFAULT_RATE_FPS, WARN_INTERVAL, TokenBucket  # noqa: E402


class FakeClock:
    """Deterministic monotonic-like clock: starts at t=1000.0, advanced explicitly."""

    def __init__(self, start=1000.0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class TokenBucketBasics(unittest.TestCase):
    # -- admission contract -------------------------------------------------------
    def test_burst_frames_admitted_then_capped(self):
        clk = FakeClock()
        bucket = TokenBucket(rate=10, clock=clk)
        outcomes = [bucket.allow(100) for _ in range(12)]
        self.assertEqual(outcomes, [True] * 10 + [False] * 2)

    def test_default_rate_matches_design_constant(self):
        self.assertEqual(DEFAULT_RATE_FPS, 200.0)
        bucket = TokenBucket(clock=FakeClock())
        self.assertEqual(bucket.rate, 200.0)
        self.assertEqual(bucket.burst, 200.0)          # burst defaults to 1s worth

    def test_allow_returns_strict_bool(self):
        bucket = TokenBucket(clock=FakeClock())
        self.assertIs(bucket.allow(60), True)
        drained = TokenBucket(rate=1, clock=FakeClock())
        drained.allow(0)
        self.assertIs(drained.allow(0), False)

    def test_custom_burst_smaller_than_rate(self):
        clk = FakeClock()
        bucket = TokenBucket(rate=200, burst=5, clock=clk)
        outcomes = [bucket.allow(1500) for _ in range(7)]
        self.assertEqual(outcomes, [True] * 5 + [False] * 2)


class TokenRefill(unittest.TestCase):
    # -- time-based regeneration ---------------------------------------------------
    def test_partial_refill_grants_fractional_budget(self):
        clk = FakeClock()
        bucket = TokenBucket(rate=10, clock=clk)
        for _ in range(10):
            bucket.allow(0)                            # drain the initial burst
        self.assertFalse(bucket.allow(0))
        clk.advance(0.5)                               # half a second -> 5 tokens
        outcomes = [bucket.allow(0) for _ in range(6)]
        self.assertEqual(outcomes, [True] * 5 + [False])

    def test_steady_stream_below_rate_never_drops(self):
        clk = FakeClock()
        bucket = TokenBucket(rate=200, clock=clk)
        for _ in range(2000):                          # 10s of a 100/s stream
            self.assertTrue(bucket.allow(72))
            clk.advance(0.005)                         # 0.005s * 200/s = 1 token/frame
        self.assertEqual(bucket.stats["dropped"], 0)

    def test_sustained_overload_caps_at_one_refill_second(self):
        clk = FakeClock()
        bucket = TokenBucket(rate=200, clock=clk)
        first_second = sum(bucket.allow(64) for _ in range(1000))
        self.assertEqual(first_second, 200)            # instant flood -> burst only
        clk.advance(1.0)
        next_second = sum(bucket.allow(64) for _ in range(1000))
        self.assertEqual(next_second, 200)             # exactly one refill-second worth

    def test_idle_time_does_not_bank_tokens_past_burst(self):
        clk = FakeClock()
        bucket = TokenBucket(rate=200, clock=clk)
        bucket.allow(0)
        clk.advance(3600.0)                            # an idle hour must not stack up
        self.assertEqual(sum(bucket.allow(0) for _ in range(250)), 200)


class ClockRobustness(unittest.TestCase):
    # -- injectable-clock edge cases ------------------------------------------------
    def test_backward_clock_jump_is_ignored(self):
        clk = FakeClock()
        bucket = TokenBucket(rate=10, clock=clk)
        for _ in range(10):
            bucket.allow(0)
        clk.advance(-5.0)                              # monotonic clocks never do this...
        self.assertFalse(bucket.allow(0))              # ...but no negative-time tokens

    def test_buckets_with_separate_clocks_are_independent(self):
        c1, c2 = FakeClock(), FakeClock()
        b1 = TokenBucket(rate=1, clock=c1)
        b2 = TokenBucket(rate=1, clock=c2)
        self.assertTrue(b1.allow(0) and b2.allow(0))
        self.assertFalse(b1.allow(0))
        c2.advance(10.0)                               # only b2's timeline moves
        self.assertTrue(b2.allow(0))
        self.assertFalse(b1.allow(0))


class ByteStatsAndWarnings(unittest.TestCase):
    # -- accounting + throttled "warn on drop" --------------------------------------
    def test_byte_counters_track_admission(self):
        clk = FakeClock()
        bucket = TokenBucket(rate=2, clock=clk)
        self.assertTrue(bucket.allow(100))
        self.assertTrue(bucket.allow(300))
        self.assertFalse(bucket.allow(500))
        s = bucket.stats
        self.assertEqual((s["frames"], s["allowed"], s["dropped"]), (3, 2, 1))
        self.assertEqual((s["bytes_in"], s["bytes_allowed"], s["bytes_dropped"]),
                         (900, 400, 500))

    def test_negative_frame_len_does_not_corrupt_stats(self):
        bucket = TokenBucket(rate=2, clock=FakeClock())
        self.assertTrue(bucket.allow(-5))
        self.assertEqual(bucket.stats["bytes_in"], 0)

    def test_drop_warning_throttled_by_interval(self):
        lines = []
        clk = FakeClock()
        bucket = TokenBucket(rate=1, clock=clk, log=lines.append, warn_interval=0.3)
        bucket.allow(0)                                # the only allowed frame
        for _ in range(5):                             # 5 drops over 0.25s: inside the
            self.assertFalse(bucket.allow(0))          # throttle window -> silent
            clk.advance(0.05)
        self.assertEqual(len(lines), 1)                # one warning so far, not six
        for _ in range(4):                             # keep dropping past the boundary
            self.assertFalse(bucket.allow(0))          # (refills stay below 1 token/frame)
            clk.advance(0.05)
        self.assertEqual(len(lines), 2)                # exactly one more warning

    def test_silent_bucket_when_no_log_given(self):
        bucket = TokenBucket(rate=1, clock=FakeClock())
        bucket.allow(0)
        for _ in range(5):
            self.assertFalse(bucket.allow(0))          # must not raise without a logger


class Validation(unittest.TestCase):
    def test_invalid_construction_rejected(self):
        clk = FakeClock()
        for kwargs in ({"rate": 0}, {"rate": -1}, {"rate": 10, "burst": 0.5}):
            with self.assertRaises(ValueError):
                TokenBucket(clock=clk, **kwargs)


if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TokenBucketBasics))
    suite.addTests(loader.loadTestsFromTestCase(TokenRefill))
    suite.addTests(loader.loadTestsFromTestCase(ClockRobustness))
    suite.addTests(loader.loadTestsFromTestCase(ByteStatsAndWarnings))
    suite.addTests(loader.loadTestsFromTestCase(Validation))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print("DONE_MARKER_RATE_LIMIT")
        sys.exit(0)
    sys.exit(1)
