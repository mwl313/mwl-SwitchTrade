"""Feature-neutral RFU bridge at the locally terminated Reliable boundary."""

from __future__ import annotations

from collections import deque

from . import reliable
from .sim import (ACK_PERIOD, PARENT_RTX_LIMIT, RELIABLE_BATCH_MAX,
                  RTX_GAP_LIMIT, Sim)
from switchtrade.rfu_tunnel import Envelope, Kind, MAX_PAYLOAD_BYTES


MAX_PENDING_REMOTE = 256


class _NoGameEngine:
    """Sim constructor placeholder; tunnel mode never interprets game commands."""


class TunnelSim(Sim):
    """Terminate local Pia/Reliable and carry opaque RFU bytes to the peer.

    ``parent=False`` is beside the group leader's Switch and joins its room.
    ``parent=True`` hosts the mirrored room beside the joining Switch.
    """

    def __init__(self, transport, pia_crypto, our_ip, peer_ip, tunnel, *, conn,
                 our_var, parent=False, compress=False, capture_path=None,
                 observer=None, local_seat="member_a", log=lambda *args: None):
        self.tunnel = tunnel
        self._pending_remote = deque()
        self._tunnel_generation = getattr(tunnel, "connection_generation", None)
        self.parent = bool(parent)
        self.observer = observer
        self.local_seat = local_seat
        self.remote_seat = "member_b" if local_seat == "member_a" else "member_a"
        super().__init__(
            transport, pia_crypto, _NoGameEngine(), our_ip, peer_ip,
            conn=conn, our_var=our_var, compress=compress,
            parent_session_id=b"\x01\x00" if parent else None,
            capture_path=capture_path, log=log,
        )

    def _on_reliable_app(self, flags_a, payload):
        """Forward exact application bytes; no RFU opcode or activity knowledge."""
        send_rfu = getattr(self.tunnel, "send_rfu", None)
        if callable(send_rfu):
            send_rfu(payload, flags=flags_a)
        else:
            self.tunnel.send(payload, kind=Kind.RFU, flags=flags_a)
        if self.observer is not None:
            sender_role = "child" if self.parent else "parent"
            self.observer.submit(self.local_seat, sender_role, payload)

    def _drain_tunnel(self):
        connected = getattr(self.tunnel, "connected", None)
        if connected is not None and not connected.is_set():
            self._pending_remote.clear()
            return
        generation = getattr(self.tunnel, "connection_generation", None)
        if generation != self._tunnel_generation:
            self._pending_remote.clear()
            self._tunnel_generation = generation
        for envelope in self.tunnel.poll():
            if envelope.kind == Kind.PEER_CLOSE:
                self.host_disconnected = True
            elif getattr(envelope.kind, "name", None) == "RFU":
                if len(envelope.payload) > MAX_PAYLOAD_BYTES:
                    raise RuntimeError("RFU payload exceeds the Pia Reliable wire limit")
                if len(self._pending_remote) >= MAX_PENDING_REMOTE:
                    raise RuntimeError("RFU receive backlog overflow")
                self._pending_remote.append(envelope)

    def _drive_tunnel_reliable(self):
        self._drain_tunnel()
        now_ms = self._now_ms
        limit = PARENT_RTX_LIMIT if self.parent else RTX_GAP_LIMIT
        batch = list(self.rel.due_retransmits(now_ms, limit=limit))[:RELIABLE_BATCH_MAX]

        while self._pending_remote and len(batch) < RELIABLE_BATCH_MAX:
            if self.rel.inflight() >= self.rel.max_inflight:
                break
            envelope: Envelope = self._pending_remote.popleft()
            flags = envelope.flags & 0xFF
            if not flags & 0x01:
                self.log(f"[tunnel] rejected non-AppData RFU flags=0x{flags:02x}")
                continue
            if self.observer is not None:
                sender_role = "parent" if self.parent else "child"
                self.observer.submit(self.remote_seat, sender_role, envelope.payload)
            seq = self.rel.queue(envelope.payload, flags, now_ms)
            batch.append((seq, flags, envelope.payload))

        due = self.parent or (self._tick - self._last_ack_tick) >= ACK_PERIOD
        if due and (self._ack_owed or self.rel.recv_ooo):
            batch.append((None, reliable.FLAGSA_CTRL, self.rel.ack_payload()))
            self._ack_owed = False
            self._last_ack_tick = self._tick
        self._tx_reliable_batch(batch)

    def _drive_reliable(self):
        self._drive_tunnel_reliable()

    def _drive_parent_reliable(self):
        self._drive_tunnel_reliable()
