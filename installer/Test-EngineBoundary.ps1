[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$TestRoot,
    [string]$Rootfs = ''
)

$ErrorActionPreference = 'Stop'
$TestRoot = [IO.Path]::GetFullPath($TestRoot)
New-Item -ItemType Directory -Force -Path $TestRoot | Out-Null
. (Join-Path $PSScriptRoot 'engine\PlatformOps.ps1')

function Assert-Equal {
    param([AllowEmptyString()][string]$Actual, [AllowEmptyString()][string]$Expected, [string]$What)
    if ($Actual -cne $Expected) {
        throw "$What`n  expected: [$Expected]`n  actual:   [$Actual]"
    }
}

function Assert-True {
    param([bool]$Condition, [string]$What)
    if (-not $Condition) { throw $What }
}

# ---------------------------------------------------------------
# 1. Pure command-line quoting (CRT rules)
# ---------------------------------------------------------------
Assert-Equal (ConvertTo-NativeCommandLineArgument 'simple') 'simple' 'plain argument must stay unquoted'
Assert-Equal (ConvertTo-NativeCommandLineArgument 'has space') '"has space"' 'spaces must be quoted'
Assert-Equal (ConvertTo-NativeCommandLineArgument 'quote"inside') '"quote\"inside"' 'embedded quotes must be escaped'
Assert-Equal (ConvertTo-NativeCommandLineArgument '') '""' 'empty argument must be quoted'
Assert-Equal (ConvertTo-NativeCommandLineArgument '유니코드 $x') '"유니코드 $x"' 'unicode and dollar must survive quoting'
Assert-Equal (ConvertTo-NativeCommandLineArgument 'back\slash') 'back\slash' 'backslash-only values must stay unquoted'

# ---------------------------------------------------------------
# 2. Exact argv round trip through a real native process
# ---------------------------------------------------------------
$echo = Join-Path $TestRoot 'echo-args.ps1'
$echoSource = @'
param()
$i = 0
foreach ($a in $args) { Write-Output ("ARG[{0}]={1}" -f $i, $a); $i++ }
'@
Set-Content -LiteralPath $echo -Value $echoSource -Encoding UTF8

$roundTripArgs = @(
    'plain',
    'has space',
    'quote"inside',
    'trailing\',
    '',
    '유니코드 경로 $p',
    'back\\slash',
    '{"json":["a","b"]}'
)
$echoArgs = @('-NoProfile', '-File', $echo) + $roundTripArgs
$rt = Invoke-SwitchTradeProcess -FilePath 'powershell.exe' -Arguments $echoArgs -TimeoutSeconds 15
if ($rt.ExitCode -ne 0) { throw "echo round trip failed: $($rt.Error)" }
$linesOut = @($rt.Output -split "\r?\n" | Where-Object { $_ })
if ($linesOut.Count -ne $roundTripArgs.Count) { throw "argv count mismatch: expected $($roundTripArgs.Count), got $($linesOut.Count)" }
for ($i = 0; $i -lt $linesOut.Count; $i++) {
    $expected = "ARG[$i]=" + $roundTripArgs[$i]
    if ($linesOut[$i] -cne $expected) { throw "argv[$i] corrupted: expected [$expected], got [$($linesOut[$i])]" }
}

# Working directory and environment handoff
$envProbe = Join-Path $TestRoot 'env-probe.ps1'
$envProbeSource = @'
param()
Write-Output ("CWD=" + (Get-Location).Path)
Write-Output ("VAR=" + $env:SWITCHTRADE_BOUNDARY_TEST)
'@
Set-Content -LiteralPath $envProbe -Value $envProbeSource -Encoding UTF8
$wd = Join-Path $TestRoot 'sub dir'
New-Item -ItemType Directory -Force -Path $wd | Out-Null
$envResult = Invoke-SwitchTradeProcess -FilePath 'powershell.exe' -Arguments @('-NoProfile', '-File', $envProbe) -WorkingDirectory $wd -Environment @{ SWITCHTRADE_BOUNDARY_TEST = 'sentinel value' } -TimeoutSeconds 15
if ($envResult.ExitCode -ne 0 -or $envResult.Output -notmatch "CWD=$([regex]::Escape($wd))" -or $envResult.Output -notmatch 'VAR=sentinel value') {
    throw "working directory or environment handoff failed: $($envResult.Output)"
}

# ---------------------------------------------------------------
# 3. Timeout and cancellation
# ---------------------------------------------------------------
$timedOut = $false
try {
    Invoke-SwitchTradeProcess -FilePath 'powershell.exe' -Arguments @('-NoProfile', '-Command', 'Start-Sleep -Seconds 30') -TimeoutSeconds 2 | Out-Null
} catch { $timedOut = [string]$_.Exception.Message -match '^PROCESS_TIMEOUT:' }
if (-not $timedOut) { throw 'bounded child process did not time out' }

$cancelled = $false
$script:cancelChecks = 0
try {
    Invoke-SwitchTradeProcess -FilePath 'powershell.exe' -Arguments @('-NoProfile', '-Command', 'Start-Sleep -Seconds 30') -TimeoutSeconds 30 -CancellationCheck { $script:cancelChecks++; $script:cancelChecks -gt 5 } | Out-Null
} catch { $cancelled = [string]$_.Exception.Message -eq 'PROCESS_CANCELLED' }
if (-not $cancelled) { throw 'cancellation did not stop the child process' }

# stdout-only success and stderr-only failure classification
$stderrOnly = Join-Path $TestRoot 'stderr-only.ps1'
'[Console]::Error.WriteLine(''stderr-only text'') ' | Set-Content -LiteralPath $stderrOnly -Encoding UTF8
$stdoutOnlyFail = Join-Path $TestRoot 'stdout-fail.ps1'
'[Console]::Out.WriteLine(''stdout text''); exit 5 ' | Set-Content -LiteralPath $stdoutOnlyFail -Encoding UTF8
$s1 = Invoke-SwitchTradeProcess -FilePath 'powershell.exe' -Arguments @('-NoProfile', '-File', $stderrOnly) -TimeoutSeconds 10
if ($s1.ExitCode -ne 0 -or $s1.Output -ne '' -or $s1.Error -notmatch 'stderr-only text') { throw 'stderr-only result misclassified' }
$s2 = Invoke-SwitchTradeProcess -FilePath 'powershell.exe' -Arguments @('-NoProfile', '-File', $stdoutOnlyFail) -TimeoutSeconds 10
if ($s2.ExitCode -ne 5 -or $s2.Error -ne '' -or $s2.Output -notmatch 'stdout text') { throw 'stdout-only failure misclassified' }

# Output normalization strips UTF-16 NULs
$nul = "a" + [string][char]0 + "b" + [string][char]0
if ((ConvertFrom-SwitchTradeProcessOutput $nul) -cne 'ab') { throw 'UTF-16 NUL stripping failed' }

# ---------------------------------------------------------------
# 4. Gated: real wsl.exe --exec argv round trip on a disposable distro
# Gate owner: a real WSL runtime and a SwitchTrade rootfs must be available.
# Never points at SwitchTrade, Ubuntu, or any user distro.
# ---------------------------------------------------------------
$wslRuntimeAvailable = $false
$wslPath = (Get-Command wsl.exe -ErrorAction SilentlyContinue)
if ($wslPath) {
    $storeRuntime = Join-Path $env:ProgramFiles 'WSL\wsl.exe'
    $wslRuntimeAvailable = (Test-Path -LiteralPath $storeRuntime -PathType Leaf) -or (Get-Service WslService -ErrorAction SilentlyContinue) -or (Get-AppxPackage -Name MicrosoftCorporationII.WindowsSubsystemForLinux -ErrorAction SilentlyContinue)
}
$rootfs = $Rootfs
if (-not $rootfs) {
    $candidates = @(
        (Join-Path $PSScriptRoot '..\artifacts\final-package-27d17b1\SwitchTrade-unsigned-private-beta-27d17b1\payload\switchtrade-rootfs.tar.gz'),
        (Join-Path $PSScriptRoot '..\artifacts\final-package-27d17b1\payload\switchtrade-rootfs.tar.gz')
    )
    $rootfs = @($candidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1)
}
$disposable = ''
if ($wslRuntimeAvailable -and $rootfs -and (Test-Path -LiteralPath $rootfs -PathType Leaf)) {
    $disposable = 'SwitchTradeBoundaryTest-' + [guid]::NewGuid().ToString('N').Substring(0, 8)
    $disposableRoot = Join-Path $TestRoot ('wsl-' + $disposable)
    try {
        $import = Invoke-SwitchTradeWsl -Arguments @('--import', $disposable, $disposableRoot, $rootfs, '--version', '2') -TimeoutSeconds 600
        if ($import.ExitCode -ne 0) { throw "disposable import failed: $($import.Error)" }
        Write-Host "disposable distro $disposable imported for argv round trip"

        # 4a. Marker probe on a fresh import: either markerless (exit 44) or the generic
        #     rootfs marker (valid, no install id). Both prove the unowned fresh state.
        $probe = Get-SwitchTradeDistroMarkerProbe -Distro $disposable -TimeoutSeconds 60
        $freshStateOk = ($probe.Missing -and $probe.ExitCode -eq 44) -or ($probe.Valid -and -not $probe.InstallId)
        if (-not $freshStateOk) { throw 'fresh disposable import did not report an unowned marker state' }

        # 4b. Install-id marker write round trip (data as positional args).
        $testInstallId = '0123456789abcdef0123456789abcdef'
        Set-SwitchTradeDistroMarker -Distro $disposable -InstallId $testInstallId -TimeoutSeconds 60 | Out-Null
        $probe2 = Get-SwitchTradeDistroMarkerProbe -Distro $disposable -TimeoutSeconds 60
        if (-not $probe2.Valid -or $probe2.InstallId -cne $testInstallId) { throw 'marker write round trip failed' }

        # 4c. Exact argv round trip via --exec with shell-sensitive data.
        $bashArgs = @(
            'plain',
            'has space',
            'quote"inside',
            'trailing\',
            '',
            '유니코드 경로',
            'literal $p and $(whoami) and `echo hi`',
            'back\\slash',
            '{"json":["a","b"]}'
        )
        $bashScript = 'printf ''<%s>\n'' "$@"'
        $rr = Invoke-SwitchTradeWslCommand -Distro $disposable -Command (@('bash', '-c', $bashScript, '_') + $bashArgs) -TimeoutSeconds 60
        if ($rr.ExitCode -ne 0) { throw "wsl argv round trip failed: $($rr.Error)" }
        $bashLines = @($rr.Output -split "\r?\n" | Where-Object { $_ })
        if ($bashLines.Count -ne $bashArgs.Count) { throw "wsl argv count mismatch: expected $($bashArgs.Count), got $($bashLines.Count)" }
        for ($i = 0; $i -lt $bashLines.Count; $i++) {
            if ($bashLines[$i] -cne ("<" + $bashArgs[$i] + ">")) {
                throw "wsl argv[$i] corrupted: expected [<$($bashArgs[$i])>], got [$($bashLines[$i])]"
            }
        }

        # 4d. Constant-script sh execution with positional data (the ee6379c regression).
        $shArgs = @('alpha beta', '$p', '$(whoami)', '`echo hi`', '유니코드', 'end\')
        $shScript = 'i=1; for a in "$@"; do printf ''<%s>=<%s>\n'' "$i" "$a"; i=$((i+1)); done'
        $sr = Invoke-SwitchTradeWslSh -Distro $disposable -ScriptText $shScript -Arguments $shArgs -TimeoutSeconds 60
        if ($sr.ExitCode -ne 0) { throw "wsl sh round trip failed: $($sr.Error)" }
        $shLines = @($sr.Output -split "\r?\n" | Where-Object { $_ })
        $expectedSh = @()
        for ($i = 0; $i -lt $shArgs.Count; $i++) { $expectedSh += ("<" + ($i + 1) + ">=<" + $shArgs[$i] + ">") }
        if (($shLines -join '|') -cne ($expectedSh -join '|')) {
            throw "wsl sh positional data corrupted: got [$(($shLines -join '|'))], expected [$(($expectedSh -join '|'))]"
        }
    } finally {
        if ($disposable) {
            try { Invoke-SwitchTradeWsl -Arguments @('--terminate', $disposable) -TimeoutSeconds 60 | Out-Null } catch { }
            try { Invoke-SwitchTradeWsl -Arguments @('--unregister', $disposable) -TimeoutSeconds 120 | Out-Null } catch { }
            Write-Host "disposable distro $disposable removed"
        }
    }
} else {
    $gate = if (-not $wslRuntimeAvailable) { 'a real WSL 2 runtime is not installed on this host' } else { 'no SwitchTrade rootfs was provided (pass -Rootfs)' }
    Write-Host "SKIPPED real wsl.exe argv round trip (external gate: $gate)"
}

Write-Host 'Engine boundary simulation PASS'