"""Thread owner that keeps one admitted Direct A/B LDN context alive for C and D."""

from __future__ import annotations

from dataclasses import dataclass
import threading


@dataclass(frozen=True)
class StageResources:
    network: object
    transport: object
    advertisement: bytes


class StageSession:
    """Run one Direct stage once; ``stop`` is the sole LDN-context exit owner."""

    def __init__(self, stage: object, *, timeout: float = 180, stop_timeout: float = 15):
        if timeout <= 0 or stop_timeout <= 0:
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

            result = trio.run(self.stage.run)
            self.report = result[0] if isinstance(result, tuple) else result
        except BaseException as error:
            self._error = error
        finally:
            self._done.set()
            self._ready.set()

    def wait_ready(self) -> StageResources:
        if not self._ready.wait(self.timeout):
            raise TimeoutError("direct stage did not reach its sustained-session checkpoint")
        if self.resources is not None:
            return self.resources
        if self._error is not None:
            raise RuntimeError("direct stage failed before readiness") from self._error
        failure = self.report.get("failure") if isinstance(self.report, dict) else None
        code = failure.get("code") if isinstance(failure, dict) else "DIRECT_STAGE_FAILED"
        raise RuntimeError(str(code))

    def stop(self) -> None:
        if self._thread is None:
            return
        self._stop.set()
        self._thread.join(self.stop_timeout)
        if self._thread.is_alive():
            raise RuntimeError("direct stage did not release its LDN context")
        self._thread = None
        if self._error is not None:
            raise RuntimeError("direct stage failed during LDN teardown") from self._error
        if not isinstance(self.report, dict) or self.report.get("status") != "passed":
            raise RuntimeError("direct stage did not complete after LDN teardown")


__all__ = ["StageResources", "StageSession"]
