from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
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
        self.assertIn("switchtrade/VERSION", entries)
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

    @unittest.skipUnless(sys.platform == "win32", "requires Windows path semantics")
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
        [pscustomobject]@{{ GitHead = ('0' * 40); ContentId = $script:contentId; Dirty = $false; Files = $files; Modes = @{{ 'switchtrade/example.py' = '644' }} }}
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
        if ($Command -eq '/usr/bin/stat') {{
            $output = (($Arguments | Select-Object -Skip 3 | ForEach-Object {{ "644:$_" }}) -join "`n")
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

    @unittest.skipUnless(sys.platform == "win32", "requires Windows path semantics")
    def test_git_modes_are_identity_bound_restored_only_in_staging_and_verified(self):
        module_path = str(MODULE).replace("'", "''")
        script = f"""
$ErrorActionPreference = 'Stop'
$module = Import-Module '{module_path}' -Force -PassThru
& $module {{
    $script:executable = '100755'
    function Invoke-DevCapturedProcess {{
        param($FilePath, $ArgumentList)
        $output = if ($ArgumentList -contains '--stage') {{
            "$script:executable $('a' * 40) 0`tscripts/wsl-radio-prepare.sh`n100644 $('b' * 40) 0`tswitchtrade/VERSION"
        }} elseif ($ArgumentList -contains 'rev-parse') {{ 'a' * 40 }} else {{ '' }}
        [pscustomobject]@{{ ExitCode = 0; Stdout = $output; Stderr = '' }}
    }}
    $paths = @('scripts/wsl-radio-prepare.sh', 'switchtrade/VERSION')
    $script:manifest = Get-SourceManifest $paths
    $script:executable = '100644'
    $other = Get-SourceManifest $paths
    if ($manifest.ContentId -eq $other.ContentId) {{ throw 'mode not included in content identity' }}
    if ($manifest.Modes[$paths[0]] -ne '755' -or $manifest.Modes[$paths[1]] -ne '644') {{ throw 'incorrect Git mode mapping' }}
    $script:badMode = $false
    $script:chmodCalls = 0
    function Invoke-DevWsl {{
        param($Distro, $Command, $Arguments)
        $output = ''
        if ($Command -eq '/bin/chmod') {{
            $script:chmodCalls++
            foreach ($target in @($Arguments | Select-Object -Skip 2)) {{
                if ($target -notlike '/opt/switchtrade-dev/.staging-*/*') {{ throw 'mutated published release' }}
                if ($target.EndsWith('.sh') -and $Arguments[0] -ne '755') {{ throw 'script not executable' }}
            }}
        }} elseif ($Command -eq '/usr/bin/sha256sum') {{
            $output = (($manifest.Files.Keys | ForEach-Object {{ "$($manifest.Files[$_])  /overlay/$_" }}) -join "`n")
        }} elseif ($Command -eq '/usr/bin/stat') {{
            $output = (($manifest.Files.Keys | ForEach-Object {{
                $mode = if ($script:badMode) {{ '666' }} else {{ $manifest.Modes[$_] }}
                "${{mode}}:/overlay/$_"
            }}) -join "`n")
        }}
        [pscustomobject]@{{ ExitCode = 0; Stdout = $output; Stderr = '' }}
    }}
    Set-StagingFileModes 'mock' $manifest ("/opt/switchtrade-dev/.staging-" + ('a' * 64) + '-' + ('b' * 32))
    if ($script:chmodCalls -ne 2) {{ throw 'missing file mode groups' }}
    try {{ Set-StagingFileModes 'mock' $manifest '/opt/switchtrade-dev/releases/existing'; throw 'accepted immutable target' }}
    catch [DevOverlayException] {{ if ($_.Exception.Code -ne 'DEV_EXTRACT_FAILED') {{ throw }} }}
    Assert-RemoteManifest 'mock' $manifest '/overlay'
    $script:badMode = $true
    try {{ Assert-RemoteManifest 'mock' $manifest '/overlay'; throw 'accepted nonexecutable tar modes' }}
    catch [DevOverlayException] {{ if ($_.Exception.Code -ne 'DEV_MANIFEST_MISMATCH') {{ throw }} }}
    'MODE_CONTRACT_PASS'
}}
"""
        result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-Command", script],
                                cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "MODE_CONTRACT_PASS")

    def test_large_manifest_batches_preserve_all_evidence_and_stop_on_failure(self):
        powershell = shutil.which("pwsh")
        if powershell is None:
            self.skipTest("PowerShell 7 is unavailable")
        module_path = str(MODULE).replace("'", "''")
        python_path = sys.executable.replace("'", "''")
        script = f"""
$ErrorActionPreference = 'Stop'
$module = Import-Module '{module_path}' -Force -PassThru
& $module {{
    $script:root = '/opt/switchtrade-dev/.staging-' + ('a' * 64) + '-' + ('b' * 32)
    $script:manifest = [pscustomobject]@{{ Files = [ordered]@{{}}; Modes = @{{}} }}
    1..240 | ForEach-Object {{
        $path = 'switchtrade/' + ('long path-' * 9) + "/file-$_.py"
        $manifest.Files[$path] = '1' * 64
        $manifest.Modes[$path] = if ($_ % 2) {{ '644' }} else {{ '755' }}
    }}
    $script:lastPath = @($manifest.Files.Keys)[-1]
    $unsplit = @($manifest.Files.Keys | ForEach-Object {{ "$script:root/$_" }}) -join ' '
    if ($unsplit.Length -le 32768) {{ throw 'fixture did not exceed Windows launch size' }}
    $script:captured = ${{function:Invoke-DevCapturedProcess}}
    $script:failure = ''
    $script:counts = @{{}}
    $script:seen = @{{}}
    function Invoke-DevCapturedProcess {{
        param($FilePath, [string[]]$ArgumentList)
        if ($FilePath -ne 'wsl.exe' -or $ArgumentList[0] -ne '--distribution' -or
            $ArgumentList[1] -ne 'mock' -or $ArgumentList[4] -ne '--cd' -or
            $ArgumentList[5] -ne '/opt/switchtrade') {{ throw 'lost explicit WSL identity' }}
        $command = $ArgumentList[7]
        $script:counts[$command]++
        $budget = ($ArgumentList | ForEach-Object {{ 2 * $_.Length + 3 }} | Measure-Object -Sum).Sum
        if ($budget -gt 9000) {{ throw 'unbounded command' }}
        if (-not $script:failure) {{
            # Real Windows Process.Start with every quoted path argument, but
            # Python instead of WSL: no live runtime/radio needed by this test.
            $probe = & $script:captured -FilePath '{python_path}' -ArgumentList (
                @('-c', 'import sys; print(len(sys.argv)-1)') + $ArgumentList)
            if ($probe.ExitCode -ne 0 -or [int]$probe.Stdout -ne $ArgumentList.Count) {{ throw 'real argv launch failed' }}
        }}
        $skip = switch ($command) {{ '/usr/bin/sha256sum' {{ 8 }} '/usr/bin/stat' {{ 11 }} '/bin/chmod' {{ 10 }} default {{ throw 'unexpected command' }} }}
        $output = [System.Collections.Generic.List[string]]::new()
        foreach ($target in @($ArgumentList | Select-Object -Skip $skip)) {{
            if (-not $target.StartsWith("$script:root/")) {{ throw 'unowned path' }}
            $path = $target.Substring($script:root.Length + 1)
            if (-not $manifest.Files.Contains($path)) {{ throw 'unknown source path' }}
            $key = "$command/$path"
            $script:seen[$key]++
            $bad = $path -eq $script:lastPath
            if ($command -eq '/usr/bin/sha256sum') {{
                if ($bad -and $script:failure -eq 'missing') {{ continue }}
                $hash = if ($bad -and $script:failure -eq 'hash') {{ '2' * 64 }} else {{ $manifest.Files[$path] }}
                $output.Add("$hash  $target")
                if ($bad -and $script:failure -eq 'duplicate') {{ $output.Add("$hash  $target") }}
            }} elseif ($command -eq '/usr/bin/stat') {{
                $mode = if ($bad -and $script:failure -eq 'mode') {{ '666' }} else {{ $manifest.Modes[$path] }}
                $output.Add("${{mode}}:$target")
            }} elseif ($ArgumentList[8] -ne $manifest.Modes[$path]) {{ throw 'wrong chmod mode' }}
        }}
        $failed = $script:failure -eq $command -and $script:counts[$command] -eq 2
        [pscustomobject]@{{ ExitCode = [int]$failed; Stdout = $output -join "`n"; Stderr = $(if ($failed) {{ 'first batch failure' }} else {{ '' }}) }}
    }}
    Set-StagingFileModes 'mock' $manifest $script:root
    Assert-RemoteManifest 'mock' $manifest $script:root
    foreach ($command in @('/bin/chmod', '/usr/bin/sha256sum', '/usr/bin/stat')) {{
        if ($script:counts[$command] -lt 2) {{ throw 'did not split command' }}
        foreach ($path in $manifest.Files.Keys) {{
            if ($script:seen["$command/$path"] -ne 1) {{ throw 'file omitted or repeated across batches' }}
        }}
    }}
    foreach ($failure in @('hash', 'missing', 'duplicate', 'mode', '/usr/bin/sha256sum', '/usr/bin/stat', '/bin/chmod')) {{
        $script:failure = $failure
        $script:counts = @{{}}
        try {{
            if ($failure -eq '/bin/chmod') {{ Set-StagingFileModes 'mock' $manifest $script:root }}
            else {{ Assert-RemoteManifest 'mock' $manifest $script:root }}
            throw "accepted $failure"
        }} catch [DevOverlayException] {{
            $expected = if ($failure -eq '/bin/chmod') {{ 'DEV_EXTRACT_FAILED' }} else {{ 'DEV_MANIFEST_MISMATCH' }}
            if ($_.Exception.Code -ne $expected) {{ throw }}
        }}
        if ($failure.StartsWith('/') -and $script:counts[$failure] -ne 2) {{ throw 'continued after failed batch' }}
    }}
    'BATCH_CONTRACT_PASS'
}}
"""
        result = subprocess.run(
            [powershell, "-NoProfile", "-Command", script], cwd=ROOT,
            capture_output=True, text=True, check=False, timeout=90,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "BATCH_CONTRACT_PASS")

    def test_interactive_process_forwards_output_before_exit(self) -> None:
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if powershell is None:
            self.skipTest("PowerShell is unavailable")
        module_path = str(MODULE).replace("'", "''")
        python_path = sys.executable.replace("'", "''")
        with tempfile.TemporaryDirectory() as state:
            marker = Path(state) / "stdout-observed"
            marker_arg = str(marker).replace("'", "''")
            child = (
                'import pathlib,sys,time; print("ready", flush=True); end=time.monotonic()+10\n'
                'while not pathlib.Path(sys.argv[1]).exists():\n'
                ' if time.monotonic() >= end: sys.exit(42)\n'
                ' time.sleep(.01)\n'
                'print("ack", flush=True)'
            )
            script = (
                f"$module = Import-Module -Name '{module_path}' -Force -PassThru; "
                f"& $module {{ exit (Invoke-DevInteractiveProcess -FilePath '{python_path}' "
                f"-ArgumentList @('-c', '{child}', '{marker_arg}')) }}"
            )
            process = subprocess.Popen(
                [powershell, "-NoProfile", "-Command", script], cwd=ROOT,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            try:
                assert process.stdout is not None
                self.assertEqual(process.stdout.readline().strip(), "ready")
                # Child cannot exit successfully until the parent observes its
                # streamed stdout. PowerShell's cold start isn't the I/O clock.
                marker.touch()
                stdout, stderr = process.communicate(timeout=15)
                self.assertEqual(process.returncode, 0, stderr)
                self.assertEqual(stdout.strip(), "ack")
            finally:
                marker.touch()
                if process.poll() is None:
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                if process.stdout is not None:
                    process.stdout.close()
                if process.stderr is not None:
                    process.stderr.close()


if __name__ == "__main__":
    unittest.main()
