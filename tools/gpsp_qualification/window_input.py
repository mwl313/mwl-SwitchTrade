"""Public key messages to one harness-owned SDL window; never product code.

No foreground focus, global SendInput, process injection, or memory access.
Every message rechecks both the Popen handle and the window's owning PID.
"""
import ctypes
from ctypes import wintypes
import msvcrt
import os
import subprocess
import time
import uuid


class PrivateDesktop:
    """An invisible test desktop, never switched onto the user's display."""
    def __init__(self):
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.user32.CreateDesktopW.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p,
                                              ctypes.c_void_p, wintypes.DWORD,
                                              wintypes.DWORD, ctypes.c_void_p]
        self.user32.CreateDesktopW.restype = wintypes.HANDLE
        self.user32.GetThreadDesktop.argtypes = [wintypes.DWORD]
        self.user32.GetThreadDesktop.restype = wintypes.HANDLE
        self.user32.SetThreadDesktop.argtypes = [wintypes.HANDLE]
        self.user32.CloseDesktop.argtypes = [wintypes.HANDLE]
        self.previous = self.user32.GetThreadDesktop(ctypes.windll.kernel32.GetCurrentThreadId())
        self.name = "SwitchTradeP0_" + uuid.uuid4().hex
        self.handle = self.user32.CreateDesktopW(self.name, None, None, 0, 0x10000000, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        if not self.user32.SetThreadDesktop(self.handle):
            error = ctypes.WinError(ctypes.get_last_error())
            self.user32.CloseDesktop(self.handle)
            raise error

    def close(self):
        return bool(self.user32.SetThreadDesktop(self.previous) and self.user32.CloseDesktop(self.handle))


class OwnedProcess:
    """CreateProcess with lpDesktop, which subprocess.STARTUPINFO does not expose."""
    def __init__(self, argv, *, desktop, log, cwd):
        class Startup(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("reserved", wintypes.LPWSTR),
                        ("desktop", wintypes.LPWSTR), ("title", wintypes.LPWSTR),
                        *[(name, wintypes.DWORD) for name in
                          ("x", "y", "width", "height", "xchars", "ychars", "fill", "flags")],
                        ("show", wintypes.WORD), ("reserved_size", wintypes.WORD),
                        ("reserved_ptr", ctypes.c_void_p), ("stdin", wintypes.HANDLE),
                        ("stdout", wintypes.HANDLE), ("stderr", wintypes.HANDLE)]
        class Information(ctypes.Structure):
            _fields_ = [("process", wintypes.HANDLE), ("thread", wintypes.HANDLE),
                        ("pid", wintypes.DWORD), ("tid", wintypes.DWORD)]
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateProcessW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR,
            ctypes.c_void_p, ctypes.c_void_p, wintypes.BOOL, wintypes.DWORD,
            ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(Startup), ctypes.POINTER(Information)]
        self.kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        self.kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        startup, info = Startup(), Information()
        startup.cb = ctypes.sizeof(startup)
        startup.desktop = "winsta0\\" + desktop.name
        startup.flags, startup.show = 0x101, 1
        output_handle = msvcrt.get_osfhandle(log.fileno())
        with open(os.devnull, "rb") as null:
            input_handle = msvcrt.get_osfhandle(null.fileno())
            os.set_handle_inheritable(input_handle, True)
            os.set_handle_inheritable(output_handle, True)
            startup.stdin, startup.stdout, startup.stderr = input_handle, output_handle, output_handle
            try:
                if not self.kernel.CreateProcessW(argv[0], ctypes.create_unicode_buffer(subprocess.list2cmdline(argv)),
                    None, None, True, 0, None, str(cwd), ctypes.byref(startup), ctypes.byref(info)):
                    raise ctypes.WinError(ctypes.get_last_error())
            finally:
                os.set_handle_inheritable(output_handle, False)
        self.kernel.CloseHandle(info.thread)
        self.handle, self.pid, self.returncode = info.process, info.pid, None

    def poll(self):
        code = wintypes.DWORD()
        if not self.kernel.GetExitCodeProcess(self.handle, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        self.returncode = None if code.value == 259 else code.value
        return self.returncode

    def wait(self, timeout):
        result = self.kernel.WaitForSingleObject(self.handle, int(timeout * 1000))
        if result == 258:
            raise subprocess.TimeoutExpired("owned RetroArch", timeout)
        if result != 0:
            raise ctypes.WinError(ctypes.get_last_error())
        return self.poll()

    def terminate(self):
        if not self.kernel.TerminateProcess(self.handle, 1):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.poll() is None:
            return False
        return bool(self.kernel.CloseHandle(self.handle))


class WindowInput:
    def __init__(self, process, desktop):
        self.process = process
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        self.user32.PostMessageW.restype = wintypes.BOOL
        self.callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        self.user32.EnumDesktopWindows.argtypes = [wintypes.HANDLE, self.callback_type, wintypes.LPARAM]
        self.hwnd = None
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            windows = []
            @self.callback_type
            def visit(hwnd, _):
                pid = wintypes.DWORD()
                self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                title = ctypes.create_unicode_buffer(512)
                self.user32.GetWindowTextW(hwnd, title, len(title))
                if pid.value == process.pid and "RetroArch" in title.value:
                    windows.append(hwnd)
                return True
            if not self.user32.EnumDesktopWindows(desktop.handle, visit, 0):
                raise ctypes.WinError(ctypes.get_last_error())
            if len(windows) == 1:
                self.hwnd = windows[0]
                self.post(0x06, 1)  # WM_ACTIVATE on the private desktop only.
                return
            if process.poll() is not None:
                raise RuntimeError("P0_FRONTEND_EXITED_BEFORE_WINDOW")
            time.sleep(.1)
        raise RuntimeError("P0_OWNED_WINDOW_NOT_FOUND")

    def post(self, message, key=0, data=0):
        pid = wintypes.DWORD()
        self.user32.GetWindowThreadProcessId(self.hwnd, ctypes.byref(pid))
        if self.process.poll() is not None or pid.value != self.process.pid:
            raise RuntimeError("P0_WINDOW_IDENTITY_LOST")
        if not self.user32.PostMessageW(self.hwnd, message, key, data):
            raise ctypes.WinError(ctypes.get_last_error())

    def command(self, value):
        if value == "QUIT":
            self.post(0x10)  # WM_CLOSE, same normal close path as the title bar.
            return
        key = {"MENU_TOGGLE": 0x70, "MENU_B": 0x08,
               "MENU_DOWN": 0x28, "MENU_UP": 0x26, "MENU_A": 0x0D}[value]
        scan = self.user32.MapVirtualKeyW(key, 0)
        bits = 1 | (scan << 16) | ((key in (0x26, 0x28)) << 24)
        self.post(0x100, key, bits)
        time.sleep(.08)
        self.post(0x101, key, bits | (3 << 30))
        time.sleep(.2)
