"""Real dev.ps1/module route; replace only the external WSL process boundary.

No WSL, radio or installed state is read. Git, source allowlist, manifest hashing,
dependency matching, dispatcher and option/role normalization remain real.
Console interrupt + actual CLI and complete RFU qualification are separate tests.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from tests.test_dev_console_interrupt import quoted, encoded


ROOT = Path(__file__).resolve().parents[1]


def test_real_overlay_selection_can_import_package_in_an_isolated_directory(tmp_path):
    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("PowerShell unavailable")
    script = f"""
$module = Import-Module {quoted(ROOT / 'scripts/dev/DevOverlay.psm1')} -Force -PassThru
& $module {{ @(Get-SourceFiles) | ConvertTo-Json -Compress }}
"""
    result = subprocess.run([pwsh, "-NoProfile", "-EncodedCommand", encoded(script)],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=15)
    assert result.returncode == 0, result.stderr
    selected = json.loads(result.stdout)
    assert "switchtrade/VERSION" in selected
    for relative in ("switchtrade/__init__.py", "switchtrade/VERSION"):
        assert relative in selected
        target = tmp_path / relative
        target.parent.mkdir(exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    subprocess.run([sys.executable, "-I", "-c",
        "import sys; sys.path.insert(0, sys.argv[1]); import switchtrade; assert switchtrade.__version__",
        str(tmp_path)], cwd=tmp_path, check=True, timeout=10)


@pytest.mark.parametrize("encoding,option", [("utf-16-le", "-OutputEncoding ([Text.Encoding]::Unicode)"), ("utf-8", "")])
def test_captured_process_decodes_wsl_inventory_without_changing_linux_output(encoding, option):
    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("PowerShell unavailable")
    expected = "SwitchTrade-한글\n"
    producer = ("import sys; value=" + repr(expected) + "; "
                f"sys.stdout.buffer.write(value.encode('{encoding}')); "
                f"sys.stderr.buffer.write(value.encode('{encoding}'))")
    script = f"""
$module = Import-Module {quoted(ROOT / 'scripts/dev/DevOverlay.psm1')} -Force -PassThru
& $module {{
    Invoke-DevCapturedProcess -FilePath {quoted(sys.executable)} -ArgumentList @('-c', {quoted(producer)}) {option} | ConvertTo-Json -Compress
}}
"""
    result = subprocess.run([pwsh, "-NoProfile", "-EncodedCommand", encoded(script)],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=15)
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value == {"ExitCode": 0, "Stdout": expected, "Stderr": expected}


@pytest.mark.parametrize("fault", [None, "missing", "owner", "schema", "product", "release_id", "payload_sha256"])
def test_doctor_requires_the_real_provisioner_ownership_contract(fault):
    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("PowerShell unavailable")
    marker = {"schema": 1, "owner": "switchtrade-provisioner", "product": "SwitchTrade",
              "release_id": "test-release", "payload_sha256": "a" * 64}
    if fault == "missing":
        del marker["product"]
    elif fault:
        marker[fault] = 2 if fault == "schema" else "wrong"
    script = f"""
$module = Import-Module {quoted(ROOT / 'scripts/dev/DevOverlay.psm1')} -Force -PassThru
& $module {{
    function Get-ActiveRuntime {{ [pscustomobject]@{{Name='SwitchTrade-Test'; ReleaseId='test-release'}} }}
    function Invoke-DevCapturedProcess {{ [pscustomobject]@{{ExitCode=0; Stdout='SwitchTrade-Test'; Stderr=''}} }}
    function Invoke-DevWsl {{
        param($Distro, $Command, $Arguments)
        $value = if ($Command -eq '/bin/cat') {{ {quoted(json.dumps(marker))} }} else {{ 'Python 3.12' }}
        [pscustomobject]@{{ExitCode=0; Stdout=$value; Stderr=''}}
    }}
    function Assert-DependencyCompatibility {{}}
    try {{ Invoke-DevDoctor }} catch {{ [Console]::Out.WriteLine($_.Exception.Code) }}
}}
"""
    result = subprocess.run([pwsh, "-NoProfile", "-EncodedCommand", encoded(script)],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=15)
    assert result.returncode == 0, result.stderr
    if fault:
        assert result.stdout.strip() == "DEV_RUNTIME_OWNERSHIP_INVALID"
    else:
        assert json.loads(result.stdout)["dependency_match"] is True


def test_actual_dev_missing_runtime_reports_original_code_without_type_resolution_error(tmp_path):
    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("PowerShell unavailable")
    result = subprocess.run([pwsh, "-NoProfile", "-File", str(ROOT / "dev.ps1"), "doctor"],
        cwd=ROOT, env={**os.environ, "LOCALAPPDATA": str(tmp_path)},
        capture_output=True, text=True, timeout=10)
    assert result.returncode == 1
    assert "DEV_ACTIVE_RUNTIME_MISSING:" in result.stderr
    assert "Unable to find type" not in result.stderr


@pytest.mark.parametrize("arguments", [
    ["join"], ["join", "42"], ["join", "１２３４５６"], ["host", "--channel"],
    ["host", "--channel", "999"], ["host", "--usb-id", "bad"], ["host", "--unknown"],
    ["host", "--relay", "https://secret@relay.example"],
])
def test_invalid_actual_dev_arguments_fail_before_runtime_or_radio_access(arguments, tmp_path):
    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("PowerShell unavailable")
    result = subprocess.run([pwsh, "-NoProfile", "-File", str(ROOT / "dev.ps1"), "run", *arguments],
        cwd=ROOT, env={**os.environ, "LOCALAPPDATA": str(tmp_path)},
        capture_output=True, text=True, timeout=10)
    assert result.returncode == 1
    assert "DEV_CORE_ARGUMENT_INVALID:" in result.stderr
    assert "DEV_ACTIVE_RUNTIME_MISSING" not in result.stderr


@pytest.mark.parametrize("candidate,expected", [
    ("config/prod.keys", "switchtrade/ordinary.py"),
    ("switchtrade/credential_fixture.py", "DEV_SOURCE_FORBIDDEN"),
    ("switchtrade/captures/input.py", "DEV_SOURCE_FORBIDDEN"),
])
def test_source_exclusion_does_not_weaken_selected_path_secret_gate(candidate, expected):
    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("PowerShell unavailable")
    script = f"""
$module = Import-Module {quoted(ROOT / 'scripts/dev/DevOverlay.psm1')} -Force -PassThru
& $module {{
    function Invoke-DevCapturedProcess {{
        [pscustomobject]@{{ ExitCode=0; Stdout="switchtrade/ordinary.py`n{candidate}"; Stderr='' }}
    }}
    try {{ Get-SourceFiles }} catch {{ [Console]::Out.WriteLine($_.Exception.Code) }}
}}
"""
    result = subprocess.run([pwsh, "-NoProfile", "-EncodedCommand", encoded(script)],
        cwd=ROOT, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == expected


@pytest.mark.skipif(sys.platform != "win32", reason="Windows development entrypoint")
@pytest.mark.parametrize("mode", ["host", "join", "generic", "environment"])
def test_actual_dev_ps1_dispatches_through_manifest_and_wsl_boundary(mode, tmp_path):
    pwsh = shutil.which("pwsh")
    assert pwsh
    state = tmp_path / "SwitchTrade/state/active-runtime.json"
    state.parent.mkdir(parents=True)
    state.write_text(json.dumps({"schema": 1, "active_runtime": "SwitchTrade-Test", "release_id": "test-release"}), encoding="utf-8")
    options = ["--relay", "https://relay.example", "--usb-id=0bda:818b", "--channel", "11"]
    environment = {**os.environ, "LOCALAPPDATA": str(tmp_path)}
    environment.pop("SWITCHTRADE_CORE_RELAY", None)
    if mode == "environment":
        mode = "host"
        environment["SWITCHTRADE_CORE_RELAY"] = "https://relay.example"
        options = ["--usb-id=0bda:818b", "--channel", "11", "--log-dir", "host"]
    arguments = (["run", "--", "--version"] if mode == "generic" else
                 ["run", mode] + (["003817"] if mode == "join" else []) + options)
    # Import interception installs the modeled external-process boundary after
    # the real module loads, not a replacement dev/main/Invoke-DevRun function.
    script = r'''
function Import-Module {
    param([string]$Name, [switch]$Force)
    $module = Microsoft.PowerShell.Core\Import-Module -Name $Name -Force -PassThru -Global
    & $module {
        $script:RealCaptured = (Get-Command Invoke-DevCapturedProcess).ScriptBlock
        $script:ModeChecks = 0
        function script:Invoke-DevCapturedProcess {
            param([string]$FilePath, [string[]]$ArgumentList, [string]$WorkingDirectory = $script:RepoRoot)
            if ($FilePath -eq 'git') {
                return (& $script:RealCaptured -FilePath $FilePath -ArgumentList $ArgumentList -WorkingDirectory $WorkingDirectory)
            }
            if ($FilePath -ne 'wsl.exe') { throw "unexpected external process $FilePath" }
            $out = ''
            if ($ArgumentList[0] -eq '--list') { $out = 'SwitchTrade-Test' }
            else {
                if ($ArgumentList[1] -ne 'SwitchTrade-Test') { throw 'wrong runtime identity' }
                $index = [Array]::IndexOf($ArgumentList, '--')
                $command = $ArgumentList[$index + 1]
                $args = @($ArgumentList | Select-Object -Skip ($index + 2))
                switch ($command) {
                    '/bin/cat' { $out = '{"schema":1,"owner":"switchtrade-provisioner","product":"SwitchTrade","release_id":"test-release","payload_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}' }
                    '/usr/bin/test' { }
                    '/opt/switchtrade/bridge/.venv/bin/python' { $out = 'Python 3.12' }
                    '/usr/bin/sha256sum' {
                        $out = (@(foreach ($path in $args) {
                            if ($path.StartsWith('/opt/switchtrade/')) {
                                $relative = $path.Substring('/opt/switchtrade/'.Length)
                            } elseif ($path -match '^/opt/switchtrade-dev/releases/[0-9a-f]{64}/(.+)$') {
                                $relative = $Matches[1]
                            } else { throw "unbound remote path $path" }
                            $hash = Get-FileDigest (Join-Path $script:RepoRoot $relative)
                            "$hash  $path"
                        }) -join "`n")
                    }
                    '/usr/bin/stat' {
                        if (($args[0..2] -join ' ') -ne '-c %a:%n --') { throw 'unexpected stat arguments' }
                        $manifest = Get-SourceManifest -RelativePaths @(Get-SourceFiles)
                        $out = (@(foreach ($path in ($args | Select-Object -Skip 3)) {
                            if ($path -notmatch '^/opt/switchtrade-dev/releases/[0-9a-f]{64}/(.+)$') {
                                throw "unbound mode path $path"
                            }
                            $relative = $Matches[1]
                            if (-not $manifest.Modes.Contains($relative)) { throw 'unknown mode path' }
                            "$($manifest.Modes[$relative]):$path"
                        }) -join "`n")
                        $script:ModeChecks += 1
                    }
                    '/bin/mkdir' { }
                    '/bin/rmdir' { }
                    '/bin/ln' { }
                    '/bin/mv' { }
                    '/bin/rm' { }
                    default { throw "unexpected WSL primitive $command" }
                }
            }
            [pscustomobject]@{ ExitCode=0; Stdout=$out; Stderr='' }
        }
        function script:Invoke-DevInteractiveProcess {
            param([string]$FilePath, [string[]]$ArgumentList, [string]$WorkingDirectory, [switch]$ParentLifetime)
            if ($FilePath -ne 'wsl.exe') { throw 'not WSL boundary' }
            [Console]::Out.WriteLine((@{ argv=$ArgumentList; lifetime=[bool]$ParentLifetime; mode_checks=$script:ModeChecks } | ConvertTo-Json -Compress))
            [Console]::Error.WriteLine('ordinary child stderr')
            return [int]23
        }
    }
}
'''
    script += f"& {quoted(ROOT / 'dev.ps1')} " + " ".join(map(quoted, arguments))
    script += "; exit $LASTEXITCODE"
    result = subprocess.run([pwsh, "-NoProfile", "-EncodedCommand", encoded(script)],
        cwd=ROOT, env=environment,
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 23, (result.stdout, result.stderr)
    assert "ordinary child stderr" in result.stderr
    value = json.loads(result.stdout)
    assert value["mode_checks"] >= 1
    argv = value["argv"]
    assert argv[:4] == ["--distribution", "SwitchTrade-Test", "--user", "root"]
    assert value["lifetime"] is (mode != "generic")
    if mode == "generic":
        assert argv[-1] == "--version" and "./scripts/wsl-radio-prepare.sh" not in argv
    else:
        assert "switchtrade.parent_lifetime" in argv
        assert "SWITCHTRADE_PARENT_STDIN=1" in argv
        assert any(item.startswith("SWITCHTRADE_CORE_RELEASE=") for item in argv)
        gate = argv.index("./scripts/wsl-radio-prepare.sh")
        assert argv[gate:gate + 7] == ["./scripts/wsl-radio-prepare.sh", "--role",
            "guest" if mode == "host" else "host", "--usb-id", "0bda:818b", "--target-channel", "11"]
        module = argv.index("switchtrade.core_cli")
        normalized = (["--relay", environment["SWITCHTRADE_CORE_RELAY"]] if "SWITCHTRADE_CORE_RELAY" in environment else []) + options
        assert argv[module + 1:] == normalized + [mode] + (["003817"] if mode == "join" else [])
