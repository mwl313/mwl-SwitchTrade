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

    @staticmethod
    def _sequence_sim():
        sim = Sim.__new__(Sim)
        sim._seen_in = OrderedDict()
        sim.last_in_seq = 0
        sim._in_seq_initialized = False
        return sim

    def test_sliding_window_rejects_evicted_stale_duplicate(self):
        sim = self._sequence_sim()
        self.assertTrue(sim._note_in_seq(0))
        for sequence in range(1, 4097):
            self.assertTrue(sim._note_in_seq(sequence))
        self.assertFalse(sim._note_in_seq(0))

    def test_sliding_window_accepts_wrap_and_one_bounded_out_of_order_frame(self):
        sim = self._sequence_sim()
        self.assertTrue(sim._note_in_seq(0xFFFF))
        self.assertTrue(sim._note_in_seq(0))
        self.assertFalse(sim._note_in_seq(0xFFFF))
        self.assertTrue(sim._note_in_seq(0xFFFE))
        self.assertFalse(sim._note_in_seq(0xFFFE))

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
