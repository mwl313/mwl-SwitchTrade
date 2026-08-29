"""Structured per-run diagnostics and privacy-aware support bundles."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import secrets
import shutil
import subprocess
import threading
from typing import Any
import zipfile


RUN_ID = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{8}$")
SENSITIVE_NAMES = (
    "password", "passcode", "passphrase", "secret", "token", "master_key", "prod.keys",
    "session_id", "room_code",
)
TEXT_SECRETS = (
    (re.compile(r"(?i)\bauthorization\s*[:=]\s*bearer\s+[^\s,;\"']+"),
     "Authorization: Bearer <redacted>"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer <redacted>"),
    (re.compile(
        r"(?i)\b(member_token|reconnect_token)\b\s*[\"']?\s*[:=]\s*[\"']?[^\s,;}\"']+"
    ), r"\1=<redacted>"),
    (re.compile(r"(?i)\b(pass(?:word|code|phrase)|token|secret)\s*[=:]\s*\S+"), r"\1=<redacted>"),
    (re.compile(r"(?i)\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b"), "<redacted-mac>"),
)


def default_runs_root() -> Path:
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "SwitchTrade" / "runs"
    state = os.environ.get("XDG_STATE_HOME")
    return (Path(state) if state else Path.home() / ".local" / "state") / "switchtrade" / "runs"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _redact(value: Any, name: str = "") -> Any:
    if value is None:
        return None
    if any(fragment in name.lower() for fragment in SENSITIVE_NAMES):
        return "<redacted>"
    if isinstance(value, dict):
        return {str(key): _redact(item, str(key)) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    if isinstance(value, bytes):
        return {"length": len(value), "sha256": hashlib.sha256(value).hexdigest()}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_text(value: str) -> str:
    """Redact common credentials and device identifiers from command output."""
    for pattern, replacement in TEXT_SECRETS:
        value = pattern.sub(replacement, value)
    return value


def _bounded_support_text(path: Path, limit: int = 256_000) -> str:
    """Read a bounded UTF-8 tail so a noisy child cannot inflate a support bundle."""
    try:
        with path.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            size = stream.tell()
            stream.seek(max(0, size - limit))
            data = stream.read(limit)
    except OSError:
        return ""
    prefix = f"[truncated {size - len(data)} bytes]\n" if size > len(data) else ""
    return redact_text(prefix + data.decode("utf-8", errors="replace"))


def _git_commit(repo: Path) -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
            capture_output=True, text=True, timeout=2,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


class RunLogger:
    def __init__(self, component: str, runs_root: str | Path | None = None, metadata: dict | None = None):
        self.run_id = f"{_utc_now():%Y%m%dT%H%M%SZ}-{secrets.token_hex(4)}"
        self.root = Path(runs_root) if runs_root else default_runs_root()
        self.run_dir = self.root / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=False)
        self._lock = threading.Lock()
        self._events = self.run_dir / "events.jsonl"
        self._console = self.run_dir / "console.log"
        repo = Path(__file__).resolve().parents[1]
        base = {
            "run_id": self.run_id,
            "component": component,
            "started_utc": _utc_now().isoformat(),
            "application_commit": _git_commit(repo),
            "platform": platform.platform(),
            "python": platform.python_version(),
        }
        base.update(metadata or {})
        (self.run_dir / "metadata.json").write_text(
            json.dumps(_redact(base), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        self.event("run_started", component=component)

    def event(self, event: str, level: str = "info", **fields: Any) -> None:
        record = _redact({
            "timestamp_utc": _utc_now().isoformat(),
            "run_id": self.run_id,
            "level": level,
            "event": event,
            **fields,
        })
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        readable = f"{record['timestamp_utc']} {level.upper():7} {event}"
        if fields:
            readable += " " + json.dumps(_redact(fields), ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            with self._events.open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")
            with self._console.open("a", encoding="utf-8") as stream:
                stream.write(readable + "\n")

    def close(self, outcome: str = "stopped") -> None:
        self.event("run_finished", outcome=outcome)

    def support_bundle(self, destination: str | Path | None = None,
                       summary: dict | None = None,
                       related_run_ids: list[str] | None = None) -> Path:
        destination = Path(destination) if destination else self.root / f"support-{self.run_id}.zip"
        entries: list[tuple[str, Path]] = [
            (name, self.run_dir / name)
            for name in ("metadata.json", "events.jsonl", "console.log")
        ]
        for path in sorted(self.run_dir.glob("diagnostic-*.txt")):
            entries.append((path.name, path))
        if (self.run_dir / "diagnostic-report.json").is_file():
            entries.append(("diagnostic-report.json", self.run_dir / "diagnostic-report.json"))
        diagnostic_root = self.run_dir / "hardware-diagnostics"
        if diagnostic_root.is_dir():
            for run_dir in sorted(diagnostic_root.iterdir()):
                if (not run_dir.is_dir() or run_dir.is_symlink() or
                        not RUN_ID.fullmatch(run_dir.name)):
                    continue
                for name in ("metadata.json", "events.jsonl", "console.log",
                             "diagnostic-report.json"):
                    path = run_dir / name
                    if path.is_file() and not path.is_symlink():
                        entries.append((path.relative_to(self.run_dir).as_posix(), path))
                for path in sorted(run_dir.glob("diagnostic-*.txt")):
                    if path.is_file() and not path.is_symlink():
                        entries.append((path.relative_to(self.run_dir).as_posix(), path))
        production_root = self.run_dir / "production-diagnostics"
        if production_root.is_dir() and not production_root.is_symlink():
            for run_dir in sorted(production_root.iterdir()):
                report = run_dir / "production-diagnostic-report.json"
                if (run_dir.is_dir() and not run_dir.is_symlink() and report.is_file() and
                        not report.is_symlink()):
                    entries.append((report.relative_to(self.run_dir).as_posix(), report))
        launch_root = self.run_dir / "endpoint-launches"
        if launch_root.is_dir() and not launch_root.is_symlink():
            allowed_launch_file = re.compile(
                r"^[0-9a-f]{32}\.(?:json|out\.log|err\.log)$")
            for path in sorted(launch_root.iterdir()):
                if (path.is_file() and not path.is_symlink() and
                        allowed_launch_file.fullmatch(path.name)):
                    entries.append((path.relative_to(self.run_dir).as_posix(), path))
        for run_id in dict.fromkeys(related_run_ids or []):
            if not RUN_ID.fullmatch(run_id) or run_id == self.run_id:
                continue
            run_dir = self.root / run_id
            if not run_dir.is_dir() or run_dir.is_symlink():
                continue
            for name in ("metadata.json", "events.jsonl", "console.log"):
                path = run_dir / name
                if path.is_file() and not path.is_symlink():
                    entries.append((f"related-runs/{run_id}/{name}", path))
        manifest = {
            "run_id": self.run_id,
            "created_utc": _utc_now().isoformat(),
            "contents": [name for name, _path in entries],
            "privacy": "Known secret fields are redacted. Review before sharing.",
        }
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for name, path in entries:
                if path.is_file():
                    bundle.writestr(name, _bounded_support_text(path))
            bundle.writestr("privacy-manifest.json", json.dumps(manifest, indent=2) + "\n")
            if summary is not None:
                bundle.writestr(
                    "runtime-summary.json",
                    json.dumps(_redact(summary), ensure_ascii=False, indent=2) + "\n",
                )
        self.event("support_bundle_created", path=destination)
        return destination


def rotate_runs(root: str | Path, keep: int = 20) -> list[Path]:
    """Remove only old, recognized run directories directly below *root*."""
    root = Path(root).resolve()
    candidates = sorted(
        (path for path in root.iterdir() if path.is_dir() and RUN_ID.fullmatch(path.name)),
        key=lambda path: path.name,
        reverse=True,
    ) if root.is_dir() else []
    removed = []
    for path in candidates[max(0, keep):]:
        if path.resolve().parent != root:
            raise RuntimeError(f"refusing to rotate path outside run root: {path}")
        shutil.rmtree(path)
        removed.append(path)
    return removed
