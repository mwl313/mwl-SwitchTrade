"""Small cross-platform process lock used by production entry points."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile


class AlreadyRunningError(RuntimeError):
    pass


class SingleInstanceLock:
    """Hold a one-byte OS lock for the lifetime of one service process."""

    def __init__(self, name: str, directory: str | Path | None = None):
        root = Path(directory) if directory else Path(
            os.environ.get("SWITCHTRADE_RUNTIME_DIR", tempfile.gettempdir())
        )
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / f"switchtrade-{name}.lock"
        self._stream = None

    def acquire(self) -> "SingleInstanceLock":
        stream = self.path.open("a+b")
        try:
            stream.seek(0)
            if stream.read(1) == b"":
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError, PermissionError) as error:
            stream.close()
            raise AlreadyRunningError(f"SwitchTrade {self.path.stem} is already running") from error
        self._stream = stream
        return self

    def close(self) -> None:
        if self._stream is None:
            return
        try:
            if os.name == "nt":
                import msvcrt
                self._stream.seek(0)
                msvcrt.locking(self._stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._stream.fileno(), fcntl.LOCK_UN)
        finally:
            self._stream.close()
            self._stream = None

    def __enter__(self) -> "SingleInstanceLock":
        return self.acquire()

    def __exit__(self, *_args) -> None:
        self.close()
