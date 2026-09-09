"""Trial10 head-of-line model; no physical radio or commercial-game claim."""
import asyncio
from collections import deque

import pytest

from bridge.frlgsim import ni, rfu as native
from switchtrade.endpoints.retroarch_gpsp.cadence import RfuCadence, NI_RETRY_SECONDS
from switchtrade.endpoints.retroarch_gpsp import rfu as r
from tests.test_gpsp_rfu import TranslatorFixture, rfu1, parent_t, GPSP_DEVICE
from tests.test_rfu_flow_control import simulation, CoreTunnelAdapter, PROTOCOL
from switchtrade.core.contracts import LinkPacket


def child_action(slot, timestamp=1):
    return r.TranslatorAction("tunnel", r._gba(r.GBA_TRANSFER,
        timestamp.to_bytes(4, "little") + bytes((0, len(slot), 0, 0)) +
        slot + bytes((-len(slot)) & 3)), "child_transfer", flags=7)


def receipt(timestamp):
    return r.TranslatorAction("tunnel", r._gba(r.GBA_ACK,
        timestamp.to_bytes(4, "little") + bytes((1, 0, 0, 0)) +
        timestamp.to_bytes(4, "little")), "parent_ack", flags=7)


def test_ni_retry_keeps_new_lanes_bytes_and_recovery_without_fabricated_ack():
    clock = [0.0]
    flow = RfuCadence(lambda: clock[0])
    for phase in range(4):
        slot = native.child_ni_llsf(native.LCOM_NI, 1, phase, 0, 1) + b"a"
        action = child_action(slot)
        assert flow.admit([action]) == (action,)
        assert flow.admit([action]) == ()
        changed = child_action(slot[:-1] + b"b")
        assert flow.admit([changed]) == (changed,)  # changed bytes are never hidden
        wrapped = child_action(native.child_ni_llsf(native.LCOM_NI, 0, phase, 0, 1) + b"b")
        assert flow.admit([wrapped]) == (wrapped,)
    clock[0] += NI_RETRY_SECONDS
    assert flow.admit([wrapped]) == (wrapped,)  # actual game retries remain possible
    assert flow.poll() == ()  # never originate NI/ACK on the game's behalf
    null = child_action(native.child_ni_llsf(native.LCOM_NULL, 1, 0, 0, 0))
    assert flow.admit([null]) == (null,)
    assert flow.snapshot()["ni_lanes"] == 0


@pytest.mark.parametrize("slot", [b"\x5a", b"\xff\xff", native.uni_slot(bytes(14)),
    native.child_ni_llsf(native.LCOM_NI_END, 0, 0, 0, 0) * 2,
    native.child_ni_llsf(native.LCOM_NI, 1, 0, 1, 1) + b"x"])
def test_uni_unknown_mixed_and_ambiguous_slots_are_not_coalesced(slot):
    flow = RfuCadence(lambda: 0)
    ni_action = child_action(native.child_ni_llsf(native.LCOM_NI_END, 0, 0, 0, 0))
    assert flow.admit([ni_action]) == (ni_action,)
    actions = [child_action(slot, i + 1) for i in range(300)]
    assert flow.admit(actions) == tuple(actions)
    assert flow.snapshot()["ni_lanes"] == 0
    assert flow.admit([ni_action]) == (ni_action,)  # no stale lane across opaque input


def test_latest_unsent_receipt_is_bounded_numbered_on_emit_and_retired():
    clock = [0.0]
    flow = RfuCadence(lambda: clock[0])
    first = flow.admit([receipt(0xFFFFFFFE)])[0]
    assert int.from_bytes(first.payload[4:8], "little") == 1
    for timestamp in (0xFFFFFFFF, *range(1, 1000)):
        assert flow.admit([receipt(timestamp)]) == ()
    assert flow.snapshot()["receipt_pending"] == 1
    clock[0] = .3
    last = flow.poll()[0]
    assert int.from_bytes(last.payload[4:8], "little") == 2
    assert int.from_bytes(last.payload[12:16], "little") == 999
    flow.admit([receipt(1000)])
    flow.close()
    clock[0] = 100
    assert flow.poll() == ()
    assert flow.snapshot()["receipt_pending"] == 0
    fresh = RfuCadence(lambda: clock[0])
    assert int.from_bytes(fresh.admit([receipt(1001)])[0].payload[4:8], "little") == 1


def test_native_state_change_loss_retry_and_scheduler_pause_are_not_timeouts():
    clock = [0.0]
    flow = RfuCadence(lambda: clock[0])
    for ack in (0, 1):
        for state in (native.LCOM_NI_START, native.LCOM_NI, native.LCOM_NI_END):
            action = child_action(native.child_ni_llsf(state, 0, 0, ack, 0))
            assert flow.admit([action]) == (action,)  # same lane, new state
            assert flow.admit([action]) == ()
            clock[0] += .26  # first copy or its native response may be lost
            assert flow.admit([action]) == (action,)
    clock[0] += 1800  # VM descheduled; no manufactured catch-up burst or failure
    assert flow.poll() == ()
    assert flow.admit([action]) == (action,)
    assert flow.admit([action]) == ()


@pytest.mark.parametrize("ack", [0, 1])
def test_new_native_transaction_does_not_inherit_other_phases_retry_identity(ack):
    flow = RfuCadence(lambda: 0)
    slot = native.child_ni_llsf(native.LCOM_NI, 1, 2, ack, 0)
    data = child_action(slot)
    start = child_action(native.child_ni_llsf(native.LCOM_NI_START, 1, 0, ack, 0))
    for _ in range(2):
        assert flow.admit([start]) == (start,)
        assert flow.admit([start]) == ()
        assert flow.admit([data]) == (data,)
        assert flow.admit([data]) == ()


def test_deferred_receipt_disconnect_is_final_and_wrong_flags_still_fail():
    flow = RfuCadence(lambda: 0)
    flow.admit([receipt(1), receipt(2)])
    disconnect = r.TranslatorAction("tunnel", r._gba(r.GBA_DISCONNECT, bytes(2)), "disconnect", flags=7)
    assert flow.admit([disconnect, receipt(3)]) == (disconnect,)
    assert flow.poll() == ()
    translator = TranslatorFixture.connected()
    payload = parent_t(1, ni.parent_recv_ack_slot(native.LCOM_NI, 1, 0))
    translator.from_switch(payload, flags=7, generation=1, sequence=3)
    with pytest.raises(r.TranslatorError):
        # Even a duplicate is validated by the translator before cadence sees it.
        translator.from_switch(payload, flags=0x107, generation=1, sequence=4)


async def deadline_path(paced):
    """60Hz native repeats, ~15fps local service, real converter/FIFO/Reliable.

    This models the observed *service deficit*, not exact over-air packet loss.
    Local delivery and native ACK are separate: no native END_ACK before END
    crosses the delayed local boundary. The old policy remains a counterfactual.
    """
    clock = [0.0]
    flow = RfuCadence(lambda: clock[0]) if paced else None
    translator = TranslatorFixture.connected()
    adapter = CoreTunnelAdapter("test", PROTOCOL)
    sim, sent = simulation(adapter)
    core_seq, remote_seq, parent_timestamp = 2, 3, 1
    queued = deque()
    arrived = set()
    end_seen, null_sent, null_arrived = False, False, None
    backlog_high = 0
    async def admit(actions):
        queued.extend(flow.admit(actions) if flow else actions)
        while queued:
            action = queued.popleft()
            assert action.destination == "tunnel"
            await adapter.deliver_from_core(LinkPacket("test", PROTOCOL, action.payload, action.flags))
    try:
        for tick in range(270):
            clock[0] = tick / 59.727
            sim._tick = tick
            if tick % 24 == 0:
                for seq, (_flags, payload) in sent.items():
                    if seq in arrived:
                        continue
                    arrived.add(seq)
                    if payload.startswith(b"WT"):
                        slot = payload[12:12 + payload[9]]
                        state = native.parse_llsf_child(slot)["state"]
                        if state == native.LCOM_NI_END:
                            end_seen = True
                        if state == native.LCOM_NULL:
                            null_arrived = clock[0]
                sim.rel.on_ack(sim.rel.out_seq, now_ms=sim._now_ms)
            # The parent repeats its last native response once per game frame.
            state = native.LCOM_NI_END if end_seen else native.LCOM_NI
            parent_slot = ni.parent_recv_ack_slot(state, 0 if end_seen else 1, 0)
            actions = translator.from_switch(parent_t(parent_timestamp, parent_slot),
                flags=7, generation=1, sequence=remote_seq)
            assert len(actions) == 1 and actions[0].classification == "parent_transfer"
            remote_seq += 1
            parent_timestamp += 1
            await admit(translator.from_core(rfu1(r.RFU1_CLIENT_ACK, GPSP_DEVICE),
                peer_id=1, sequence=core_seq))
            core_seq += 1
            slot = None
            if tick < 21:
                slot = native.child_ni_llsf(native.LCOM_NI, 1, tick % 3, 0, 1) + bytes([tick % 3])
            elif not end_seen:
                slot = native.child_ni_llsf(native.LCOM_NI_END, 0, 0, 0, 0)
            elif not null_sent:
                slot = native.child_ni_llsf(native.LCOM_NULL, 1, 0, 0, 0)
                null_sent = True
            if slot is not None:
                await admit(translator.from_core(rfu1(r.RFU1_CLIENT_SEND,
                    len(slot) << 24 | GPSP_DEVICE, slot, size=104), peer_id=1, sequence=core_seq))
                core_seq += 1
            if flow:
                for action in flow.poll():
                    await adapter.deliver_from_core(LinkPacket("test", PROTOCOL, action.payload, action.flags))
            sim._drive_tunnel_reliable()
            backlog_high = max(backlog_high, len(sim._pending_remote) + len(adapter._core_to_local))
        return null_arrived, backlog_high
    finally:
        sim.close()
        adapter.close()


def test_trial10_service_deficit_blocks_fifo_null_but_not_paced_ni():
    old, old_backlog = asyncio.run(deadline_path(False))
    new, new_backlog = asyncio.run(deadline_path(True))
    assert old is None and old_backlog >= 256  # reproduce the original gap
    assert new is not None and new < 2, (new, new_backlog)
    assert new_backlog < 32
