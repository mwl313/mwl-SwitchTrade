[CmdletBinding()]
param([Parameter(Mandatory)][string]$TestRoot)

$ErrorActionPreference = 'Stop'
$TestRoot = [IO.Path]::GetFullPath($TestRoot)
New-Item -ItemType Directory -Force -Path $TestRoot | Out-Null
. (Join-Path $PSScriptRoot 'KernelLifecycle.ps1')
. (Join-Path $PSScriptRoot 'SetupLifecycle.ps1')

function New-TestRelease([string]$Root, [string]$ReleaseId) {
    New-Item -ItemType Directory -Force -Path $Root | Out-Null
    $config = Join-Path $Root 'config.json'
    '{"relay_url":"https://relay.invalid"}' | Set-Content -LiteralPath $config -Encoding UTF8
    $hash = Get-FileSha256 $config
    [ordered]@{
        schema = 2; release_id = $ReleaseId
        artifact_hashes = [ordered]@{ 'payload/release-config.json' = $hash }
    } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $Root 'manifest.json') -Encoding UTF8
    Write-WindowsReleaseMarker -Root $Root -ReleaseId $ReleaseId
}

foreach ($fault in @('after_active_retained', 'after_candidate_activated')) {
    $faultRoot = Join-Path $TestRoot $fault
    $faultActive = Join-Path $faultRoot 'active'
    $faultPrevious = Join-Path $faultRoot 'previous'
    $faultCandidate = Join-Path $faultRoot 'candidate'
    New-TestRelease -Root $faultActive -ReleaseId release-a
    New-TestRelease -Root $faultCandidate -ReleaseId release-b
    try {
        Commit-SwitchTradeWindowsRelease -Candidate $faultCandidate -Active $faultActive `
            -Previous $faultPrevious -ExpectedReleaseId release-b -FaultAfter $fault | Out-Null
        throw "fault $fault was not injected"
    } catch {
        if ([string]$_.Exception.Message -notmatch '^INJECTED_') { throw }
    }
    if ((Get-InstalledWindowsReleaseId $faultActive) -ne 'release-a' -or
        (Get-InstalledWindowsReleaseId $faultCandidate) -ne 'release-b' -or
        (Test-Path -LiteralPath $faultPrevious)) {
        throw "fault $fault left a mixed Windows release"
    }
}

$active = Join-Path $TestRoot 'active'
$previous = Join-Path $TestRoot 'previous'
$candidate = Join-Path $TestRoot 'candidate'
$transaction = Join-Path $TestRoot 'transaction.json'
New-TestRelease -Root $active -ReleaseId release-a
New-TestRelease -Root $candidate -ReleaseId release-b
New-SwitchTradeTransaction -Path $transaction -Action Update -ReleaseId release-b `
    -PriorReleaseId release-a -WindowsStage $candidate | Out-Null
$recordedTransaction = Get-Content -Raw -LiteralPath $transaction | ConvertFrom-Json
if ([int]$recordedTransaction.schema -ne 2 -or
        [string]$recordedTransaction.wsl_active_path -cne '/opt/switchtrade' -or
        [string]$recordedTransaction.wsl_commit_swap_path -cne '/opt/switchtrade.commit-swap' -or
        -not ($recordedTransaction.PSObject.Properties.Name -contains 'distro_existed_before')) {
    throw 'transaction did not persist exact pre-mutation paths and ownership facts'
}
Set-SwitchTradeTransactionPhase -Path $transaction -Phase windows_staged | Out-Null
$prior = Commit-SwitchTradeWindowsRelease -Candidate $candidate -Active $active `
    -Previous $previous -ExpectedReleaseId release-b
if ($prior -ne 'release-a' -or (Get-InstalledWindowsReleaseId $active) -ne 'release-b' -or
    (Get-InstalledWindowsReleaseId $previous) -ne 'release-a') {
    throw 'A to B commit did not preserve a coherent rollback pair'
}
Switch-SwitchTradeWindowsRollback -Active $active -Previous $previous `
    -ExpectedReleaseId release-a | Out-Null
if ((Get-InstalledWindowsReleaseId $active) -ne 'release-a' -or
    (Get-InstalledWindowsReleaseId $previous) -ne 'release-b') {
    throw 'B to A compensation did not restore the coherent prior pair'
}

$recoveryTransaction = [pscustomobject]@{
    schema = 2; transaction_id = 'test-transaction'; phase = 'wsl_staged'
    release_id = 'release-b'; prior_release_id = 'release-a'
    package_root = (Join-Path $TestRoot 'package-a')
    distro_existed_before = $true; distro_owned_before = $true
    wsl_prior_release_id = 'release-a'; kernel_prior_release_id = 'release-a'
    kernel_change_expected = $true
}
function New-RecoveryActual {
    param([hashtable]$Changes = @{})
    $value = [ordered]@{
        DistroExists = $true; DistroOwned = $true
        WindowsActiveExists = $true; WindowsActiveRelease = 'release-a'
        WindowsPreviousExists = $false; WindowsPreviousRelease = ''
        WindowsStageExists = $true
        WslActiveRelease = 'release-a'; WslCandidateExists = $true
        WslCandidateRelease = 'release-b'; WslPreviousRelease = ''
        WslCommitSwapExists = $false; WslCommitSwapRelease = ''
        KernelRelease = 'release-a'
    }
    foreach ($key in $Changes.Keys) { $value[$key] = $Changes[$key] }
    return [pscustomobject]$value
}

$phaseMatrix = @(
    @{
        Name = 'death_after_windows_stage_before_phase_persist'; Actual = (New-RecoveryActual -Changes @{
            WslCandidateExists = $false; WslCandidateRelease = ''
        })
        Windows = 'none'; Wsl = 'none'; Kernel = 'none'; RemoveStage = $true
    },
    @{
        Name = 'death_after_wsl_stage_before_phase_persist'; Actual = (New-RecoveryActual)
        Windows = 'none'; Wsl = 'abort_candidate'; Kernel = 'none'; RemoveStage = $true
    },
    @{
        Name = 'death_inside_wsl_commit_swap'; Actual = (New-RecoveryActual -Changes @{
            WslActiveRelease = ''; WslCommitSwapExists = $true
            WslCommitSwapRelease = 'release-a'
        })
        Windows = 'none'; Wsl = 'recover_interrupted'; Kernel = 'none'; RemoveStage = $true
    },
    @{
        Name = 'death_after_wsl_commit_before_phase_persist'; Actual = (New-RecoveryActual -Changes @{
            WslActiveRelease = 'release-b'; WslCandidateExists = $false
            WslCandidateRelease = ''; WslPreviousRelease = 'release-a'
        })
        Windows = 'none'; Wsl = 'compensate'; Kernel = 'none'; RemoveStage = $true
    },
    @{
        Name = 'death_after_kernel_apply_before_phase_persist'; Actual = (New-RecoveryActual -Changes @{
            KernelRelease = 'release-b'
        })
        Windows = 'none'; Wsl = 'abort_candidate'; Kernel = 'rollback'; RemoveStage = $true
    },
    @{
        Name = 'death_after_windows_move_before_phase_persist'; Actual = (New-RecoveryActual -Changes @{
            WindowsActiveExists = $false; WindowsActiveRelease = ''
            WindowsPreviousExists = $true; WindowsPreviousRelease = 'release-a'
        })
        Windows = 'restore_prior'; Wsl = 'abort_candidate'; Kernel = 'none'; RemoveStage = $true
    }
)
foreach ($case in $phaseMatrix) {
    $plan = Resolve-SwitchTradeTransactionRecovery -Transaction $recoveryTransaction `
        -Actual $case.Actual
    if ($plan.Disposition -ne 'compensate' -or $plan.WindowsAction -ne $case.Windows -or
            $plan.WslAction -ne $case.Wsl -or $plan.KernelAction -ne $case.Kernel -or
            $plan.RemoveStage -ne $case.RemoveStage) {
        throw "transaction recovery matrix failed: $($case.Name)"
    }
}

$committed = New-RecoveryActual -Changes @{
    WindowsActiveRelease = 'release-b'; WindowsPreviousExists = $true
    WindowsPreviousRelease = 'release-a'; WindowsStageExists = $false
    WslActiveRelease = 'release-b'; WslCandidateExists = $false; WslCandidateRelease = ''
    WslPreviousRelease = 'release-a'; KernelRelease = 'release-b'
}
$finalize = Resolve-SwitchTradeTransactionRecovery -Transaction $recoveryTransaction -Actual $committed
if ($finalize.Disposition -ne 'finalize') { throw 'coherent post-commit transaction was not finalized' }

$afterCompensation = New-RecoveryActual -Changes @{
    WindowsStageExists = $false; WslCandidateExists = $false; WslCandidateRelease = ''
}
$rerun = Resolve-SwitchTradeTransactionRecovery -Transaction $recoveryTransaction `
    -Actual $afterCompensation
if ($rerun.Disposition -ne 'compensate' -or $rerun.WindowsAction -ne 'none' -or
        $rerun.WslAction -ne 'none' -or $rerun.KernelAction -ne 'none') {
    throw 'rerun Repair did not converge on the proven prior release'
}

$newDistroTransaction = $recoveryTransaction.PSObject.Copy()
$newDistroTransaction.prior_release_id = ''
$newDistroTransaction.wsl_prior_release_id = ''
$newDistroTransaction.kernel_prior_release_id = ''
$newDistroTransaction.kernel_change_expected = $false
$newDistroTransaction.distro_existed_before = $false
$newDistroTransaction.distro_owned_before = $false
$newDistroActual = New-RecoveryActual -Changes @{
    WindowsActiveExists = $false; WindowsActiveRelease = ''; KernelRelease = ''
    WslActiveRelease = ''; WslCandidateExists = $false; WslCandidateRelease = ''
}
$newDistroPlan = Resolve-SwitchTradeTransactionRecovery -Transaction $newDistroTransaction `
    -Actual $newDistroActual
if ($newDistroPlan.WslAction -ne 'unregister_new') {
    throw 'death between distro import and phase persistence was not compensated from recorded pre-state'
}

$legacyFailedClosed = $false
try {
    $legacy = $recoveryTransaction.PSObject.Copy(); $legacy.schema = 1
    Resolve-SwitchTradeTransactionRecovery -Transaction $legacy -Actual $afterCompensation | Out-Null
} catch { $legacyFailedClosed = [string]$_.Exception.Message -match 'LEGACY_AMBIGUOUS' }
if (-not $legacyFailedClosed) { throw 'legacy ambiguous transaction did not fail closed' }

$mismatchFailedClosed = $false
try {
    Assert-SwitchTradeTransactionPackage -Transaction $recoveryTransaction `
        -PackageRoot (Join-Path $TestRoot 'package-b') -ReleaseId 'release-b'
} catch { $mismatchFailedClosed = [string]$_.Exception.Message -match 'PACKAGE_MISMATCH' }
if (-not $mismatchFailedClosed) { throw 'mismatched Repair package was accepted' }

$foreignFailedClosed = $false
try {
    $foreign = New-RecoveryActual -Changes @{ DistroOwned = $false }
    Resolve-SwitchTradeTransactionRecovery -Transaction $recoveryTransaction -Actual $foreign | Out-Null
} catch { $foreignFailedClosed = [string]$_.Exception.Message -match 'DISTRO_OWNERSHIP_CHANGED' }
if (-not $foreignFailedClosed) { throw 'foreign distro was accepted for transaction recovery' }

$unsafeStageFailedClosed = $false
try {
    Assert-SwitchTradeRecordedStagePath -Recorded (Join-Path $TestRoot 'outside\stage') `
        -InstallRoot (Join-Path $TestRoot 'Programs\SwitchTrade') | Out-Null
} catch { $unsafeStageFailedClosed = [string]$_.Exception.Message -match 'PATH_INVALID' }
if (-not $unsafeStageFailedClosed) { throw 'unvalidated transaction path was accepted' }

'tampered' | Set-Content -LiteralPath (Join-Path $previous 'config.json') -Encoding UTF8
$failedClosed = $false
try {
    Switch-SwitchTradeWindowsRollback -Active $active -Previous $previous `
        -ExpectedReleaseId release-b | Out-Null
} catch {
    $failedClosed = [string]$_.Exception.Message -match 'ROLLBACK_WINDOWS_HASH_MISMATCH'
}
if (-not $failedClosed -or (Get-InstalledWindowsReleaseId $active) -ne 'release-a' -or
    (Get-InstalledWindowsReleaseId $previous) -ne 'release-b') {
    throw 'corrupt rollback validation mutated the active/retained release pair'
}

$redacted = Redact-SwitchTradeSetupText 'Authorization: Bearer abc.def reconnect_token=secret'
if ($redacted -match 'abc\.def|=secret') { throw 'setup log redaction failed' }
$usbState = '{"Devices":[{"BusId":"9-4","InstanceId":"USB\\VID_0BDA&PID_818B\\RADIO-A"},{"BusId":"1-2","InstanceId":"USB\\VID_0BDA&PID_818B\\RADIO-B"}]}' | ConvertFrom-Json
$resolved = Resolve-SwitchTradeUsbDeviceFromState -State $usbState `
    -InstanceId 'USB\VID_0BDA&PID_818B\RADIO-A' -UsbId '0bda:818b'
if ([string]$resolved.BusId -ne '9-4') { throw 'stable USB identity did not survive a bus-ID change' }
$selection = Write-SwitchTradeHardwareSelection -StateRoot $TestRoot -UsbId '0bda:818b' `
    -InstanceId 'USB\VID_0BDA&PID_818B\RADIO-A' -BusId '9-4'
$savedSelection = Get-Content -Raw -LiteralPath $selection | ConvertFrom-Json
if ([string]$savedSelection.instance_id -ne 'USB\VID_0BDA&PID_818B\RADIO-A' -or
    [string]$savedSelection.bus_id -ne '9-4') { throw 'stable USB selection was not persisted' }

Test-SwitchTradeWslCapabilities -VersionText 'WSL version: 2.6.1.0' `
    -HelpText '--import --distribution --cd --version' | Out-Null
Test-SwitchTradeUsbipdCapabilities -VersionText '5.3.0' -MinimumVersion ([version]'5.3.0') `
    -HelpText 'attach bind state --wsl --busid' -State ($usbState) | Out-Null

$argumentScript = Join-Path $TestRoot 'echo-argument.ps1'
'param([string]$Value); [Console]::Out.Write($Value)' | Set-Content -LiteralPath $argumentScript -Encoding UTF8
$argumentValue = Join-Path $TestRoot '공백 경로\usbipd-win.msi'
$argumentResult = Invoke-BoundedNativeProcess -FilePath 'powershell.exe' `
    -Arguments @('-NoProfile', '-File', $argumentScript, '-Value', $argumentValue) -TimeoutSeconds 10
if ($argumentResult.ExitCode -ne 0 -or $argumentResult.Output -cne $argumentValue) {
    throw 'argument-safe process invocation corrupted a path with spaces/non-ASCII characters'
}
$timedOut = $false
try {
    Invoke-BoundedNativeProcess -FilePath 'powershell.exe' `
        -Arguments @('-NoProfile', '-Command', 'Start-Sleep -Seconds 3') -TimeoutSeconds 1 | Out-Null
} catch { $timedOut = [string]$_.Exception.Message -match '^PROCESS_TIMEOUT:' }
if (-not $timedOut) { throw 'bounded child process did not time out' }

$watcherState = Join-Path $TestRoot 'watcher-state'
New-Item -ItemType Directory -Force -Path $watcherState | Out-Null
Write-AtomicJson -Path (Join-Path $watcherState 'usb-watcher.json') -Value `
    ([ordered]@{ schema = 1; pid = 2147483647; instance_id = 'test'; distro = 'test' })
Stop-SwitchTradeUsbWatcher -StateRoot $watcherState | Out-Null
if (Test-Path -LiteralPath (Join-Path $watcherState 'usb-watcher.json')) {
    throw 'stale watcher state was not cleaned during uninstall simulation'
}
$watcherCommand = Get-SwitchTradeUsbWatcherCommand `
    -ScriptPath (Join-Path $TestRoot '공백 경로\UsbAutoAttachWatcher.ps1') -Distro 'Switch Trade' `
    -InstanceId 'USB\VID_0BDA&PID_818B\stable' -StateFile (Join-Path $TestRoot '공백 경로\watcher.json')
if ($watcherCommand -notmatch 'UsbAutoAttachWatcher\.ps1"' -or
    $watcherCommand -notmatch 'USB\\VID_0BDA&PID_818B\\stable') {
    throw 'restart watcher command did not preserve stable identity and argument quoting'
}
Write-Host 'Setup lifecycle simulation PASS'
