"""Endpoint-neutral owner for one Pair's local generation lifecycle."""

from __future__ import annotations

import asyncio
import base64
import json
from enum import StrEnum

from switchtrade.core.contracts import EndpointDriver, EndpointKind, GenerationOffer, LinkPacket, LocalGeneration, PairCredentials, PairSeat
from switchtrade.transport import FrameKind, TransportError, WireClient


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
    def __init__(self, credentials: PairCredentials, driver: EndpointDriver, transport: WireClient) -> None:
        if credentials.seat is not transport.state.seat:
            raise SupervisorError("S_SEAT_MISMATCH")
        self.credentials, self.driver, self.transport = credentials, driver, transport
        self.state = SupervisorState.STARTING
        self.failure: SupervisorError | None = None
        self._cancel = asyncio.Event()
        self._generation: LocalGeneration | None = None
        self._pump_tasks: set[asyncio.Task[None]] = set()
        self._lock = asyncio.Lock()
        self._prepared = False
        self._blocked = False

    @property
    def pair_code(self) -> str | None:
        return self.credentials.code if self.credentials.seat is PairSeat.HOST else None

    @property
    def generation_id(self) -> str | None:
        return self._generation.offer.generation_id if self._generation else None

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
        try:
            await self.transport.wait_ready()
        except Exception as exc:
            raise await self._record_failure("S_TRANSPORT_FAILED") from exc
        self.state = SupervisorState.PAIRED

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
        if self._generation is None:
            await self.discover_local()
        await self.wait_for_peer()
        generation = self._generation
        self.state = SupervisorState.GENERATION_NEGOTIATING
        try:
            await self.transport.send(FrameKind.GENERATION_OFFER, generation.offer.generation_id, _offer_payload(generation.offer))
            accepted = await self.transport.receive()
            if accepted.kind is not FrameKind.GENERATION_ACCEPT or accepted.generation_id != generation.offer.generation_id:
                raise SupervisorError("S_GENERATION_STALE")
        except Exception as exc:
            raise await self._record_failure("S_TRANSPORT_FAILED") from exc
        self._activate()

    async def accept_next_offer(self) -> GenerationOffer:
        if self.credentials.seat is not PairSeat.GUEST:
            raise SupervisorError("S_ROLE_INVALID")
        await self.wait_for_peer()
        self._admit_generation()
        self.state = SupervisorState.WAITING_FOR_OFFER
        try:
            frame = await self.transport.receive()
            if frame.kind is not FrameKind.GENERATION_OFFER:
                raise SupervisorError("S_OFFER_INVALID")
            offer = _parse_offer(frame.generation_id, frame.payload)
            self.state = SupervisorState.OPENING_LOCAL
            self._generation = await self.driver.accept(offer, self._cancel)
            await self.transport.send(FrameKind.GENERATION_ACCEPT, offer.generation_id)
        except Exception as exc:
            raise await self._record_failure("S_ENDPOINT_FAILED") from exc
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
            report = await generation.close(outcome)
            if not (report.endpoint_stopped and report.local_resources_released and report.transport_drained):
                self._blocked = True
                raise await self._record_failure("S_CLEANUP_FAILED")
            if notify_peer and self.transport.state.active_generation == generation.offer.generation_id:
                try:
                    await self.transport.send(FrameKind.GENERATION_CLOSE, generation.offer.generation_id)
                except TransportError as exc:
                    raise await self._record_failure("S_TRANSPORT_FAILED") from exc
            self._generation = None
            self.state = SupervisorState.FAILED if self.failure else SupervisorState.PAIRED

    async def stop(self) -> None:
        if self.state is SupervisorState.STOPPED:
            return
        self._cancel.set()
        self.state = SupervisorState.STOPPING
        try:
            await self.close_generation("stopped")
            report = await self.driver.close()
            if not (report.endpoint_stopped and report.local_resources_released and report.transport_drained):
                raise SupervisorError("S_CLEANUP_FAILED")
            await self.transport.close()
        except SupervisorError as exc:
            self._blocked = True
            self.failure = self.failure or exc
            self.state = SupervisorState.FAILED
            raise
        self.state = SupervisorState.STOPPED

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

    async def _fail_and_cleanup(self, code: str) -> None:
        await self._record_failure(code)
        try:
            await self.close_generation("failed")
        except SupervisorError:
            pass
