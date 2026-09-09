"""Independent receive-stream bootstrap over real encrypted Pia datagrams."""
import asyncio
from types import SimpleNamespace

import pytest

from tests.test_rfu_flow_control import PROTOCOL
from frlgsim import reliable
from frlgsim.crypto import PiaCrypto
from frlgsim.tunnel import TunnelSim
from bridge.tests.test_pia_host import pia_reliable_datagram
from switchtrade.endpoints.switch_ldn.tunnel_adapter import CoreTunnelAdapter


def receiver(*, parent=False, capacity=8):
    adapter = CoreTunnelAdapter("test", PROTOCOL, capacity=capacity)
    cipher = PiaCrypto(bytes(range(16)))
    conn = SimpleNamespace(on_message=lambda *args, **kw: None, learn_ids=lambda *args: None)
    sim = TunnelSim(object(), cipher, "169.254.1.2", "169.254.1.1", adapter,
                    conn=conn, our_var=0x1234, parent=parent)
    def receive(seq, payload=b"opaque", flags=7, window=None):
        datagram = pia_reliable_datagram(cipher, "169.254.1.1", 0x1234, 0x5678,
            seq & 255, seq, seq if window is None else window, flags, payload)
        assert sim.process_datagram(datagram, "169.254.1.1")
    return sim, adapter, receive


@pytest.mark.parametrize("parent", [False, True])
@pytest.mark.parametrize("start", [0, 0x2345, 0xFFF0, 0xFFFF])
def test_peer_initialized_frame_seeds_receive_not_local_send_sequence(parent, start):
    async def exercise():
        sim, adapter, receive = receiver(parent=parent)
        try:
            outgoing = sim.rel.queue(b"local-open", 15, 0)
            receive(start, b"peer-open", 15)
            assert (await asyncio.wait_for(adapter.receive_for_core(), 1)).payload == b"peer-open"
            assert sim.rel.recv_next == (start + 1) & 0xFFFF
            assert sim.rel.out_seq == (outgoing + 1) & 0xFFFF
            assert outgoing in sim.rel.unacked
            status = sim.flow_status()
            assert status["reliable_rx_first_seq"] == start
            assert status["reliable_rx_first_flags"] == 15
            assert status["reliable_rx_first_window"] == start
            assert status["reliable_rx_initialized"] == 1
            receive((start + 1) & 0xFFFF, b"next")
            assert (await adapter.receive_for_core()).payload == b"next"
            receive(start, b"peer-open", 15)  # Lost ACK: retransmit, not a new stream.
            assert not adapter._local_to_core
            assert sim.rel.recv_next == (start + 2) & 0xFFFF
        finally:
            adapter.close()
            sim.close()
    asyncio.run(exercise())


def test_missing_init_is_not_falsely_acked_or_rebased_to_later_data():
    async def exercise():
        sim, adapter, receive = receiver()
        try:
            receive(0x2346, b"later")
            receive(0xFFF0, b"coincidentally-equals-local-start")
            assert not adapter._local_to_core
            assert not sim._seen_in
            assert not sim._ack_owed
            assert sim.flow_status()["reliable_rx_init_waits"] == 2
            # The opposite send window can still progress while init is missing.
            outgoing = sim.rel.queue(b"local-open", 15, 0)
            receive(0, reliable.build_bulk_ack(outgoing + 1), 0)
            assert not sim.rel.unacked
            receive(0x2345, b"opening-retransmission", 15)
            assert (await adapter.receive_for_core()).payload == b"opening-retransmission"
            receive(0x2346, b"later")
            assert (await adapter.receive_for_core()).payload == b"later"
            assert sim.rel.recv_next == 0x2347
        finally:
            adapter.close()
            sim.close()
    asyncio.run(exercise())


def test_full_queue_does_not_commit_bootstrap_until_admitted():
    async def exercise():
        sim, adapter, receive = receiver(capacity=1)
        try:
            adapter.send_rfu(b"occupied", flags=7)
            receive(0xFFFF, b"opening", 15)
            assert not sim._in_seq_initialized
            assert not sim._seen_in
            assert not sim._ack_owed
            assert sim.rel.recv_next == 0xFFF0
            assert (await adapter.receive_for_core()).payload == b"occupied"
            receive(0xFFFF, b"opening", 15)
            assert sim.rel.recv_next == 0
            receive(0, b"next")  # Still full: do not ACK/dedupe it.
            assert sim.rel.recv_next == 0
            assert 0 not in sim._seen_in
            assert (await adapter.receive_for_core()).payload == b"opening"
            receive(1, b"future", 15)  # Initialized cannot reset an open stream.
            assert sim.rel.recv_next == 0
            assert not adapter._local_to_core
            receive(0, b"next")
            assert (await adapter.receive_for_core()).payload == b"next"
            receive(1, b"future", 15)
            assert (await adapter.receive_for_core()).payload == b"future"
            assert sim.rel.recv_next == 2
        finally:
            adapter.close()
            sim.close()
    asyncio.run(exercise())


def test_truncated_reliable_init_is_not_a_valid_stream_opener():
    wire = reliable.build_reliable(0x2345, 0x2345, b"opening", flagsA=15)
    assert reliable.parse_reliable(wire[:-1]) is None
