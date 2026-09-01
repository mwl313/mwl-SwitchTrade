"""Bounded application-session evidence shared by production processes."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from typing import Any, Callable

from switchtrade.diagnostics import _redact, redact_text


SESSION_ID_ENV = "SWITCHTRADE_APP_SESSION_ID"
SESSION_PATH_ENV = "SWITCHTRADE_SESSION_WSL_PATH"
LINE_LIMIT = 16 * 1024
EVENT_FILE_LIMIT = 8 * 1024 * 1024


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _event_file(component: str) -> str:
    if "endpoint" in component:
        return "endpoint-events.jsonl"
    if component in {"control", "control-api", "service", "connection-service"}:
        return "service-events.jsonl"
    return "wrapper-events.jsonl"


class ApplicationEvidence:
    """One process-local writer for its component-owned application-session file."""

    def __init__(self, component: str, session_id: str, session_path: str | Path):
        self.component = component
        self.session_id = session_id
        self.root = Path(session_path)
        self.root.mkdir(parents=True, exist_ok=True)
        self.events_path = self.root / _event_file(component)
        self._lock = threading.Lock()

    @classmethod
    def from_environment(cls, component: str) -> "ApplicationEvidence | None":
        session_id = os.environ.get(SESSION_ID_ENV, "")
        session_path = os.environ.get(SESSION_PATH_ENV, "")
        if not session_id or not session_path:
            return None
        return cls(component, session_id, session_path)

    def event(self, event: str, *, run_id: str | None = None,
              gate: str | None = None, code: str | None = None, **fields: Any) -> None:
        record = _redact({
            "schema": "application-event.v1",
            "app_session_id": self.session_id,
            "run_id": run_id or "not-created",
            "component": self.component,
            "event": event,
            "utc": _utc(),
            "process_monotonic_ms": round(time.monotonic() * 1000),
            "pid": os.getpid(),
            "gate": gate,
            "code": code,
            **fields,
        })
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        if len(line) > LINE_LIMIT:
            line = json.dumps(_redact({
                "schema": "application-event.v1",
                "app_session_id": self.session_id,
                "run_id": run_id or "not-created",
                "component": self.component,
                "event": event,
                "utc": _utc(),
                "process_monotonic_ms": round(time.monotonic() * 1000),
                "pid": os.getpid(),
                "gate": gate,
                "code": code,
                "truncated": True,
                "original_sha256": hashlib.sha256(line.encode("utf-8")).hexdigest(),
            }), ensure_ascii=False, separators=(",", ":"))
        encoded = (line + "\n").encode("utf-8")
        with self._lock:
            try:
                size = self.events_path.stat().st_size
            except FileNotFoundError:
                size = 0
            if size + len(encoded) > EVENT_FILE_LIMIT:
                marker = self.events_path.with_suffix(self.events_path.suffix + ".truncated")
                if not marker.exists():
                    marker.write_text("TRUNCATED: event file reached 8 MiB\n", encoding="utf-8")
                return
            with self.events_path.open("ab", buffering=0) as stream:
                stream.write(encoded)

    def write_failure_summary(self, summary: dict) -> Path:
        target = self.root / "failure-summary.v1.json"
        temporary = target.with_suffix(".json.tmp")
        value = {
            "schema": "failure-summary.v1",
            "app_session_id": self.session_id,
            **summary,
        }
        temporary.write_text(
            json.dumps(_redact(value), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(target)
        return target

    def capture_wsl_snapshot(
            self, stage: str, *, selected_usb_identity: str = "unknown",
            runner: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> Path | None:
        """Capture bounded facts; evidence failure never changes the functional outcome."""
        output_path = self.root / f"wsl-{stage}.json"
        command = [
            "sh", "-lc",
            "printf '==kernel==\\n'; uname -r; "
            "printf '==modules==\\n'; lsmod | grep -E 'mac80211|cfg80211|rtl8|rtw|mt76' || true; "
            "printf '==usb==\\n'; lsusb || true; "
            "printf '==radio==\\n'; iw dev 2>&1 || true; "
            "printf '==phy==\\n'; find /sys/class/ieee80211 -maxdepth 2 -type l -print 2>/dev/null || true; "
            "printf '==dmesg==\\n'; dmesg --color=never 2>&1 | "
            "grep -Ei 'usb|wlan|rtl|rtw|cfg80211|mac80211|firmware|inactive port' | tail -n 120 || true",
        ]
        try:
            completed = runner(command, capture_output=True, text=True, timeout=2, check=False)
            raw = (completed.stdout or "") + (completed.stderr or "")
            payload = {
                "schema": "wsl-evidence.v1",
                "app_session_id": self.session_id,
                "stage": stage,
                "captured_utc": _utc(),
                "selected_usb_hash": hashlib.sha256(
                    selected_usb_identity.encode("utf-8")).hexdigest()[:16],
                "command_exit_code": completed.returncode,
                "evidence": redact_text(raw[-256_000:]),
            }
            output_path.write_text(
                json.dumps(_redact(payload), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8")
            return output_path
        except (OSError, subprocess.SubprocessError) as error:
            self.event(
                "evidence_capture_failed", gate=stage, code="EVIDENCE_CAPTURE_FAILED",
                message=str(error))
            return None
