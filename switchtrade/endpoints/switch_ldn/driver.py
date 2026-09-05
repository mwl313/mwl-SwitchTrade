"""Concrete Switch LDN endpoint boundary; Direct A/B integration follows in C2/C3."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import PurePosixPath
import re
from typing import Callable
from uuid import uuid4

from switchtrade.connection.a_stage import DirectAStage
from switchtrade.connection.stage_session import StageResources, StageSession
from switchtrade.core.contracts import (
    Cancellation,
    CleanupReport,
    EndpointCapabilities,
    EndpointKind,
    GenerationOffer,
    GenerationRole,
    LocalGeneration,
    RuntimeKind,
)

from .errors import SwitchLdnEndpointError
from .generation import LeaderGeneration


SWITCH_LDN_PROTOCOL = "switchtrade.gba-frame.v1"
_PHY = re.compile(r"phy[0-9]+$")
_IFNAME = re.compile(r"[a-zA-Z0-9_.-]{1,15}$")
_RETRYABLE_A_CODES = frozenset({"A_ROOM_NOT_OBSERVED", "A_SCAN_TIMEOUT"})


@dataclass(frozen=True)
class SwitchLdnPolicy:
    run_id: str
    release: str
    usb_id: str
    hardware_profile: str
    phy: str
    ifname: str
    keys_path: str
    retry_delay: float = 0.5
    session_timeout: float = 180
    session_stop_timeout: float = 15

    def validate(self) -> None:
        if (
            not all((self.run_id, self.release, self.usb_id, self.hardware_profile))
            or not re.fullmatch(r"[0-9a-fA-F]{4}:[0-9a-fA-F]{4}", self.usb_id)
            or not _PHY.fullmatch(self.phy)
            or not _IFNAME.fullmatch(self.ifname)
            or not PurePosixPath(self.keys_path).is_absolute()
            or not 0.5 <= self.retry_delay <= 2
            or self.session_timeout <= 0
            or self.session_stop_timeout <= 0
        ):
            raise SwitchLdnEndpointError(
                "SWITCH_ENDPOINT_POLICY_INVALID", "Switch LDN policy is invalid"
            )


def _direct_a_stage(policy: SwitchLdnPolicy) -> DirectAStage:
    return DirectAStage(
        run_id=policy.run_id,
        release=policy.release,
        phy=policy.phy,
        ifname=policy.ifname,
        keys_path=policy.keys_path,
    )


class SwitchLdnEndpointDriver:
    """Phase-B-compatible boundary for the managed-WSL Switch LDN endpoint."""

    capabilities = EndpointCapabilities(
        EndpointKind.SWITCH_LDN,
        RuntimeKind.MANAGED_WSL,
        (SWITCH_LDN_PROTOCOL,),
        (GenerationRole.ORIGIN, GenerationRole.MIRROR),
    )

    def __init__(
        self,
        policy: SwitchLdnPolicy | None = None,
        *,
        stage_factory: Callable[[SwitchLdnPolicy], object] = _direct_a_stage,
        session_factory: Callable[..., StageSession] = StageSession,
    ) -> None:
        self._policy = policy
        self._stage_factory = stage_factory
        self._session_factory = session_factory
        self._prepared = False
        self._generation: LeaderGeneration | None = None
        self._cleanup_verified = True

    async def prepare(self) -> None:
        if self._policy is None:
            raise SwitchLdnEndpointError(
                "SWITCH_ENDPOINT_POLICY_INVALID", "Switch LDN policy is required"
            )
        self._policy.validate()
        if self._generation is not None:
            raise SwitchLdnEndpointError("SWITCH_ENDPOINT_BUSY", "Switch LDN generation is active")
        if not self._cleanup_verified:
            raise SwitchLdnEndpointError(
                "SWITCH_ENDPOINT_CLEANUP_FAILED", "prior Switch LDN cleanup is unverified"
            )
        self._prepared = True

    async def discover(self, cancel: Cancellation) -> LocalGeneration:
        if not self._prepared or self._policy is None:
            raise SwitchLdnEndpointError(
                "SWITCH_ENDPOINT_POLICY_INVALID", "Switch LDN driver is not prepared"
            )
        if self._generation is not None:
            raise SwitchLdnEndpointError("SWITCH_ENDPOINT_BUSY", "Switch LDN generation is active")
        if not self._cleanup_verified:
            raise SwitchLdnEndpointError(
                "SWITCH_ENDPOINT_CLEANUP_FAILED", "prior Switch LDN cleanup is unverified"
            )
        while True:
            if cancel.is_set():
                raise asyncio.CancelledError
            session = self._session_factory(
                self._stage_factory(self._policy),
                timeout=self._policy.session_timeout,
                stop_timeout=self._policy.session_stop_timeout,
            ).start()
            try:
                resources = await self._wait_ready_or_cancel(session, cancel)
            except asyncio.CancelledError:
                await self._stop_session(session)
                raise
            except BaseException as failure:
                cleanup_ok = await self._stop_session(session)
                if cancel.is_set():
                    raise asyncio.CancelledError from failure
                if not cleanup_ok or getattr(failure, "code", None) not in _RETRYABLE_A_CODES:
                    raise
                await self._backoff(cancel)
                continue
            return self._leader_generation(session, resources)

    async def accept(
        self, offer: GenerationOffer, cancel: Cancellation
    ) -> LocalGeneration:
        del offer, cancel
        raise NotImplementedError("Switch LDN acceptance is implemented in C3")

    async def close(self) -> CleanupReport:
        if self._generation is None:
            if not self._cleanup_verified:
                return CleanupReport(
                    False,
                    False,
                    False,
                    {"endpoint_kind": EndpointKind.SWITCH_LDN, "cleanup": "unverified"},
                )
            return CleanupReport(True, True, True, {"endpoint_kind": EndpointKind.SWITCH_LDN})
        return await self._generation.close("driver_stop")

    async def _wait_ready_or_cancel(
        self, session: StageSession, cancel: Cancellation
    ) -> StageResources:
        ready_task = asyncio.create_task(asyncio.to_thread(session.wait_ready))
        cancel_task = asyncio.create_task(cancel.wait())
        try:
            done, _pending = await asyncio.wait(
                (ready_task, cancel_task), return_when=asyncio.FIRST_COMPLETED
            )
            if cancel_task in done or cancel.is_set():
                raise asyncio.CancelledError
            return ready_task.result()
        finally:
            for task in (ready_task, cancel_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(ready_task, cancel_task, return_exceptions=True)

    async def _stop_session(self, session: StageSession) -> bool:
        try:
            await asyncio.to_thread(session.stop)
        except BaseException:
            self._cleanup_verified = False
            return False
        return True

    async def _backoff(self, cancel: Cancellation) -> None:
        assert self._policy is not None
        try:
            await asyncio.wait_for(cancel.wait(), timeout=self._policy.retry_delay)
        except TimeoutError:
            return
        raise asyncio.CancelledError

    def _leader_generation(
        self, session: StageSession, resources: StageResources
    ) -> LeaderGeneration:
        offer = GenerationOffer(
            uuid4().hex,
            SWITCH_LDN_PROTOCOL,
            EndpointKind.SWITCH_LDN,
            resources.advertisement,
        )
        generation = LeaderGeneration(offer, session, self._generation_closed)
        self._generation = generation
        return generation

    def _generation_closed(self, cleanup_verified: bool) -> None:
        self._generation = None
        self._cleanup_verified = cleanup_verified
