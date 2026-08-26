[CmdletBinding(SupportsShouldProcess)]
param(
    [ValidateSet('Audit', 'Install', 'Repair', 'Update', 'Resume', 'Rollback', 'Uninstall')]
    [string]$Action = 'Audit',
    [string]$Distro = 'SwitchTrade',
    [string]$UserProfileRoot = '',
    [string]$LocalAppDataRoot = '',
    [string]$DesktopRoot = '',
    [string]$InvokingUserSid = '',
    [string]$InstallRoot = '',
    [string]$DistroRoot = '',
    [ValidatePattern('^$|^\d+-\d+$')][string]$BusId = '',
    [ValidatePattern('^$|^[0-9a-fA-F]{4}:[0-9a-fA-F]{4}$')][string]$UsbId = '',
    [ValidateLength(0, 512)][string]$UsbInstanceId = '',
    [switch]$AcceptGlobalKernelChange,
    [switch]$AcceptPrerequisiteChanges,
    [switch]$AcceptVmwareRelease,
    [switch]$DeferHardwareSetup,
    [switch]$AllowUnsignedPackage,
    [switch]$NoShortcut,
    [switch]$PurgeDistro
)

$ErrorActionPreference = 'Stop'
$UserProfileRoot = if ($UserProfileRoot) { [IO.Path]::GetFullPath($UserProfileRoot) } else { $env:USERPROFILE }
$LocalAppDataRoot = if ($LocalAppDataRoot) { [IO.Path]::GetFullPath($LocalAppDataRoot) } else { $env:LOCALAPPDATA }
$DesktopRoot = if ($DesktopRoot) { [IO.Path]::GetFullPath($DesktopRoot) } else { Join-Path $UserProfileRoot 'Desktop' }
if (-not $InvokingUserSid) { $InvokingUserSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value }
if ($InvokingUserSid -notmatch '^S-1-5-21-(?:\d+-){3}\d+$') { throw 'INVOKING_USER_CONTEXT_INVALID' }
if (-not $InstallRoot) { $InstallRoot = Join-Path $LocalAppDataRoot 'Programs\SwitchTrade' }
if (-not $DistroRoot) { $DistroRoot = Join-Path $LocalAppDataRoot 'SwitchTrade\wsl' }
$SetupStage = 'initialize'
$SetupLog = ''
trap {
    $message = [string]$_.Exception.Message
    $candidateCode = ($message -split ':', 2)[0]
    $code = if ($candidateCode -match '^[A-Z][A-Z0-9_.-]+$') { $candidateCode } else { 'SETUP_FAILED' }
    if ($SetupLog) {
        try { Write-SwitchTradeSetupLog -Path $SetupLog -Stage $SetupStage -Message ($_ | Out-String) -Level error } catch { }
    }
    [Console]::Error.WriteLine("SWITCHTRADE_SETUP_ERROR: $message")
    $manualRecovery = $code -match '^SETUP_TRANSACTION_(LEGACY_AMBIGUOUS|.*_AMBIGUOUS|.*_MISMATCH|.*_INVALID|DISTRO_OWNERSHIP_CHANGED)'
    $primaryAction = if ($code -eq 'SETUP_TRANSACTION_PACKAGE_MISMATCH') {
        'Run Repair from the package that started the transaction'
    } elseif ($manualRecovery) { 'Contact SwitchTrade support' } else { 'Run Setup Repair' }
    $recoverable = $code -eq 'SETUP_TRANSACTION_PACKAGE_MISMATCH' -or -not $manualRecovery
    $failure = [ordered]@{
        code = $code; message = Redact-SwitchTradeSetupText $message; stage = $SetupStage
        recoverable = $recoverable; primary_action = $primaryAction; action = $Action
        correlation_id = [guid]::NewGuid().ToString('N')
    }
    [Console]::Error.WriteLine("SWITCHTRADE_SETUP_FAILURE: $($failure | ConvertTo-Json -Compress)")
    exit 1
}
$PackageRoot = Split-Path -Parent $PSScriptRoot
$Payload = Join-Path $PackageRoot 'payload\app'
$Rootfs = Join-Path $PackageRoot 'payload\switchtrade-rootfs.tar.gz'
$RootfsHash = Join-Path $PackageRoot 'payload\switchtrade-rootfs.sha256'
$DesktopExe = Join-Path $PackageRoot 'windows\SwitchTrade.exe'
$DesktopHash = Join-Path $PackageRoot 'windows\SwitchTrade.exe.sha256'
$ReleaseConfig = Join-Path $PackageRoot 'payload\release-config.json'
$Kernel = Join-Path $PackageRoot 'payload\kernel\kernel'
$KernelModulesVhdx = Join-Path $PackageRoot 'payload\kernel\modules.vhdx'
$KernelModulesVhd = Join-Path $PackageRoot 'payload\kernel\modules.vhd'
$KernelModulesArchive = Join-Path $PackageRoot 'payload\kernel\modules.tar.gz'
$KernelModules = @($KernelModulesVhdx, $KernelModulesVhd, $KernelModulesArchive) |
    Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
$KernelManifest = Join-Path $PackageRoot 'payload\kernel\manifest.json'
$StateRoot = Join-Path $LocalAppDataRoot 'SwitchTrade'
$KernelStorageRoot = Join-Path $env:ProgramData 'SwitchTrade\kernel'
$UsbipdMsi = Join-Path $PackageRoot 'payload\prerequisites\usbipd-win.msi'
$UsbipdManifest = Join-Path $PackageRoot 'payload\prerequisites\usbipd-win.json'
$PreviousInstall = "$InstallRoot.previous"
. (Join-Path $PSScriptRoot 'KernelLifecycle.ps1')
. (Join-Path $PSScriptRoot 'PackageIntegrity.ps1')
. (Join-Path $PSScriptRoot 'HostCompatibility.ps1')
. (Join-Path $PSScriptRoot 'SetupLifecycle.ps1')

$ResumeStatePath = Join-Path $StateRoot 'setup-resume.json'
$TransactionPath = Join-Path $StateRoot 'setup-transaction.json'
$SetupLog = Join-Path $StateRoot 'logs\setup.jsonl'
$ResumeRunOnce = 'SwitchTradeSetupResume'
$ResumeRegistryPath = "Registry::HKEY_USERS\$InvokingUserSid\Software\Microsoft\Windows\CurrentVersion\RunOnce"
$StartupRegistryPath = "Registry::HKEY_USERS\$InvokingUserSid\Software\Microsoft\Windows\CurrentVersion\Run"
$WasResume = $Action -eq 'Resume'

function Save-SetupResume([string]$ResumeAction) {
    if ($BusId -and -not $UsbInstanceId) {
        throw 'USB_STABLE_ID_REQUIRED: reselect the adapter before scheduling setup resume'
    }
    if ($UsbInstanceId -and ($UsbInstanceId.ToCharArray() | Where-Object { [char]::IsControl($_) })) {
        throw 'USB_STABLE_ID_INVALID: the adapter instance identity contains invalid characters'
    }
    New-Item -ItemType Directory -Force -Path $StateRoot | Out-Null
    @{
        schema = 3; package_root = $PackageRoot; action = $ResumeAction
        distro = $Distro; install_root = $InstallRoot; distro_root = $DistroRoot
        user_profile_root = $UserProfileRoot; local_app_data_root = $LocalAppDataRoot
        desktop_root = $DesktopRoot; invoking_user_sid = $InvokingUserSid
        bus_id = $BusId; usb_id = $UsbId; usb_instance_id = $UsbInstanceId
        accept_global_kernel_change = [bool]$AcceptGlobalKernelChange
        accept_prerequisite_changes = [bool]$AcceptPrerequisiteChanges
        accept_vmware_release = [bool]$AcceptVmwareRelease
        defer_hardware_setup = [bool]$DeferHardwareSetup
        no_shortcut = [bool]$NoShortcut
    } | ConvertTo-Json | Set-Content -LiteralPath $ResumeStatePath -Encoding UTF8
    $setupExe = Join-Path $PackageRoot 'SwitchTradeSetup.exe'
    if (-not (Test-Path -LiteralPath $setupExe -PathType Leaf)) {
        throw 'SETUP_RESUME_UNAVAILABLE: the native setup executable is missing'
    }
    $command = "`"$setupExe`" resume"
    New-Item -Path $ResumeRegistryPath -Force | Out-Null
    Set-ItemProperty -Path $ResumeRegistryPath `
        -Name $ResumeRunOnce -Value $command
}

function Clear-SetupResume {
    if (Test-Path -LiteralPath $ResumeStatePath -PathType Leaf) {
        Remove-Item -LiteralPath $ResumeStatePath -Force
    }
    Remove-ItemProperty -Path $ResumeRegistryPath `
        -Name $ResumeRunOnce -ErrorAction SilentlyContinue
}

if ($WasResume) {
    if (-not (Test-Path -LiteralPath $ResumeStatePath -PathType Leaf)) {
        throw 'SETUP_RESUME_STATE_MISSING: rerun the signed SwitchTrade setup package'
    }
    $resume = Get-Content -Raw -LiteralPath $ResumeStatePath | ConvertFrom-Json
    if ([int]$resume.schema -ne 3 -or [string]$resume.package_root -ne $PackageRoot -or
        [string]$resume.action -notin @('Install', 'Repair', 'Update')) {
        throw 'SETUP_RESUME_STATE_INVALID: rerun the signed SwitchTrade setup package'
    }
    if ([string]$resume.user_profile_root -ne $UserProfileRoot -or
        [string]$resume.local_app_data_root -ne $LocalAppDataRoot -or
        [string]$resume.desktop_root -ne $DesktopRoot -or
        [string]$resume.invoking_user_sid -ne $InvokingUserSid) {
        throw 'SETUP_RESUME_USER_MISMATCH: resume must run as the user who started setup'
    }
    $Action = [string]$resume.action
    $Distro = [string]$resume.distro
    $InstallRoot = [string]$resume.install_root
    $DistroRoot = [string]$resume.distro_root
    $BusId = [string]$resume.bus_id
    $UsbId = [string]$resume.usb_id
    $UsbInstanceId = [string]$resume.usb_instance_id
    $AcceptGlobalKernelChange = [bool]$resume.accept_global_kernel_change
    $AcceptPrerequisiteChanges = [bool]$resume.accept_prerequisite_changes
    $AcceptVmwareRelease = [bool]$resume.accept_vmware_release
    $DeferHardwareSetup = [bool]$resume.defer_hardware_setup
    $NoShortcut = [bool]$resume.no_shortcut
    $PreviousInstall = "$InstallRoot.previous"
}

function Get-Distros {
    if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) { return @() }
    try { $result = Invoke-BoundedNativeProcess -FilePath 'wsl.exe' -Arguments @('--list', '--quiet') -TimeoutSeconds 15 }
    catch { return @() }
    if ($result.ExitCode -ne 0) { return @() }
    return @(($result.Output -split "`r?`n") | ForEach-Object { $_.Trim([char]0).Trim() } | Where-Object { $_ })
}

function Convert-ToWslPath([string]$Path) {
    $resolved = (Resolve-Path -LiteralPath $Path).Path
    if ($resolved -notmatch '^([A-Za-z]):\\(.*)$') { throw "cannot map path into WSL: $resolved" }
    return "/mnt/$($Matches[1].ToLowerInvariant())/$($Matches[2].Replace('\', '/'))"
}

function Test-SwitchTradeDistroOwned {
    param([Parameter(Mandatory)][string]$Name)
    try {
        $result = Invoke-BoundedNativeProcess -FilePath 'wsl.exe' `
            -Arguments @('-d', $Name, '-u', 'root', '--', 'cat', '/etc/switchtrade-distro.json') `
            -TimeoutSeconds 20
    } catch { return $false }
    $raw = $result.Output.Trim()
    if ($result.ExitCode -ne 0 -or -not $raw) { return $false }
    try {
        $marker = $raw | ConvertFrom-Json
        return [int]$marker.schema -eq 1 -and [string]$marker.owner -ceq 'switchtrade-installer' -and
            [string]$marker.product -ceq 'SwitchTrade'
    } catch { return $false }
}

function Assert-SwitchTradeDistroOwned {
    param([Parameter(Mandatory)][string]$Name)
    if (-not (Test-SwitchTradeDistroOwned -Name $Name)) {
        throw "DISTRO_NAME_COLLISION: '$Name' exists but is not owned by SwitchTrade Setup; choose another distro name"
    }
}

function Invoke-LoggedWsl {
    param(
        [Parameter(Mandatory)][string[]]$Arguments,
        [Parameter(Mandatory)][string]$FailureCode,
        [Parameter(Mandatory)][string]$Stage
    )
    $script:SetupStage = $Stage
    $result = Invoke-BoundedNativeProcess -FilePath 'wsl.exe' -Arguments $Arguments -TimeoutSeconds 600
    $output = @($result.Output, $result.Error | Where-Object { $_ })
    foreach ($line in (($output -join "`n") -split "`r?`n")) {
        if (-not $line) { continue }
        Write-SwitchTradeSetupLog -Path $SetupLog -Stage $Stage -Message ([string]$line)
    }
    if ($result.ExitCode -ne 0) {
        throw "${FailureCode}: $((($output -join "`n")).Trim())"
    }
    return $result.Output
}

function Get-SwitchTradeWslRuntimeState {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][ValidateSet('active', 'candidate', 'previous', 'commit_swap')]
        [string]$Location
    )
    $path = @{
        active = '/opt/switchtrade'; candidate = '/opt/switchtrade.candidate'
        previous = '/opt/switchtrade.previous'; commit_swap = '/opt/switchtrade.commit-swap'
    }[$Location]
    $probe = 'p="{0}"; if [ ! -e "$p" ]; then printf ''absent''; elif [ ! -d "$p" ] || [ ! -f "$p/.switchtrade-release.json" ]; then printf ''invalid''; else cat "$p/.switchtrade-release.json"; fi' -f $path
    try {
        $result = Invoke-BoundedNativeProcess -FilePath 'wsl.exe' `
            -Arguments @('-d', $Name, '-u', 'root', '--', 'sh', '-lc', $probe) -TimeoutSeconds 30
    } catch {
        return [pscustomobject]@{ Exists = $true; Valid = $false; ReleaseId = '' }
    }
    $raw = $result.Output.Trim()
    if ($result.ExitCode -ne 0 -or $raw -eq 'invalid') {
        return [pscustomobject]@{ Exists = $true; Valid = $false; ReleaseId = '' }
    }
    if ($raw -eq 'absent') {
        return [pscustomobject]@{ Exists = $false; Valid = $true; ReleaseId = '' }
    }
    try {
        $marker = $raw | ConvertFrom-Json
        $release = [string]$marker.release_id
        $valid = [int]$marker.schema -eq 1 -and $release -match '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'
        return [pscustomobject]@{ Exists = $true; Valid = $valid; ReleaseId = $(if ($valid) { $release } else { '' }) }
    } catch {
        return [pscustomobject]@{ Exists = $true; Valid = $false; ReleaseId = '' }
    }
}

function Repair-SwitchTradeInterruptedTransaction {
    param([Parameter(Mandatory)]$Transaction)
    $script:SetupStage = 'transaction_recovery'
    if ($Action -ne 'Repair') {
        throw "SETUP_TRANSACTION_INCOMPLETE: transaction $($Transaction.transaction_id) stopped at $($Transaction.phase); run the matching package Repair"
    }
    if ([int]$Transaction.schema -ne 2) {
        throw 'SETUP_TRANSACTION_LEGACY_AMBIGUOUS: legacy transaction lacks pre-mutation ownership facts; contact support'
    }
    Assert-SwitchTradeTransactionPackage -Transaction $Transaction -PackageRoot $PackageRoot `
        -ReleaseId $ReleaseId
    Assert-SwitchTradeRecordedPath -Recorded ([string]$Transaction.install_root) `
        -Expected $InstallRoot -Code 'SETUP_TRANSACTION_INSTALL_PATH_MISMATCH' | Out-Null
    Assert-SwitchTradeRecordedPath -Recorded ([string]$Transaction.previous_install) `
        -Expected $PreviousInstall -Code 'SETUP_TRANSACTION_PREVIOUS_PATH_MISMATCH' | Out-Null
    Assert-SwitchTradeRecordedPath -Recorded ([string]$Transaction.distro_root) `
        -Expected $DistroRoot -Code 'SETUP_TRANSACTION_DISTRO_PATH_MISMATCH' | Out-Null
    Assert-SwitchTradeRecordedPath -Recorded ([string]$Transaction.kernel_state_path) `
        -Expected (Join-Path $StateRoot 'kernel-state.json') `
        -Code 'SETUP_TRANSACTION_KERNEL_PATH_MISMATCH' | Out-Null
    if ([string]$Transaction.distro_name -cne $Distro) {
        throw 'SETUP_TRANSACTION_DISTRO_MISMATCH: recorded distribution name does not match Repair'
    }
    $expectedWslPaths = @{
        wsl_active_path = '/opt/switchtrade'; wsl_candidate_path = '/opt/switchtrade.candidate'
        wsl_previous_path = '/opt/switchtrade.previous'
        wsl_commit_swap_path = '/opt/switchtrade.commit-swap'
    }
    foreach ($property in $expectedWslPaths.Keys) {
        if ([string]$Transaction.$property -cne $expectedWslPaths[$property]) {
            throw 'SETUP_TRANSACTION_WSL_PATH_MISMATCH: recorded runtime paths are not the fixed product paths'
        }
    }
    $stage = Assert-SwitchTradeRecordedStagePath -Recorded ([string]$Transaction.windows_stage) `
        -InstallRoot $InstallRoot

    $distroExists = (Get-Distros) -contains $Distro
    $distroOwned = $distroExists -and (Test-SwitchTradeDistroOwned -Name $Distro)
    $emptyWsl = [pscustomobject]@{ Exists = $false; Valid = $true; ReleaseId = '' }
    $wslActive = $emptyWsl; $wslCandidate = $emptyWsl
    $wslPrevious = $emptyWsl; $wslCommitSwap = $emptyWsl
    if ($distroOwned) {
        $wslActive = Get-SwitchTradeWslRuntimeState -Name $Distro -Location active
        $wslCandidate = Get-SwitchTradeWslRuntimeState -Name $Distro -Location candidate
        $wslPrevious = Get-SwitchTradeWslRuntimeState -Name $Distro -Location previous
        $wslCommitSwap = Get-SwitchTradeWslRuntimeState -Name $Distro -Location commit_swap
        foreach ($runtimeState in @($wslActive, $wslCandidate, $wslPrevious, $wslCommitSwap)) {
            if (-not $runtimeState.Valid) {
                throw 'SETUP_TRANSACTION_WSL_LAYOUT_INVALID: a runtime transaction path is not a proven release tree'
            }
        }
    }
    $kernelStatePath = Join-Path $StateRoot 'kernel-state.json'
    $kernelState = $null
    if (Test-Path -LiteralPath $kernelStatePath -PathType Leaf) {
        try { $kernelState = Get-Content -Raw -LiteralPath $kernelStatePath | ConvertFrom-Json }
        catch { throw 'SETUP_TRANSACTION_KERNEL_STATE_INVALID: kernel state is unreadable' }
    }
    foreach ($windowsTree in @(
            @($InstallRoot, (Test-Path -LiteralPath $InstallRoot -PathType Container)),
            @($PreviousInstall, (Test-Path -LiteralPath $PreviousInstall -PathType Container)))) {
        if ($windowsTree[1]) {
            $treeRelease = Get-InstalledWindowsReleaseId -Root $windowsTree[0]
            if (-not $treeRelease) {
                throw 'SETUP_TRANSACTION_WINDOWS_TREE_INVALID: a Windows release tree has no valid identity'
            }
            Test-WindowsReleaseTree -Root $windowsTree[0] -ExpectedReleaseId $treeRelease | Out-Null
        }
    }
    if ($kernelState) {
        if (-not [bool]$kernelState.owns_kernel_change -or
                -not (Test-Path -LiteralPath ([string]$kernelState.kernel_path) -PathType Leaf) -or
                (Get-FileSha256 ([string]$kernelState.kernel_path)) -ne [string]$kernelState.kernel_sha256) {
            throw 'SETUP_TRANSACTION_KERNEL_STATE_INVALID: active kernel artifact is not proven'
        }
        if ($kernelState.modules_path -and
                (-not (Test-Path -LiteralPath ([string]$kernelState.modules_path) -PathType Leaf) -or
                 (Get-FileSha256 ([string]$kernelState.modules_path)) -ne [string]$kernelState.modules_sha256)) {
            throw 'SETUP_TRANSACTION_KERNEL_STATE_INVALID: active kernel modules are not proven'
        }
        if ([string]$kernelState.package_release_id -eq [string]$Transaction.kernel_prior_release_id -and
                ([string]$kernelState.kernel_path -ne [string]$Transaction.kernel_prior_path -or
                 [string]$kernelState.modules_path -ne [string]$Transaction.kernel_prior_modules_path)) {
            throw 'SETUP_TRANSACTION_KERNEL_PRIOR_MISMATCH: active prior kernel paths changed'
        }
        if ([string]$kernelState.package_release_id -eq $ReleaseId -and
                [string]$Transaction.kernel_prior_release_id) {
            if ([string]$kernelState.rollback_kernel_path -ne [string]$Transaction.kernel_prior_path -or
                    [string]$kernelState.rollback_modules_path -ne [string]$Transaction.kernel_prior_modules_path) {
                throw 'SETUP_TRANSACTION_KERNEL_ROLLBACK_MISMATCH: retained kernel paths differ from the recorded prior state'
            }
            Test-SwitchTradeKernelRollback -StateRoot $StateRoot `
                -ExpectedReleaseId ([string]$Transaction.kernel_prior_release_id) | Out-Null
        }
    }
    $actual = [pscustomobject]@{
        DistroExists = $distroExists; DistroOwned = $distroOwned
        WindowsActiveExists = (Test-Path -LiteralPath $InstallRoot -PathType Container)
        WindowsActiveRelease = Get-InstalledWindowsReleaseId -Root $InstallRoot
        WindowsPreviousExists = (Test-Path -LiteralPath $PreviousInstall -PathType Container)
        WindowsPreviousRelease = Get-InstalledWindowsReleaseId -Root $PreviousInstall
        WindowsStageExists = (Test-Path -LiteralPath $stage -PathType Container)
        WslActiveRelease = $wslActive.ReleaseId
        WslCandidateExists = $wslCandidate.Exists; WslCandidateRelease = $wslCandidate.ReleaseId
        WslPreviousRelease = $wslPrevious.ReleaseId
        WslCommitSwapExists = $wslCommitSwap.Exists; WslCommitSwapRelease = $wslCommitSwap.ReleaseId
        KernelRelease = if ($kernelState) { [string]$kernelState.package_release_id } else { '' }
    }
    $plan = Resolve-SwitchTradeTransactionRecovery -Transaction $Transaction -Actual $actual
    if ($plan.Disposition -eq 'finalize') {
        $provision = Convert-ToWslPath (Join-Path $PackageRoot 'installer\provision-wsl.sh')
        Invoke-LoggedWsl -Arguments @('-d', $Distro, '-u', 'root', '--', 'bash', $provision,
            '--validate-active', '--release-id', $ReleaseId) `
            -FailureCode 'WSL_RECOVERY_ACTIVE_INVALID' -Stage $SetupStage | Out-Null
        if ([string]$Transaction.wsl_prior_release_id) {
            Invoke-LoggedWsl -Arguments @('-d', $Distro, '-u', 'root', '--', 'bash', $provision,
                '--validate-retained', '--release-id', [string]$Transaction.wsl_prior_release_id) `
                -FailureCode 'WSL_RECOVERY_RETAINED_INVALID' -Stage $SetupStage | Out-Null
        }
        Set-SwitchTradeTransactionPhase -Path $TransactionPath -Phase 'completed' `
            -Fields @{ windows_committed = $true; wsl_committed = $true } | Out-Null
        Write-SwitchTradeSetupLog -Path $SetupLog -Stage $SetupStage `
            -Message "finalized coherent interrupted transaction $($Transaction.transaction_id)"
        return 'finalize'
    }

    if ($plan.KernelAction -eq 'rollback') {
        if ([string]$kernelState.rollback_kernel_path -ne [string]$Transaction.kernel_prior_path -or
                [string]$kernelState.rollback_modules_path -ne [string]$Transaction.kernel_prior_modules_path) {
            throw 'SETUP_TRANSACTION_KERNEL_ROLLBACK_MISMATCH: retained kernel paths differ from the recorded prior state'
        }
        Switch-SwitchTradeKernelRollback -StateRoot $StateRoot `
            -ExpectedReleaseId ([string]$Transaction.kernel_prior_release_id) `
            -UserProfileRoot $UserProfileRoot | Out-Null
    } elseif ($plan.KernelAction -eq 'restore_original') {
        Restore-SwitchTradeKernel -StateRoot $StateRoot -UserProfileRoot $UserProfileRoot | Out-Null
    }

    $provision = Convert-ToWslPath (Join-Path $PackageRoot 'installer\provision-wsl.sh')
    switch ($plan.WslAction) {
        'abort_candidate' {
            Invoke-LoggedWsl -Arguments @('-d', $Distro, '-u', 'root', '--', 'bash', $provision,
                '--abort', '--release-id', $ReleaseId) -FailureCode 'WSL_RECOVERY_ABORT_FAILED' `
                -Stage $SetupStage | Out-Null
        }
        'compensate' {
            Invoke-LoggedWsl -Arguments @('-d', $Distro, '-u', 'root', '--', 'bash', $provision,
                '--compensate', '--release-id', [string]$Transaction.wsl_prior_release_id) `
                -FailureCode 'WSL_RECOVERY_COMPENSATION_FAILED' -Stage $SetupStage | Out-Null
        }
        'recover_interrupted' {
            Invoke-LoggedWsl -Arguments @('-d', $Distro, '-u', 'root', '--', 'bash', $provision,
                '--recover-interrupted', '--release-id', $ReleaseId, '--prior-release-id',
                [string]$Transaction.wsl_prior_release_id) `
                -FailureCode 'WSL_RECOVERY_SWAP_FAILED' -Stage $SetupStage | Out-Null
        }
        'unregister_new' {
            Assert-SwitchTradeDistroOwned -Name $Distro
            $unregister = Invoke-BoundedNativeProcess -FilePath 'wsl.exe' `
                -Arguments @('--unregister', $Distro) -TimeoutSeconds 120
            if ($unregister.ExitCode -ne 0) { throw 'DISTRO_RECOVERY_UNREGISTER_FAILED' }
        }
    }

    switch ($plan.WindowsAction) {
        'rollback' {
            Switch-SwitchTradeWindowsRollback -Active $InstallRoot -Previous $PreviousInstall `
                -ExpectedReleaseId ([string]$Transaction.prior_release_id) | Out-Null
        }
        'restore_prior' {
            Test-WindowsReleaseTree -Root $PreviousInstall `
                -ExpectedReleaseId ([string]$Transaction.prior_release_id) | Out-Null
            Move-Item -LiteralPath $PreviousInstall -Destination $InstallRoot
        }
        'remove_new' {
            Test-WindowsReleaseTree -Root $InstallRoot -ExpectedReleaseId $ReleaseId | Out-Null
            Remove-Item -LiteralPath $InstallRoot -Recurse -Force
        }
    }
    if ($plan.RemoveStage) {
        $stageItem = Get-Item -LiteralPath $stage -Force
        if ($stageItem.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw 'SETUP_TRANSACTION_STAGE_REPARSE_POINT: refusing to remove a redirected stage path'
        }
        Remove-Item -LiteralPath $stage -Recurse -Force
    }
    Set-SwitchTradeTransactionPhase -Path $TransactionPath -Phase 'compensated' | Out-Null
    Write-SwitchTradeSetupLog -Path $SetupLog -Stage $SetupStage `
        -Message "compensated interrupted transaction $($Transaction.transaction_id)"
    return 'compensate'
}

function Resolve-StableUsbBusId {
    if (-not $UsbInstanceId) { return $BusId }
    $script:SetupStage = 'usb_identity'
    $result = Invoke-BoundedNativeProcess -FilePath 'usbipd.exe' -Arguments @('state') -TimeoutSeconds 15
    $raw = ($result.Output + $result.Error).Trim()
    if ($result.ExitCode -ne 0) { throw "USBIPD_STATE_FAILED: $raw" }
    $state = $raw | ConvertFrom-Json
    $device = Resolve-SwitchTradeUsbDeviceFromState -State $state -InstanceId $UsbInstanceId -UsbId $UsbId
    return [string]$device.BusId
}

function Assert-SwitchTradeHostCapabilities {
    param([switch]$SkipUsbipd)
    $script:SetupStage = 'host_capabilities'
    $wslVersion = Invoke-BoundedNativeProcess -FilePath 'wsl.exe' -Arguments @('--version') -TimeoutSeconds 15
    $wslHelp = Invoke-BoundedNativeProcess -FilePath 'wsl.exe' -Arguments @('--help') -TimeoutSeconds 15
    if ($wslVersion.ExitCode -ne 0 -or $wslHelp.ExitCode -ne 0) { throw 'WSL_CAPABILITY_PROBE_FAILED' }
    Test-SwitchTradeWslCapabilities -VersionText $wslVersion.Output -HelpText $wslHelp.Output | Out-Null

    if ($SkipUsbipd) { return }

    $usbipdCommand = Get-Command usbipd.exe -ErrorAction Stop
    $usbipdMetadata = Get-Content -Raw -LiteralPath $UsbipdManifest | ConvertFrom-Json
    $minimumUsbipd = [version][string]$usbipdMetadata.version
    $usbipdVersion = [string]$usbipdCommand.FileVersionInfo.ProductVersion
    $usbipdHelp = Invoke-BoundedNativeProcess -FilePath $usbipdCommand.Source -Arguments @('--help') -TimeoutSeconds 15
    $attachHelp = Invoke-BoundedNativeProcess -FilePath $usbipdCommand.Source -Arguments @('attach', '--help') -TimeoutSeconds 15
    $stateResult = Invoke-BoundedNativeProcess -FilePath $usbipdCommand.Source -Arguments @('state') -TimeoutSeconds 15
    if ($usbipdHelp.ExitCode -ne 0 -or $attachHelp.ExitCode -ne 0 -or $stateResult.ExitCode -ne 0) {
        throw 'USBIPD_CAPABILITY_PROBE_FAILED'
    }
    $state = $stateResult.Output | ConvertFrom-Json
    Test-SwitchTradeUsbipdCapabilities -VersionText $usbipdVersion -MinimumVersion $minimumUsbipd `
        -HelpText ($usbipdHelp.Output + "`n" + $attachHelp.Output) -State $state | Out-Null
}

function Test-StagedControlReadiness {
    param([Parameter(Mandatory)][string]$ExpectedReleaseId)
    $script:SetupStage = 'control_readiness'
    $port = 18787
    $arguments = @(
        '-d', $Distro, '-u', 'root', '--cd', '/opt/switchtrade.candidate', '--',
        'env', "SWITCHTRADE_CONTROL_PORT=$port", 'SWITCHTRADE_CONTROL_INSTANCE=setup-candidate',
        'SWITCHTRADE_RELEASE_ROOT=/opt/switchtrade.candidate',
        '/opt/switchtrade.candidate/bridge/.venv/bin/python', '-m', 'switchtrade.control'
    )
    $process = Start-Process wsl.exe -ArgumentList $arguments -WindowStyle Hidden -PassThru
    try {
        for ($attempt = 0; $attempt -lt 30; $attempt++) {
            if ($process.HasExited) { break }
            try {
                $ready = Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/v1/app/readiness" -TimeoutSec 1
                if ($ready.contract_version -eq 'app-readiness.v1' -and $ready.compatible -and
                    [string]$ready.release_id -eq $ExpectedReleaseId) { return $true }
                if ($ready) { throw 'STAGED_CONTROL_RELEASE_MISMATCH' }
            } catch {
                if ([string]$_.Exception.Message -eq 'STAGED_CONTROL_RELEASE_MISMATCH') { throw }
            }
            Start-Sleep -Milliseconds 500
        }
        throw 'STAGED_CONTROL_NOT_READY: staged control did not advertise the package release'
    } finally {
        if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue }
        try { Invoke-BoundedNativeProcess -FilePath 'wsl.exe' -Arguments @('--terminate', $Distro) -TimeoutSeconds 30 | Out-Null } catch { }
    }
}

function Test-Setup {
    $distros = Get-Distros
    $vmware = Get-Service VMUSBArbService -ErrorAction SilentlyContinue
    $computer = Get-CimInstance Win32_ComputerSystem -ErrorAction SilentlyContinue
    $operatingSystem = Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue
    $processors = @(Get-CimInstance Win32_Processor -ErrorAction SilentlyContinue)
    $wslCommandPresent = [bool](Get-Command wsl.exe -ErrorAction SilentlyContinue)
    $wslFeature = $null
    $vmFeature = $null
    try {
        $wslFeature = Get-WindowsOptionalFeature -Online `
            -FeatureName Microsoft-Windows-Subsystem-Linux -ErrorAction Stop
        $vmFeature = Get-WindowsOptionalFeature -Online `
            -FeatureName VirtualMachinePlatform -ErrorAction Stop
    } catch { }
    $wslFeaturesEnabled = $wslFeature -and $vmFeature -and
        [string]$wslFeature.State -in @('Enabled', 'EnablePending') -and
        [string]$vmFeature.State -in @('Enabled', 'EnablePending')
    $wslStatusExit = 1
    $wslVersionExit = 1
    $wslVersion = 'Absent'
    $wslCapabilityReady = $false
    if ($wslCommandPresent) {
        try {
            $statusProbe = Invoke-BoundedNativeProcess -FilePath 'wsl.exe' -Arguments @('--status') -TimeoutSeconds 15
            $versionProbe = Invoke-BoundedNativeProcess -FilePath 'wsl.exe' -Arguments @('--version') -TimeoutSeconds 15
            $wslStatusExit = $statusProbe.ExitCode
            $wslVersionExit = $versionProbe.ExitCode
            if ($wslVersionExit -eq 0) {
                $wslVersion = $versionProbe.Output.Replace([string][char]0, '').Trim()
                $helpProbe = Invoke-BoundedNativeProcess -FilePath 'wsl.exe' -Arguments @('--help') -TimeoutSeconds 15
                if ($helpProbe.ExitCode -eq 0) {
                    try {
                        Test-SwitchTradeWslCapabilities -VersionText $wslVersion `
                            -HelpText $helpProbe.Output | Out-Null
                        $wslCapabilityReady = $true
                    } catch { }
                }
            }
        } catch { }
    }
    $architecture = [Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
    $windowsBuild = if ($operatingSystem) { [int]$operatingSystem.BuildNumber } else {
        [Environment]::OSVersion.Version.Build
    }
    $productType = if ($operatingSystem) { [int]$operatingSystem.ProductType } else { 0 }
    $firmwareVirtualization = [bool]($processors | Where-Object { $_.VirtualizationFirmwareEnabled } |
        Select-Object -First 1)
    [pscustomobject]@{
        Windows64Bit = [Environment]::Is64BitOperatingSystem
        WindowsSupported = Test-SwitchTradeWindowsHost -Build $windowsBuild `
            -ProductType $productType -Architecture $architecture
        WindowsProductType = $productType
        WslInstalled = $wslCommandPresent -and ($wslFeaturesEnabled -or $wslStatusExit -eq 0)
        WslFeaturesEnabled = [bool]$wslFeaturesEnabled
        WslModern = $wslCapabilityReady
        WslVersion = $wslVersion
        UsbipdInstalled = [bool](Get-Command usbipd.exe -ErrorAction SilentlyContinue)
        DistroInstalled = $distros -contains $Distro
        PayloadPresent = Test-Path -LiteralPath $Payload -PathType Container
        RootfsPresent = Test-Path -LiteralPath $Rootfs -PathType Leaf
        InstallRoot = $InstallRoot
        Distro = $Distro
        KernelPolicy = 'unchanged'
        ExistingWslConfig = Test-Path -LiteralPath (Join-Path $UserProfileRoot '.wslconfig')
        WindowsBuild = $windowsBuild
        Architecture = $architecture
        FreeSpaceGB = [math]::Round((Get-PSDrive -Name ([IO.Path]::GetPathRoot($InstallRoot).Substring(0,1))).Free / 1GB, 1)
        PendingReboot = Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired'
        VirtualizationReady = [bool](($computer -and $computer.HypervisorPresent) -or
            $firmwareVirtualization)
        VmwareUsbArbitrator = if ($vmware) { [string]$vmware.Status } else { 'Absent' }
        KernelBundlePresent = (Test-Path -LiteralPath $Kernel) -and (Test-Path -LiteralPath $KernelManifest)
    }
}

if ($Action -eq 'Audit') {
    Test-Setup | Format-List
    exit
}

$ReleaseId = ''
if ($Action -in @('Install', 'Repair', 'Update')) {
    $SetupStage = 'package_integrity'
    Test-SwitchTradePackage -PackageRoot $PackageRoot -AllowUnsignedPackage:$AllowUnsignedPackage | Out-Null
    $ReleaseId = Get-SwitchTradeReleaseId -ManifestPath (Join-Path $PackageRoot 'manifest.json')
}

$SetupStage = 'mutex'
$SetupMutex = Enter-SwitchTradeSetupMutex
Write-SwitchTradeSetupLog -Path $SetupLog -Stage $SetupStage -Message "setup action=$Action acquired the mutation mutex"
$namedDistroExists = (Get-Distros) -contains $Distro
$recoveredCommitted = $false
if ($namedDistroExists) { Assert-SwitchTradeDistroOwned -Name $Distro }
if (Test-Path -LiteralPath $TransactionPath -PathType Leaf) {
    $staleTransaction = Get-Content -Raw -LiteralPath $TransactionPath | ConvertFrom-Json
    if ([string]$staleTransaction.phase -notin @('completed', 'compensated')) {
        $recoveryDisposition = Repair-SwitchTradeInterruptedTransaction -Transaction $staleTransaction
        $recoveredCommitted = $recoveryDisposition -eq 'finalize'
        $namedDistroExists = (Get-Distros) -contains $Distro
        if ($namedDistroExists) { Assert-SwitchTradeDistroOwned -Name $Distro }
    }
}

if ($Action -eq 'Uninstall') {
    Clear-SetupResume
    Unregister-SwitchTradeUsbWatcherStartup -RegistryPath $StartupRegistryPath
    Stop-SwitchTradeUsbWatcher -StateRoot $StateRoot | Out-Null
    Restore-SwitchTradeKernel -StateRoot $StateRoot -UserProfileRoot $UserProfileRoot | Out-Null
    if (Test-Path -LiteralPath $InstallRoot) {
        if ($PSCmdlet.ShouldProcess($InstallRoot, 'Remove SwitchTrade application files')) {
            Remove-Item -LiteralPath $InstallRoot -Recurse -Force
        }
    }
    if (Test-Path -LiteralPath $PreviousInstall) {
        if ($PSCmdlet.ShouldProcess($PreviousInstall, 'Remove retained SwitchTrade rollback version')) {
            Remove-Item -LiteralPath $PreviousInstall -Recurse -Force
        }
    }
    if ($PurgeDistro -and ((Get-Distros) -contains $Distro)) {
        if ($PSCmdlet.ShouldProcess($Distro, 'Unregister only the named SwitchTrade WSL distribution')) {
            $unregister = Invoke-BoundedNativeProcess -FilePath 'wsl.exe' `
                -Arguments @('--unregister', $Distro) -TimeoutSeconds 120
            if ($unregister.ExitCode -ne 0) { throw "DISTRO_UNREGISTER_FAILED: $($unregister.Error)" }
        }
    }
    $shortcutPath = Join-Path $DesktopRoot 'SwitchTrade.lnk'
    if (-not $NoShortcut -and (Test-Path -LiteralPath $shortcutPath -PathType Leaf)) {
        if ($PSCmdlet.ShouldProcess($shortcutPath, 'Remove SwitchTrade shortcut')) {
            Remove-Item -LiteralPath $shortcutPath -Force
        }
    }
    Write-Host "SwitchTrade application removed.$(if ($PurgeDistro) { ' Distro purge requested.' })"
    exit
}

if ($Action -eq 'Rollback') {
    Clear-SetupResume
    if (-not (Test-Path -LiteralPath $PreviousInstall -PathType Container)) {
        throw 'ROLLBACK_WINDOWS_MISSING: no retained SwitchTrade application version is available'
    }
    if (-not $namedDistroExists) { throw 'ROLLBACK_DISTRO_MISSING: the owned SwitchTrade distro is absent' }
    $SetupStage = 'rollback_validate'
    $rollbackRelease = Get-InstalledWindowsReleaseId -Root $PreviousInstall
    $activeRelease = Get-InstalledWindowsReleaseId -Root $InstallRoot
    Test-WindowsReleaseTree -Root $PreviousInstall -ExpectedReleaseId $rollbackRelease | Out-Null
    Test-WindowsReleaseTree -Root $InstallRoot -ExpectedReleaseId $activeRelease | Out-Null
    $runtimeProvision = Convert-ToWslPath (Join-Path $PSScriptRoot 'provision-wsl.sh')
    Invoke-LoggedWsl -Arguments @('-d', $Distro, '-u', 'root', '--', 'bash', $runtimeProvision,
        '--validate-retained', '--release-id', $rollbackRelease) `
        -FailureCode 'ROLLBACK_RUNTIME_INVALID' -Stage 'rollback_validate' | Out-Null
    Test-SwitchTradeKernelRollback -StateRoot $StateRoot -ExpectedReleaseId $rollbackRelease | Out-Null
    $runtimeRolledBack = $false
    $kernelRolledBack = $false
    $windowsRolledBack = $false
    try {
        $SetupStage = 'rollback_commit'
        Invoke-BoundedNativeProcess -FilePath 'wsl.exe' -Arguments @('--terminate', $Distro) `
            -TimeoutSeconds 30 | Out-Null
        Invoke-LoggedWsl -Arguments @('-d', $Distro, '-u', 'root', '--', 'bash', $runtimeProvision,
            '--rollback', '--release-id', $rollbackRelease) `
            -FailureCode 'ROLLBACK_RUNTIME_COMMIT_FAILED' -Stage $SetupStage | Out-Null
        $runtimeRolledBack = $true
        $kernelRolledBack = Switch-SwitchTradeKernelRollback -StateRoot $StateRoot `
            -ExpectedReleaseId $rollbackRelease -UserProfileRoot $UserProfileRoot
        Switch-SwitchTradeWindowsRollback -Active $InstallRoot -Previous $PreviousInstall `
            -ExpectedReleaseId $rollbackRelease | Out-Null
        $windowsRolledBack = $true
    } catch {
        $failure = $_
        try {
            if ($windowsRolledBack) {
                Switch-SwitchTradeWindowsRollback -Active $InstallRoot -Previous $PreviousInstall `
                    -ExpectedReleaseId $activeRelease | Out-Null
            }
            if ($kernelRolledBack) {
                Switch-SwitchTradeKernelRollback -StateRoot $StateRoot -ExpectedReleaseId $activeRelease `
                    -UserProfileRoot $UserProfileRoot | Out-Null
            }
            if ($runtimeRolledBack) {
                Invoke-BoundedNativeProcess -FilePath 'wsl.exe' -Arguments @('--terminate', $Distro) `
                    -TimeoutSeconds 30 | Out-Null
                Invoke-LoggedWsl -Arguments @('-d', $Distro, '-u', 'root', '--', 'bash', $runtimeProvision,
                    '--compensate', '--release-id', $activeRelease) `
                    -FailureCode 'ROLLBACK_RUNTIME_RECOVERY_FAILED' -Stage 'rollback_compensate' | Out-Null
            }
        } catch {
            throw "ROLLBACK_PARTIAL_FAILURE: $($failure.Exception.Message); recovery: $($_.Exception.Message)"
        }
        throw $failure
    }
    Write-Host 'SwitchTrade application, WSL runtime, and retained kernel rollback completed.'
    exit
}

$audit = Test-Setup
if (-not $audit.WindowsSupported) {
    throw 'SwitchTrade requires Windows 10 22H2 x64 (build 19045) or Windows 11 x64.'
}
if ($audit.FreeSpaceGB -lt 8) { throw 'SwitchTrade requires at least 8 GB of free space for safe install and rollback.' }
if (-not $audit.VirtualizationReady) { throw 'Hardware virtualization/Hyper-V is not available to WSL 2.' }
if (-not $audit.PayloadPresent) { throw "application payload is missing: $Payload" }
if (-not (Test-Path -LiteralPath $ReleaseConfig -PathType Leaf)) {
    throw 'signed installation configuration is missing'
}
if ($audit.PendingReboot) {
    throw 'WINDOWS_RESTART_PENDING: restart Windows before installing or repairing SwitchTrade'
}
if (Test-Path -LiteralPath $DesktopExe -PathType Leaf) {
    if (-not (Test-Path -LiteralPath $DesktopHash -PathType Leaf)) {
        throw "desktop checksum is missing: $DesktopHash"
    }
    $expectedDesktopHash = ((Get-Content -LiteralPath $DesktopHash -TotalCount 1) -split '\s+')[0]
    $actualDesktopHash = Get-FileSha256 $DesktopExe
    if ($expectedDesktopHash -notmatch '^[0-9a-fA-F]{64}$' -or
        $expectedDesktopHash.ToLowerInvariant() -ne $actualDesktopHash) {
        throw 'SwitchTrade desktop checksum verification failed.'
    }
}
if (-not $audit.WslInstalled) {
    if (-not $AcceptPrerequisiteChanges) {
        throw 'WSL 2 is required and may require a reboot. Rerun after accepting prerequisite changes.'
    }
    if (-not (Test-Path -LiteralPath (Join-Path $PackageRoot 'SwitchTradeSetup.exe') -PathType Leaf)) {
        throw 'SETUP_RESUME_UNAVAILABLE: use the complete native setup package before enabling WSL'
    }
    $dismWsl = Invoke-BoundedNativeProcess -FilePath 'dism.exe' -Arguments @('/online', '/enable-feature',
        '/featurename:Microsoft-Windows-Subsystem-Linux', '/all', '/norestart') -TimeoutSeconds 600
    if ($dismWsl.ExitCode -notin @(0, 3010)) { throw 'WSL_FEATURE_ENABLE_FAILED' }
    $dismVm = Invoke-BoundedNativeProcess -FilePath 'dism.exe' -Arguments @('/online', '/enable-feature',
        '/featurename:VirtualMachinePlatform', '/all', '/norestart') -TimeoutSeconds 600
    if ($dismVm.ExitCode -notin @(0, 3010)) { throw 'VIRTUAL_MACHINE_PLATFORM_ENABLE_FAILED' }
    Save-SetupResume -ResumeAction $Action
    Write-Host 'WSL prerequisites were enabled. Restart Windows; SwitchTrade Setup will resume after sign-in.'
    exit 3010
}
if (-not $audit.WslModern) {
    if (-not $AcceptPrerequisiteChanges) {
        throw 'The current Microsoft Store version of WSL 2 is required. Rerun after accepting prerequisite changes.'
    }
    $wslUpdate = Invoke-BoundedNativeProcess -FilePath 'wsl.exe' `
        -Arguments @('--update', '--web-download') -TimeoutSeconds 600
    if ($wslUpdate.ExitCode -ne 0) {
        $wslUpdate = Invoke-BoundedNativeProcess -FilePath 'wsl.exe' -Arguments @('--update') -TimeoutSeconds 600
    }
    if ($wslUpdate.ExitCode -ne 0) {
        throw 'WSL_UPDATE_FAILED: install the current Microsoft Store WSL package, restart Windows, and run Setup again.'
    }
}
Assert-SwitchTradeHostCapabilities -SkipUsbipd
$usbipdNeedsInstall = -not $audit.UsbipdInstalled
if (-not $usbipdNeedsInstall) {
    try { Assert-SwitchTradeHostCapabilities }
    catch {
        if (-not $AcceptPrerequisiteChanges) { throw }
        $usbipdNeedsInstall = $true
    }
}
if ($usbipdNeedsInstall) {
    if (-not $AcceptPrerequisiteChanges) {
        throw 'usbipd-win is required. Rerun after accepting prerequisite changes.'
    }
    if (-not (Test-Path -LiteralPath (Join-Path $PackageRoot 'SwitchTradeSetup.exe') -PathType Leaf)) {
        throw 'SETUP_RESUME_UNAVAILABLE: use the complete native setup package before installing usbipd-win'
    }
    if (-not (Test-Path -LiteralPath $UsbipdMsi) -or -not (Test-Path -LiteralPath $UsbipdManifest)) {
        throw 'the pinned usbipd-win installer is missing from this package'
    }
    $usbipdMetadata = Get-Content -Raw -LiteralPath $UsbipdManifest | ConvertFrom-Json
    if ((Get-FileSha256 $UsbipdMsi) -ne
        ([string]$usbipdMetadata.sha256).ToLowerInvariant()) {
        throw 'usbipd-win installer checksum verification failed'
    }
    $msi = Invoke-BoundedNativeProcess -FilePath 'msiexec.exe' `
        -Arguments @('/i', $UsbipdMsi, '/qn', '/norestart') -TimeoutSeconds 600
    if ($msi.ExitCode -notin @(0, 3010)) { throw "USBIPD_INSTALL_FAILED: exit $($msi.ExitCode) $($msi.Error)" }
    if ($msi.ExitCode -eq 3010) {
        Save-SetupResume -ResumeAction $Action
        Write-Host 'usbipd-win requires a restart. SwitchTrade Setup will resume after sign-in.'
        exit 3010
    }
}
Assert-SwitchTradeHostCapabilities
if (-not $recoveredCommitted) {
$installParent = Split-Path -Parent $InstallRoot
New-Item -ItemType Directory -Force -Path $installParent | Out-Null
$stage = Join-Path $installParent ("SwitchTrade.stage." + [guid]::NewGuid().ToString('N'))
$priorReleaseId = ''
if (Test-Path -LiteralPath $InstallRoot -PathType Container) {
    $priorReleaseId = Get-InstalledWindowsReleaseId -Root $InstallRoot
    if (-not $priorReleaseId) {
        throw 'INSTALLED_RELEASE_ID_MISSING: existing application files are not a committed SwitchTrade release'
    }
    Test-WindowsReleaseTree -Root $InstallRoot -ExpectedReleaseId $priorReleaseId | Out-Null
}
$distroExistedBefore = $namedDistroExists
$distroOwnedBefore = $namedDistroExists -and (Test-SwitchTradeDistroOwned -Name $Distro)
$wslPriorReleaseId = ''
if ($distroExistedBefore) {
    if (-not $distroOwnedBefore) { throw 'DISTRO_NAME_COLLISION' }
    $wslPriorState = Get-SwitchTradeWslRuntimeState -Name $Distro -Location active
    if (-not $wslPriorState.Valid -or -not $wslPriorState.ReleaseId) {
        throw 'INSTALLED_WSL_RELEASE_ID_MISSING: existing runtime is not a committed SwitchTrade release'
    }
    $wslPriorReleaseId = [string]$wslPriorState.ReleaseId
}
$kernelStatePath = Join-Path $StateRoot 'kernel-state.json'
$kernelPriorState = $null
if (Test-Path -LiteralPath $kernelStatePath -PathType Leaf) {
    try { $kernelPriorState = Get-Content -Raw -LiteralPath $kernelStatePath | ConvertFrom-Json }
    catch { throw 'KERNEL_STATE_INVALID: existing kernel ownership state is unreadable' }
}
$kernelPriorReleaseId = if ($kernelPriorState) { [string]$kernelPriorState.package_release_id } else { '' }
$kernelPriorPath = if ($kernelPriorState) { [string]$kernelPriorState.kernel_path } else { '' }
$kernelPriorModulesPath = if ($kernelPriorState) { [string]$kernelPriorState.modules_path } else { '' }
$softwarePriorAxes = @(@($priorReleaseId, $wslPriorReleaseId) | Where-Object { $_ })
if ($softwarePriorAxes.Count -ne 0 -and
        ($softwarePriorAxes.Count -ne 2 -or $priorReleaseId -ne $wslPriorReleaseId)) {
    throw 'INSTALLED_RELEASE_MISMATCH: Windows and WSL must identify the same committed release before Repair or Update'
}
if ($kernelPriorReleaseId -and $priorReleaseId -and $kernelPriorReleaseId -ne $priorReleaseId) {
    throw 'INSTALLED_KERNEL_RELEASE_MISMATCH: managed kernel state does not match the installed release'
}
$kernelChangeExpected = (Test-Path -LiteralPath $Kernel -PathType Leaf) -and
    (Test-Path -LiteralPath $KernelManifest -PathType Leaf)
$distroImported = $false
$kernelApplied = $false
$kernelHadManagedPrior = $false
$kernelApplyAttempted = $false
$wslStaged = $false
$wslStageAttempted = $false
$wslCommitted = $false
$wslCommitAttempted = $false
$windowsCommitted = $false
$provision = ''
$transaction = New-SwitchTradeTransaction -Path $TransactionPath -Action $Action -ReleaseId $ReleaseId `
    -PriorReleaseId $priorReleaseId -WindowsStage $stage -PackageRoot $PackageRoot `
    -InstallRoot $InstallRoot -PreviousInstall $PreviousInstall -DistroName $Distro `
    -DistroRoot $DistroRoot -DistroExistedBefore $distroExistedBefore `
    -DistroOwnedBefore $distroOwnedBefore -WslPriorReleaseId $wslPriorReleaseId `
    -KernelPriorReleaseId $kernelPriorReleaseId -KernelStatePath $kernelStatePath `
    -KernelPriorPath $kernelPriorPath -KernelPriorModulesPath $kernelPriorModulesPath `
    -KernelChangeExpected $kernelChangeExpected
try {
    $SetupStage = 'windows_stage'
    New-Item -ItemType Directory -Path $stage | Out-Null
    Copy-Item -LiteralPath (Join-Path $PackageRoot 'installer') -Destination $stage -Recurse
    Copy-Item -LiteralPath $Payload -Destination $stage -Recurse
    Copy-Item -LiteralPath (Join-Path $PackageRoot 'manifest.json') -Destination $stage
    if (Test-Path -LiteralPath (Join-Path $PackageRoot 'manifest.json.p7s') -PathType Leaf) {
        Copy-Item -LiteralPath (Join-Path $PackageRoot 'manifest.json.p7s') -Destination $stage
    }
    Copy-Item -LiteralPath $ReleaseConfig -Destination (Join-Path $stage 'config.json')
    if (Test-Path -LiteralPath $DesktopExe -PathType Leaf) {
        Copy-Item -LiteralPath $DesktopExe -Destination (Join-Path $stage 'SwitchTrade.exe')
    }
    Write-WindowsReleaseMarker -Root $stage -ReleaseId $ReleaseId
    Test-WindowsReleaseTree -Root $stage -ExpectedReleaseId $ReleaseId | Out-Null
    Set-SwitchTradeTransactionPhase -Path $TransactionPath -Phase 'windows_staged' | Out-Null

    $SetupStage = 'distro_identity'
    if (-not $namedDistroExists) {
        if (-not $audit.RootfsPresent) { throw "ROOTFS_MISSING: $Rootfs" }
        if (-not (Test-Path -LiteralPath $RootfsHash -PathType Leaf)) { throw "ROOTFS_HASH_MISSING: $RootfsHash" }
        $expectedHash = ((Get-Content -LiteralPath $RootfsHash -TotalCount 1) -split '\s+')[0]
        if ($expectedHash -notmatch '^[0-9a-fA-F]{64}$' -or
            $expectedHash.ToLowerInvariant() -ne (Get-FileSha256 $Rootfs)) {
            throw 'ROOTFS_HASH_MISMATCH: SwitchTrade rootfs checksum verification failed'
        }
        New-Item -ItemType Directory -Force -Path $DistroRoot | Out-Null
        $import = Invoke-BoundedNativeProcess -FilePath 'wsl.exe' `
            -Arguments @('--import', $Distro, $DistroRoot, $Rootfs, '--version', '2') -TimeoutSeconds 600
        if ($import.ExitCode -ne 0) { throw "DISTRO_IMPORT_FAILED: $($import.Error)" }
        $distroImported = $true
        Set-SwitchTradeTransactionPhase -Path $TransactionPath -Phase 'distro_imported' `
            -Fields @{ distro_imported = $true } | Out-Null
        Assert-SwitchTradeDistroOwned -Name $Distro
    }

    $source = Convert-ToWslPath $Payload
    $provision = Convert-ToWslPath (Join-Path $PackageRoot 'installer\provision-wsl.sh')
    $wslStageAttempted = $true
    Invoke-LoggedWsl -Arguments @('-d', $Distro, '-u', 'root', '--', 'bash', $provision,
        '--stage', '--source', $source, '--release-id', $ReleaseId) `
        -FailureCode 'WSL_STAGE_FAILED' -Stage 'wsl_stage' | Out-Null
    $wslStaged = $true
    Set-SwitchTradeTransactionPhase -Path $TransactionPath -Phase 'wsl_staged' `
        -Fields @{ wsl_staged = $true } | Out-Null
    Invoke-LoggedWsl -Arguments @('-d', $Distro, '-u', 'root', '--', 'bash', $provision,
        '--validate', '--release-id', $ReleaseId) `
        -FailureCode 'WSL_VALIDATE_FAILED' -Stage 'wsl_validate' | Out-Null
    Test-StagedControlReadiness -ExpectedReleaseId $ReleaseId | Out-Null
    Set-SwitchTradeTransactionPhase -Path $TransactionPath -Phase 'software_validated' | Out-Null

    if ((Test-Path -LiteralPath $Kernel -PathType Leaf) -and
        (Test-Path -LiteralPath $KernelManifest -PathType Leaf)) {
        $SetupStage = 'kernel_apply'
        if ($priorReleaseId) {
            $kernelHadManagedPrior = Initialize-SwitchTradeKernelReleaseIdentity -StateRoot $StateRoot `
                -CurrentReleaseId $priorReleaseId
        }
        $kernelArguments = @{
            Kernel = $Kernel; Manifest = $KernelManifest; StateRoot = $StateRoot
            KernelStorageRoot = $KernelStorageRoot; ReleaseId = $ReleaseId
            UserProfileRoot = $UserProfileRoot
            AcceptGlobalKernelChange = $AcceptGlobalKernelChange
        }
        if ($KernelModules -and (Test-Path -LiteralPath $KernelModules -PathType Leaf)) {
            $kernelArguments.KernelModules = $KernelModules
        }
        $kernelApplyAttempted = $true
        $kernelState = Install-SwitchTradeKernel @kernelArguments
        $kernelApplied = $true
        Set-SwitchTradeTransactionPhase -Path $TransactionPath -Phase 'kernel_applied' `
            -Fields @{ kernel_applied = $true } | Out-Null
        $kernelProbe = Invoke-BoundedNativeProcess -FilePath 'wsl.exe' `
            -Arguments @('-d', $Distro, '--', 'uname', '-r') -TimeoutSeconds 30
        $kernelOutput = ($kernelProbe.Output + $kernelProbe.Error).Trim()
        if ($kernelProbe.ExitCode -ne 0 -or $kernelOutput -ne [string]$kernelState.kernel_release) {
            if ($kernelOutput -match '(?i)policy|blocked|access.+denied|administrator') {
                throw "CUSTOM_KERNEL_BLOCKED_BY_POLICY: this managed PC is unsupported by the private beta. $kernelOutput"
            }
            throw "CUSTOM_KERNEL_START_FAILED: expected $($kernelState.kernel_release), got $kernelOutput"
        }
        if ($KernelModules -and $kernelState.modules_format -eq 'archive') {
            $modulesWsl = Convert-ToWslPath $KernelModules
            $extractCommand = 'set -eu; command -v depmod >/dev/null 2>&1 && command -v modinfo >/dev/null 2>&1 || { echo "RUNTIME_OS_DEPENDENCY_MISSING: kmod" >&2; exit 1; }; mkdir -p /lib/modules; tar -xzf "{0}" -C /lib/modules; depmod -a "{1}"' -f `
                $modulesWsl, [string]$kernelState.kernel_release
            Invoke-LoggedWsl -Arguments @('-d', $Distro, '-u', 'root', '--', 'sh', '-lc', $extractCommand) `
                -FailureCode 'KERNEL_MODULE_INSTALL_FAILED' -Stage 'kernel_modules' | Out-Null
        }
        if ($KernelModules) {
            $kernelMetadata = Get-Content -Raw -LiteralPath $KernelManifest | ConvertFrom-Json
            $firmwareDigest = if ($kernelMetadata.PSObject.Properties.Name -contains 'firmware_sha256') {
                [string]$kernelMetadata.firmware_sha256
            } else { '' }
            $builtInFirmwareVerified = $firmwareDigest -match '^[0-9a-fA-F]{64}$'
            $moduleVerify = if ($builtInFirmwareVerified) {
                'set -eu; test "$(uname -r)" = "{0}"; test "$(modinfo -F vermagic rtl8xxxu | awk ''{{print $1}}'')" = "{0}"' -f [string]$kernelState.kernel_release
            } else {
                'set -eu; test "$(uname -r)" = "{0}"; test "$(modinfo -F vermagic rtl8xxxu | awk ''{{print $1}}'')" = "{0}"; modinfo -F firmware rtl8xxxu | while IFS= read -r fw; do test -z "$fw" || test -f "/lib/firmware/$fw"; done' -f [string]$kernelState.kernel_release
            }
            Invoke-LoggedWsl -Arguments @('-d', $Distro, '-u', 'root', '--', 'sh', '-lc', $moduleVerify) `
                -FailureCode 'KERNEL_ABI_OR_FIRMWARE_MISMATCH' -Stage 'kernel_verify' | Out-Null
        }
    }

    $SetupStage = 'commit'
    $wslCommitAttempted = $true
    Invoke-LoggedWsl -Arguments @('-d', $Distro, '-u', 'root', '--', 'bash', $provision,
        '--commit', '--release-id', $ReleaseId) -FailureCode 'WSL_COMMIT_FAILED' -Stage $SetupStage | Out-Null
    $wslCommitted = $true
    Set-SwitchTradeTransactionPhase -Path $TransactionPath -Phase 'wsl_committed' `
        -Fields @{ wsl_committed = $true } | Out-Null
    $committedPrior = Commit-SwitchTradeWindowsRelease -Candidate $stage -Active $InstallRoot `
        -Previous $PreviousInstall -ExpectedReleaseId $ReleaseId
    $windowsCommitted = $true
    if ($committedPrior -ne $priorReleaseId) { throw 'WINDOWS_PRIOR_RELEASE_CHANGED: setup state changed during commit' }
    Set-SwitchTradeTransactionPhase -Path $TransactionPath -Phase 'completed' `
        -Fields @{ windows_committed = $true } | Out-Null
} catch {
    $transactionFailure = $_
    $SetupStage = 'compensate'
    try {
        if ($wslStageAttempted -and -not $wslStaged) {
            $candidateProbe = Invoke-BoundedNativeProcess -FilePath 'wsl.exe' -Arguments @('-d', $Distro,
                '-u', 'root', '--', 'bash', $provision, '--validate-candidate', '--release-id', $ReleaseId) `
                -TimeoutSeconds 30
            $wslStaged = $candidateProbe.ExitCode -eq 0
        }
        if ($wslCommitAttempted -and -not $wslCommitted) {
            $activeProbe = Invoke-BoundedNativeProcess -FilePath 'wsl.exe' -Arguments @('-d', $Distro,
                '-u', 'root', '--', 'bash', $provision, '--validate-active', '--release-id', $ReleaseId) `
                -TimeoutSeconds 30
            $wslCommitted = $activeProbe.ExitCode -eq 0
        }
        if ($windowsCommitted) {
            if ($priorReleaseId) {
                Switch-SwitchTradeWindowsRollback -Active $InstallRoot -Previous $PreviousInstall `
                    -ExpectedReleaseId $priorReleaseId | Out-Null
            } else {
                Test-WindowsReleaseTree -Root $InstallRoot -ExpectedReleaseId $ReleaseId | Out-Null
                Remove-Item -LiteralPath $InstallRoot -Recurse -Force
            }
        }
        if ($wslCommitted -and $priorReleaseId) {
            Invoke-LoggedWsl -Arguments @('-d', $Distro, '-u', 'root', '--', 'bash', $provision,
                '--compensate', '--release-id', $priorReleaseId) `
                -FailureCode 'WSL_COMPENSATION_FAILED' -Stage $SetupStage | Out-Null
        } elseif ($wslStaged -and -not $wslCommitted) {
            Invoke-LoggedWsl -Arguments @('-d', $Distro, '-u', 'root', '--', 'bash', $provision,
                '--abort', '--release-id', $ReleaseId) `
                -FailureCode 'WSL_ABORT_FAILED' -Stage $SetupStage | Out-Null
        }
        if ($kernelApplyAttempted) {
            $kernelStatePath = Join-Path $StateRoot 'kernel-state.json'
            $currentKernelRelease = if (Test-Path -LiteralPath $kernelStatePath -PathType Leaf) {
                [string]((Get-Content -Raw -LiteralPath $kernelStatePath | ConvertFrom-Json).package_release_id)
            } else { '' }
            if ($currentKernelRelease -eq $ReleaseId -and $ReleaseId -ne $priorReleaseId) {
                if ($priorReleaseId -and $kernelHadManagedPrior) {
                    Switch-SwitchTradeKernelRollback -StateRoot $StateRoot `
                        -ExpectedReleaseId $priorReleaseId -UserProfileRoot $UserProfileRoot | Out-Null
                } else {
                    Restore-SwitchTradeKernel -StateRoot $StateRoot -UserProfileRoot $UserProfileRoot | Out-Null
                }
            } elseif ($currentKernelRelease -and $currentKernelRelease -ne $priorReleaseId) {
                throw "KERNEL_COMPENSATION_RELEASE_MISMATCH: expected $priorReleaseId, found $currentKernelRelease"
            }
        }
        if ($distroImported) {
            Assert-SwitchTradeDistroOwned -Name $Distro
            $unregister = Invoke-BoundedNativeProcess -FilePath 'wsl.exe' `
                -Arguments @('--unregister', $Distro) -TimeoutSeconds 120
            if ($unregister.ExitCode -ne 0) { throw 'DISTRO_IMPORT_COMPENSATION_FAILED' }
        }
        if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
        Set-SwitchTradeTransactionPhase -Path $TransactionPath -Phase 'compensated' | Out-Null
    } catch {
        throw "SETUP_COMPENSATION_FAILED: $($transactionFailure.Exception.Message); compensation: $($_.Exception.Message)"
    }
    throw $transactionFailure
}
}

if ($audit.VmwareUsbArbitrator -eq 'Running') {
    $SetupStage = 'hardware_ownership'
    if (-not $AcceptVmwareRelease) {
        throw 'VMWARE_USB_OWNERSHIP_REQUIRED: run Setup Repair after accepting the temporary VMware USB release'
    }
    Stop-Service VMUSBArbService -Force
}
if ($DeferHardwareSetup) {
    Write-Host 'Wi-Fi adapter setup was deferred. Software release committed coherently; use Setup Repair for hardware readiness.'
} else {
    $SetupStage = 'hardware_readiness'
    $BusId = Resolve-StableUsbBusId
    $radioPreflight = Join-Path $Payload 'scripts\windows\wsl-radio-preflight.ps1'
    $profileFile = Join-Path $Payload 'config\wsl-radio-hardware.tsv'
    $preflightArguments = @{
        Distro = $Distro; ProfileFile = $profileFile; Prepare = $true; AutoAttach = $true
        InstanceId = $UsbInstanceId; WatcherStateRoot = $StateRoot
        WatcherScript = (Join-Path $InstallRoot 'installer\UsbAutoAttachWatcher.ps1')
        LifecycleScript = (Join-Path $InstallRoot 'installer\SetupLifecycle.ps1')
    }
    if ($BusId) { $preflightArguments.BusId = $BusId }
    if ($UsbId) { $preflightArguments.UsbId = @($UsbId) }
    & $radioPreflight @preflightArguments
    if ($LASTEXITCODE -ne 0) { throw 'USB_OWNERSHIP_PREFLIGHT_FAILED: reconnect the selected adapter and run Setup Repair' }
    Register-SwitchTradeUsbWatcherStartup -RegistryPath $StartupRegistryPath `
        -ScriptPath $preflightArguments.WatcherScript -Distro $Distro -InstanceId $UsbInstanceId `
        -StateFile (Join-Path $StateRoot 'usb-watcher.json')
    $wslHealthArguments = @(
        '-d', $Distro, '-u', 'root', '--cd', '/opt/switchtrade', '--',
        './scripts/wsl-radio-prepare.sh', '--role', 'guest',
        '--health-channels', '1,6,11', '--target-channel', '6'
    )
    if ($UsbId) { $wslHealthArguments += @('--usb-id', $UsbId.ToLowerInvariant()) }
    $wslHealthArguments += @('--', 'true')
    Invoke-LoggedWsl -Arguments $wslHealthArguments -FailureCode 'RADIO_RX_HEALTH_FAILED' `
        -Stage $SetupStage | Out-Null
    if ($UsbInstanceId -and $UsbId -and $BusId) {
        $windowsSelection = Write-SwitchTradeHardwareSelection -StateRoot $StateRoot -UsbId $UsbId `
            -InstanceId $UsbInstanceId -BusId $BusId
        $selectionSource = Convert-ToWslPath $windowsSelection
        $selectionRoot = '/root/.local/state/switchtrade/runtime'
        $selectionTarget = "$selectionRoot/hardware-selection.json"
        $selectionTemporary = "$selectionRoot/.hardware-selection.$ReleaseId.tmp"
        Invoke-LoggedWsl -Arguments @('-d', $Distro, '-u', 'root', '--',
            'install', '-d', '-m', '0700', $selectionRoot) `
            -FailureCode 'HARDWARE_SELECTION_IMPORT_FAILED' -Stage 'hardware_selection_import' | Out-Null
        try {
            Invoke-LoggedWsl -Arguments @('-d', $Distro, '-u', 'root', '--',
                'install', '-m', '0600', $selectionSource, $selectionTemporary) `
                -FailureCode 'HARDWARE_SELECTION_IMPORT_FAILED' -Stage 'hardware_selection_import' | Out-Null
            Invoke-LoggedWsl -Arguments @('-d', $Distro, '-u', 'root', '--',
                'mv', '-f', $selectionTemporary, $selectionTarget) `
                -FailureCode 'HARDWARE_SELECTION_IMPORT_FAILED' -Stage 'hardware_selection_import' | Out-Null
        } finally {
            Invoke-LoggedWsl -Arguments @('-d', $Distro, '-u', 'root', '--',
                'rm', '-f', $selectionTemporary) `
                -FailureCode 'HARDWARE_SELECTION_CLEANUP_FAILED' -Stage 'hardware_selection_import' | Out-Null
        }
    }
}

if (-not $NoShortcut) {
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut((Join-Path $DesktopRoot 'SwitchTrade.lnk'))
    $installedDesktop = Join-Path $InstallRoot 'SwitchTrade.exe'
    $shortcut.TargetPath = if (Test-Path -LiteralPath $installedDesktop) { $installedDesktop } else { 'powershell.exe' }
    $shortcut.Arguments = if (Test-Path -LiteralPath $installedDesktop) { '' } else {
        "-NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $InstallRoot 'installer\Launch-SwitchTrade.ps1')`""
    }
    $shortcut.WorkingDirectory = $InstallRoot
    $shortcut.Save()
}

Write-Host "SwitchTrade $Action completed. Only the named distro and the explicitly accepted kernel selection were changed."
Clear-SetupResume
