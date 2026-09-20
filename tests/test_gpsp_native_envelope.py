"""Trial13 envelope reproductions, NOT a model of the closed native RFU receiver.

Real converter/cadence/Core adapter/TunnelSim/Reliable/serialization/crypto;
in-memory wire and scripted RFU1 input only. No socket, emulator or game input.
The tests deliberately retain observed deviations instead of calling them a
proven receiver fault. No fixture generates the next parent on an ACK.
"""
import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from bridge.frlgsim import gbaframe, ni, reliable, rfu
from bridge.frlgsim.crypto import PiaCrypto, PiaHeader, decompress
from bridge.frlgsim.sim import RELIABLE_BATCH_MAX
from bridge.frlgsim.tunnel import TunnelSim
from bridge.frlgsim.tunnel_progress import NativeRfuProgress
from switchtrade.core.contracts import LinkPacket
from switchtrade.endpoints.retroarch_gpsp import rfu as gpsp
from switchtrade.endpoints.retroarch_gpsp.cadence import RfuCadence
from switchtrade.endpoints.switch_ldn.tunnel_adapter import CoreTunnelAdapter
from switchtrade.endpoints.switch_ldn.errors import SwitchLdnEndpointError
from tools.audit_rfu_trace import native_envelope_observations, native_service_observations
from tests.test_gpsp_rfu import TranslatorFixture, GPSP_DEVICE, accept, parent_t, rfu1
from tests import test_gpsp_cadence as cadence_model


class EnvelopePath:
    def __init__(self, cadence=RfuCadence, *, parent=False):
        self.clock = [0.0]
        self.flow = cadence(lambda: self.clock[0])
        self.translator = TranslatorFixture.connected()
        self.adapter = CoreTunnelAdapter("envelope", "switchtrade.gba-frame.v1", clock=lambda: self.clock[0])
        self.crypto = PiaCrypto(bytes(range(16)), game_key=bytes(range(16, 32)))
        self.datagrams = []
        transport = SimpleNamespace(send=lambda data, dst: self.datagrams.append(data))
        conn = SimpleNamespace(on_message=lambda *a, **kw: None, learn_ids=lambda *a: None)
        self.sim = TunnelSim(transport, self.crypto, "192.0.2.2", "192.0.2.1",
                             self.adapter, conn=conn, our_var=0x1234, parent=parent)
        self.sim.host_var = bytes.fromhex("5678")
        self.sim._learned = True
        self.sim._rfu_progress = NativeRfuProgress(parent=parent, clock=lambda: self.clock[0])

    async def admit(self, actions):
        for action in actions:
            if action.destination == "tunnel":
                await self.adapter.deliver_from_core(LinkPacket(
                    "envelope", "switchtrade.gba-frame.v1", action.payload, action.flags))

    def decode(self):
        output = []
        for datagram in self.datagrams:
            plaintext = self.crypto.decrypt(datagram, "192.0.2.2")
            assert plaintext is not None
            app, _ = decompress(plaintext)
            messages, _, _ = reliable.parse_app(app)
            assert messages and all(m.proto == reliable.PROTO_RELIABLE for m in messages)
            frames = [reliable.parse_reliable(m.payload) for m in messages]
            assert all(f is not None for f in frames)
            output.append(frames)
        self.datagrams.clear()
        return output

    def tick(self, tick):
        self.sim._tick = tick
        self.sim._drive_tunnel_reliable()
        return self.decode()

    def bulk_ack(self, next_expected, mask=bytes(16)):
        # Only lower-layer acknowledgment; the native RFU receiver is absent.
        payload = reliable.build_bulk_ack(next_expected, mask)
        self.incoming(payload, 0, reliable.FLAGSA_CTRL)

    def incoming(self, payload, sequence, flags=7):
        frame = reliable.build_reliable(sequence, 0, payload, flagsA=flags)
        body = reliable.build_message(reliable.PROTO_RELIABLE, frame,
            msgflags=0x40 if flags == reliable.FLAGSA_CTRL else None) + b"\x12\x34"
        pad = (-len(body)) % 16
        header = PiaHeader(dst=0x1234, src=0x5678, pktid=1, nonce8=bytes(8), flags=pad << 4, footer=2)
        packet = self.crypto.encrypt(body + b"\xff" * pad, "192.0.2.1", header)
        assert self.sim.process_datagram(packet, "192.0.2.1")

    def summary(self):
        batch = self.sim.drain_diagnostics(final=True)
        assert batch["dropped"] == 0
        return native_envelope_observations(batch)

    def close(self):
        self.flow.close()
        self.sim.close()
        self.adapter.close()


@pytest.mark.parametrize("delay_ticks", [0, 1, 12])
def test_first_uni_callback_spacing_changes_grouping_not_payload_or_native_verdict(delay_ticks):
    async def exercise():
        path = EnvelopePath()
        try:
            parent = parent_t(100, rfu.parent_uni_slot([bytes(14)]))
            path.sim._rfu_progress.observe(parent, 30, 7, received=True)
            local, = path.flow.admit(path.translator.from_switch(parent, flags=7, generation=1, sequence=3))
            assert local.destination == "core"
            receipt, = path.flow.admit(path.translator.from_core(
                rfu1(gpsp.RFU1_CLIENT_ACK, GPSP_DEVICE), peer_id=1, sequence=2))
            await path.admit([receipt])
            packets = path.tick(0) if delay_ticks else []
            child_slot = rfu.uni_slot(bytes(14))
            child, = path.flow.admit(path.translator.from_core(rfu1(
                gpsp.RFU1_CLIENT_SEND, len(child_slot) << 24 | GPSP_DEVICE, child_slot, size=104),
                peer_id=1, sequence=3))
            await path.admit([child])
            packets += path.tick(delay_ticks)
            frames = [f for p in packets for f in p if f.flagsA & 1]
            assert {f.payload for f in frames} == {receipt.payload, child.payload}
            path.bulk_ack(path.sim.rel.out_seq)
            assert path.sim.rel.inflight() == 0
            # A quiet parent is never advanced by the fixture's transport ACK.
            assert path.tick(600) == []
            summary = path.summary()
            assert summary["status"] == "OBSERVED_NOT_NATIVE_VALIDATED"
            uni = summary["first_uni"]
            assert uni["parent_count"] == uni["child_queued_count"] == 1
            assert uni["same_scheduled_datagram"] is (delay_ticks == 0)
            assert uni["next_parent_after_ms"] is None
            assert uni["native_completion"] == "NOT_OBSERVED"
            assert uni["child_queue_to_window_release_ms"] is not None
        finally:
            path.close()
    asyncio.run(exercise())


@pytest.mark.parametrize("legacy", [False, True])
def test_transport_retry_cannot_recover_receipt_removed_above_reliable(legacy):
    async def exercise():
        path = EnvelopePath(cadence_model.LegacyReceiptCadence if legacy else RfuCadence)
        try:
            # TranslatorFixture already accepted WA. Open the independent real
            # native Reliable/adapter receive stream with that same valid WA.
            path.incoming(accept(), 0xFFF0, 15)
            assert (await path.adapter.receive_for_core()).payload == accept()
            admitted = []
            for seq, stamp in enumerate((10, 11, 12), 0xFFF1):
                path.incoming(parent_t(stamp, None), seq)
                packet = await path.adapter.receive_for_core()
                admitted += path.flow.admit(path.translator.from_switch(
                    packet.payload, flags=packet.flags, generation=1, sequence=seq - 0xFFF1 + 3))
            path.clock[0] = .3
            admitted += path.flow.poll()
            expected = [10, 12] if legacy else [10, 11, 12]
            assert [int.from_bytes(a.payload[12:16], "little") for a in admitted] == expected
            await path.admit(admitted)
            assert path.sim.rel.recv_next == 0xFFF4
            # Native resends the same Reliable identity. It is already admitted
            # below cadence, so normal dedup correctly prevents redelivery.
            path.incoming(parent_t(11, None), 0xFFF2)
            assert not path.adapter._local_to_core
            path.clock[0] = 240
            assert path.flow.poll() == ()
            frames = [f for p in path.tick(0) for f in p if f.flagsA & 1]
            assert [int.from_bytes(f.payload[12:16], "little") for f in frames] == expected
            # The previous direct-translator recovery test requires a DIFFERENT
            # Reliable identity. Do not assume the native peer will invent it.
            path.incoming(parent_t(11, None), 0xFFF4)
            packet = await path.adapter.receive_for_core()
            recovered, = path.flow.admit(path.translator.from_switch(
                packet.payload, flags=packet.flags, generation=1, sequence=6))
            assert recovered.classification == "parent_ack"
            assert int.from_bytes(recovered.payload[12:16], "little") == 11
        finally:
            path.close()
    asyncio.run(exercise())


def test_lossless_receipts_still_need_service_budget_with_unthrottled_input():
    # Preserve the overload counterexample; full native ingress is tested in
    # test_gpsp_flow_control_path, not assumed by this direct-input model.
    baseline, backlog = asyncio.run(cadence_model.deadline_path(True, cadence=cadence_model.LegacyReceiptCadence))
    assert baseline is not None and baseline < 2 and backlog < 32
    delayed, backlog = asyncio.run(cadence_model.deadline_path(True))
    assert delayed is None and backlog > 100  # NULL misses the modeled 4.5s bound
    prompt, backlog = asyncio.run(cadence_model.deadline_path(True, ack_period=3))
    assert prompt is not None and prompt < 2 and backlog < 32


@pytest.mark.parametrize("service_ticks", [3, 24])
def test_asymmetric_native_service_carries_ni_backlog_into_first_uni(service_ticks):
    """Real encrypted boundary, 30Hz scripted ingress vs six slots / 400ms.

    NOT a replay of the native receiver: ACK timing is an explicit independent
    input. In particular no fixture invents a next parent when UNI is delivered.
    Unlike the drained-tail test, the first UNI arrives with NI receipts pending.
    """
    async def exercise():
        path = EnvelopePath()
        try:
            path.incoming(accept(), 0xFFF0, 15)
            await path.adapter.receive_for_core()
            expected, sent, entries = [], {}, []
            first_uni_tick = 720
            for tick in range(2200):
                path.clock[0] = tick / 60
                path.sim._tick = tick
                if tick <= first_uni_tick and tick % 2 == 0:
                    index = tick // 2
                    slot = (rfu.parent_uni_slot([bytes(14)]) if tick == first_uni_tick else
                            ni.parent_recv_ack_slot(rfu.LCOM_NI, 1, 0))
                    parent = parent_t(100 + index, slot)
                    path.incoming(parent, (0xFFF1 + index) & 65535)
                    packet = await path.adapter.receive_for_core()
                    local = path.flow.admit(path.translator.from_switch(
                        packet.payload, flags=packet.flags, generation=1, sequence=index + 3))
                    assert any(a.destination == "core" for a in local)
                    actions = path.flow.admit(path.translator.from_core(
                        rfu1(gpsp.RFU1_CLIENT_ACK, GPSP_DEVICE), peer_id=1, sequence=index + 2))
                    await path.admit(actions)
                    expected.extend(a.payload for a in actions if a.destination == "tunnel")
                    if tick == first_uni_tick:
                        child_slot = rfu.uni_slot(bytes(14))
                        actions = path.flow.admit(path.translator.from_core(rfu1(
                            gpsp.RFU1_CLIENT_SEND, len(child_slot) << 24 | GPSP_DEVICE,
                            child_slot, size=104), peer_id=1, sequence=index + 3))
                        await path.admit(actions)
                        expected.extend(a.payload for a in actions if a.destination == "tunnel")
                if tick and tick % service_ticks == 0:
                    # Cumulative release of the active window, independently
                    # scheduled. Selective receipts alone cannot free its gap.
                    path.bulk_ack(path.sim.rel.out_seq)
                elif service_ticks == 24 and path.sim.rel.inflight() == 6 and tick % 4 == 0:
                    path.bulk_ack(path.sim.rel.send_low(), b"\x1f" + bytes(15))
                for packet in path.tick(tick):
                    for frame in packet:
                        if frame.flagsA & 1:
                            if frame.seq in sent:
                                assert sent[frame.seq] == frame.payload
                            sent.setdefault(frame.seq, frame.payload)
                if tick % 300 == 0:  # Production's five-second diagnostic flush interval.
                    batch = path.sim.drain_diagnostics()
                    assert batch["dropped"] == 0
                    entries.extend(batch["entries"])
                if tick > first_uni_tick and len(sent) == len(expected) and not path.sim.rel.inflight():
                    break
            else:
                pytest.fail("scripted service never drained")
            assert list(sent.values()) == expected  # Every WK and the child, in original order.
            assert len(expected) == 362 and path.sim.rel.max_inflight == 6
            batch = path.sim.drain_diagnostics(final=True)
            assert batch["dropped"] == 0
            entries.extend(batch["entries"])
            observed = native_envelope_observations({**batch, "entries": entries})
            service = native_service_observations(entries)
            assert service["status"] == "OBSERVED_NOT_NATIVE_VALIDATED"
            assert service["delays"]["core_wait"]["max_ms"] == 0
            assert service["delays"]["core_queue"]["max_ms"] == 0
            assert service["pending_without_native_admission"] == 0
            assert service["released_frames"] == len(expected)
            uni = observed["first_uni"]
            assert uni["parent_count"] == uni["child_queued_count"] == 1
            assert uni["next_parent_after_ms"] is None
            assert uni["native_completion"] == "NOT_OBSERVED"
            if service_ticks == 24:
                assert service["peak_pending"] > 150
                assert service["selective_acks"] and service["acks_without_release"]
                assert uni["parent_to_child_attempt_ms"] > 10000
                assert service["delays"]["pending"]["max_ms"] > 10000
            else:
                assert service["peak_pending"] < 6
                assert uni["parent_to_child_attempt_ms"] < 100
                assert service["delays"]["pending"]["max_ms"] < 100
        finally:
            path.close()
    asyncio.run(exercise())


def test_host_queue_timing_separates_core_wait_from_poll_and_native_wait_then_resets():
    async def exercise():
        path = EnvelopePath()
        path.adapter._capacity = 1
        blocked = None
        try:
            action = lambda i: gpsp.TranslatorAction("tunnel", gbaframe.build_k(i, 1, i), "parent_ack", flags=7)
            await path.admit([action(1)])
            path.clock[0] = 1
            blocked = asyncio.create_task(path.admit([action(2)]))
            await asyncio.sleep(0)
            assert not blocked.done()
            path.clock[0] = 3
            path.sim._drain_tunnel()  # first packet waited in Core for 3s
            await asyncio.wait_for(blocked, 1)  # second waited for capacity for 2s
            path.clock[0] = 4
            path.sim._drain_tunnel()  # second then waited in Core for 1s
            path.clock[0] = 8
            assert path.sim.flow_status()["native_backlog"]["oldest_ms"] == 5000
            path.tick(480)
            path.bulk_ack(path.sim.rel.out_seq)
            batch = path.sim.drain_diagnostics(final=True)
            service = native_service_observations(batch["entries"])
            assert service["delays"] == {
                "core_wait": {"pairs": 2, "max_ms": 2000},
                "core_queue": {"pairs": 2, "max_ms": 3000},
                "pending": {"pairs": 2, "max_ms": 5000},
                "core_to_reliable": {"pairs": 2, "max_ms": 8000}}
            assert service["pre_clear"][0]["max_residence_ms"] == 5000
            # A fresh connection generation must not inherit the preceding ages.
            path.adapter.reset("envelope")
            path.tick(481)
            status = path.sim.flow_status()["native_backlog"]
            assert status == {"count": 0, "oldest_ms": 0, "peak": 0,
                              "max_residence_ms": 0, "pre_clear": None}
        finally:
            if blocked is not None:
                blocked.cancel()
                await asyncio.gather(blocked, return_exceptions=True)
            path.close()
    asyncio.run(exercise())


def test_saturated_retirement_keeps_native_backlog_evidence_and_releases_blocked_producer():
    async def exercise():
        path = EnvelopePath()
        blocked = None
        try:
            action = gpsp.TranslatorAction("tunnel", b"PRIVATE", "opaque", flags=7)
            await path.admit([action] * 256)
            path.tick(0)  # six in flight, 250 pending
            await path.admit([action] * 6)
            path.tick(1)  # 256 pending; exactly the bound, not an overflow
            await path.admit([action] * 256)
            blocked = asyncio.create_task(path.admit([action]))
            await asyncio.sleep(0)
            assert not blocked.done()
            path.clock[0] = 10
            path.adapter.close()
            with pytest.raises(SwitchLdnEndpointError, match="Core tunnel is not connected"):
                await asyncio.wait_for(blocked, 1)
            path.tick(600)
            status = path.sim.flow_status()
            assert status["pending_remote"] == 0
            assert status["native_backlog"]["pre_clear"]["count"] == 256
            assert status["native_backlog"]["pre_clear"]["oldest_ms"] == 10000
            assert status["pre_clear"]["core_to_local_queue"] == 256
            batch = path.sim.drain_diagnostics(final=True)
            assert batch["dropped"] == 0
            service = native_service_observations(batch["entries"])
            assert service["pending_without_native_admission"] == 256
            assert service["pre_clear"][0]["count"] == 256
            import json
            assert "PRIVATE" not in json.dumps(batch)
        finally:
            if blocked is not None:
                blocked.cancel()
                await asyncio.gather(blocked, return_exceptions=True)
            path.close()
    asyncio.run(exercise())


@pytest.mark.parametrize("parent", [False, True])
def test_ack_observation_preserves_both_native_roles_reliable_state_through_wrap(parent):
    async def exercise():
        path = EnvelopePath(parent=parent)
        try:
            path.sim.rel.out_seq = path.sim.rel.window_lo = 65534
            actions = [gpsp.TranslatorAction("tunnel", bytes([i]), "opaque", flags=7) for i in range(6)]
            await path.admit(actions)
            path.tick(0)
            baseline = deepcopy(path.sim.rel)
            for tick, ackid, mask in ((3, 65534, b"\x1f" + bytes(15)),
                                      (4, 65534, b"\x1f" + bytes(15)),
                                      (5, 65535, bytes(16)),
                                      (6, 4, bytes(16))):
                path.sim._tick = tick
                path.clock[0] = tick / 60
                baseline.on_ack(ackid, mask, now_ms=path.sim._now_ms)
                path.bulk_ack(ackid, mask)
                assert vars(path.sim.rel) == vars(baseline)
            assert path.sim.rel.inflight() == 0 and path.sim.rel.send_low() == 4
            trace = path.sim.drain_diagnostics(final=True)
            acks = [e for e in trace["entries"] if e["event"] == "native_ack"]
            assert [e["released"] for e in acks] == [0, 0, 6, 0]
            assert [e["selective_bits"] for e in acks] == [5, 5, 0, 0]
        finally:
            path.close()
    asyncio.run(exercise())


@pytest.mark.parametrize("older_kind", ["WK", "WT"])
@pytest.mark.parametrize("start", [0xFFF0, 0xFFFF])
def test_lost_ack_regroups_old_frame_before_new_wk_without_changing_reliable_bytes(older_kind, start):
    async def exercise():
        path = EnvelopePath()
        try:
            path.sim.rel.out_seq = path.sim.rel.window_lo = start
            old = (gbaframe.build_k(1, 1, 10) if older_kind == "WK" else
                   gbaframe.wrap_t(rfu.uni_slot(bytes(14)), 10))
            new = gbaframe.build_k(2, 1, 11)
            action = lambda data: gpsp.TranslatorAction("tunnel", data, "parent_ack", flags=7)
            await path.admit([action(old)])
            first, = path.tick(0)
            assert [(f.seq, f.payload) for f in first] == [(start, old)]
            # Omit the peer ACK. Retransmit is now due when a NEW receipt arrives.
            await path.admit([action(new)])
            combined, = path.tick(30)
            assert [(f.seq, f.payload) for f in combined] == [(start, old), ((start + 1) & 65535, new)]
            assert int.from_bytes(combined[1].payload[8:12], "little") == 1  # wire position is 2
            # Selectively ACK the later frame: the earlier gap must remain.
            path.bulk_ack(start, b"\x01" + bytes(15))
            assert path.sim.rel.send_low() == start
            retry, = path.tick(60)
            assert [(f.seq, f.payload) for f in retry] == [(start, old)]
            path.bulk_ack((start + 2) & 65535)
            assert path.tick(90) == [] and path.sim.rel.inflight() == 0
            summary = path.summary()
            assert summary["wk_position_differences"] == 1
            mismatch, = summary["first_position_differences"]
            assert (mismatch["message_index"], mismatch["app_position"]) == (1, 2)
        finally:
            path.close()
    asyncio.run(exercise())


def test_ni_receipt_replacement_is_visible_before_uni_flush_and_repeat_recovery():
    async def exercise():
        path = EnvelopePath(cadence_model.LegacyReceiptCadence)
        try:
            admitted = []
            for sequence, stamp in enumerate((10, 11, 12), 3):
                admitted += path.flow.admit(path.translator.from_switch(
                    parent_t(stamp, None), flags=7, generation=1, sequence=sequence))
            assert len(admitted) == 1
            # A real parent UNI triggers flush of the last deferred NI receipt.
            actions = path.flow.admit(path.translator.from_switch(
                parent_t(13, rfu.parent_uni_slot([bytes(14)])), flags=7, generation=1, sequence=6))
            admitted += [a for a in actions if a.destination == "tunnel"]
            assert [int.from_bytes(a.payload[12:16], "little") for a in admitted] == [10, 12]
            assert [int.from_bytes(a.payload[4:8], "little") for a in admitted] == [1, 2]
            assert path.flow.receipts_coalesced == 1
            # Recovery requires an actual repeated WT; quiet time alone cannot recover 11.
            path.clock[0] = 240
            assert path.flow.poll() == ()
            repeated = path.flow.admit(path.translator.from_switch(
                parent_t(11, None), flags=7, generation=1, sequence=7))
            assert len(repeated) == 1 and repeated[0].destination == "tunnel"
            assert int.from_bytes(repeated[0].payload[12:16], "little") == 11
            assert int.from_bytes(repeated[0].payload[4:8], "little") == 3
            await path.admit(admitted + list(repeated))
            packet, = path.tick(0)
            assert [f.payload for f in packet] == [a.payload for a in admitted + list(repeated)]
        finally:
            path.close()
    asyncio.run(exercise())


def test_serializer_datagram_split_and_control_frames_match_observer_positions():
    path = EnvelopePath()
    try:
        # Serializer-only boundary: not an increased production send window.
        batch = [(i, 7, gbaframe.build_k(i + 1, 1, i + 10)) for i in range(RELIABLE_BATCH_MAX + 2)]
        batch.insert(RELIABLE_BATCH_MAX - 1, (None, 0, reliable.build_bulk_ack(0)))
        path.sim._rfu_progress.scheduled(batch, RELIABLE_BATCH_MAX)
        path.sim._tx_reliable_batch(batch)
        packets = path.decode()
        assert [len(p) for p in packets] == [RELIABLE_BATCH_MAX, 3]
        assert [f.payload for p in packets for f in p] == [data for _, _, data in batch]
        positions = [i for p in packets for i, _ in enumerate([f for f in p if f.flagsA & 1], 1)]
        observer = path.sim.flow_status()["rfu_boundary"]["wk_scheduled"]
        assert [e["app_position"] for e in observer["first"]] == positions
    finally:
        path.close()
