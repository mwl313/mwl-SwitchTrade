"""Windows-only console primitive qualification; never launches WSL/devices."""

import base64
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "scripts/dev/DevOverlay.psm1"


def quoted(value):
    return "'" + str(value).replace("'", "''") + "'"


def encoded(script):
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def test_native_entry_preserves_streams_arguments_and_scalar_exit():
    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("PowerShell 7 is unavailable")
    child = 'import json,sys,time; print(json.dumps(sys.argv[1:]),flush=True); print("diagnostic",file=sys.stderr,flush=True); time.sleep(.2); sys.exit(23)'
    args = ["-c", child, "003817", "a b", 'a"b', "--channel", "11"]
    script = f"$m=Import-Module {quoted(MODULE)} -PassThru; & $m {{ $v=@(Invoke-DevInteractiveProcess -FilePath {quoted(sys.executable)} -ArgumentList @({','.join(map(quoted,args))})); if($v.Count -ne 1 -or $v[0] -isnot [int]) {{throw 'scalar contract'}}; [Console]::Out.WriteLine('EXIT='+$v[0]) }}"
    result = subprocess.run([pwsh, "-NoProfile", "-EncodedCommand", encoded(script)],
        cwd=ROOT, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    import json
    lines = result.stdout.splitlines()
    assert json.loads(lines[0]) == args[2:]
    assert lines[1] == "EXIT=23"
    assert "diagnostic" in result.stderr


@pytest.mark.skipif(sys.platform != "win32", reason="Windows console Ctrl+C primitive")
def test_actual_windows_ctrl_c_reaches_cli_and_cleans_real_stage(tmp_path):
    pwsh = shutil.which("pwsh")
    assert pwsh, "Windows qualification requires PowerShell 7"
    ready, stopped = tmp_path / "ready", tmp_path / "stopped"
    args = ["-m", "tests.cli_signal_child", str(ready), str(stopped)]
    script = f"$m=Import-Module {quoted(MODULE)} -PassThru; & $m {{ exit (Invoke-DevInteractiveProcess -FilePath {quoted(sys.executable)} -ArgumentList @({','.join(map(quoted,args))}) -WorkingDirectory {quoted(ROOT)} -ParentLifetime) }}"
    # CI/agent hosts may inherit the Windows IGNORE_CTRL_C attribute. Model an
    # interactive user console explicitly; otherwise Windows suppresses the
    # signal before any PowerShell/.NET/Python handler can see it.
    setup = 'using System; using System.Runtime.InteropServices; public static class TestConsoleInput { [DllImport("kernel32.dll")] public static extern bool SetConsoleCtrlHandler(IntPtr p, bool add); }'
    script = f"Add-Type -TypeDefinition {quoted(setup)}; if(-not [TestConsoleInput]::SetConsoleCtrlHandler([IntPtr]::Zero,$false)){{throw 'console setup failed'}}; " + script
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    process = subprocess.Popen([pwsh, "-NoProfile", "-EncodedCommand", encoded(script)],
        cwd=ROOT, creationflags=subprocess.CREATE_NEW_CONSOLE, startupinfo=startup,
        env={**os.environ, "SWITCHTRADE_PARENT_STDIN": "1"},
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline and process.poll() is None:
            time.sleep(.02)
        assert ready.exists(), process.communicate(timeout=25)
        # Attach a separate signal sender ONLY to this test's new, hidden console.
        # CTRL_C_EVENT goes to that owned console, never the user's terminal.
        sender = (
            "import ctypes,time; k=ctypes.WinDLL('kernel32',use_last_error=True); "
            "k.FreeConsole(); "
            f"assert k.AttachConsole({process.pid}),ctypes.get_last_error(); "
            "assert k.SetConsoleCtrlHandler(None,True); "
            "assert k.GenerateConsoleCtrlEvent(0,0),ctypes.get_last_error(); "
            "time.sleep(.3); k.FreeConsole()")
        subprocess.run([sys.executable, "-c", sender], check=True, timeout=5)
        try:
            output, error = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            output, error = process.communicate(timeout=25)
            pytest.fail(f"no graceful interrupt: {output}\n{error}")
        assert stopped.exists(), (output, error)
        assert stopped.read_text(encoding="ascii") == "CTRL_C_CLI_CLEAN", (output, error)
        assert process.returncode == 0, (output, error)
    finally:
        if process.poll() is None:
            # Child also has a 20s self-deadline; do not confuse forced parent
            # termination with verified CLI cleanup.
            process.wait(timeout=25)
        process.stdout.close()
        process.stderr.close()
