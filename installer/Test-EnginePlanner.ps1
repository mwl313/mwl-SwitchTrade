[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$TestRoot
)

$ErrorActionPreference = 'Stop'
$TestRoot = [IO.Path]::GetFullPath($TestRoot)
New-Item -ItemType Directory -Force -Path $TestRoot | Out-Null
. (Join-Path $PSScriptRoot 'engine\PlatformOps.ps1')
. (Join-Path $PSScriptRoot 'engine\StateInspector.ps1')
. (Join-Path $PSScriptRoot 'engine\Planner.ps1')
# Capture the engine marker-bootstrap gate before SetupLifecycle.ps1 shadows the name.
${engineMarkerBootstrapGate} = ${function:Test-SwitchTradeFreshImportMarkerBootstrap}
. (Join-Path $PSScriptRoot 'KernelLifecycle.ps1')
. (Join-Path $PSScriptRoot 'SetupLifecycle.ps1')

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

# Build a normalized State snapshot fixture (pure objects; no I/O).
function New-TestState {
    param(
        [hashtable]$Identity = @{},
        $Transaction = $null,
        [hashtable]$WindowsActive = @{},
        [hashtable]$WindowsPrevious = @{},
        [hashtable]$WindowsSwap = @{},
        [bool]$WindowsStageExists = $false,
        [hashtable]$Kernel = @{},
        [hashtable]$WslActive = @{},
        [hashtable]$WslCandidate = @{},
        [hashtable]$WslPrevious = @{},
        [hashtable]$WslCommitSwap = @{},
        [hashtable]$WslRollbackSwap = @{}
    )
    $emptyTree = { [pscustomobject]@{ Exists = $false; Valid = $true; ReleaseId = ''; IntegritySha256 = '' } }
    $kernelDefaults = @{ Exists = $false; Valid = $false; ReleaseId = ''; State = $null }
    function Merge-TestDefaults {
        param([Parameter(Mandatory)]$Defaults, [hashtable]$Overrides = @{})
        $result = [pscustomobject]$Defaults
        foreach ($key in $Overrides.Keys) {
            $result | Add-Member -NotePropertyName $key -NotePropertyValue $Overrides[$key] -Force
        }
        return $result
    }
    return [pscustomobject]@{
        Context = $null
        Host = [pscustomobject]@{ WindowsSupported = $true; FreeSpaceGB = 100; VirtualizationReady = $true; PendingReboot = $false; WslInstalled = $true; WslCapabilityReady = $true; VmwareUsbArbitrator = 'Absent' }
        WslCapability = [pscustomobject]@{ Version = '2.7.12'; MinimumMet = $true; CapabilityReady = $true; ProbeFailed = $false }
        Identity = Merge-TestDefaults -Defaults @{
            Classification = 'absent'; DistroExists = $false; EnumerationKnown = $true
            RegistrationExists = $false; BasePath = ''; MarkerMissing = $false
            MarkerValid = $false; InstallId = ''
        } -Overrides $Identity
        Transaction = [pscustomobject]@{
            Classification = 'absent'; Transaction = $Transaction; Phase = if ($Transaction) { [string]$Transaction.phase } else { '' }
            Schema = if ($Transaction) { [int]$Transaction.schema } else { 0 }
            TransactionId = if ($Transaction) { [string]$Transaction.transaction_id } else { '' }
            ReleaseId = if ($Transaction) { [string]$Transaction.release_id } else { '' }
        }
        WindowsActive = Merge-TestDefaults -Defaults @{ Exists = $false; Valid = $false; ReleaseId = ''; IntegritySha256 = '' } -Overrides $WindowsActive
        WindowsPrevious = Merge-TestDefaults -Defaults @{ Exists = $false; Valid = $false; ReleaseId = ''; IntegritySha256 = '' } -Overrides $WindowsPrevious
        WindowsSwap = Merge-TestDefaults -Defaults @{ Exists = $false; Valid = $false; ReleaseId = ''; IntegritySha256 = '' } -Overrides $WindowsSwap
        WindowsStageExists = $WindowsStageExists
        Kernel = Merge-TestDefaults -Defaults $kernelDefaults -Overrides $Kernel
        WslActive = Merge-TestDefaults -Defaults @{ Exists = $false; Valid = $true; ReleaseId = ''; IntegritySha256 = '' } -Overrides $WslActive
        WslCandidate = Merge-TestDefaults -Defaults @{ Exists = $false; Valid = $true; ReleaseId = ''; IntegritySha256 = '' } -Overrides $WslCandidate
        WslPrevious = Merge-TestDefaults -Defaults @{ Exists = $false; Valid = $true; ReleaseId = ''; IntegritySha256 = '' } -Overrides $WslPrevious
        WslCommitSwap = Merge-TestDefaults -Defaults @{ Exists = $false; Valid = $true; ReleaseId = ''; IntegritySha256 = '' } -Overrides $WslCommitSwap
        WslRollbackSwap = Merge-TestDefaults -Defaults @{ Exists = $false; Valid = $true; ReleaseId = ''; IntegritySha256 = '' } -Overrides $WslRollbackSwap
        Resume = $null
        UsbipdInstalled = $true
        UsbipdPath = ''
        StageParent = $TestRoot
        Correlations = [ordered]@{}
    }
}

# Legacy DistroOwned includes the recorded install-id match (SwitchTradeSetup.ps1:652).
function ConvertTo-LegacyActual {
    param([Parameter(Mandatory)]$State, $Transaction = $null)
    $identity = $State.Identity
    $expectedId = if ($Transaction) { [string]$Transaction.install_id } else { '' }
    $distroOwned = $identity.DistroExists -and $identity.MarkerValid -and
        (-not $expectedId -or $identity.InstallId -ceq $expectedId)
    return [pscustomobject]@{
        EnumerationKnown = [bool]$identity.EnumerationKnown
        DistroExists = [bool]$identity.DistroExists
        DistroOwned = $distroOwned
        DistroInstallId = [string]$identity.InstallId
        DistroBasePath = [string]$identity.BasePath
        WindowsActiveExists = [bool]$State.WindowsActive.Exists
        WindowsActiveRelease = [string]$State.WindowsActive.ReleaseId
        WindowsActiveIntegrity = [string]$State.WindowsActive.IntegritySha256
        WindowsPreviousExists = [bool]$State.WindowsPrevious.Exists
        WindowsPreviousRelease = [string]$State.WindowsPrevious.ReleaseId
        WindowsPreviousIntegrity = [string]$State.WindowsPrevious.IntegritySha256
        WindowsSwapExists = [bool]$State.WindowsSwap.Exists
        WindowsSwapRelease = [string]$State.WindowsSwap.ReleaseId
        WindowsSwapIntegrity = [string]$State.WindowsSwap.IntegritySha256
        WindowsStageExists = [bool]$State.WindowsStageExists
        WslActiveRelease = [string]$State.WslActive.ReleaseId
        WslActiveIntegrity = [string]$State.WslActive.IntegritySha256
        WslCandidateExists = [bool]$State.WslCandidate.Exists
        WslCandidateRelease = [string]$State.WslCandidate.ReleaseId
        WslPreviousRelease = [string]$State.WslPrevious.ReleaseId
        WslCommitSwapExists = [bool]$State.WslCommitSwap.Exists
        WslCommitSwapRelease = [string]$State.WslCommitSwap.ReleaseId
        WslRollbackSwapExists = [bool]$State.WslRollbackSwap.Exists
        WslRollbackSwapRelease = [string]$State.WslRollbackSwap.ReleaseId
        KernelRelease = [string]$State.Kernel.ReleaseId
    }
}

# Legacy rollback recovery consumes a NESTED Actual (Windows/Wsl/Kernel axes).
function ConvertTo-LegacyRollbackActual {
    param([Parameter(Mandatory)]$State)
    $axis = {
        param($Tree)
        [pscustomobject]@{
            ActiveExists = [bool]$Tree.ActiveExists; ActiveRelease = [string]$Tree.ActiveRelease
            ActiveIntegrity = [string]$Tree.ActiveIntegrity
            PreviousExists = [bool]$Tree.PreviousExists; PreviousRelease = [string]$Tree.PreviousRelease
            PreviousIntegrity = [string]$Tree.PreviousIntegrity
            SwapExists = [bool]$Tree.SwapExists; SwapRelease = [string]$Tree.SwapRelease
            SwapIntegrity = [string]$Tree.SwapIntegrity
        }
    }
    return [pscustomobject]@{
        Windows = & $axis @{
            ActiveExists = $State.WindowsActive.Exists; ActiveRelease = $State.WindowsActive.ReleaseId; ActiveIntegrity = $State.WindowsActive.IntegritySha256
            PreviousExists = $State.WindowsPrevious.Exists; PreviousRelease = $State.WindowsPrevious.ReleaseId; PreviousIntegrity = $State.WindowsPrevious.IntegritySha256
            SwapExists = $State.WindowsSwap.Exists; SwapRelease = $State.WindowsSwap.ReleaseId; SwapIntegrity = $State.WindowsSwap.IntegritySha256
        }
        Wsl = & $axis @{
            ActiveExists = $State.WslActive.Exists; ActiveRelease = $State.WslActive.ReleaseId; ActiveIntegrity = $State.WslActive.IntegritySha256
            PreviousExists = $State.WslPrevious.Exists; PreviousRelease = $State.WslPrevious.ReleaseId; PreviousIntegrity = $State.WslPrevious.IntegritySha256
            SwapExists = $State.WslRollbackSwap.Exists; SwapRelease = $State.WslRollbackSwap.ReleaseId; SwapIntegrity = $State.WslRollbackSwap.IntegritySha256
        }
        Kernel = [pscustomobject]@{
            package_release_id = if ($State.Kernel.State) { [string]$State.Kernel.State.package_release_id } else { '' }
            kernel_path = if ($State.Kernel.State) { [string]$State.Kernel.State.kernel_path } else { '' }
            modules_path = if ($State.Kernel.State) { [string]$State.Kernel.State.modules_path } else { '' }
            kernel_release = if ($State.Kernel.State) { [string]$State.Kernel.State.kernel_release } else { '' }
            modules_format = if ($State.Kernel.State) { [string]$State.Kernel.State.modules_format } else { '' }
            kernel_sha256 = if ($State.Kernel.State) { [string]$State.Kernel.State.kernel_sha256 } else { '' }
            modules_sha256 = if ($State.Kernel.State) { [string]$State.Kernel.State.modules_sha256 } else { '' }
        }
    }
}

# The legacy marker-bootstrap gate consumes Registration/Marker objects; the engine gate
# consumes the normalized State. Both must agree on the same fixture.
function Test-MarkerBootstrapGates {
    param([Parameter(Mandatory)]$Transaction, [Parameter(Mandatory)]$State)
    $identity = $State.Identity
    $registration = [pscustomobject]@{ Exists = [bool]$identity.RegistrationExists; BasePath = [string]$identity.BasePath }
    $marker = [pscustomobject]@{ Missing = [bool]$identity.MarkerMissing; Valid = [bool]$identity.MarkerValid; InstallId = [string]$identity.InstallId }
    $legacyGate = Test-SwitchTradeFreshImportMarkerBootstrap -Transaction $Transaction -Registration $registration -Marker $marker
    $engineGate = & $engineMarkerBootstrapGate -Transaction $Transaction -State $State
    return [pscustomobject]@{ Legacy = $legacyGate; Engine = $engineGate }
}

# Recovery decision parity: new engine vs legacy resolver must agree on every fixture.
function Assert-RecoveryDecisionParity {
    param([Parameter(Mandatory)]$Transaction, [Parameter(Mandatory)]$State, [string]$What)
    $actual = ConvertTo-LegacyActual -State $State -Transaction $Transaction
    $legacy = $null
    try { $legacy = Resolve-SwitchTradeTransactionRecovery -Transaction $Transaction -Actual $actual }
    catch { $legacy = "THREW:" + $_.Exception.Message }
    $new = $null
    try { $new = Resolve-SwitchTradeRecoveryDecision -Transaction $Transaction -State $State }
    catch { $new = "THREW:" + $_.Exception.Message }
    if ($legacy -is [string] -or $new -is [string]) {
        if ($legacy -ne $new) { throw "$What parity mismatch: legacy=[$legacy] new=[$new]" }
        return
    }
    $l = @($legacy.Disposition, $legacy.WindowsAction, $legacy.WslAction, $legacy.KernelAction, $legacy.RemoveStage) -join '|'
    $n = @($new.Disposition, $new.WindowsAction, $new.WslAction, $new.KernelAction, $new.RemoveStage) -join '|'
    if ($l -cne $n) { throw "$What parity mismatch: legacy=[$l] new=[$n]" }
}

function New-TestTransaction {
    param(
        [string]$Phase = 'windows_staged',
        [string]$ReleaseId = 'beta-test',
        [string]$PriorReleaseId = 'beta-prior',
        [string]$InstallId = '0123456789abcdef0123456789abcdef',
        [bool]$DistroExistedBefore = $true,
        [bool]$DistroOwnedBefore = $true,
        [string]$WslPriorReleaseId = 'beta-prior',
        [string]$KernelPriorReleaseId = 'beta-prior',
        [bool]$KernelChangeExpected = $true,
        [string]$WindowsIntegrity = '1111111111111111111111111111111111111111111111111111111111111111',
        [string]$WslIntegrity = '2222222222222222222222222222222222222222222222222222222222222222',
        [string]$WindowsPriorIntegrity = '3333333333333333333333333333333333333333333333333333333333333333',
        [string]$WslPriorIntegrity = '4444444444444444444444444444444444444444444444444444444444444444'
    )
    return [pscustomobject]@{
        schema = 3
        transaction_id = 'test-transaction-id'
        action = 'Install'
        release_id = $ReleaseId
        prior_release_id = $PriorReleaseId
        phase = $Phase
        windows_stage = (Join-Path $TestRoot 'SwitchTrade.stage.0123456789abcdef0123456789abcdef')
        package_root = (Join-Path $TestRoot 'package')
        package_manifest_sha256 = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
        install_root = (Join-Path $TestRoot 'Programs\SwitchTrade')
        previous_install = (Join-Path $TestRoot 'Programs\SwitchTrade.previous')
        distro_name = 'SwitchTrade'
        distro_root = (Join-Path $TestRoot 'wsl')
        distro_existed_before = $DistroExistedBefore
        distro_owned_before = $DistroOwnedBefore
        wsl_prior_release_id = $WslPriorReleaseId
        wsl_active_path = '/opt/switchtrade'
        wsl_candidate_path = '/opt/switchtrade.candidate'
        wsl_previous_path = '/opt/switchtrade.previous'
        wsl_commit_swap_path = '/opt/switchtrade.commit-swap'
        wsl_rollback_swap_path = '/opt/switchtrade.rollback-swap'
        kernel_prior_release_id = $KernelPriorReleaseId
        kernel_state_path = (Join-Path $TestRoot 'kernel-state.json')
        kernel_prior_path = (Join-Path $TestRoot 'kernel-prior')
        kernel_prior_modules_path = ''
        kernel_change_expected = $KernelChangeExpected
        install_id = $InstallId
        distro_base_path = (Join-Path $TestRoot 'wsl')
        windows_integrity_sha256 = $WindowsIntegrity
        wsl_integrity_sha256 = $WslIntegrity
        windows_prior_integrity_sha256 = $WindowsPriorIntegrity
        wsl_prior_integrity_sha256 = $WslPriorIntegrity
        distro_imported = $false
        wsl_staged = $false
        kernel_applied = $false
        wsl_committed = $false
        windows_committed = $false
        started_utc = '2026-08-27T00:00:00Z'
    }
}

# ---------------------------------------------------------------------------
# Recovery parity matrix (handoff section 10: kill at every stage).
# ---------------------------------------------------------------------------
$owned = @{ Classification = 'present_owned'; DistroExists = $true; EnumerationKnown = $true; RegistrationExists = $true; BasePath = (Join-Path $TestRoot 'wsl'); MarkerValid = $true; InstallId = '0123456789abcdef0123456789abcdef' }
$foreign = @{ Classification = 'present_foreign'; DistroExists = $true; EnumerationKnown = $true; RegistrationExists = $true; BasePath = (Join-Path $TestRoot 'wsl'); MarkerValid = $true; InstallId = 'ffffffffffffffffffffffffffffffff' }
$generic = @{ Classification = 'present_generic'; DistroExists = $true; EnumerationKnown = $true; RegistrationExists = $true; BasePath = (Join-Path $TestRoot 'wsl'); MarkerMissing = $true; MarkerValid = $false; InstallId = '' }
$absent = @{ Classification = 'absent'; DistroExists = $false; EnumerationKnown = $true; RegistrationExists = $false; BasePath = ''; MarkerValid = $false; InstallId = '' }
$unknownEnum = @{ Classification = 'enumeration_timed_out'; DistroExists = $false; EnumerationKnown = $false; RegistrationExists = $false; BasePath = ''; MarkerValid = $false; InstallId = '' }

$integrityA = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
$integrityB = 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'

function New-TreeState {
    param([string]$ReleaseId, [string]$Integrity, [bool]$Exists = $true)
    if (-not $Exists) { return @{ Exists = $false; Valid = $true; ReleaseId = ''; IntegritySha256 = '' } }
    return @{ Exists = $true; Valid = $true; ReleaseId = $ReleaseId; IntegritySha256 = $Integrity }
}

# 1. Coherent commit -> finalize.
$tx1 = New-TestTransaction -Phase 'wsl_committed' -WindowsIntegrity $integrityA -WslIntegrity $integrityB
$state1 = New-TestState -Identity $owned -Transaction $tx1 -WindowsActive (New-TreeState beta-test $integrityA) -WindowsPrevious (New-TreeState beta-prior $integrityB) -WslActive (New-TreeState beta-test $integrityB) -WslPrevious (New-TreeState beta-prior $integrityA) -Kernel @{ Exists = $true; Valid = $true; ReleaseId = 'beta-test'; State = $null }
Assert-RecoveryDecisionParity -Transaction $tx1 -State $state1 -What 'coherent commit'
$d1 = Resolve-SwitchTradeRecoveryDecision -Transaction $tx1 -State $state1
Assert-Equal $d1.Disposition 'finalize' 'coherent commit must finalize'

# 2. Staged candidate with prior -> abort_candidate.
$tx2 = New-TestTransaction -Phase 'wsl_staged'
$state2 = New-TestState -Identity $owned -Transaction $tx2 -WindowsActive (New-TreeState beta-prior $integrityA) -WslActive (New-TreeState beta-prior $integrityA) -WslCandidate (New-TreeState beta-test $integrityB) -Kernel @{ Exists = $true; Valid = $true; ReleaseId = 'beta-prior'; State = $null }
Assert-RecoveryDecisionParity -Transaction $tx2 -State $state2 -What 'staged candidate'
$d2 = Resolve-SwitchTradeRecoveryDecision -Transaction $tx2 -State $state2
Assert-Equal $d2.WslAction 'abort_candidate' 'staged candidate must abort'

# 3. WSL committed but Windows still on the prior release -> compensate.
$tx3 = New-TestTransaction -Phase 'wsl_committed' -WindowsIntegrity $integrityA -WslIntegrity $integrityB
$state3 = New-TestState -Identity $owned -Transaction $tx3 -WindowsActive (New-TreeState beta-prior $integrityB) -WindowsPrevious @{ Exists = $false; Valid = $true; ReleaseId = ''; IntegritySha256 = '' } -WslActive (New-TreeState beta-test $integrityB) -WslPrevious (New-TreeState beta-prior $integrityA) -Kernel @{ Exists = $true; Valid = $true; ReleaseId = 'beta-prior'; State = $null }
Assert-RecoveryDecisionParity -Transaction $tx3 -State $state3 -What 'committed with prior'
$d3 = Resolve-SwitchTradeRecoveryDecision -Transaction $tx3 -State $state3
Assert-Equal $d3.WslAction 'compensate' 'committed with prior must compensate'

# 4. Interrupted commit swap -> recover_interrupted.
$tx4 = New-TestTransaction -Phase 'wsl_committed' -WindowsIntegrity $integrityA -WslIntegrity $integrityB
$state4 = New-TestState -Identity $owned -Transaction $tx4 -WindowsActive (New-TreeState beta-test $integrityA) -WindowsPrevious (New-TreeState beta-prior $integrityB) -WslActive (New-TreeState '' $integrityB) -WslCommitSwap (New-TreeState beta-prior $integrityA) -Kernel @{ Exists = $true; Valid = $true; ReleaseId = 'beta-test'; State = $null }
Assert-RecoveryDecisionParity -Transaction $tx4 -State $state4 -What 'commit swap'
$d4 = Resolve-SwitchTradeRecoveryDecision -Transaction $tx4 -State $state4
Assert-Equal $d4.WslAction 'recover_interrupted' 'commit swap must recover'

# 5. Foreign install id -> ownership changed (both engines throw).
$tx5 = New-TestTransaction -Phase 'staging_wsl'
$state5 = New-TestState -Identity $foreign -Transaction $tx5
$legacy5 = $null; $new5 = $null
try { Resolve-SwitchTradeTransactionRecovery -Transaction $tx5 -Actual (ConvertTo-LegacyActual -State $state5 -Transaction $tx5) | Out-Null; $legacy5 = 'no-throw' } catch { $legacy5 = [string]$_.Exception.Message }
try { Resolve-SwitchTradeRecoveryDecision -Transaction $tx5 -State $state5 | Out-Null; $new5 = 'no-throw' } catch { $new5 = [string]$_.Exception.Message }
if ($legacy5 -notmatch 'DISTRO_OWNERSHIP_CHANGED' -or $new5 -notmatch 'DISTRO_OWNERSHIP_CHANGED') { throw "foreign distro parity mismatch: legacy=[$legacy5] new=[$new5]" }

# 6. Enumeration unknown -> fail closed.
$tx6 = New-TestTransaction -Phase 'staging_wsl'
$state6 = New-TestState -Identity $unknownEnum -Transaction $tx6
$legacy6 = $null; $new6 = $null
try { Resolve-SwitchTradeTransactionRecovery -Transaction $tx6 -Actual (ConvertTo-LegacyActual -State $state6 -Transaction $tx6) | Out-Null; $legacy6 = 'no-throw' } catch { $legacy6 = [string]$_.Exception.Message }
try { Resolve-SwitchTradeRecoveryDecision -Transaction $tx6 -State $state6 | Out-Null; $new6 = 'no-throw' } catch { $new6 = [string]$_.Exception.Message }
if ($legacy6 -notmatch 'ENUMERATION_UNKNOWN' -or $new6 -notmatch 'ENUMERATION_UNKNOWN') { throw "enumeration parity mismatch: legacy=[$legacy6] new=[$new6]" }

# 7. Fresh install with generic marker at recorded BasePath: early fresh install recovery.
$tx7 = New-TestTransaction -Phase 'importing_distro' -PriorReleaseId '' -DistroExistedBefore $false -DistroOwnedBefore $false -WslPriorReleaseId '' -KernelPriorReleaseId '' -KernelChangeExpected $true
$state7 = New-TestState -Identity $generic -Transaction $tx7 -WindowsStageExists $true
$gates7 = Test-MarkerBootstrapGates -Transaction $tx7 -State $state7
Assert-True $gates7.Legacy 'legacy marker bootstrap gate must recognize the markerless fresh import'
Assert-True $gates7.Engine 'engine marker bootstrap gate must recognize the markerless fresh import'
Assert-True (Test-SwitchTradeEarlyFreshInstallRecovery -Transaction $tx7) 'early fresh install recovery gate must match'
$plan7 = Resolve-SwitchTradeRecoveryPlan -Context ([pscustomobject]@{ Action = 'Repair' }) -State $state7 -Package ([pscustomobject]@{ ReleaseId = 'beta-test'; ManifestSha256 = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' })
$kinds7 = @($plan7.Steps | ForEach-Object { $_.Kind }) -join ','
if ($kinds7 -notmatch 'bootstrap_marker' -or $kinds7 -notmatch 'recovery_decide' -or $kinds7 -notmatch 'create_transaction' -or $kinds7 -notmatch 'ensure_distro') {
    throw "early fresh install recovery plan missing steps: $kinds7"
}
if ($plan7.TerminalPhase -ne 'completed') { throw 'early fresh install recovery must terminate completed' }

# 8. Fresh install markerless state (absent distro) -> plain install plan.
$tx8 = New-TestTransaction -Phase 'created' -PriorReleaseId '' -DistroExistedBefore $false -DistroOwnedBefore $false -WslPriorReleaseId '' -KernelPriorReleaseId ''
$state8 = New-TestState -Identity $absent -Transaction $null
$plan8 = Resolve-SwitchTradeInstallPlan -Context ([pscustomobject]@{ Action = 'Repair' }) -State $state8 -Package ([pscustomobject]@{ ReleaseId = 'beta-test'; ManifestSha256 = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' })
$kinds8 = @($plan8.Steps | ForEach-Object { $_.Kind }) -join ','
foreach ($expected in @('require_prerequisites', 'create_transaction', 'stage_windows', 'ensure_distro', 'provision_stage', 'provision_validate', 'control_readiness', 'apply_kernel', 'provision_commit', 'commit_windows')) {
    if ($kinds8 -notmatch $expected) { throw "install plan missing step kind $expected" }
}

# 9. Rollback pair position parity.
$journal = [pscustomobject]@{
    schema = 2
    source_action = 'Install'
    initiating_package = [pscustomobject]@{ root = (Join-Path $TestRoot 'package'); release_id = 'beta-test'; manifest_sha256 = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' }
    source = [pscustomobject]@{ release_id = 'beta-test'; windows_integrity_sha256 = $integrityA; wsl_integrity_sha256 = $integrityB; kernel_path = '/k1'; modules_path = ''; kernel_release = 'r1'; modules_format = 'vhd'; kernel_sha256 = $integrityA; modules_sha256 = '' }
    target = [pscustomobject]@{ release_id = 'beta-prior'; windows_integrity_sha256 = $integrityB; wsl_integrity_sha256 = $integrityA; kernel_path = '/k2'; modules_path = ''; kernel_release = 'r2'; modules_format = 'vhd'; kernel_sha256 = $integrityB; modules_sha256 = '' }
}
$kernelJournalState = @{ Exists = $true; Valid = $true; ReleaseId = 'beta-test'; State = [pscustomobject]@{ package_release_id = 'beta-test'; kernel_path = '/k1'; modules_path = ''; kernel_release = 'r1'; modules_format = 'vhd'; kernel_sha256 = $integrityA; modules_sha256 = ''; rollback_package_release_id = 'beta-prior'; rollback_kernel_path = '/k2'; rollback_modules_path = ''; rollback_kernel_release = 'r2'; rollback_modules_format = 'vhd'; rollback_kernel_sha256 = $integrityB; rollback_modules_sha256 = '' } }
foreach ($position in @('source', 'target', 'target_transition')) {
    $windowsActive = @{ Exists = $false; Valid = $true; ReleaseId = ''; IntegritySha256 = '' }
    $windowsPrevious = @{ Exists = $false; Valid = $true; ReleaseId = ''; IntegritySha256 = '' }
    $windowsSwap = @{ Exists = $false; Valid = $true; ReleaseId = ''; IntegritySha256 = '' }
    $wslActive = @{ Exists = $false; Valid = $true; ReleaseId = ''; IntegritySha256 = '' }
    $wslPrevious = @{ Exists = $false; Valid = $true; ReleaseId = ''; IntegritySha256 = '' }
    $wslRollbackSwap = @{ Exists = $false; Valid = $true; ReleaseId = ''; IntegritySha256 = '' }
    switch ($position) {
        'source' {
            $windowsActive = @{ Exists = $true; Valid = $true; ReleaseId = 'beta-test'; IntegritySha256 = $integrityA }
            $windowsPrevious = @{ Exists = $true; Valid = $true; ReleaseId = 'beta-prior'; IntegritySha256 = $integrityB }
            $wslActive = @{ Exists = $true; Valid = $true; ReleaseId = 'beta-test'; IntegritySha256 = $integrityB }
            $wslPrevious = @{ Exists = $true; Valid = $true; ReleaseId = 'beta-prior'; IntegritySha256 = $integrityA }
        }
        'target' {
            $windowsActive = @{ Exists = $true; Valid = $true; ReleaseId = 'beta-prior'; IntegritySha256 = $integrityB }
            $windowsPrevious = @{ Exists = $true; Valid = $true; ReleaseId = 'beta-test'; IntegritySha256 = $integrityA }
            $wslActive = @{ Exists = $true; Valid = $true; ReleaseId = 'beta-prior'; IntegritySha256 = $integrityA }
            $wslPrevious = @{ Exists = $true; Valid = $true; ReleaseId = 'beta-test'; IntegritySha256 = $integrityB }
        }
        'target_transition' {
            $windowsActive = @{ Exists = $true; Valid = $true; ReleaseId = 'beta-prior'; IntegritySha256 = $integrityB }
            $windowsSwap = @{ Exists = $true; Valid = $true; ReleaseId = 'beta-test'; IntegritySha256 = $integrityA }
            $wslActive = @{ Exists = $true; Valid = $true; ReleaseId = 'beta-prior'; IntegritySha256 = $integrityA }
            $wslRollbackSwap = @{ Exists = $true; Valid = $true; ReleaseId = 'beta-test'; IntegritySha256 = $integrityB }
        }
    }
    $state9 = New-TestState -Identity $owned -Transaction $tx1 -WindowsActive $windowsActive -WindowsPrevious $windowsPrevious -WindowsSwap $windowsSwap -WslActive $wslActive -WslPrevious $wslPrevious -WslRollbackSwap $wslRollbackSwap -Kernel $kernelJournalState
    $legacy9 = Resolve-SwitchTradeRollbackRecovery -Transaction ([pscustomobject]@{ schema = 3; phase = 'rollback_prepared'; release_id = 'beta-test'; prior_release_id = 'beta-prior'; wsl_prior_release_id = 'beta-prior'; rollback_journal = $journal }) -Actual (ConvertTo-LegacyRollbackActual -State $state9)
    $new9 = Resolve-SwitchTradeRollbackRecoveryDecision -Journal $journal -State $state9
    if ($legacy9.Direction -cne $new9.Direction) { throw "rollback position $position parity mismatch: legacy=[$($legacy9.Direction)] new=[$($new9.Direction)]" }
}

# 10. Dispatcher blockers: corrupt / legacy transactions.
$corruptState = New-TestState -Identity $absent -Transaction $null
$corruptState.Transaction = [pscustomobject]@{ Classification = 'corrupt'; Transaction = $null; Phase = ''; Schema = 0; TransactionId = ''; ReleaseId = '' }
$blockerCorrupt = Resolve-SwitchTradePlan -Context ([pscustomobject]@{ Action = 'Repair' }) -State $corruptState -Package ([pscustomobject]@{})
Assert-Equal $blockerCorrupt.Outcome 'blocker' 'corrupt transaction must block'
Assert-Equal $blockerCorrupt.Code 'SETUP_TRANSACTION_CORRUPT' 'corrupt transaction code'
$legacyTx = New-TestTransaction | ForEach-Object { $_.schema = 2; $_ }
$stateLegacy = New-TestState -Identity $absent -Transaction $legacyTx
$stateLegacy.Transaction = [pscustomobject]@{ Classification = 'legacy'; Transaction = $legacyTx; Phase = 'windows_staged'; Schema = 2; TransactionId = 'x'; ReleaseId = 'beta-test' }
$blockerLegacy = Resolve-SwitchTradePlan -Context ([pscustomobject]@{ Action = 'Repair' }) -State $stateLegacy -Package ([pscustomobject]@{})
Assert-Equal $blockerLegacy.Code 'SETUP_TRANSACTION_LEGACY_AMBIGUOUS' 'legacy transaction must block'

# 11. Determinism: identical inputs produce identical plans.
$planA = Resolve-SwitchTradeInstallPlan -Context ([pscustomobject]@{ Action = 'Repair' }) -State $state8 -Package ([pscustomobject]@{ ReleaseId = 'beta-test'; ManifestSha256 = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' })
$planB = Resolve-SwitchTradeInstallPlan -Context ([pscustomobject]@{ Action = 'Repair' }) -State $state8 -Package ([pscustomobject]@{ ReleaseId = 'beta-test'; ManifestSha256 = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' })
if (($planA | ConvertTo-Json -Depth 8) -cne ($planB | ConvertTo-Json -Depth 8)) { throw 'planner is not deterministic' }

# 12. Live fixture: the real interrupted transaction must produce the markerless recovery plan.
$liveFixture = Join-Path $PSScriptRoot '..\tests\fixtures\installer\live-importing-distro-20260827\setup-transaction.json'
if (Test-Path -LiteralPath $liveFixture -PathType Leaf) {
    $liveTxRaw = (Get-Content -Raw -LiteralPath $liveFixture) -replace '<USER>', $env:USERNAME
    $liveTx = $liveTxRaw | ConvertFrom-Json
    $liveIdentity = @{
        Classification = 'present_generic'; DistroExists = $true; EnumerationKnown = $true
        RegistrationExists = $true; BasePath = [IO.Path]::GetFullPath([string]$liveTx.distro_base_path)
        MarkerMissing = $true; MarkerValid = $false; InstallId = ''
    }
    $liveState = New-TestState -Identity $liveIdentity -Transaction $liveTx -WindowsStageExists $true
    $liveGates = Test-MarkerBootstrapGates -Transaction $liveTx -State $liveState
    Assert-True $liveGates.Legacy 'live fixture must be recognized as markerless fresh import (legacy gate)'
    Assert-True $liveGates.Engine 'live fixture must be recognized as markerless fresh import (engine gate)'
    $livePlan = Resolve-SwitchTradeRecoveryPlan -Context ([pscustomobject]@{ Action = 'Repair' }) -State $liveState -Package ([pscustomobject]@{ ReleaseId = 'beta-5b2c414'; ManifestSha256 = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' })
    $liveKinds = @($livePlan.Steps | ForEach-Object { $_.Kind }) -join ','
    if ($liveKinds -notmatch 'bootstrap_marker') { throw 'live fixture recovery plan must bootstrap the marker' }
    if ($liveKinds -notmatch 'ensure_distro') { throw 'live fixture recovery plan must continue the install' }
} else {
    Write-Host 'SKIPPED live fixture assertion (fixture missing)'
}

Write-Host 'Engine planner simulation PASS'