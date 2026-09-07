"""Read-only Windows observation. Never starts, stops, or reconfigures a frontend.

Toolhelp/process-time queries identify a running process and its loaded core;
the TCP owner table binds the accepted loopback socket to that exact process.
Files/modules are identity evidence, not proof of Netplay or RFU readiness.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import socket
import struct

from .errors import GpspError


RETROARCH_SHA256 = "81c11b6f24932bf7918f05eee8928035bff3887335fd2a081507c75e9d94d06a"
GPSP_SHA256 = "c84f619c1077a7fbae84c385df752fbeb867d301880400add7cce6a380dbd516"


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    executable: Path
    start_ticks: int


def _unsupported():
    if os.name != "nt":
        raise GpspError("GPSP_NATIVE_WINDOWS_REQUIRED", "gpSP 연결은 네이티브 Windows에서 실행하세요.")


if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    _kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    _ip = ctypes.WinDLL("iphlpapi", use_last_error=True)

    class _ProcessEntry(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("usage", wintypes.DWORD),
                    ("pid", wintypes.DWORD), ("heap", ctypes.c_size_t),
                    ("module", wintypes.DWORD), ("threads", wintypes.DWORD),
                    ("parent", wintypes.DWORD), ("priority", wintypes.LONG),
                    ("flags", wintypes.DWORD), ("exe", wintypes.WCHAR * 260)]

    class _ModuleEntry(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("module", wintypes.DWORD),
                    ("pid", wintypes.DWORD), ("global_usage", wintypes.DWORD),
                    ("process_usage", wintypes.DWORD), ("base", ctypes.c_void_p),
                    ("base_size", wintypes.DWORD), ("handle", wintypes.HMODULE),
                    ("name", wintypes.WCHAR * 256), ("path", wintypes.WCHAR * 260)]

    _kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    _kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    for prefix, entry in (("Process", _ProcessEntry), ("Module", _ModuleEntry)):
        for suffix in ("FirstW", "NextW"):
            getattr(_kernel, prefix + "32" + suffix).argtypes = [wintypes.HANDLE, ctypes.POINTER(entry)]
    _kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel.OpenProcess.restype = wintypes.HANDLE
    _kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    _kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    _ip.GetExtendedTcpTable.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD),
                                      wintypes.BOOL, wintypes.ULONG, ctypes.c_int, wintypes.ULONG]


def _query_error():
    return GpspError("EMULATOR_QUERY_FAILED", "RetroArch 실행 상태를 조회하지 못했습니다. 실행 계정과 권한을 확인하세요.")


@contextmanager
def _handle(value):
    failure = None
    try:
        yield value
    except BaseException as error:
        failure = error
        raise
    finally:
        if not _kernel.CloseHandle(value):
            if failure is not None:
                failure.add_note("EMULATOR_QUERY_HANDLE_CLOSE_FAILED")
            else:
                raise _query_error()


def _entries(pid, modules=False):
    _unsupported()
    # Module snapshots can change during DLL loading; bounded technical retry,
    # never an attempt to relaunch/recover the observed process.
    for _ in range(3):
        value = _kernel.CreateToolhelp32Snapshot(0x18 if modules else 0x02, pid)
        if value != ctypes.c_void_p(-1).value:
            break
        if ctypes.get_last_error() != 24:  # ERROR_BAD_LENGTH
            raise _query_error()
    else:
        raise _query_error()
    entry = _ModuleEntry() if modules else _ProcessEntry()
    entry.size = ctypes.sizeof(entry)
    prefix = "Module" if modules else "Process"
    with _handle(value):
        more = getattr(_kernel, prefix + "32FirstW")(value, ctypes.byref(entry))
        while more:
            yield Path(entry.path) if modules else (entry.pid, entry.exe)
            more = getattr(_kernel, prefix + "32NextW")(value, ctypes.byref(entry))
        if ctypes.get_last_error() != 18:  # ERROR_NO_MORE_FILES, not access denied.
            raise _query_error()


def _identity(pid: int) -> ProcessIdentity:
    _unsupported()
    value = _kernel.OpenProcess(0x1000 | 0x100000, False, pid)  # Query + synchronize only.
    if not value:
        if ctypes.get_last_error() == 87:
            raise GpspError("EMULATOR_EXITED", "RetroArch가 종료됐습니다. 게임을 실행한 뒤 다시 참가하세요.")
        raise _query_error()
    with _handle(value):
        status = _kernel.WaitForSingleObject(value, 0)
        if status == 0:
            raise GpspError("EMULATOR_EXITED", "RetroArch가 종료됐습니다. 게임을 실행한 뒤 다시 참가하세요.")
        if status != 258:
            raise _query_error()
        capacity = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(capacity.value)
        times = [wintypes.FILETIME() for _ in range(4)]
        if not _kernel.QueryFullProcessImageNameW(value, 0, buffer, ctypes.byref(capacity)):
            raise _query_error()
        if not _kernel.GetProcessTimes(value, *(ctypes.byref(t) for t in times)):
            raise _query_error()
        ticks = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
        return ProcessIdentity(pid, Path(os.path.normcase(buffer.value)), ticks)


def _digest(path):
    try:
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()
    except OSError as error:
        raise _query_error() from error


def _tcp_owners(local_port, remote_port):
    _unsupported()
    size = wintypes.DWORD()
    status = _ip.GetExtendedTcpTable(None, ctypes.byref(size), False, 2, 5, 0)
    if status not in (0, 122):
        raise _query_error()
    for _ in range(3):
        if not 4 <= size.value <= 4 * 1024 * 1024:
            raise _query_error()
        buffer = ctypes.create_string_buffer(size.value)
        status = _ip.GetExtendedTcpTable(buffer, ctypes.byref(size), False, 2, 5, 0)
        if status == 0:
            break
        if status != 122:
            raise _query_error()
    else:
        raise _query_error()
    count = struct.unpack_from("<I", buffer)[0]
    if 4 + count * 24 > len(buffer):
        raise _query_error()
    owners = set()
    loopback = int.from_bytes(socket.inet_aton("127.0.0.1"), "little")
    for index in range(count):
        state, local, port, remote, peer_port, pid = struct.unpack_from("<6I", buffer, 4 + index * 24)
        if (state == 5 and local == remote == loopback and socket.ntohs(port & 0xFFFF) == local_port
                and socket.ntohs(peer_port & 0xFFFF) == remote_port):
            owners.add(pid)
    return owners


class ProcessObserver:
    """Borrowed process identity only. There is deliberately no launch/close API."""
    def __init__(self, identity: ProcessIdentity, core: Path):
        self.identity = identity
        self.core = core

    @classmethod
    def select(cls, pid: int | None = None):
        _unsupported()
        if pid is not None and (type(pid) is not int or not 0 < pid <= 0xFFFFFFFF):
            raise GpspError("EMULATOR_PID_INVALID", "--emulator-pid에 올바른 RetroArch PID를 지정하세요.")
        candidates = [p for p, name in _entries(0) if name.casefold() == "retroarch.exe"]
        if pid is not None:
            if pid not in candidates:
                raise GpspError("EMULATOR_PID_NOT_FOUND", "지정한 RetroArch PID가 실행 중인지 확인하세요.")
            candidates = [pid]
        if not candidates:
            raise GpspError("RETROARCH_NOT_RUNNING", "RetroArch에서 gpSP로 게임을 실행한 뒤 다시 시도하세요.")
        if len(candidates) != 1:
            raise GpspError("RETROARCH_AMBIGUOUS", "RetroArch가 여러 개 실행 중입니다. --emulator-pid로 대상을 지정하세요.")
        identity = _identity(candidates[0])
        if _digest(identity.executable) != RETROARCH_SHA256:
            raise GpspError("RETROARCH_UNSUPPORTED_BUILD", "검증된 RetroArch 1.22.2 빌드를 사용하세요.")
        modules = tuple(_entries(identity.pid, modules=True))
        cores = [p for p in modules if p.name.casefold() == "gpsp_libretro.dll"]
        if len(cores) != 1:
            raise GpspError("GPSP_CORE_NOT_LOADED", "RetroArch에서 gpSP 코어로 게임을 실행하세요.")
        if _digest(cores[0]) != GPSP_SHA256:
            raise GpspError("GPSP_UNSUPPORTED_BUILD", "검증된 gpSP 코어 빌드를 사용하세요.")
        observer = cls(identity, cores[0])
        observer.check()
        return observer

    def check(self):
        if _identity(self.identity.pid) != self.identity:
            raise GpspError("EMULATOR_IDENTITY_CHANGED", "선택한 RetroArch가 바뀌었습니다. 실행 대상을 확인하고 다시 참가하세요.")
        if self.core not in tuple(_entries(self.identity.pid, modules=True)):
            raise GpspError("EMULATOR_CORE_CHANGED", "선택한 gpSP 코어가 종료되거나 바뀌었습니다. 게임을 확인하고 다시 참가하세요.")

    def check_connection(self, client_port: int, listener_port: int):
        self.check()
        if _tcp_owners(client_port, listener_port) != {self.identity.pid}:
            raise GpspError("EMULATOR_SOCKET_IDENTITY_MISMATCH", "선택한 RetroArch의 로컬 연결인지 확인하지 못했습니다.")
        self.check()
