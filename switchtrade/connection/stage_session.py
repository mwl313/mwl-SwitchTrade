"""Thread owner that keeps one admitted Direct A/B LDN context alive for C and D."""

from __future__ import annotations

from dataclasses import dataclass
import threading


@dataclass(frozen=True)
class StageResources:
    network: object
    transport: object
    advertisement: bytes


class StageSessionError(RuntimeError):
    """Preserve the stable failure identity returned by a Direct A/B stage."""

    def __init__(self, code: str, gate: str, message: str,
                 last_passed_gate: str | None = None):
        super().__init__(message)
        self.code = code
        self.gate = gate
        self.message = message
        self.last_passed_gate = last_passed_gate


class StageSession:
    """Run one Direct stage once; ``stop`` is the sole LDN-context exit owner."""

    def __init__(self, stage: object, *, timeout: float | None = None, stop_timeout: float = 15):
        if (timeout is not None and timeout <= 0) or stop_timeout <= 0:
            raise ValueError("stage session timeout must be positive")
        self.stage = stage
        self.timeout = timeout
        self.stop_timeout = stop_timeout
        self.resources: StageResources | None = None
        self.report: dict | None = None
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._done = threading.Event()
        self._thread: threading.Thread | None = None
        self._error: BaseException | None = None
        self._trio_token = None
        self._cancel_scope = None
        self._trio_ready = threading.Event()
        self._stop_error: BaseException | None = None
        stage.session_handler = self._hold

    async def _hold(self, network: object, transport: object, advertisement: bytes) -> None:
        import trio

        self.resources = StageResources(network, transport, bytes(advertisement))
        self._ready.set()
        await trio.to_thread.run_sync(self._stop.wait, abandon_on_cancel=True)

    def start(self) -> "StageSession":
        if self._thread is not None:
            raise RuntimeError("stage session was already started")
        self._thread = threading.Thread(
            target=self._run, name="switchtrade-direct-stage", daemon=True)
        self._thread.start()
        return self

    def _run(self) -> None:
        try:
            import trio

            async def run_stage():
                self._trio_token = trio.lowlevel.current_trio_token()
                with trio.CancelScope() as scope:
                    self._cancel_scope = scope
                    self._trio_ready.set()
                    result = await self.stage.run()
                if scope.cancelled_caught:
                    raise StageSessionError(
                        "DIRECT_STAGE_CANCELLED", "DIRECT_STAGE_READY",
                        "direct stage was cancelled without a cleanup report",
                    )
                return result

            result = trio.run(run_stage)
            self.report = result[0] if isinstance(result, tuple) else result
        except BaseException as error:
            self._error = error
        finally:
            self._trio_ready.set()
            self._done.set()
            self._ready.set()

    def wait_ready(self) -> StageResources:
        if not self._ready.wait(self.timeout):
            raise StageSessionError(
                "DIRECT_STAGE_READY_TIMEOUT", "DIRECT_STAGE_READY",
                "direct stage did not reach its sustained-session checkpoint",
            )
        if self.resources is not None:
            return self.resources
        if self._error is not None:
            raise self._error
        failure = self.report.get("failure") if isinstance(self.report, dict) else None
        if isinstance(failure, dict):
            raise StageSessionError(
                str(failure.get("code") or "DIRECT_STAGE_FAILED"),
                str(failure.get("gate") or "DIRECT_STAGE_READY"),
                str(failure.get("message") or "direct stage failed before readiness"),
                str(self.report["last_passed_gate"])
                if self.report.get("last_passed_gate") is not None else None,
            )
        raise StageSessionError(
            "DIRECT_STAGE_FAILED", "DIRECT_STAGE_READY",
            "direct stage failed before readiness",
        )

    def stop(self) -> None:
        if self._thread is None:
            if self._stop_error is not None:
                raise self._stop_error
            return
        try:
            self._stop.set()
            if self.resources is None and self._trio_ready.wait(self.stop_timeout) and self._trio_token is not None and self._cancel_scope is not None:
                try:
                    import trio
                    trio.from_thread.run_sync(self._cancel_scope.cancel, trio_token=self._trio_token)
                except RuntimeError:
                    pass
            self._thread.join(self.stop_timeout)
            if self._thread.is_alive():
                raise RuntimeError("direct stage did not release its LDN context")
            self._thread = None
            if self._error is not None:
                raise RuntimeError("direct stage failed during LDN teardown") from self._error
            if not isinstance(self.report, dict):
                raise RuntimeError("direct stage did not report LDN teardown")
            cleanup = self.report.get("cleanup")
            if (
                not isinstance(cleanup, dict)
                or cleanup.get("ldn_context_released") is not True
                or cleanup.get("radio_quiescent") is not True
                or cleanup.get("ap_stop_timed_out", False) is not False
            ):
                raise RuntimeError("direct stage did not prove LDN context cleanup")
        except BaseException as error:
            self._stop_error = error
            raise


__all__ = ["StageResources", "StageSession", "StageSessionError"]
