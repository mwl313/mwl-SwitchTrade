"""Borrowed frontend connection with independently owned RFU Generations.

Frontend/process observation is not game readiness. No process/configuration
control belongs here; only our loopback stream and RFU peer are owned.
"""
from __future__ import annotations

import asyncio
from collections import Counter
import json
import logging
import time

from switchtrade.core.contracts import (
    CleanupReport, EndpointCapabilities, EndpointKind, GenerationEnded,
    GenerationRole, LinkPacket, RuntimeKind,
)
from .errors import GpspError
from .cadence import RfuCadence
from .netplay import LocalNetplay, MAX_QUEUE
from .process import ProcessObserver
from .rfu import (
    RfuTranslator, _parse_rfu1, _rfu1, RFU1_CONNECT_REQ, RFU1_CONNECT_ACK,
    RFU1_CONNECT_NACK, RFU1_DISCONNECT, RFU1_CLIENT_SEND, RFU1_CLIENT_ACK,
)

PROTOCOL = "switchtrade.gba-frame.v1"
LOG = logging.getLogger(__name__)
_RFU_KIND_NAMES = (
    "broadcast", "connect_request", "connect_ack", "connect_nack",
    "disconnect", "host_send", "client_send", "client_ack",
)


def clean(report):
    return report.endpoint_stopped and report.local_resources_released and report.transport_drained


async def sticky_close(task):
    while True:
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            if task.cancelled():
                raise


class RetroArchGpspEndpointDriver:
    capabilities = EndpointCapabilities(EndpointKind.RETROARCH_GPSP, RuntimeKind.NATIVE,
        (PROTOCOL,), (GenerationRole.MIRROR,))

    def __init__(self, *, pid=None, port=55435, observer=None):
        self._pid, self._port, self._observer = pid, port, observer
        self.local = None
        self._runner = self._closing = self._opening = None
        self._stop, self._ready, self._failed = asyncio.Event(), asyncio.Event(), asyncio.Event()
        self.failure = None
        self._generation = None
        self._next_id = 1
        self._retired_hosts, self._retired_children = set(), set()
        self._cleanup_verified = True
        self._cleanup_errors = []
        self.rfu_mode_verified = False
        self._probe_unresolved = False

    @property
    def generation(self):
        return self._generation

    def _check(self):
        if self.failure is not None:
            raise self.failure
        if self._closing is not None:
            raise GpspError("EMULATOR_ENDPOINT_CLOSED", "에뮬레이터 중계가 종료됐습니다.")
        if not self._cleanup_verified:
            raise GpspError("EMULATOR_CLEANUP_UNPROVEN", "이전 통신 정리를 확인하지 못해 새 방을 시작할 수 없습니다.")

    def _fail(self, error):
        if self.failure is None:
            self.failure = error
            LOG.error("endpoint_failure code=%s", getattr(error, "code", type(error).__name__))
        self._failed.set()

    async def wait_failed(self):
        await self._failed.wait()
        raise self.failure

    async def _wait(self, operation, cancel=None):
        task = asyncio.ensure_future(operation)
        guards = [asyncio.create_task(self.wait_failed())]
        if cancel is not None:
            guards.append(asyncio.create_task(cancel.wait()))
        try:
            await asyncio.wait([task, *guards], return_when=asyncio.FIRST_COMPLETED)
            if task.done() and not task.cancelled() and task.exception() is not None:
                return task.result()
            self._check()
            if cancel is not None and cancel.is_set():
                raise asyncio.CancelledError
            return await task
        finally:
            for pending in (task, *guards):
                if not pending.done():
                    pending.cancel()
            await asyncio.gather(task, *guards, return_exceptions=True)

    async def prepare(self):
        self._check()
        if self._runner is not None:
            return
        # Fail absence/ambiguity/unknown before CLI joins a Pair. Native observer
        # never launches the emulator and never acquires process-write rights.
        self._observer = self._observer or ProcessObserver.select(self._pid)
        self._observer.check()
        LOG.info("observed_process identity=%s core=%s", getattr(self._observer, "identity", None),
            getattr(self._observer, "core", None))
        self.local = LocalNetplay(self._observer, self._port)
        self._runner = asyncio.create_task(self._run(), name="gpsp-frontend")
        # Allow bind failures to surface before external Pair admission.
        await self._wait(self.local.listening.wait())

    async def _probe_mode(self):
        # PING follows synchronous core netpacket callbacks in pinned stock v7.
        # NACK proves the RFU dispatcher is live, even before game input. This
        # does not prove a game link or permit Bridge active to be announced.
        self._probe_unresolved = True
        await self.local.send(_rfu1(RFU1_CONNECT_REQ, 0))
        await self.local.barrier()
        packets = [_parse_rfu1(item.payload) for item in self.local.drain()]
        assignments = [header for kind, header, _ in packets if kind == RFU1_CONNECT_ACK]
        if assignments:
            # Wrong in-game role: retire only the RFU connection we just made.
            for assignment in assignments:
                if assignment & 0xFFFC0000 or not assignment & 0xFFFF:
                    self._cleanup_verified = False
                    raise GpspError("EMULATOR_PROBE_INVALID", "RFU 연결 확인 응답이 잘못됐습니다.")
                await self.local.send(_rfu1(RFU1_DISCONNECT, assignment))
            await self.local.barrier()
            self.local.drain()
            self._probe_unresolved = False
            raise GpspError("EMULATOR_ROLE_UNSUPPORTED", "에뮬레이터의 Group Leader 방을 나와 Join Group을 선택하세요.")
        if len(packets) != 1 or packets[0][:2] != (RFU1_CONNECT_NACK, 0):
            # The barrier completed without an RFU response. The pinned core
            # may be disabled, or retain an old host-side slot. Do not guess
            # either game state or claim RFU cleanup from frontend liveness.
            raise GpspError("EMULATOR_RFU_MODE_UNPROVEN", "gpSP의 GBA Wireless Adapter 설정을 확인하세요. 적용에 필요한 게임 재로드는 직접 해주세요.")
        self._probe_unresolved = False
        self.rfu_mode_verified = True
        LOG.info("local_netplay_rfu_mode_verified port=%s", self._port)

    async def _run(self):
        try:
            await self.local.open(self._stop)
            await self._probe_mode()
            self._ready.set()
            while True:
                packet = await self.local.receive()
                kind, header, _ = _parse_rfu1(packet.payload)
                if kind == RFU1_CONNECT_REQ and header in self._retired_hosts:
                    # A cached old beacon must fail its game-side connection,
                    # not leave gpSP CONNECTING forever. Never NACK a newer
                    # admitted connection: that contradictory order is unsafe.
                    if self._generation is not None and self._generation.translator.state not in ("searching", "closed"):
                        raise GpspError("EMULATOR_CONNECT_REORDERED", "이전 방의 연결 요청이 새 연결과 겹쳤습니다.")
                    await self.local.send(_rfu1(RFU1_CONNECT_NACK, 0))
                    continue
                if (kind in (RFU1_CLIENT_SEND, RFU1_CLIENT_ACK, RFU1_DISCONNECT)
                     and header & 0xFFFF in self._retired_children):
                    continue
                generation = self._generation
                if generation is None:
                    raise GpspError("EMULATOR_RFU_UNEXPECTED", "새 방 연결 전에 예상하지 못한 RFU 데이터가 도착했습니다.")
                await generation.feed(packet)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._fail(error)

    async def discover(self, cancel):
        raise GpspError("EMULATOR_ROLE_UNSUPPORTED", "gpSP는 현재 Join Group만 지원합니다.")

    async def accept(self, offer, cancel):
        self._check()
        if self._opening is not None or self._generation is not None:
            raise GpspError("EMULATOR_GENERATION_BUSY", "이전 방 정리가 끝나지 않았습니다.")
        if offer.protocol_id != PROTOCOL:
            raise GpspError("EMULATOR_PROTOCOL_UNSUPPORTED", "상대의 통신 규격을 지원하지 않습니다.")
        if self._runner is None:
            raise GpspError("EMULATOR_NOT_PREPARED", "에뮬레이터 연결 준비가 필요합니다.")
        self._opening = asyncio.current_task()
        try:
            await self._wait(self._ready.wait(), cancel)
            # Never reuse RFU device identities within a frontend connection;
            # queued old requests cannot bind to a repeated Switch session ID.
            if self._next_id >= 65535:
                raise GpspError("EMULATOR_IDENTITIES_EXHAUSTED", "로컬 Netplay 연결을 새로 시작하세요.")
            host, child = self._next_id, self._next_id + 1
            self._next_id += 2
            generation = GpspGeneration(self, offer, host, child)
            self._generation = generation
            LOG.info("generation_prepared id=%s", offer.generation_id)
            return generation  # Core DATA must activate BEFORE game RFU ACK.
        finally:
            self._opening = None

    async def abort_opening(self):
        if self._generation is not None:
            return await self._generation.close("opening_aborted")
        return CleanupReport(self._cleanup_verified, self._cleanup_verified, self._cleanup_verified)

    async def close(self):
        if self._closing is None:
            self._closing = asyncio.create_task(self._close(), name="gpsp-endpoint-cleanup")
        return await sticky_close(self._closing)

    async def _close(self):
        self._stop.set()
        if self._opening is not None:
            self._opening.cancel()
            await asyncio.gather(self._opening, return_exceptions=True)
        if self._generation is not None:
            await self._generation.close("endpoint_stopped")
        if self._runner is not None:
            self._runner.cancel()
            await asyncio.gather(self._runner, return_exceptions=True)
        if self._probe_unresolved:
            self._cleanup_verified = False
            self._cleanup_errors.append("EMULATOR_RFUPROBE_CLEANUP_UNPROVEN")
        if self.local is not None:
            report = await self.local.close()
            if not clean(report):
                self._cleanup_verified = False
                self._cleanup_errors.append(dict(report.details))
        return CleanupReport(self._cleanup_verified, self._cleanup_verified, self._cleanup_verified,
            {"cleanup_errors": tuple(self._cleanup_errors)})


class GpspGeneration:
    def __init__(self, driver, offer, host, child):
        self.driver, self.offer, self.host, self.child = driver, offer, host, child
        self.translator = RfuTranslator(attempt_id=offer.generation_id, tunnel_epoch=host,
            child_connection_id=child.to_bytes(2, "little"), gpsp_device_id=child, gpsp_host_id=host)
        self._broadcast = self.translator.accept_advertisement(offer.setup_payload, generation=host)
        self.cadence = RfuCadence()
        self._out = asyncio.Queue(MAX_QUEUE)
        self._wake = asyncio.Event()
        self._space = asyncio.Event()
        self._lock = asyncio.Lock()
        self._advertiser = self._closing = None
        self._active = False
        self._finished = False
        self._link_ready = asyncio.Event()
        self._received = self._sent = 0
        self._advertisements = self._local_writes = 0
        self._core_enqueued = self._core_dequeued = 0
        self._gpsp_kinds = Counter()
        self._diagnostic_state = None
        self._diagnostic_due = 0.0

    def _diagnose(self, event, *, force=False):
        # Counts/types only: no advertisement, RFU bytes, names, RFU IDs or saves.
        # A completed socket write is NOT proof of gpSP/game consumption.
        state = (self.translator.state, self._link_ready.is_set(), self.translator.progress.milestone)
        now = time.monotonic()
        if not force and state == self._diagnostic_state and now < self._diagnostic_due:
            return
        self._diagnostic_state = state
        self._diagnostic_due = now + 5
        LOG.info("gpsp_rfu_progress id=%s %s", self.offer.generation_id, json.dumps({
            "event": event, "state": state[0], "link_ready": state[1],
            "advertisement_writes": self._advertisements,
            "local_writes": self._local_writes, "gpsp_packets": self._received,
            "gpsp_kinds": dict(self._gpsp_kinds), "switch_packets": self._sent,
            "core_enqueued": self._core_enqueued, "core_dequeued": self._core_dequeued,
            "core_queue": self._out.qsize(),
            "disconnected_by": self.translator.disconnected_by,
            "llsf": self.translator.progress.snapshot(),
            "cadence": self.cadence.snapshot(),
        }, sort_keys=True))

    def activate(self):
        self.driver._check()
        if self._closing is not None:
            raise GenerationEnded()
        if not self._active:
            self._active = True
            for action in self.translator.start():
                self._enqueue(action)
            self._diagnose("activated", force=True)
            self._advertiser = asyncio.create_task(self._advertise(), name="gpsp-room-advertisement")

    def _enqueue(self, action):
        try:
            self._out.put_nowait(LinkPacket(self.offer.generation_id, PROTOCOL, action.payload, action.flags))
            self._core_enqueued += 1
            self._wake.set()
        except asyncio.QueueFull as error:
            raise GpspError("EMULATOR_QUEUE_FULL", "RFU 송신 대기열이 가득 찼습니다.") from error

    async def _actions(self, actions, *, paced=True):
        if paced:
            actions = self.cadence.admit(actions)
        for action in actions:
            if action.destination == "tunnel":
                while self._out.full() and self._closing is None:
                    self._space.clear()
                    await self.driver._wait(self._space.wait())
                if self._closing is not None:
                    return
                self.driver._check()
                self._enqueue(action)
            else:
                await self.driver.local.send(action.payload, peer_id=action.peer_id)
                self._local_writes += 1
                if action.classification == "broadcast":
                    self._advertisements += 1
                    if self._advertisements == 1:
                        self._diagnose("first_advertisement_write", force=True)

    async def _advertise(self):
        try:
            while not self._finished:
                async with self._lock:
                    if self.translator.state == "searching":
                        await self._actions(self._broadcast)
                    await self._actions(self.cadence.poll(), paced=False)
                    self._diagnose("periodic")
                await asyncio.sleep(.1)  # Beacon cadence, never a discovery timeout.
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._diagnose("advertiser_failed", force=True)
            self.driver._fail(error)

    async def feed(self, packet):
        # Cleanup holds _lock while awaiting the ordered Netplay barrier.
        # Keep draining retired traffic so a full reader cannot hide its PONG.
        if self._closing is not None:
            return
        async with self._lock:
            if self._closing is not None:
                return
            if not self._active:
                raise GpspError("EMULATOR_DATA_BEFORE_ACTIVE", "새 방 준비 전에 RFU 데이터가 도착했습니다.")
            self._received += 1
            kind = int.from_bytes(packet.payload[4:8], "big")
            name = _RFU_KIND_NAMES[kind] if kind < len(_RFU_KIND_NAMES) else "invalid"
            self._gpsp_kinds[name] += 1
            try:
                actions = self.translator.from_core(packet.payload, peer_id=packet.peer_id, sequence=self._received)
                await self._actions(actions)
                if self._closing is not None:
                    return
                if any(action.classification == "child_transfer" for action in actions):
                    self._link_ready.set()
                self._finish_if_closed()
            finally:
                self._diagnose("gpsp_packet", force=self._gpsp_kinds[name] == 1)

    async def send(self, packet):
        self.driver._check()
        async with self._lock:
            if (not self._active or self._closing is not None or
                packet.generation_id != self.offer.generation_id or packet.protocol_id != PROTOCOL):
                raise GpspError("EMULATOR_GENERATION_STALE", "이전 방의 데이터를 차단했습니다.")
            if self._finished:
                # Local RFU close can precede in-flight peer DATA. Retire it;
                # receive() still drains our final disconnect before Core CLOSE.
                return
            self._sent += 1
            try:
                actions = self.translator.from_switch(packet.payload, flags=packet.flags,
                    generation=self.host, sequence=self._sent)
                await self._actions(actions)
                self._finish_if_closed()
            finally:
                self._diagnose("switch_packet", force=self._sent == 1)

    def _finish_if_closed(self):
        if self.translator.state == "closed":
            self._finished = True
            self.driver._retired_hosts.add(self.host)
            self.driver._retired_children.add(self.child)
            self._wake.set()

    async def receive(self):
        # Drain the final GBA disconnect before signaling normal completion to
        # Core. Core may then cancel other pumps and emit GENERATION_CLOSE.
        while True:
            self.driver._check()
            if not self._out.empty():
                self._core_dequeued += 1
                packet = self._out.get_nowait()
                self._space.set()
                return packet
            if self._finished:
                raise GenerationEnded()
            self._wake.clear()
            await self.driver._wait(self._wake.wait())

    async def wait_ended(self):
        # Normal completion belongs to receive(), after final outbound data.
        # Failures remain observable even when no local packet is queued.
        await self.driver.wait_failed()

    async def wait_link_ready(self):
        await self.driver._wait(self._link_ready.wait())

    async def close(self, outcome):
        if self._closing is None:
            self._closing = asyncio.create_task(self._close(outcome), name="gpsp-generation-cleanup")
            # Wake a producer holding _lock before cleanup needs that lock.
            self._space.set()
        return await sticky_close(self._closing)

    async def _close(self, outcome):
        if self._advertiser is not None:
            self._advertiser.cancel()
            await asyncio.gather(self._advertiser, return_exceptions=True)
        errors = []
        async with self._lock:
            self.cadence.close()
            try:
                # NACK retires a CONNECTING core; DISCONNECT retires a CLIENT.
                # A stream loss cannot prove callback delivery: fail closed.
                await self.driver.local.send(_rfu1(RFU1_CONNECT_NACK, 0))
                await self.driver.local.send(_rfu1(RFU1_DISCONNECT, self.child))
                await self.driver.local.barrier()
            except Exception as error:
                errors.append(getattr(error, "code", type(error).__name__))
            while not self._out.empty():
                self._out.get_nowait()
            self.driver._retired_hosts.add(self.host)
            self.driver._retired_children.add(self.child)
            self._finished = True
            self._wake.set()
            self._active = False
            if errors:
                self.driver._cleanup_verified = False
                self.driver._cleanup_errors.extend(errors)
            LOG.info("generation_closed id=%s outcome=%s clean=%s sent=%s received=%s",
                self.offer.generation_id, outcome, not errors, self._sent, self._received)
            self._diagnose("closed", force=True)
            if self.driver._generation is self:
                self.driver._generation = None
        return CleanupReport(not errors, not errors, not errors,
            {"outcome": outcome, "cleanup_errors": tuple(errors)})
