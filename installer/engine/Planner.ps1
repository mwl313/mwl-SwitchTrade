# SwitchTrade installer engine: pure planner (deterministic, no I/O, no WSL)
#
# Handoff 8.2: consumes requested action + verified package identity + normalized snapshot and
# returns an ordered explicit mutation plan (preconditions, checkpoints, compensation, terminal
# state) or a stable structured blocker (stage, code, recovery action, evidence). Identical
# inputs produce identical plans. Testable without Windows, WSL, administrator rights, or real
# files. This file performs NO I/O; the executor applies the returned plan.
Set-StrictMode -Version Latest

# Package identity verified by PackageIntegrity before planning.
function New-SwitchTradePackageIdentity {
    param(
        [Parameter(Mandatory)][string]$ReleaseId,
        [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{64}$')][string]$ManifestSha256
    )
    return [pscustomobject]@{ ReleaseId = $ReleaseId; ManifestSha256 = $ManifestSha256.ToLowerInvariant() }
}

function New-SwitchTradeBlocker {
    param(
        [Parameter(Mandatory)][string]$Code,
        [Parameter(Mandatory)][string]$Message,
        [Parameter(Mandatory)][string]$Stage,
        [bool]$Recoverable = $true,
        [string]$PrimaryAction = 'Run Setup Repair',
        [string]$Evidence = ''
    )
    return [pscustomobject]@{
        Outcome = 'blocker'
        Code = $Code
        Message = $Message
        Stage = $Stage
        Recoverable = $Recoverable
        PrimaryAction = $PrimaryAction
        Evidence = $Evidence
    }
}

# ---------------------------------------------------------------------------
# Recovery decision: port of Resolve-SwitchTradeTransactionRecovery (SetupLifecycle.ps1)
# operating on the normalized snapshot. Kept decision-identical; parity is asserted by
# Test-EnginePlanner.ps1 against the legacy resolver on the same fixtures.
# ---------------------------------------------------------------------------
function Resolve-SwitchTradeRecoveryDecision {
    param(
        [Parameter(Mandatory)]$Transaction,
        [Parameter(Mandatory)]$State
    )
    if ([int]$Transaction.schema -ne 3) {
        throw 'SETUP_TRANSACTION_LEGACY_AMBIGUOUS: the interrupted transaction cannot prove pre-mutation ownership'
    }
    $actual = $State.Identity
    if (-not [bool]$actual.EnumerationKnown) {
        throw 'SETUP_TRANSACTION_DISTRO_ENUMERATION_UNKNOWN: WSL distribution state could not be determined'
    }
    $distroOwned = $actual.DistroExists -and $actual.MarkerValid -and
        $actual.InstallId -ceq [string]$Transaction.install_id
    $distroBaseMatches = [string]::Equals(
        [IO.Path]::GetFullPath([string]$actual.BasePath).TrimEnd('\'),
        [IO.Path]::GetFullPath([string]$Transaction.distro_base_path).TrimEnd('\'),
        [StringComparison]::OrdinalIgnoreCase)
    if ($actual.DistroExists -and -not $distroOwned) {
        throw 'SETUP_TRANSACTION_DISTRO_OWNERSHIP_CHANGED: the named distribution is not installer-owned'
    }
    if ($actual.DistroExists -and
            ([string]$actual.InstallId -cne [string]$Transaction.install_id -or -not $distroBaseMatches)) {
        throw 'SETUP_TRANSACTION_DISTRO_IDENTITY_CHANGED: distribution install identity or BasePath changed'
    }
    if ([bool]$Transaction.distro_existed_before -and
            (-not [bool]$Transaction.distro_owned_before -or -not $actual.DistroExists)) {
        throw 'SETUP_TRANSACTION_PRIOR_DISTRO_MISSING: the prior owned distribution cannot be proven'
    }

    $release = [string]$Transaction.release_id
    $windowsPrior = [string]$Transaction.prior_release_id
    $wslPrior = [string]$Transaction.wsl_prior_release_id
    $kernelPrior = [string]$Transaction.kernel_prior_release_id
    $windowsIntegrity = [string]$Transaction.windows_integrity_sha256
    $wslIntegrity = [string]$Transaction.wsl_integrity_sha256
    $kernelExpected = if ([bool]$Transaction.kernel_change_expected) { $release } else { $kernelPrior }
    $retainedReady = (-not $windowsPrior -or $State.WindowsPrevious.ReleaseId -eq $windowsPrior) -and
        (-not $wslPrior -or $State.WslPrevious.ReleaseId -eq $wslPrior)
    $coherentCommit = $windowsIntegrity -and $wslIntegrity -and
        $State.WindowsActive.ReleaseId -eq $release -and
        $State.WindowsActive.IntegritySha256 -eq $windowsIntegrity -and
        $State.WslActive.ReleaseId -eq $release -and $State.WslActive.IntegritySha256 -eq $wslIntegrity -and
        $State.Kernel.ReleaseId -eq $kernelExpected -and $retainedReady -and
        -not $State.WindowsStageExists -and -not $State.WslCandidate.Exists -and
        -not $State.WslCommitSwap.Exists -and -not $State.WslRollbackSwap.Exists
    if ($coherentCommit) {
        return [pscustomobject]@{
            Disposition = 'finalize'; WindowsAction = 'none'; WslAction = 'none'
            KernelAction = 'none'; RemoveStage = $false
        }
    }

    $windowsAction = 'none'
    if ($State.WindowsActive.Exists -and -not $State.WindowsActive.ReleaseId) {
        throw 'SETUP_TRANSACTION_WINDOWS_ACTIVE_INVALID: the active Windows tree is not a proven release'
    }
    if ($State.WindowsPrevious.Exists -and -not $State.WindowsPrevious.ReleaseId) {
        throw 'SETUP_TRANSACTION_WINDOWS_RETAINED_INVALID: the retained Windows tree is not a proven release'
    }
    if ($State.WindowsSwap.Exists) {
        if (-not $windowsPrior -or $State.WindowsSwap.ReleaseId -ne $release -or
                -not (($State.WindowsActive.ReleaseId -eq '' -and
                        $State.WindowsPrevious.ReleaseId -eq $windowsPrior) -or
                       ($State.WindowsActive.ReleaseId -eq $windowsPrior -and
                        -not $State.WindowsPrevious.Exists))) {
            throw 'SETUP_TRANSACTION_WINDOWS_SWAP_INVALID: interrupted rollback state is not proven'
        }
        $windowsAction = 'rollback'
    } elseif ($windowsPrior) {
        if ($State.WindowsActive.ReleaseId -eq $windowsPrior) { $windowsAction = 'none' }
        elseif ($State.WindowsActive.ReleaseId -eq $release -and
                $State.WindowsPrevious.ReleaseId -eq $windowsPrior) { $windowsAction = 'rollback' }
        elseif (-not $State.WindowsActive.Exists -and
                $State.WindowsPrevious.ReleaseId -eq $windowsPrior) { $windowsAction = 'restore_prior' }
        else { throw 'SETUP_TRANSACTION_WINDOWS_AMBIGUOUS: Windows release state cannot be compensated safely' }
    } elseif ($State.WindowsActive.ReleaseId -eq $release) {
        $windowsAction = 'remove_new'
    } elseif ($State.WindowsActive.Exists) {
        throw 'SETUP_TRANSACTION_WINDOWS_AMBIGUOUS: an unexpected Windows release is active'
    }

    $wslAction = 'none'
    if (-not [bool]$Transaction.distro_existed_before) {
        if ($actual.DistroExists) { $wslAction = 'unregister_new' }
    } else {
        if (-not $wslPrior) {
            throw 'SETUP_TRANSACTION_WSL_PRIOR_UNKNOWN: the prior WSL release was not recorded'
        }
        if (($State.WslCandidate.Exists -and $State.WslCandidate.ReleaseId -ne $release) -or
                ($State.WslCommitSwap.Exists -and $State.WslCommitSwap.ReleaseId -ne $wslPrior) -or
                ($State.WslRollbackSwap.Exists -and $State.WslRollbackSwap.ReleaseId -ne $release)) {
            throw 'SETUP_TRANSACTION_WSL_LAYOUT_INVALID: an unproven WSL runtime occupies a transaction path'
        }
        if ($State.WslRollbackSwap.Exists -and
                (($State.WslActive.ReleaseId -eq '' -and $State.WslPrevious.ReleaseId -eq $wslPrior) -or
                 ($State.WslActive.ReleaseId -eq $wslPrior -and $State.WslPrevious.ReleaseId -eq ''))) {
            $wslAction = 'compensate'
        } elseif ($State.WslActive.ReleaseId -eq $wslPrior -and
                -not $State.WslCommitSwap.Exists) {
            if ($State.WslCandidate.Exists) { $wslAction = 'abort_candidate' }
        } elseif ($State.WslActive.ReleaseId -eq $release -and
                $State.WslPrevious.ReleaseId -eq $wslPrior -and
                -not $State.WslCommitSwap.Exists) {
            $wslAction = 'compensate'
        } elseif ($State.WslCommitSwap.ReleaseId -eq $wslPrior -and
                $State.WslActive.ReleaseId -in @('', $release)) {
            $wslAction = 'recover_interrupted'
        } else {
            throw 'SETUP_TRANSACTION_WSL_AMBIGUOUS: WSL release state cannot be compensated safely'
        }
    }

    $kernelAction = 'none'
    if ($State.Kernel.ReleaseId -eq $kernelPrior) { $kernelAction = 'none' }
    elseif ([bool]$Transaction.kernel_change_expected -and $State.Kernel.ReleaseId -eq $release) {
        $kernelAction = if ($kernelPrior) { 'rollback' } else { 'restore_original' }
    } else {
        throw 'SETUP_TRANSACTION_KERNEL_AMBIGUOUS: kernel release state cannot be compensated safely'
    }
    return [pscustomobject]@{
        Disposition = 'compensate'; WindowsAction = $windowsAction; WslAction = $wslAction
        KernelAction = $kernelAction; RemoveStage = [bool]$State.WindowsStageExists
    }
}

# Fresh-import marker bootstrap gate (port of Test-SwitchTradeFreshImportMarkerBootstrap).
function Test-SwitchTradeFreshImportMarkerBootstrap {
    param(
        [Parameter(Mandatory)]$Transaction,
        [Parameter(Mandatory)]$State
    )
    return [int]$Transaction.schema -eq 3 -and
        [string]$Transaction.phase -eq 'importing_distro' -and
        -not [string]$Transaction.prior_release_id -and
        -not [bool]$Transaction.distro_existed_before -and
        -not [bool]$Transaction.distro_owned_before -and
        [bool]$State.Identity.RegistrationExists -and
        [string]::Equals(
            [IO.Path]::GetFullPath([string]$State.Identity.BasePath).TrimEnd('\'),
            [IO.Path]::GetFullPath([string]$Transaction.distro_base_path).TrimEnd('\'),
            [StringComparison]::OrdinalIgnoreCase) -and
        -not [string]$State.Identity.InstallId -and
        ([bool]$State.Identity.MarkerMissing -or [bool]$State.Identity.MarkerValid)
}

# Early fresh-install recovery gate (port of Test-SwitchTradeEarlyFreshInstallRecovery).
function Test-SwitchTradeEarlyFreshInstallRecovery {
    param([Parameter(Mandatory)]$Transaction)
    return [int]$Transaction.schema -eq 3 -and
        -not [string]$Transaction.prior_release_id -and
        -not [bool]$Transaction.distro_existed_before -and
        [string]$Transaction.phase -in @('created', 'windows_staged', 'importing_distro',
            'distro_imported')
}

# Interrupted-rollback decision (port of Resolve-SwitchTradeRollbackRecovery + pair position).
function Get-SwitchTradeRollbackPairPositionDecision {
    param(
        [Parameter(Mandatory)]$Source,
        [Parameter(Mandatory)]$Target,
        [Parameter(Mandatory)]$Axis
    )
    $sourceActive = $Axis.ActiveExists -and
        [string]$Axis.ActiveRelease -eq [string]$Source.release_id -and
        [string]$Axis.ActiveIntegrity -eq [string]$Source.integrity_sha256
    $targetActive = $Axis.ActiveExists -and
        [string]$Axis.ActiveRelease -eq [string]$Target.release_id -and
        [string]$Axis.ActiveIntegrity -eq [string]$Target.integrity_sha256
    $sourcePrevious = $Axis.PreviousExists -and
        [string]$Axis.PreviousRelease -eq [string]$Source.release_id -and
        [string]$Axis.PreviousIntegrity -eq [string]$Source.integrity_sha256
    $targetPrevious = $Axis.PreviousExists -and
        [string]$Axis.PreviousRelease -eq [string]$Target.release_id -and
        [string]$Axis.PreviousIntegrity -eq [string]$Target.integrity_sha256
    $sourceSwap = $Axis.SwapExists -and
        [string]$Axis.SwapRelease -eq [string]$Source.release_id -and
        [string]$Axis.SwapIntegrity -eq [string]$Source.integrity_sha256
    $targetSwap = $Axis.SwapExists -and
        [string]$Axis.SwapRelease -eq [string]$Target.release_id -and
        [string]$Axis.SwapIntegrity -eq [string]$Target.integrity_sha256
    if (-not $Axis.SwapExists -and $sourceActive -and $targetPrevious) { return 'source' }
    if (-not $Axis.SwapExists -and $targetActive -and $sourcePrevious) { return 'target' }
    if ($sourceSwap -and
            ((-not $Axis.ActiveExists -and $targetPrevious) -or
             ($targetActive -and -not $Axis.PreviousExists))) {
        return 'target_transition'
    }
    if ($targetSwap -and
            ((-not $Axis.ActiveExists -and $sourcePrevious) -or
             ($sourceActive -and -not $Axis.PreviousExists))) {
        return 'source_transition'
    }
    throw 'ROLLBACK_STATE_AMBIGUOUS: release pair or integrity anchor changed'
}

function Resolve-SwitchTradeRollbackRecoveryDecision {
    param(
        [Parameter(Mandatory)]$Journal,
        [Parameter(Mandatory)]$State
    )
    $windowsSource = [pscustomobject]@{
        release_id = [string]$Journal.source.release_id
        integrity_sha256 = [string]$Journal.source.windows_integrity_sha256
    }
    $windowsTarget = [pscustomobject]@{
        release_id = [string]$Journal.target.release_id
        integrity_sha256 = [string]$Journal.target.windows_integrity_sha256
    }
    $wslSource = [pscustomobject]@{
        release_id = [string]$Journal.source.release_id
        integrity_sha256 = [string]$Journal.source.wsl_integrity_sha256
    }
    $wslTarget = [pscustomobject]@{
        release_id = [string]$Journal.target.release_id
        integrity_sha256 = [string]$Journal.target.wsl_integrity_sha256
    }
    $windowsAxis = [pscustomobject]@{
        ActiveExists = $State.WindowsActive.Exists; ActiveRelease = $State.WindowsActive.ReleaseId
        ActiveIntegrity = $State.WindowsActive.IntegritySha256
        PreviousExists = $State.WindowsPrevious.Exists; PreviousRelease = $State.WindowsPrevious.ReleaseId
        PreviousIntegrity = $State.WindowsPrevious.IntegritySha256
        SwapExists = $State.WindowsSwap.Exists; SwapRelease = $State.WindowsSwap.ReleaseId
        SwapIntegrity = $State.WindowsSwap.IntegritySha256
    }
    $wslAxis = [pscustomobject]@{
        ActiveExists = $State.WslActive.Exists; ActiveRelease = $State.WslActive.ReleaseId
        ActiveIntegrity = $State.WslActive.IntegritySha256
        PreviousExists = $State.WslPrevious.Exists; PreviousRelease = $State.WslPrevious.ReleaseId
        PreviousIntegrity = $State.WslPrevious.IntegritySha256
        SwapExists = $State.WslRollbackSwap.Exists; SwapRelease = $State.WslRollbackSwap.ReleaseId
        SwapIntegrity = $State.WslRollbackSwap.IntegritySha256
    }
    $windows = Get-SwitchTradeRollbackPairPositionDecision -Source $windowsSource -Target $windowsTarget -Axis $windowsAxis
    $wsl = Get-SwitchTradeRollbackPairPositionDecision -Source $wslSource -Target $wslTarget -Axis $wslAxis
    $kernel = ''
    $kernelState = $State.Kernel.State
    foreach ($direction in @('source', 'target')) {
        $axis = $Journal.$direction
        $kernel = if ($kernelState -and
                [string]$kernelState.package_release_id -eq [string]$axis.release_id -and
                [string]::Equals([string]$kernelState.kernel_path, [string]$axis.kernel_path,
                    [StringComparison]::OrdinalIgnoreCase) -and
                [string]::Equals([string]$kernelState.modules_path, [string]$axis.modules_path,
                    [StringComparison]::OrdinalIgnoreCase) -and
                [string]$kernelState.kernel_release -eq [string]$axis.kernel_release -and
                [string]$kernelState.modules_format -eq [string]$axis.modules_format -and
                [string]$kernelState.kernel_sha256 -eq [string]$axis.kernel_sha256 -and
                [string]$kernelState.modules_sha256 -eq [string]$axis.modules_sha256) { $direction } else { $kernel }
    }
    if (-not $kernel) { throw 'ROLLBACK_KERNEL_STATE_AMBIGUOUS: kernel identity or anchor changed' }
    $desired = if ($windows -notin @('source', 'source_transition') -and
            $wsl -notin @('source', 'source_transition') -and $kernel -ne 'source') {
        'target'
    } else { 'source' }
    return [pscustomobject]@{
        Direction = $desired; WindowsPosition = $windows; WslPosition = $wsl
        KernelPosition = $kernel
    }
}

# ---------------------------------------------------------------------------
# Plan step vocabulary. Kinds are implemented by Executor.ps1. Every mutating step
# carries a checkpoint phase (persisted BEFORE mutation), a progress stage, and an
# optional completion phase (persisted AFTER success).
# ---------------------------------------------------------------------------
function New-SwitchTradePlanStep {
    param(
        [Parameter(Mandatory)][string]$Id,
        [Parameter(Mandatory)][string]$Kind,
        [string]$Phase = '',
        [hashtable]$Fields = @{},
        [hashtable]$Args = @{},
        [string]$Stage = '',
        [string]$CompletePhase = '',
        [hashtable]$CompleteFields = @{},
        [string]$BlockerCode = '',
        [string]$BlockerMessage = ''
    )
    return [pscustomobject]@{
        Id = $Id; Kind = $Kind; Phase = $Phase; Fields = $Fields; Args = $Args
        Stage = $Stage; CompletePhase = $CompletePhase; CompleteFields = $CompleteFields
        BlockerCode = $BlockerCode; BlockerMessage = $BlockerMessage
    }
}

function New-SwitchTradePlan {
    param(
        [Parameter(Mandatory)][string]$Action,
        [Parameter(Mandatory)][array]$Steps,
        [string]$TerminalPhase = 'completed'
    )
    return [pscustomobject]@{
        Outcome = 'plan'; Action = $Action; Steps = @($Steps)
        TerminalPhase = $TerminalPhase
    }
}

# ---------------------------------------------------------------------------
# Install / Update plan (Update is Install with a prior release present).
# ---------------------------------------------------------------------------
function Resolve-SwitchTradeInstallPlan {
    param(
        [Parameter(Mandatory)]$Context,
        [Parameter(Mandatory)]$State,
        [Parameter(Mandatory)]$Package
    )
    # Phase persistence is owned by the executor step functions (checkpoint before mutation,
    # completion after success) so replay after process death sees exactly the persisted intent.
    $steps = [System.Collections.Generic.List[object]]::new()
    $steps.Add((New-SwitchTradePlanStep -Id 'install.require_prerequisites' -Kind 'require_prerequisites' -Stage 'prerequisite_inspection'))
    $steps.Add((New-SwitchTradePlanStep -Id 'install.ensure_wsl' -Kind 'ensure_wsl' -Stage 'prerequisites_enable'))
    $steps.Add((New-SwitchTradePlanStep -Id 'install.ensure_usbipd' -Kind 'ensure_usbipd' -Stage 'usbipd_install'))
    $steps.Add((New-SwitchTradePlanStep -Id 'install.create_transaction' -Kind 'create_transaction' -Stage 'transaction'))
    $steps.Add((New-SwitchTradePlanStep -Id 'install.stage_windows' -Kind 'stage_windows' -Stage 'windows_stage'))
    $steps.Add((New-SwitchTradePlanStep -Id 'install.ensure_distro' -Kind 'ensure_distro' -Stage 'distro_identity'))
    $steps.Add((New-SwitchTradePlanStep -Id 'install.stage_wsl' -Kind 'provision_stage' -Stage 'wsl_stage'))
    $steps.Add((New-SwitchTradePlanStep -Id 'install.validate_wsl' -Kind 'provision_validate' -Stage 'wsl_validate'))
    $steps.Add((New-SwitchTradePlanStep -Id 'install.control_readiness' -Kind 'control_readiness' -Stage 'control_readiness'))
    $steps.Add((New-SwitchTradePlanStep -Id 'install.apply_kernel' -Kind 'apply_kernel' -Stage 'kernel_apply'))
    $steps.Add((New-SwitchTradePlanStep -Id 'install.commit_wsl' -Kind 'provision_commit' -Stage 'commit'))
    $steps.Add((New-SwitchTradePlanStep -Id 'install.commit_windows' -Kind 'commit_windows' -Stage 'commit'))
    $steps.Add((New-SwitchTradePlanStep -Id 'install.hardware' -Kind 'hardware_prepare' -Stage 'hardware_preparation'))
    $steps.Add((New-SwitchTradePlanStep -Id 'install.shortcut' -Kind 'shortcut' -Stage 'completion'))
    $steps.Add((New-SwitchTradePlanStep -Id 'install.clear_resume' -Kind 'clear_resume' -Stage 'completion'))
    return New-SwitchTradePlan -Action 'Install' -Steps $steps.ToArray()
}

function Resolve-SwitchTradeRecoveryPlan {
    param(
        [Parameter(Mandatory)]$Context,
        [Parameter(Mandatory)]$State,
        [Parameter(Mandatory)]$Package
    )
    # The recovery executor steps persist their own compensating_* phases before mutating.
    $steps = [System.Collections.Generic.List[object]]::new()
    $steps.Add((New-SwitchTradePlanStep -Id 'recovery.gate_action' -Kind 'gate_recovery_action' -Stage 'transaction_recovery'))
    $steps.Add((New-SwitchTradePlanStep -Id 'recovery.gate_package' -Kind 'gate_recovery_package' -Stage 'transaction_recovery'))
    $steps.Add((New-SwitchTradePlanStep -Id 'recovery.gate_paths' -Kind 'gate_recovery_paths' -Stage 'transaction_recovery'))
    $steps.Add((New-SwitchTradePlanStep -Id 'recovery.gate_identity' -Kind 'gate_recovery_identity' -Stage 'transaction_recovery'))
    $steps.Add((New-SwitchTradePlanStep -Id 'recovery.bootstrap_marker' -Kind 'bootstrap_marker' -Stage 'transaction_recovery'))
    if ([string]$State.Transaction.Phase -match '^rollback_') {
        $steps.Add((New-SwitchTradePlanStep -Id 'recovery.rollback' -Kind 'recover_rollback' -Stage 'rollback_recovery'))
        return New-SwitchTradePlan -Action 'Repair' -Steps $steps.ToArray() -TerminalPhase 'completed'
    }
    $steps.Add((New-SwitchTradePlanStep -Id 'recovery.decide' -Kind 'recovery_decide' -Stage 'transaction_recovery'))
    $steps.Add((New-SwitchTradePlanStep -Id 'recovery.compensate_kernel' -Kind 'compensate_kernel' -Stage 'transaction_recovery'))
    $steps.Add((New-SwitchTradePlanStep -Id 'recovery.compensate_wsl' -Kind 'compensate_wsl' -Stage 'transaction_recovery'))
    $steps.Add((New-SwitchTradePlanStep -Id 'recovery.compensate_windows' -Kind 'compensate_windows' -Stage 'transaction_recovery'))
    $steps.Add((New-SwitchTradePlanStep -Id 'recovery.remove_stage' -Kind 'remove_stage' -Stage 'transaction_recovery'))
    # Legacy parity: an early fresh-install interruption (created .. distro_imported, no prior
    # release) is compensated (stage removed, freshly imported distro unregistered) and the
    # verified current package then runs the full install pipeline with a fresh transaction.
    if (Test-SwitchTradeEarlyFreshInstallRecovery -Transaction $State.Transaction.Transaction) {
        $install = Resolve-SwitchTradeInstallPlan -Context $Context -State $State -Package $Package
        foreach ($step in $install.Steps) { $steps.Add($step) }
        return New-SwitchTradePlan -Action 'Repair' -Steps $steps.ToArray() -TerminalPhase 'completed'
    }
    return New-SwitchTradePlan -Action 'Repair' -Steps $steps.ToArray() -TerminalPhase 'compensated'
}

function Resolve-SwitchTradeRollbackPlan {
    param(
        [Parameter(Mandatory)]$Context,
        [Parameter(Mandatory)]$State,
        [Parameter(Mandatory)]$Package
    )
    $steps = [System.Collections.Generic.List[object]]::new()
    $steps.Add((New-SwitchTradePlanStep -Id 'rollback.gate' -Kind 'gate_rollback' -Stage 'rollback_validate'))
    $steps.Add((New-SwitchTradePlanStep -Id 'rollback.start' -Kind 'start_rollback' -Stage 'rollback_validate'))
    $steps.Add((New-SwitchTradePlanStep -Id 'rollback.wsl' -Kind 'rollback_wsl' -Stage 'rollback_commit'))
    $steps.Add((New-SwitchTradePlanStep -Id 'rollback.kernel' -Kind 'rollback_kernel' -Stage 'rollback_commit'))
    $steps.Add((New-SwitchTradePlanStep -Id 'rollback.windows' -Kind 'rollback_windows' -Stage 'rollback_commit'))
    $steps.Add((New-SwitchTradePlanStep -Id 'rollback.publish' -Kind 'publish_rollback' -Stage 'rollback_commit'))
    return New-SwitchTradePlan -Action 'Rollback' -Steps $steps.ToArray()
}

function Resolve-SwitchTradeUninstallPlan {
    param(
        [Parameter(Mandatory)]$Context,
        [Parameter(Mandatory)]$State
    )
    $steps = [System.Collections.Generic.List[object]]::new()
    $steps.Add((New-SwitchTradePlanStep -Id 'uninstall.gate' -Kind 'gate_uninstall' -Stage 'uninstall_validate'))
    $steps.Add((New-SwitchTradePlanStep -Id 'uninstall.persist' -Kind 'checkpoint' -Stage 'uninstall'))
    $steps.Add((New-SwitchTradePlanStep -Id 'uninstall.unregister' -Kind 'unregister_distro' -Stage 'uninstall'))
    $steps.Add((New-SwitchTradePlanStep -Id 'uninstall.watcher' -Kind 'watcher_teardown' -Stage 'uninstall'))
    $steps.Add((New-SwitchTradePlanStep -Id 'uninstall.kernel_restore' -Kind 'kernel_restore' -Stage 'uninstall'))
    $steps.Add((New-SwitchTradePlanStep -Id 'uninstall.remove_active' -Kind 'remove_tree' -Stage 'uninstall' -Args @{ Target = $Context.InstallRoot }))
    $steps.Add((New-SwitchTradePlanStep -Id 'uninstall.remove_previous' -Kind 'remove_tree' -Stage 'uninstall' -Args @{ Target = $Context.PreviousInstall }))
    $steps.Add((New-SwitchTradePlanStep -Id 'uninstall.shortcut' -Kind 'remove_shortcut' -Stage 'uninstall'))
    $steps.Add((New-SwitchTradePlanStep -Id 'uninstall.complete' -Kind 'checkpoint' -Stage 'uninstall'))
    return New-SwitchTradePlan -Action 'Uninstall' -Steps $steps.ToArray() -TerminalPhase 'uninstalled'
}

function Resolve-SwitchTradePlan {
    param(
        [Parameter(Mandatory)]$Context,
        [Parameter(Mandatory)]$State,
        [Parameter(Mandatory)]$Package
    )
    $action = $Context.Action
    $transactionState = $State.Transaction
    if ($transactionState.Classification -eq 'corrupt') {
        return New-SwitchTradeBlocker -Code 'SETUP_TRANSACTION_CORRUPT' -Message 'the persisted transaction is unreadable; contact support' -Stage 'transaction' -Recoverable $false -PrimaryAction 'Contact SwitchTrade support'
    }
    if ($transactionState.Classification -eq 'future_schema') {
        return New-SwitchTradeBlocker -Code 'SETUP_TRANSACTION_FUTURE_SCHEMA' -Message 'the persisted transaction was written by a newer Setup; use the newer package' -Stage 'transaction' -Recoverable $false -PrimaryAction 'Run Setup from the package that wrote the transaction'
    }
    if ($transactionState.Classification -eq 'legacy') {
        return New-SwitchTradeBlocker -Code 'SETUP_TRANSACTION_LEGACY_AMBIGUOUS' -Message 'legacy transaction lacks pre-mutation ownership facts; contact support' -Stage 'transaction' -Recoverable $false -PrimaryAction 'Contact SwitchTrade support'
    }
    if ($transactionState.Classification -eq 'present') {
        if ($action -notin @('Repair', 'Install', 'Update', 'Rollback', 'Uninstall')) {
            return New-SwitchTradeBlocker -Code 'SETUP_TRANSACTION_INCOMPLETE' -Message ("transaction $($transactionState.TransactionId) stopped at $($transactionState.Phase); rerun the same action or choose Repair from the package that started it") -Stage 'transaction'
        }
        return Resolve-SwitchTradeRecoveryPlan -Context $Context -State $State -Package $Package
    }
    switch ($action) {
        'Install' { return Resolve-SwitchTradeInstallPlan -Context $Context -State $State -Package $Package }
        'Update' { return Resolve-SwitchTradeInstallPlan -Context $Context -State $State -Package $Package }
        'Repair' {
            $identity = $State.Identity
            if ($identity.DistroExists -and $identity.Classification -in @('present_invalid', 'present_foreign') -and
                    -not $State.WindowsActive.Exists -and -not $State.WslActive.Exists) {
                return New-SwitchTradeBlocker -Code 'DISTRO_NAME_COLLISION' -Message "'$($Context.Distro)' exists but is not owned by SwitchTrade Setup; choose another distro name" -Stage 'distro_identity' -PrimaryAction 'Choose another distribution name'
            }
            return Resolve-SwitchTradeInstallPlan -Context $Context -State $State -Package $Package
        }
        'Rollback' {
            if (-not $State.WindowsPrevious.Exists) {
                return New-SwitchTradeBlocker -Code 'ROLLBACK_WINDOWS_MISSING' -Message 'no retained SwitchTrade application version is available' -Stage 'rollback'
            }
            return Resolve-SwitchTradeRollbackPlan -Context $Context -State $State -Package $Package
        }
        'Uninstall' { return Resolve-SwitchTradeUninstallPlan -Context $Context -State $State }
        default {
            return New-SwitchTradeBlocker -Code 'SETUP_ACTION_UNSUPPORTED' -Message "action $action is not supported in this state" -Stage 'plan'
        }
    }
}