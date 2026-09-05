"""Endpoint-neutral owner for one Pair's local generation lifecycle."""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import Awaitable, Callable
from enum import StrEnum

from switchtrade.core.contracts import EndpointDriver, EndpointKind, GenerationOffer, LinkPacket, LocalGeneration, PairCredentials, PairSeat
from switchtrade.transport import FrameKind, TransportError, WireClient
from switchtrade.transport.client import BinarySocket


class SupervisorState(StrEnum):
    STARTING = "starting"
    PAIRING = "pairing"
    WAITING_FOR_PEER = "waiting_for_peer"
    PAIRED = "paired"
    DISCOVERING_LOCAL = "discovering_local"
    WAITING_FOR_OFFER = "waiting_for_offer"
    OPENING_LOCAL = "opening_local"
    GENERATION_NEGOTIATING = "generation_negotiating"
    ACTIVE = "active"
    CLOSING_GENERATION = "closing_generation"
    RECOVERING_PAIR = "recovering_pair"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


class SupervisorError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _offer_payload(offer: GenerationOffer) -> bytes:
    return json.dumps({"protocol_id": offer.protocol_id, "origin_endpoint_kind": offer.origin_endpoint_kind, "setup_payload": base64.b64encode(offer.setup_payload).decode("ascii")}, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _parse_offer(generation_id: str, payload: bytes) -> GenerationOffer:
    try:
        data = json.loads(payload)
        return GenerationOffer(generation_id, data["protocol_id"], EndpointKind(data["origin_endpoint_kind"]), base64.b64decode(data["setup_payload"], validate=True))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SupervisorError("S_OFFER_INVALID") from exc


class CoreSupervisor:
    def __init__(self, credentials: PairCredentials, driver: EndpointDriver, transport: WireClient, *, connector: Callable[[], Awaitable[BinarySocket]] | None = None, reconnect_timeout: float = 5.0) -> None:
        if credentials.seat is not transport.state.seat:
            raise SupervisorError("S_SEAT_MISMATCH")
        if reconnect_timeout <= 0:
            raise ValueError("invalid reconnect timeout")
        self.credentials, self.driver, self.transport = credentials, driver, transport
        self._connector, self._reconnect_timeout = connector, reconnect_timeout
        self.state = SupervisorState.STARTING
        self.failure: SupervisorError | None = None
        self._cancel = asyncio.Event()
        self._generation: LocalGeneration | None = None
        self._pump_tasks: set[asyncio.Task[None]] = set()
        self._lock = asyncio.Lock()
        self._prepared = False
        self._blocked = False
        self._stop_started = False
        self._discarded_remote_packets = 0

    @property
    def pair_code(self) -> str | None:
        return self.credentials.code if self.credentials.seat is PairSeat.HOST else None

    @property
    def generation_id(self) -> str | None:
        return self._generation.offer.generation_id if self._generation else None

    @property
    def discarded_remote_packets(self) -> int:
        return self._discarded_remote_packets

    async def prepare(self) -> None:
        if self._prepared:
            return
        self._admit()
        try:
            await self.driver.prepare()
        except Exception as exc:
            raise await self._record_failure("S_ENDPOINT_FAILED") from exc
        self._prepared, self.state = True, SupervisorState.PAIRING

    async def wait_for_peer(self) -> None:
        await self.prepare()
        self.state = SupervisorState.WAITING_FOR_PEER
        while True:
            self._admit()
            try:
                await self.transport.wait_ready(timeout=0.1)
            except TransportError as exc:
                if exc.code == "T_READY_TIMEOUT":
                    continue
                if self._connector is not None:
                    await self.recover_pair()
                    continue
                raise await self._record_failure("S_TRANSPORT_FAILED") from exc
            self.state = SupervisorState.PAIRED
            return

    async def discover_local(self) -> GenerationOffer:
        if self.credentials.seat is not PairSeat.HOST:
            raise SupervisorError("S_ROLE_INVALID")
        await self.prepare()
        self._admit_generation()
        self.state = SupervisorState.DISCOVERING_LOCAL
        try:
            self._generation = await self.driver.discover(self._cancel)
        except Exception as exc:
            raise await self._record_failure("S_ENDPOINT_FAILED") from exc
        self.state = SupervisorState.WAITING_FOR_PEER
        return self._generation.offer

    async def offer_generation(self) -> None:
        if self.credentials.seat is not PairSeat.HOST:
            raise SupervisorError("S_ROLE_INVALID")
        while True:
            if self._generation is None:
                await self.discover_local()
            await self.wait_for_peer()
            if self._generation is not None:
                break
        generation = self._generation
        self.state = SupervisorState.GENERATION_NEGOTIATING
        try:
            await self.transport.send(FrameKind.GENERATION_OFFER, generation.offer.generation_id, _offer_payload(generation.offer))
            accepted = await self.transport.receive()
        except TransportError as exc:
            raise await self._fail_and_cleanup("S_TRANSPORT_FAILED") from exc
        if accepted.kind is not FrameKind.GENERATION_ACCEPT or accepted.generation_id != generation.offer.generation_id:
            raise await self._fail_and_cleanup("S_GENERATION_STALE")
        self._activate()

    async def accept_next_offer(self) -> GenerationOffer:
        if self.credentials.seat is not PairSeat.GUEST:
            raise SupervisorError("S_ROLE_INVALID")
        await self.wait_for_peer()
        self._admit_generation()
        self.state = SupervisorState.WAITING_FOR_OFFER
        try:
            frame = await self.transport.receive()
        except TransportError as exc:
            raise await self._fail_and_cleanup("S_TRANSPORT_FAILED") from exc
        if frame.kind is not FrameKind.GENERATION_OFFER:
            raise await self._fail_and_cleanup("S_OFFER_INVALID")
        try:
            offer = _parse_offer(frame.generation_id, frame.payload)
        except SupervisorError as exc:
            raise await self._fail_and_cleanup(exc.code) from exc
        self.state = SupervisorState.OPENING_LOCAL
        try:
            self._generation = await self.driver.accept(offer, self._cancel)
        except Exception as exc:
            raise await self._fail_and_cleanup("S_ENDPOINT_FAILED") from exc
        try:
            await self.transport.send(FrameKind.GENERATION_ACCEPT, offer.generation_id)
        except TransportError as exc:
            raise await self._fail_and_cleanup("S_TRANSPORT_FAILED") from exc
        self._activate()
        return offer

    async def close_generation(self, outcome: str = "closed", *, notify_peer: bool = True) -> None:
        async with self._lock:
            generation = self._generation
            if generation is None:
                return
            self.state = SupervisorState.CLOSING_GENERATION
            current = asyncio.current_task()
            tasks = tuple(task for task in self._pump_tasks if task is not current)
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            self._pump_tasks.clear()
            self._discarded_remote_packets += self.transport.discard_generation(generation.offer.generation_id)
            failure_code: str | None = None
            try:
                report = await generation.close(outcome)
                if not (report.endpoint_stopped and report.local_resources_released and report.transport_drained):
                    failure_code = "S_CLEANUP_FAILED"
            except Exception:
                failure_code = "S_CLEANUP_FAILED"
            if notify_peer and self.transport.state.active_generation == generation.offer.generation_id:
                try:
                    await self.transport.send(FrameKind.GENERATION_CLOSE, generation.offer.generation_id)
                except TransportError:
                    failure_code = failure_code or "S_TRANSPORT_FAILED"
            self._discarded_remote_packets += self.transport.discard_generation(generation.offer.generation_id)
            if failure_code:
                self._blocked = True
                raise await self._record_failure(failure_code)
            self._generation = None
            self.state = SupervisorState.FAILED if self.failure else SupervisorState.PAIRED

    async def wait_generation_end(self) -> None:
        """Wait for the active data-plane pumps and surface their terminal failure."""
        tasks = tuple(self._pump_tasks)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if self.failure is not None:
            raise self.failure

    async def stop(self) -> None:
        if self._stop_started:
            return
        self._stop_started = True
        prior_failure = self.failure
        self._cancel.set()
        self.state = SupervisorState.STOPPING
        try:
            await self.close_generation("stopped")
        except SupervisorError:
            pass
        try:
            report = await self.driver.close()
            if not (report.endpoint_stopped and report.local_resources_released and report.transport_drained):
                await self._cleanup_failed()
        except Exception:
            await self._cleanup_failed()
        try:
            await self.transport.close()
        except Exception:
            await self._cleanup_failed()
        self.state = SupervisorState.FAILED if self.failure else SupervisorState.STOPPED
        if self.failure and prior_failure is None:
            raise self.failure

    async def recover_pair(self) -> None:
        if self._connector is None:
            raise await self._record_failure("S_TRANSPORT_FAILED")
        self.state = SupervisorState.RECOVERING_PAIR
        try:
            await self.close_generation("transport_lost", notify_peer=False)
            await self.transport.close()
            socket = await asyncio.wait_for(self._connector(), self._reconnect_timeout)
            await self.transport.connect(socket)
            try:
                await self.transport.wait_ready(self._reconnect_timeout)
            except TransportError as exc:
                if exc.code != "T_READY_TIMEOUT":
                    raise
                self.state = SupervisorState.WAITING_FOR_PEER
                return
        except SupervisorError:
            raise
        except Exception as exc:
            raise await self._record_failure("S_TRANSPORT_FAILED") from exc
        self.state = SupervisorState.PAIRED

    def _activate(self) -> None:
        self.state = SupervisorState.ACTIVE
        self._pump_tasks = {asyncio.create_task(self._pump_local()), asyncio.create_task(self._pump_remote())}

    async def _pump_local(self) -> None:
        try:
            while True:
                packet = await self._generation.receive()  # type: ignore[union-attr]
                await self.transport.send(FrameKind.DATA, packet.generation_id, packet.payload, packet.flags)
        except asyncio.CancelledError:
            raise
        except TransportError:
            await self._recover_after_transport_loss()
        except Exception:
            await self._fail_and_cleanup("S_PUMP_FAILED")

    async def _pump_remote(self) -> None:
        try:
            while True:
                frame = await self.transport.receive()
                if frame.kind is FrameKind.GENERATION_CLOSE:
                    await self.close_generation("peer_closed", notify_peer=False)
                    return
                if frame.kind is not FrameKind.DATA or frame.generation_id != self.generation_id:
                    raise SupervisorError("S_GENERATION_STALE")
                await self._generation.send(LinkPacket(frame.generation_id, self._generation.offer.protocol_id, frame.payload, frame.flags))  # type: ignore[union-attr]
        except asyncio.CancelledError:
            raise
        except TransportError:
            await self._recover_after_transport_loss()
        except Exception:
            await self._fail_and_cleanup("S_PUMP_FAILED")

    def _admit(self) -> None:
        if self.failure:
            raise self.failure
        if self._cancel.is_set():
            raise SupervisorError("S_CANCELED")

    def _admit_generation(self) -> None:
        self._admit()
        if self._blocked or self._generation is not None:
            raise SupervisorError("S_NEXT_GENERATION_BLOCKED")

    async def _record_failure(self, code: str) -> SupervisorError:
        if self.failure is None:
            self.failure = SupervisorError(code)
            self.state = SupervisorState.FAILED
            self._cancel.set()
        return self.failure

    async def _cleanup_failed(self) -> SupervisorError:
        self._blocked = True
        return await self._record_failure("S_CLEANUP_FAILED")

    async def _fail_and_cleanup(self, code: str) -> SupervisorError:
        failure = await self._record_failure(code)
        try:
            await self.close_generation("failed")
        except SupervisorError:
            pass
        return failure

    async def _recover_after_transport_loss(self) -> None:
        try:
            await self.recover_pair()
        except SupervisorError:
            pass
