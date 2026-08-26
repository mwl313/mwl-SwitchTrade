"""Long-session deduplication must be deterministic and wrap-safe."""

from collections import OrderedDict
import unittest

from frlgsim.sim import K_BACKLOG_MAX, Sim, _remember_recent


class BoundedDedupTest(unittest.TestCase):
    def test_old_values_are_evicted_in_insertion_order(self):
        recent = OrderedDict()
        for value in range(5):
            self.assertTrue(_remember_recent(recent, value, 3))
        self.assertEqual(list(recent), [2, 3, 4])
        self.assertFalse(_remember_recent(recent, 4, 3))
        self.assertTrue(_remember_recent(recent, 0, 3))
        self.assertEqual(list(recent), [3, 4, 0])

    def test_sequence_wrap_soak_stays_bounded_and_accepts_the_new_cycle(self):
        recent = OrderedDict()
        accepted = 0
        for absolute in range(70_000):
            accepted += int(_remember_recent(recent, absolute & 0xFFFF, 4096))
        self.assertEqual(accepted, 70_000)
        self.assertEqual(len(recent), 4096)

    def test_full_k_backlog_does_not_mark_an_unsent_ack_as_complete(self):
        sim = Sim.__new__(Sim)
        sim._acked_ts = OrderedDict()
        sim._pending_k = [(index, index) for index in range(K_BACKLOG_MAX)]
        sim._k_seq = K_BACKLOG_MAX

        self.assertFalse(sim._queue_k_ack(999))
        self.assertNotIn(999, sim._acked_ts)
        sim._pending_k.pop(0)
        self.assertTrue(sim._queue_k_ack(999))
        self.assertIn(999, sim._acked_ts)


if __name__ == "__main__":
    unittest.main()
