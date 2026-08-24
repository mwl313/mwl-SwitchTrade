"""FSM remote-channel hook unit tests (leader-leader EMU, Track A).

Verifies that frlgsim.sim.Sim wires the RemoteTransport remote state channel into the trade FSM,
OFFLINE - no RemoteTransport, no relay server, no LDN radio. A tiny MockTransport exposes the same
remote_send/remote_poll surface as RemoteTransport (an in-memory remote channel), so the Sim's hook
logic is exercised exactly as it would be against a real RemoteTransport:

  1. TX hook: a LOCAL host broadcast (SET_MONS_TO_TRADE / CONFIRM_FINISH_TRADE / PLAYER_CANCEL_TRADE)
     is relayed over remote_send as the matching MWLB message (TRADE_SELECT / CONFIRM / CANCEL).
  2. RX hook: an inbound remote message is drained by tick() and reflected into the FSM as the
     equivalent host broadcast (the virtual GBA performs the remote player's action).
  3. Loop prevention: a reflected remote message is never echoed back out the remote channel, and a
     transport without the remote channel (ReplayTransport / plain stub) keeps the hooks fully OFF.

Run:  .venv/bin/python tests/test_fsm_hook.py
"""

import os
import sys
import unittest

EMU_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, EMU_ROOT)

from frlgsim import trade, crypto as cryptomod, mon as monmod, transport as tmod  # noqa: E402
from frlgsim.sim import Sim  # noqa: E402


def _quiet(*args, **kwargs):
    pass


class MockTransport:
    """Minimal offline transport stub with a RemoteTransport-compatible remote state channel:
    `remote_send(msg, msg_type)` queues outbound MWLB frames; `remote_poll()` drains inbound ones.
    No sockets, no radio, no relay - the local data plane is a plain in-memory list."""

    def __init__(self):
        self.sent = []                 # local datagrams: [(datagram, dst_ip)]
        self.remote_outbox = []        # [(msg, msg_type)] handed to remote_send
        self.remote_inbox = []         # [(msg_type, payload)] to be yielded by remote_poll

    def send(self, datagram, dst_ip):
        self.sent.append((datagram, dst_ip))

    def recv(self):
        return []

    # -- remote channel (duck-typed by Sim: the capability that enables the hooks) --
    def remote_send(self, msg, msg_type):
        self.remote_outbox.append((msg, msg_type))

    def remote_poll(self):
        while self.remote_inbox:
            yield self.remote_inbox.pop(0)


class PlainTransport:
    """A transport WITHOUT the remote channel (send/recv only) - must keep the hooks off."""

    def __init__(self):
        self.sent = []

    def send(self, datagram, dst_ip):
        self.sent.append((datagram, dst_ip))

    def recv(self):
        return []


def _make_engine():
    party = [monmod.Mon.empty(), monmod.Mon.empty()]
    return trade.TradeEngine(party, trade_slot=1, log=_quiet)


def _make_sim(transport):
    pc = cryptomod.PiaCrypto(bytes(16))
    engine = _make_engine()
    sim = Sim(transport, pc, engine, "169.254.21.2", "169.254.21.1", log=_quiet)
    return sim, engine


class FsmHookTest(unittest.TestCase):
    # -- 1. TX hook -----------------------------------------------------------
    def test_tx_hook_relays_host_broadcasts(self):
        mock = MockTransport()
        sim, engine = _make_sim(mock)
        # the remote-capable transport arms the hooks: sim.remote set + engine.remote_hook wired.
        self.assertIs(sim.remote, mock)
        self.assertIsNotNone(engine.remote_hook)

        # Three local host (leader) broadcasts -> the three MWLB remote messages.
        engine._on_linkcmd(trade.SET_MONS_TO_TRADE, 5)          # slot 5 -> TRADE_SELECT
        engine._on_linkcmd(trade.CONFIRM_FINISH_TRADE, 0)       # -> TRADE_CONFIRM
        engine._on_linkcmd(trade.PLAYER_CANCEL_TRADE, 0)        # -> TRADE_CANCEL

        self.assertEqual(mock.remote_outbox, [
            (b"\x05", trade.REMOTE_TRADE_SELECT),
            (b"", trade.REMOTE_TRADE_CONFIRM),
            (b"", trade.REMOTE_TRADE_CANCEL),
        ])

    # -- 2. RX hook -----------------------------------------------------------
    def test_rx_hook_reflects_remote_select_into_fsm(self):
        mock = MockTransport()
        sim, engine = _make_sim(mock)
        engine.state = trade.S4_PARTY            # SET_MONS transitions S4/S5 -> S6_CONFIRM
        mock.remote_inbox.append((trade.REMOTE_TRADE_SELECT, b"\x03"))

        sim.tick()                               # tick() drains remote_poll() -> apply_remote()

        self.assertEqual(engine.host_cursor, 3)
        self.assertEqual(engine.state, trade.S6_CONFIRM)

    # -- 3. loop prevention / no re-injection ---------------------------------
    def test_rx_reflection_is_not_echoed_back(self):
        mock = MockTransport()
        sim, engine = _make_sim(mock)
        engine.state = trade.S4_PARTY
        mock.remote_inbox.append((trade.REMOTE_TRADE_SELECT, b"\x02"))

        sim.tick()

        # The synthesized host broadcast must NOT be relayed back out (the suppress guard).
        self.assertEqual(mock.remote_outbox, [])

    def test_rx_confirm_and_cancel_reflected(self):
        mock = MockTransport()
        sim, engine = _make_sim(mock)
        # TRADE_CONFIRM -> CONFIRM_FINISH_TRADE (defers commit until READY_FINISH; no crash)
        engine.state = trade.S6_CONFIRM
        engine._finish_sent = True
        mock.remote_inbox.append((trade.REMOTE_TRADE_CONFIRM, b""))
        sim.tick()
        self.assertGreater(engine.commits, 0)

        # TRADE_CANCEL -> PLAYER_CANCEL_TRADE -> S_CANCEL + done
        mock2 = MockTransport()
        sim2, engine2 = _make_sim(mock2)
        engine2.state = trade.S5_SELECT
        mock2.remote_inbox.append((trade.REMOTE_TRADE_CANCEL, b""))
        sim2.tick()
        self.assertEqual(engine2.state, trade.S_CANCEL)
        self.assertTrue(engine2.cancelled)

    # -- 4. hooks off without the remote channel ------------------------------
    def test_hooks_off_without_remote_channel(self):
        plain = PlainTransport()
        sim, engine = _make_sim(plain)
        self.assertIsNone(sim.remote)
        self.assertIsNone(engine.remote_hook)

        # ReplayTransport (the offline regression path) has no remote channel either.
        replay = tmod.ReplayTransport([])
        sim2, engine2 = _make_sim(replay)
        self.assertIsNone(sim2.remote)
        self.assertIsNone(engine2.remote_hook)

        # A host broadcast is still processed locally, but nothing is relayed.
        engine._on_linkcmd(trade.SET_MONS_TO_TRADE, 5)
        self.assertEqual(plain.sent, [])          # no tick() -> no local datagrams yet


if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(FsmHookTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print("DONE_MARKER_FSM")
        sys.exit(0)
    sys.exit(1)
