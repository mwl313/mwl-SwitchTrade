"""Bounded RFU admission with a progressing, slower local Reliable peer."""
import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bridge"))
from frlgsim.crypto import PiaCrypto
from frlgsim import reliable
from frlgsim.tunnel import TunnelSim, MAX_PENDING_REMOTE
from bridge.tests.test_pia_host import pia_reliable_datagram
from switchtrade.core.contracts import LinkPacket
from switchtrade.endpoints.switch_ldn.errors import SwitchLdnEndpointError
from switchtrade.endpoints.switch_ldn.tunnel_adapter import CoreTunnelAdapter, CoreRfuFrame

PROTOCOL = "switchtrade.gba-frame.v1"


def packet(index, generation="test"):
    return LinkPacket(generation, PROTOCOL, index.to_bytes(4, "big"), 7)


def simulation(adapter, *, parent=False):
    sim = TunnelSim(object(), object(), "169.254.1.2", "169.254.1.1", adapter,
                    conn=None, our_var=0x1234, parent=parent)
    sent = {}
    def transmit(batch):
        for seq, flags, payload in batch:
            if seq is not None:
                sent.setdefault(seq, (flags, payload))
    sim._tx_reliable_batch = transmit
    return sim, sent


@pytest.mark.parametrize("parent", [False, True])
def test_slow_ack_pressure_preserves_every_frame_and_order(parent):
    async def exercise():
        adapter = CoreTunnelAdapter("test", PROTOCOL, capacity=8)
        sim, sent = simulation(adapter, parent=parent)
        async def produce():
            for index in range(1600):
                await adapter.deliver_from_core(packet(index))
                await asyncio.sleep(0)
        producer = asyncio.create_task(produce())
        blocked = False
        try:
            for tick in range(1, 12000):
                sim._tick = tick
                if tick % 6 == 0:
                    sim.rel.on_ack(sim.rel.out_seq, now_ms=sim._now_ms)
                sim._drive_tunnel_reliable()
                assert len(sim._pending_remote) <= MAX_PENDING_REMOTE
                assert len(adapter._core_to_local) <= 8
                blocked |= len(adapter._core_to_local) == 8 and not producer.done()
                await asyncio.sleep(0)
                await asyncio.sleep(0)
                if producer.done():
                    producer.result()
                    if len(sent) == 1600:
                        break
            else:
                pytest.fail("flow did not resume after ACKs")
            assert blocked
            assert list(sent.values()) == [(7, packet(i).payload) for i in range(1600)]
        finally:
            producer.cancel()
            await asyncio.gather(producer, return_exceptions=True)
            adapter.close()
            sim.close()
    asyncio.run(exercise())


def test_drain_respects_remaining_capacity_before_send_slots_are_consumed():
    async def exercise():
        adapter = CoreTunnelAdapter("test", PROTOCOL)
        sim, sent = simulation(adapter)
        sim._pending_remote.extend(CoreRfuFrame(packet(i).payload, 7) for i in range(255))
        await adapter.deliver_from_core(packet(255))
        await adapter.deliver_from_core(packet(256))
        try:
            sim._drive_tunnel_reliable()
            assert len(sent) == sim.rel.max_inflight == 6
            assert len(adapter._core_to_local) == 1
            assert len(sim._pending_remote) == 250
        finally:
            adapter.close()
            sim.close()
    asyncio.run(exercise())


def test_numeric_diagnostics_distinguish_new_send_retransmit_and_window_progress():
    async def exercise():
        adapter = CoreTunnelAdapter("test", PROTOCOL)
        sim, sent = simulation(adapter)
        try:
            await adapter.deliver_from_core(packet(0))
            sim._drive_tunnel_reliable()
            status = sim.flow_status()
            assert status["reliable_tx_new"] == 1
            assert status["reliable_tx_retransmits"] == 0
            assert status["reliable_rto_ms"] > 0
            oldest = status["reliable_send_window"]
            sim._tick += 120  # Virtual elapsed time only, no physical retry.
            sim._drive_tunnel_reliable()
            status = sim.flow_status()
            assert status["reliable_tx_new"] == 1
            assert status["reliable_tx_retransmits"] == 1
            assert status["reliable_send_window"] == oldest
            sim.rel.on_ack(sim.rel.out_seq, now_ms=sim._now_ms)
            assert sim.flow_status()["reliable_send_window"] == (oldest + 1) & 0xFFFF
            assert len(sent) == 1
        finally:
            adapter.close()
            sim.close()
    asyncio.run(exercise())


@pytest.mark.parametrize("ending", ["cancel", "close", "seal", "fail", "reset"])
def test_full_adapter_wait_is_cancellable_and_never_rebinds_to_reset(ending):
    async def exercise():
        adapter = CoreTunnelAdapter("test", PROTOCOL, capacity=1)
        await adapter.deliver_from_core(packet(0))
        pending = asyncio.create_task(adapter.deliver_from_core(packet(1)))
        try:
            await asyncio.sleep(0)
            assert not pending.done()
            if ending == "cancel":
                pending.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await pending
                assert [f.payload for f in adapter.poll()] == [packet(0).payload]
            else:
                cause = SwitchLdnEndpointError("TEST_FIRST_FAILURE", "synthetic")
                if ending == "reset":
                    adapter.reset("test")  # Even the same ID retires waiting admission.
                elif ending == "fail":
                    adapter.fail(cause)
                else:
                    getattr(adapter, ending)()
                with pytest.raises(SwitchLdnEndpointError) as error:
                    await asyncio.wait_for(pending, 1)
                if ending == "fail":
                    assert error.value is cause
                assert adapter.poll() == []
        finally:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
            adapter.close()
    asyncio.run(exercise())


def test_full_local_queue_does_not_ack_or_dedupe_unaccepted_reliable_data():
    async def exercise():
        adapter = CoreTunnelAdapter("test", PROTOCOL, capacity=1)
        crypto = PiaCrypto(bytes(range(16)))
        conn = SimpleNamespace(on_message=lambda *args, **kw: None, learn_ids=lambda *args: None)
        sim = TunnelSim(object(), crypto, "169.254.1.2", "169.254.1.1", adapter,
                        conn=conn, our_var=0x1234)
        def incoming(seq, payload, flags=7):
            return pia_reliable_datagram(crypto, "169.254.1.1", 0x1234, 0x5678,
                                        seq & 255, seq, 0xFFF0, flags, payload)
        try:
            sim.process_datagram(incoming(0xFFF0, b"first", 15), "169.254.1.1")
            sim.process_datagram(incoming(0xFFF1, b"second"), "169.254.1.1")
            assert sim.rel.recv_next == 0xFFF1
            assert 0xFFF1 not in sim._seen_in
            outgoing = sim.rel.queue(b"opposite direction", 7, sim._now_ms)
            ack = reliable.build_bulk_ack((outgoing + 1) & 0xFFFF)
            sim.process_datagram(incoming(0, ack, reliable.FLAGSA_CTRL), "169.254.1.1")
            assert outgoing not in sim.rel.unacked  # ACK RX is not blocked by admission.
            assert (await adapter.receive_for_core()).payload == b"first"
            # A later frame must not overtake the declined one when space opens.
            sim.process_datagram(incoming(0xFFF2, b"third"), "169.254.1.1")
            assert not adapter._local_to_core
            assert not sim.rel.recv_ooo
            sim.process_datagram(incoming(0xFFF1, b"second"), "169.254.1.1")
            assert sim.rel.recv_next == 0xFFF2
            assert (await adapter.receive_for_core()).payload == b"second"
            sim.process_datagram(incoming(0xFFF1, b"second"), "169.254.1.1")
            assert not adapter._local_to_core
            sim.process_datagram(incoming(0xFFF2, b"third"), "169.254.1.1")
            assert (await adapter.receive_for_core()).payload == b"third"
        finally:
            adapter.close()
            sim.close()
    asyncio.run(exercise())
