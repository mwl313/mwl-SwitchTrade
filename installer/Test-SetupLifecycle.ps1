[CmdletBinding()]
param([Parameter(Mandatory)][string]$TestRoot)

$ErrorActionPreference = 'Stop'
$TestRoot = [IO.Path]::GetFullPath($TestRoot)
New-Item -ItemType Directory -Force -Path $TestRoot | Out-Null
. (Join-Path $PSScriptRoot 'KernelLifecycle.ps1')
. (Join-Path $PSScriptRoot 'SetupLifecycle.ps1')
$integrityByRoot = @{}

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
    $script:integrityByRoot[[IO.Path]::GetFullPath($Root)] =
        Write-SwitchTradeTreeIntegrity -Root $Root -ReleaseId $ReleaseId
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
    -PriorReleaseId release-a -WindowsStage $candidate -InstallId ('1' * 32) `
    -DistroBasePath (Join-Path $TestRoot 'wsl') | Out-Null
$recordedTransaction = Get-Content -Raw -LiteralPath $transaction | ConvertFrom-Json
if ([int]$recordedTransaction.schema -ne 3 -or
        [string]$recordedTransaction.wsl_active_path -cne '/opt/switchtrade' -or
        [string]$recordedTransaction.wsl_commit_swap_path -cne '/opt/switchtrade.commit-swap' -or
        [string]$recordedTransaction.wsl_rollback_swap_path -cne '/opt/switchtrade.rollback-swap' -or
        [string]$recordedTransaction.install_id -cne ('1' * 32) -or
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

$completedTransaction = [pscustomobject]@{
    schema = 3; transaction_id = 'completed-transaction'; phase = 'completed'; action = 'Update'
    release_id = 'release-b'; prior_release_id = 'release-a'
    distro_name = 'SwitchTrade'; distro_base_path = (Join-Path $TestRoot 'wsl')
    install_id = ('1' * 32); wsl_prior_release_id = 'release-a'
    kernel_prior_release_id = 'release-a'; kernel_prior_path = 'kernel-a'
    kernel_prior_modules_path = 'modules-a'
    windows_integrity_sha256 = $integrityByRoot[[IO.Path]::GetFullPath($candidate)]
    windows_prior_integrity_sha256 = $integrityByRoot[[IO.Path]::GetFullPath($active)]
    wsl_integrity_sha256 = ('b' * 64); wsl_prior_integrity_sha256 = ('a' * 64)
}
$rolledBackKernel = [pscustomobject]@{
    package_release_id = 'release-a'; rollback_package_release_id = 'release-b'
    rollback_kernel_path = 'kernel-b'; rollback_modules_path = 'modules-b'
}
$rotatedPath = Join-Path $TestRoot 'rotated-transaction.json'
Write-AtomicJson -Path $rotatedPath -Value $completedTransaction
$rotated = Set-SwitchTradeCompletedRollbackState -Path $rotatedPath -Transaction $completedTransaction -KernelState $rolledBackKernel
if ($rotated.release_id -ne 'release-a' -or $rotated.prior_release_id -ne 'release-b' -or
        $rotated.wsl_prior_release_id -ne 'release-b' -or
        $rotated.kernel_prior_release_id -ne 'release-b' -or
        $rotated.kernel_prior_path -ne 'kernel-b' -or
        $rotated.windows_integrity_sha256 -ne $completedTransaction.windows_prior_integrity_sha256 -or
        $rotated.wsl_integrity_sha256 -ne $completedTransaction.wsl_prior_integrity_sha256) {
    throw 'successful rollback did not rotate every active/prior identity and integrity anchor'
}
Test-SwitchTradeTreeIntegrity -Root $active -ExpectedReleaseId release-a -ExpectedIntegritySha256 ([string]$rotated.windows_integrity_sha256) | Out-Null
$repairAnchors = Get-SwitchTradeTrustedInstalledAnchors -Transaction $rotated -ReleaseId release-a
if ($repairAnchors.Windows -ne $rotated.windows_integrity_sha256 -or
        $repairAnchors.Wsl -ne $rotated.wsl_integrity_sha256) {
    throw 'Repair did not consume the rotated completed transaction anchors'
}
Switch-SwitchTradeWindowsRollback -Active $active -Previous $previous -ExpectedReleaseId release-b -ExpectedActiveReleaseId release-a | Out-Null
$reverseKernel = [pscustomobject]@{
    package_release_id = 'release-b'; rollback_package_release_id = 'release-a'
    rollback_kernel_path = 'kernel-a'; rollback_modules_path = 'modules-a'
}
$reverse = Set-SwitchTradeCompletedRollbackState -Path $rotatedPath -Transaction $rotated -KernelState $reverseKernel
if ($reverse.release_id -ne 'release-b' -or $reverse.prior_release_id -ne 'release-a' -or
        $reverse.windows_integrity_sha256 -ne $completedTransaction.windows_integrity_sha256 -or
        $reverse.wsl_integrity_sha256 -ne $completedTransaction.wsl_integrity_sha256) {
    throw 'Repair validation followed by reverse rollback did not restore trusted active anchors'
}
Switch-SwitchTradeWindowsRollback -Active $active -Previous $previous -ExpectedReleaseId release-a -ExpectedActiveReleaseId release-b | Out-Null

$persistFaultRoot = Join-Path $TestRoot 'rollback-persist-fault'
$persistActive = Join-Path $persistFaultRoot 'active'
$persistPrevious = Join-Path $persistFaultRoot 'previous'
$persistTransaction = Join-Path $persistFaultRoot 'transaction.json'
New-TestRelease -Root $persistActive -ReleaseId release-b
New-TestRelease -Root $persistPrevious -ReleaseId release-a
Write-AtomicJson -Path $persistTransaction -Value $completedTransaction
Switch-SwitchTradeWindowsRollback -Active $persistActive -Previous $persistPrevious -ExpectedReleaseId release-a -ExpectedActiveReleaseId release-b | Out-Null
$savedAtomicWriter = (Get-Item Function:\Write-AtomicJson).ScriptBlock
try {
    Set-Item Function:\Write-AtomicJson -Value { throw 'INJECTED_ROLLBACK_TRANSACTION_PERSIST_FAILURE' }
    try {
        Set-SwitchTradeCompletedRollbackState -Path $persistTransaction -Transaction $completedTransaction -KernelState $rolledBackKernel | Out-Null
        throw 'rollback transaction persistence fault was not injected'
    } catch {
        if ([string]$_.Exception.Message -notmatch '^INJECTED_ROLLBACK_TRANSACTION_PERSIST_FAILURE') {
            throw
        }
        Switch-SwitchTradeWindowsRollback -Active $persistActive -Previous $persistPrevious -ExpectedReleaseId release-b -ExpectedActiveReleaseId release-a | Out-Null
    }
} finally {
    Set-Item Function:\Write-AtomicJson -Value $savedAtomicWriter
}
$persistedAfterFault = Get-Content -Raw -LiteralPath $persistTransaction | ConvertFrom-Json
if ((Get-InstalledWindowsReleaseId $persistActive) -ne 'release-b' -or
        (Get-InstalledWindowsReleaseId $persistPrevious) -ne 'release-a' -or
        $persistedAfterFault.release_id -ne 'release-b') {
    throw 'rollback transaction persistence failure did not compensate to the original release'
}

$recoveryTransaction = [pscustomobject]@{
    schema = 3; transaction_id = 'test-transaction'; phase = 'wsl_staged'
    release_id = 'release-b'; prior_release_id = 'release-a'
    package_root = (Join-Path $TestRoot 'package-a')
    install_id = ('1' * 32); distro_base_path = (Join-Path $TestRoot 'wsl')
    distro_existed_before = $true; distro_owned_before = $true
    wsl_prior_release_id = 'release-a'; kernel_prior_release_id = 'release-a'
    kernel_change_expected = $true
    windows_integrity_sha256 = ('b' * 64); wsl_integrity_sha256 = ('c' * 64)
    windows_prior_integrity_sha256 = ('a' * 64); wsl_prior_integrity_sha256 = ('d' * 64)
}
function New-RecoveryActual {
    param([hashtable]$Changes = @{})
    $value = [ordered]@{
        EnumerationKnown = $true; DistroExists = $true; DistroOwned = $true
        DistroInstallId = ('1' * 32); DistroBasePath = (Join-Path $TestRoot 'wsl')
        WindowsActiveExists = $true; WindowsActiveRelease = 'release-a'
        WindowsActiveIntegrity = ('a' * 64)
        WindowsPreviousExists = $false; WindowsPreviousRelease = ''
        WindowsSwapExists = $false; WindowsSwapRelease = ''
        WindowsStageExists = $true
        WslActiveRelease = 'release-a'; WslCandidateExists = $true
        WslCandidateRelease = 'release-b'; WslPreviousRelease = ''
        WslCommitSwapExists = $false; WslCommitSwapRelease = ''
        WslRollbackSwapExists = $false; WslRollbackSwapRelease = ''
        WslActiveIntegrity = ('d' * 64)
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

$unanchoredCandidate = $recoveryTransaction | ConvertTo-Json -Depth 8 | ConvertFrom-Json
$unanchoredCandidate.wsl_integrity_sha256 = ''
$unanchoredCandidate.phase = 'staging_wsl'
$coherentlyTamperedCandidate = New-RecoveryActual -Changes @{
    WslCandidateIntegrity = ('e' * 64); WslCandidateArtifactsMatchManifest = $true
}
$unanchoredPlan = Resolve-SwitchTradeTransactionRecovery -Transaction $unanchoredCandidate -Actual $coherentlyTamperedCandidate
if ($unanchoredPlan.Disposition -ne 'compensate' -or $unanchoredPlan.WslAction -ne 'abort_candidate') {
    throw 'post-crash unanchored WSL candidate was trusted instead of discarded for exact restaging'
}

$committed = New-RecoveryActual -Changes @{
    WindowsActiveRelease = 'release-b'; WindowsPreviousExists = $true
    WindowsActiveIntegrity = ('b' * 64)
    WindowsPreviousRelease = 'release-a'; WindowsStageExists = $false
    WslActiveRelease = 'release-b'; WslCandidateExists = $false; WslCandidateRelease = ''
    WslPreviousRelease = 'release-a'; WslActiveIntegrity = ('c' * 64); KernelRelease = 'release-b'
}
$finalize = Resolve-SwitchTradeTransactionRecovery -Transaction $recoveryTransaction -Actual $committed
if ($finalize.Disposition -ne 'finalize') { throw 'coherent post-commit transaction was not finalized' }

$missingRequired = Join-Path $TestRoot 'missing-required'
New-TestRelease -Root $missingRequired -ReleaseId release-b
$missingIntegrity = $integrityByRoot[[IO.Path]::GetFullPath($missingRequired)]
Remove-Item -LiteralPath (Join-Path $missingRequired 'config.json') -Force
$missingFailedClosed = $false
try {
    Test-SwitchTradeTreeIntegrity -Root $missingRequired -ExpectedReleaseId release-b `
        -ExpectedIntegritySha256 $missingIntegrity | Out-Null
} catch { $missingFailedClosed = [string]$_.Exception.Message -match 'ARTIFACT' }
if (-not $missingFailedClosed) { throw 'required Windows artifact deletion was finalized' }

$unexpectedArtifact = Join-Path $TestRoot 'unexpected-artifact'
New-TestRelease -Root $unexpectedArtifact -ReleaseId release-b
$unexpectedIntegrity = $integrityByRoot[[IO.Path]::GetFullPath($unexpectedArtifact)]
'tampered' | Set-Content -LiteralPath (Join-Path $unexpectedArtifact 'injected.exe') -Encoding UTF8
$unexpectedFailedClosed = $false
try {
    Test-SwitchTradeTreeIntegrity -Root $unexpectedArtifact -ExpectedReleaseId release-b `
        -ExpectedIntegritySha256 $unexpectedIntegrity | Out-Null
} catch { $unexpectedFailedClosed = [string]$_.Exception.Message -match 'ARTIFACT' }
if (-not $unexpectedFailedClosed) { throw 'unexpected Windows artifact was finalized' }

$afterCompensation = New-RecoveryActual -Changes @{
    WindowsStageExists = $false; WslCandidateExists = $false; WslCandidateRelease = ''
}
$rerun = Resolve-SwitchTradeTransactionRecovery -Transaction $recoveryTransaction `
    -Actual $afterCompensation
if ($rerun.Disposition -ne 'compensate' -or $rerun.WindowsAction -ne 'none' -or
        $rerun.WslAction -ne 'none' -or $rerun.KernelAction -ne 'none') {
    throw 'rerun Repair did not converge on the proven prior release'
}
$secondRerun = Resolve-SwitchTradeTransactionRecovery -Transaction $recoveryTransaction `
    -Actual $afterCompensation
if ($secondRerun.WindowsAction -ne 'none' -or $secondRerun.WslAction -ne 'none' -or
        $secondRerun.KernelAction -ne 'none') {
    throw 'second Repair pass was not idempotent after compensation'
}

$compensationFaults = @(
    @{ Name = 'after_kernel_rollback'; Changes = @{ KernelRelease = 'release-a' }; Wsl = 'abort_candidate' },
    @{ Name = 'after_candidate_abort'; Changes = @{
        WslCandidateExists = $false; WslCandidateRelease = ''
    }; Wsl = 'none' },
    @{ Name = 'after_wsl_active_moved_to_rollback_swap'; Changes = @{
        WslActiveRelease = ''; WslPreviousRelease = 'release-a'
        WslCandidateExists = $false; WslCandidateRelease = ''
        WslRollbackSwapExists = $true; WslRollbackSwapRelease = 'release-b'
    }; Wsl = 'compensate' },
    @{ Name = 'after_wsl_prior_activated'; Changes = @{
        WslActiveRelease = 'release-a'; WslPreviousRelease = ''
        WslCandidateExists = $false; WslCandidateRelease = ''
        WslRollbackSwapExists = $true; WslRollbackSwapRelease = 'release-b'
    }; Wsl = 'compensate' },
    @{ Name = 'after_wsl_compensation'; Changes = @{
        WslActiveRelease = 'release-a'; WslPreviousRelease = 'release-b'
        WslCandidateExists = $false; WslCandidateRelease = ''
    }; Wsl = 'none' },
    @{ Name = 'after_commit_target_moved_to_candidate'; Changes = @{
        WslActiveRelease = ''; WslCandidateExists = $true; WslCandidateRelease = 'release-b'
        WslCommitSwapExists = $true; WslCommitSwapRelease = 'release-a'
    }; Wsl = 'recover_interrupted' },
    @{ Name = 'after_commit_prior_restored'; Changes = @{
        WslActiveRelease = 'release-a'; WslCandidateExists = $true
        WslCandidateRelease = 'release-b'; WslCommitSwapExists = $false
        WslCommitSwapRelease = ''
    }; Wsl = 'abort_candidate' }
)
foreach ($fault in $compensationFaults) {
    $faultPlan = Resolve-SwitchTradeTransactionRecovery -Transaction $recoveryTransaction `
        -Actual (New-RecoveryActual -Changes $fault.Changes)
    if ($faultPlan.WslAction -ne $fault.Wsl) {
        throw "compensation fault did not converge: $($fault.Name)"
    }
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
    $legacy = $recoveryTransaction.PSObject.Copy(); $legacy.schema = 2
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

$copiedMarkerFailedClosed = $false
try {
    $copiedMarker = New-RecoveryActual -Changes @{
        DistroOwned = $true; DistroInstallId = ''; DistroBasePath = (Join-Path $TestRoot 'foreign-wsl')
    }
    Resolve-SwitchTradeTransactionRecovery -Transaction $recoveryTransaction `
        -Actual $copiedMarker | Out-Null
} catch { $copiedMarkerFailedClosed = [string]$_.Exception.Message -match 'DISTRO_IDENTITY_CHANGED' }
if (-not $copiedMarkerFailedClosed) {
    throw 'copied generic-marker foreign distro was accepted for unregister or mutation'
}

$validPurgeIdentity = [pscustomobject]@{
    EnumerationKnown = $true; DistroExists = $true; RegistrationExists = $true
    BasePath = (Join-Path $TestRoot 'wsl'); MarkerValid = $true; InstallId = ('1' * 32)
}
Assert-SwitchTradeDistroMutationIdentity -Transaction $completedTransaction -DistroName SwitchTrade -DistroRoot (Join-Path $TestRoot 'wsl') -Actual $validPurgeIdentity | Out-Null
$purgeMutations = 0
$enumerationUnavailable = $false
try {
    $unknownPurgeIdentity = $validPurgeIdentity.PSObject.Copy()
    $unknownPurgeIdentity.EnumerationKnown = $false
    Assert-SwitchTradeDistroMutationIdentity -Transaction $completedTransaction -DistroName SwitchTrade -DistroRoot (Join-Path $TestRoot 'wsl') -Actual $unknownPurgeIdentity | Out-Null
    $purgeMutations++
} catch { $enumerationUnavailable = [string]$_.Exception.Message -match 'ENUMERATION_UNKNOWN' }
if (-not $enumerationUnavailable -or $purgeMutations -ne 0) {
    throw 'unknown purge enumeration performed a host mutation'
}
$swapRaceFailedClosed = $false
try {
    Assert-SwitchTradeDistroMutationIdentity -Transaction $completedTransaction -DistroName SwitchTrade -DistroRoot (Join-Path $TestRoot 'wsl') -Actual $validPurgeIdentity | Out-Null
    $swappedPurgeIdentity = $validPurgeIdentity.PSObject.Copy()
    $swappedPurgeIdentity.BasePath = Join-Path $TestRoot 'foreign-wsl'
    $swappedPurgeIdentity.InstallId = ('2' * 32)
    Assert-SwitchTradeDistroMutationIdentity -Transaction $completedTransaction -DistroName SwitchTrade -DistroRoot (Join-Path $TestRoot 'wsl') -Actual $swappedPurgeIdentity | Out-Null
    $purgeMutations++
} catch { $swapRaceFailedClosed = [string]$_.Exception.Message -match 'IDENTITY_CHANGED' }
if (-not $swapRaceFailedClosed -or $purgeMutations -ne 0) {
    throw 'PurgeDistro swap race performed a host mutation or unregister'
}

foreach ($fault in @('after_active_swapped', 'after_prior_activated')) {
    $root = Join-Path $TestRoot "recovery-$fault"
    $faultActive = Join-Path $root 'active'
    $faultPrevious = Join-Path $root 'previous'
    $faultSwap = "$faultActive.rollback-swap"
    New-TestRelease -Root $faultActive -ReleaseId release-b
    New-TestRelease -Root $faultPrevious -ReleaseId release-a
    Move-Item -LiteralPath $faultActive -Destination $faultSwap
    if ($fault -eq 'after_prior_activated') {
        Move-Item -LiteralPath $faultPrevious -Destination $faultActive
    }
    Switch-SwitchTradeWindowsRollback -Active $faultActive -Previous $faultPrevious `
        -ExpectedReleaseId release-a -ExpectedActiveReleaseId release-b | Out-Null
    if ((Get-InstalledWindowsReleaseId $faultActive) -ne 'release-a' -or
            (Get-InstalledWindowsReleaseId $faultPrevious) -ne 'release-b' -or
            (Test-Path -LiteralPath $faultSwap)) {
        throw "interrupted Windows compensation did not converge: $fault"
    }
    Switch-SwitchTradeWindowsRollback -Active $faultActive -Previous $faultPrevious `
        -ExpectedReleaseId release-b -ExpectedActiveReleaseId release-a | Out-Null
    if ((Get-InstalledWindowsReleaseId $faultActive) -ne 'release-b') {
        throw "subsequent Windows rollback failed after recovered compensation: $fault"
    }
}

$windowsSwapPlan = Resolve-SwitchTradeTransactionRecovery -Transaction $recoveryTransaction `
    -Actual (New-RecoveryActual -Changes @{
        WindowsActiveExists = $false; WindowsActiveRelease = ''
        WindowsPreviousExists = $true; WindowsPreviousRelease = 'release-a'
        WindowsSwapExists = $true; WindowsSwapRelease = 'release-b'
    })
if ($windowsSwapPlan.WindowsAction -ne 'rollback') {
    throw 'interrupted Windows rollback swap was not resumed'
}
$wslSwapPlan = Resolve-SwitchTradeTransactionRecovery -Transaction $recoveryTransaction `
    -Actual (New-RecoveryActual -Changes @{
        WslActiveRelease = ''; WslPreviousRelease = 'release-a'
        WslRollbackSwapExists = $true; WslRollbackSwapRelease = 'release-b'
    })
if ($wslSwapPlan.WslAction -ne 'compensate') {
    throw 'interrupted WSL rollback swap was not resumed'
}

$enumerationFailedClosed = $false
try {
    $unknownEnumeration = New-RecoveryActual -Changes @{ EnumerationKnown = $false }
    Resolve-SwitchTradeTransactionRecovery -Transaction $recoveryTransaction `
        -Actual $unknownEnumeration | Out-Null
} catch { $enumerationFailedClosed = [string]$_.Exception.Message -match 'ENUMERATION_UNKNOWN' }
if (-not $enumerationFailedClosed) { throw 'unknown WSL enumeration mutated recovery state' }
$enumerationRetry = Resolve-SwitchTradeTransactionRecovery -Transaction $recoveryTransaction `
    -Actual (New-RecoveryActual)
if ($enumerationRetry.Disposition -ne 'compensate') {
    throw 'recovery did not retry after transient WSL enumeration failure'
}

$unsafeStageFailedClosed = $false
try {
    Assert-SwitchTradeRecordedStagePath -Recorded (Join-Path $TestRoot 'outside\stage') `
        -InstallRoot (Join-Path $TestRoot 'Programs\SwitchTrade') | Out-Null
} catch { $unsafeStageFailedClosed = [string]$_.Exception.Message -match 'PATH_INVALID' }
if (-not $unsafeStageFailedClosed) { throw 'unvalidated transaction path was accepted' }

$partialCleanup = Join-Path $TestRoot 'partial-cleanup'
New-Item -ItemType Directory -Force -Path (Join-Path $partialCleanup 'nested') | Out-Null
'one' | Set-Content -LiteralPath (Join-Path $partialCleanup 'one.txt') -Encoding UTF8
'two' | Set-Content -LiteralPath (Join-Path $partialCleanup 'nested\two.txt') -Encoding UTF8
Remove-Item -LiteralPath (Join-Path $partialCleanup 'one.txt') -Force
Remove-SwitchTradeRecoveryTree -Path $partialCleanup -ReparseCode 'TEST_REPARSE' | Out-Null
Remove-SwitchTradeRecoveryTree -Path $partialCleanup -ReparseCode 'TEST_REPARSE' | Out-Null
if (Test-Path -LiteralPath $partialCleanup) {
    throw 'partial recovery cleanup did not converge across two Repair passes'
}

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
$nulSeparatedVersion = [string]::Join([char]0, 'WSL version: 2.7.12.0'.ToCharArray())
$nulSeparatedHelp = [string]::Join([char]0, '--import --distribution --cd --version'.ToCharArray())
Test-SwitchTradeWslCapabilities -VersionText $nulSeparatedVersion -HelpText $nulSeparatedHelp | Out-Null
$missingWslCapabilityRejected = $false
try {
    Test-SwitchTradeWslCapabilities -VersionText 'WSL version: 2.7.12.0' `
        -HelpText '--import --distribution --version' | Out-Null
} catch { $missingWslCapabilityRejected = [string]$_.Exception.Message -match '^WSL_CAPABILITY_MISSING: --cd' }
if (-not $missingWslCapabilityRejected) { throw 'WSL capability validation did not fail closed' }
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
