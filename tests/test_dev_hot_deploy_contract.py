from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "scripts/dev/DevOverlay.psm1"
DISPATCHER = ROOT / "dev.ps1"
ALLOWLIST = ROOT / "scripts/dev/dev-source-allowlist.txt"


class DevHotDeployContractTests(unittest.TestCase):
    def test_command_surface_is_documented(self) -> None:
        text = DISPATCHER.read_text(encoding="utf-8")
        for command in ("doctor", "sync", "run", "test", "clean"):
            self.assertIn(f"'{command}'", text)

    def test_allowlist_is_explicit_and_secret_free(self) -> None:
        entries = {
            line.strip()
            for line in ALLOWLIST.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        self.assertIn("switchtrade/**/*.py", entries)
        self.assertIn("bridge/**/*.py", entries)
        self.assertIn("tests/**/*.py", entries)
        self.assertNotIn("config/prod.keys", entries)
        self.assertNotIn("**/*.zip", entries)
        self.assertIn("dev-source-allowlist.txt", MODULE.read_text(encoding="utf-8"))

    def test_overlay_and_process_contract_are_explicit(self) -> None:
        text = MODULE.read_text(encoding="utf-8")
        for value in (
            "/opt/switchtrade/bridge/.venv/bin/python",
            "PYTHONNOUSERSITE=1",
            "PYTHONPATH=",
            "SWITCHTRADE_SOURCE_ROOT=",
            "SWITCHTRADE_INSTALLED_ROOT=",
            "--distribution",
            "--user",
            "--cd",
        ):
            self.assertIn(value, text)
        self.assertIn("$script:OverlayRoot/current", text)
        self.assertIn("$script:OverlayRoot/releases/", text)
        self.assertIn("(?:.*/)?", text)
        self.assertIn("DEV_DEPENDENCY_MISMATCH", text)
        self.assertIn("DEV_CLEAN_REFUSED", text)
        self.assertIn("function Invoke-DevCapturedProcess", text)
        self.assertIn("function Invoke-DevInteractiveProcess", text)
        self.assertIn("Invoke-DevInteractiveWsl", text)
        self.assertIn("Assert-RemoteManifest", text)
        self.assertIn("ReadToEndAsync()", text)
        self.assertNotIn("StandardOutput.ReadToEnd()", text)
        self.assertNotIn("StandardError.ReadToEnd()", text)

    def test_production_root_is_not_a_mutation_target(self) -> None:
        text = MODULE.read_text(encoding="utf-8")
        self.assertNotRegex(text, r"(?:rm|mv|mkdir|ln)[^\n]*['\"]?/opt/switchtrade['\"]?(?:/|\s|$)")
        self.assertIn("InstalledRoot = '/opt/switchtrade'", text)
        self.assertIn("OverlayRoot = '/opt/switchtrade-dev'", text)

    def test_dispatcher_parses_without_live_wsl(self) -> None:
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if powershell is None:
            self.skipTest("PowerShell is unavailable")
        result = subprocess.run(
            [powershell, "-NoProfile", "-File", str(DISPATCHER), "help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_sync_reuses_verified_release_and_run_repeats_without_wsl(self) -> None:
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if powershell is None:
            self.skipTest("PowerShell is unavailable")
        module_path = str(MODULE).replace("'", "''")
        script = f"""
$module = Import-Module -Name '{module_path}' -Force -PassThru
& $module {{
    $script:contentId = 'a' * 64
    $script:fileHash = '1' * 64
    $script:archives = 0
    $script:activations = 0
    $script:runs = 0
    $script:releases = @{{}}
    function Invoke-DevDoctor {{ '{{"active_runtime":"mock"}}' }}
    function Get-ActiveRuntime {{ [pscustomobject]@{{ Name = 'mock' }} }}
    function Get-SourceFiles {{ @('switchtrade/example.py') }}
    function Get-SourceManifest {{
        param([string[]]$RelativePaths)
        $files = [ordered]@{{ 'switchtrade/example.py' = $script:fileHash }}
        [pscustomobject]@{{ ContentId = $script:contentId; Dirty = $false; Files = $files }}
    }}
    function Invoke-DevCapturedProcess {{
        param([string]$FilePath, [string[]]$ArgumentList, [string]$WorkingDirectory)
        if ($FilePath -eq 'tar') {{ $script:archives++ }}
        [pscustomobject]@{{ ExitCode = 0; Stdout = ''; Stderr = '' }}
    }}
    function Invoke-DevWsl {{
        param([string]$Distro, [string]$Command, [string[]]$Arguments, [string]$Cwd)
        if ($Command -eq '/usr/bin/test' -and $Arguments[0] -eq '-e') {{
            return [pscustomobject]@{{ ExitCode = [int](-not $script:releases.ContainsKey($Arguments[1])); Stdout = ''; Stderr = '' }}
        }}
        if ($Command -eq '/usr/bin/sha256sum') {{
            $output = (($Arguments | ForEach-Object {{ "$($script:fileHash)  $_" }}) -join "`n")
            return [pscustomobject]@{{ ExitCode = 0; Stdout = $output; Stderr = '' }}
        }}
        if ($Command -eq '/bin/mv' -and $Arguments.Count -eq 2) {{ $script:releases[$Arguments[1]] = $true }}
        if ($Command -eq '/bin/ln') {{ $script:activations++ }}
        [pscustomobject]@{{ ExitCode = 0; Stdout = ''; Stderr = '' }}
    }}
    function Invoke-DevInteractiveWsl {{
        param([string]$Distro, [string]$Command, [string[]]$Arguments, [string]$Cwd)
        $script:runs++
        0
    }}
    $first = Invoke-DevSync | ConvertFrom-Json
    $second = Invoke-DevSync | ConvertFrom-Json
    $script:contentId = 'b' * 64
    $script:fileHash = '2' * 64
    $third = Invoke-DevSync | ConvertFrom-Json
    $null = Invoke-DevRun -Arguments @('--version')
    $null = Invoke-DevRun -Arguments @('--version')
    [ordered]@{{
        first_reused = $first.reused
        second_reused = $second.reused
        third_reused = $third.reused
        archives = $script:archives
        activations = $script:activations
        runs = $script:runs
    }} | ConvertTo-Json -Compress
}}
"""
        result = subprocess.run(
            [powershell, "-NoProfile", "-Command", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.strip(), f"stdout={result.stdout!r} stderr={result.stderr!r}")
        outcome = json.loads(result.stdout)
        self.assertEqual(
            outcome,
            {
                "first_reused": False,
                "second_reused": True,
                "third_reused": False,
                "archives": 2,
                "activations": 5,
                "runs": 2,
            },
        )

    def test_manifest_verification_rejects_swapped_paths_without_wsl(self) -> None:
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if powershell is None:
            self.skipTest("PowerShell is unavailable")
        module_path = str(MODULE).replace("'", "''")
        script = f"""
$module = Import-Module -Name '{module_path}' -Force -PassThru
& $module {{
    function Invoke-DevWsl {{
        param([string]$Distro, [string]$Command, [string[]]$Arguments, [string]$Cwd)
        [pscustomobject]@{{
            ExitCode = 0
            Stdout = ('2' * 64) + '  /overlay/a.py' + "`n" + ('1' * 64) + '  /overlay/b.py'
            Stderr = ''
        }}
    }}
    $manifest = [pscustomobject]@{{
        Files = [ordered]@{{ 'a.py' = '1' * 64; 'b.py' = '2' * 64 }}
    }}
    try {{
        Assert-RemoteManifest -Distro 'mock' -Manifest $manifest -RemoteRoot '/overlay'
        exit 2
    }} catch [DevOverlayException] {{
        [Console]::WriteLine($_.Exception.Code)
    }}
}}
"""
        result = subprocess.run(
            [powershell, "-NoProfile", "-Command", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "DEV_MANIFEST_MISMATCH")

    def test_interactive_process_forwards_output_before_exit(self) -> None:
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if powershell is None:
            self.skipTest("PowerShell is unavailable")
        module_path = str(MODULE).replace("'", "''")
        python_path = sys.executable.replace("'", "''")
        script = (
            f"$module = Import-Module -Name '{module_path}' -Force -PassThru; "
            f"& $module {{ Invoke-DevInteractiveProcess -FilePath '{python_path}' "
            "-ArgumentList @('-c', 'import time; print(\"ready\", flush=True); time.sleep(2)') }"
        )
        started = time.monotonic()
        process = subprocess.Popen(
            [powershell, "-NoProfile", "-Command", script],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            assert process.stdout is not None
            self.assertEqual(process.stdout.readline().strip(), "ready")
            self.assertLess(time.monotonic() - started, 1.5)
            stderr = process.stderr.read() if process.stderr is not None else ""
            self.assertEqual(process.wait(timeout=5), 0, stderr)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()


if __name__ == "__main__":
    unittest.main()
