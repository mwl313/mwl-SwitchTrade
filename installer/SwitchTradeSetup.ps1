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
$SetupStage = 'initialize'
$SetupLog = ''
trap {
    $message = [string]$_.Exception.Message
    $candidateCode = ($message -split ':', 2)[0]
    $code = if ($candidateCode -match '^[A-Z][A-Z0-9_.-]+$') { $candidateCode } else { 'SETUP_FAILED' }
    $logPath = if ($SetupLog) { $SetupLog } else { '' }
    $correlation = ''
    try { $correlation = [string](Get-Variable -Name SwitchTradeCorrelationId -Scope Script -ErrorAction Stop).Value } catch { }
    if ($SetupLog) {
        try { Write-SwitchTradeSetupLog -Path $SetupLog -Stage $SetupStage -Message ($_ | Out-String) -Level error } catch { }
    }
    [Console]::Error.WriteLine("SWITCHTRADE_SETUP_ERROR: $message")
    $manualRecovery = $code -match '^SETUP_TRANSACTION_(LEGACY_AMBIGUOUS|.*_AMBIGUOUS|.*_MISMATCH|.*_INVALID|DISTRO_OWNERSHIP_CHANGED)' -or
        $code -match '^INSTALLED_(DISTRO_IDENTITY_MISSING|INTEGRITY_ANCHOR_MISSING)'
    $manualRecovery = $manualRecovery -or $code -match '^(INSTALL_INTEGRITY_|INSTALLED_WSL_INTEGRITY_)'
    $knownTransactionPath = Get-Variable TransactionPath -ValueOnly -ErrorAction SilentlyContinue
    $transactionExists = $knownTransactionPath -and
        (Test-Path -LiteralPath $knownTransactionPath -PathType Leaf)
    $primaryAction = if ($code -eq 'SETUP_TRANSACTION_PACKAGE_MISMATCH') {
        'Run Repair from the package that started the transaction'
    } elseif ($manualRecovery) { 'Contact SwitchTrade support'
    } elseif ($Action -eq 'Install' -and -not $transactionExists) {
        'Run Setup Install again'
    } else { 'Run Setup Repair' }
    $recoverable = $code -eq 'SETUP_TRANSACTION_PACKAGE_MISMATCH' -or -not $manualRecovery
    $displayMessage = if ($message.StartsWith("${code}: ", [StringComparison]::Ordinal)) {
        $message.Substring($code.Length + 2)
    } else { $message }
    $failure = [ordered]@{
        code = $code; message = Redact-SwitchTradeSetupText $displayMessage; stage = $SetupStage
        recoverable = $recoverable; primary_action = $primaryAction; action = $Action
        correlation_id = $(if ($correlation) { $correlation } else { [guid]::NewGuid().ToString('N') })
        technical_detail_log_path = $logPath
    }
    [Console]::Error.WriteLine("SWITCHTRADE_SETUP_FAILURE: $($failure | ConvertTo-Json -Compress)")
    exit 1
}

# Engine and supporting libraries.
. (Join-Path $PSScriptRoot 'engine\PlatformOps.ps1')
. (Join-Path $PSScriptRoot 'engine\StateInspector.ps1')
. (Join-Path $PSScriptRoot 'engine\Planner.ps1')
. (Join-Path $PSScriptRoot 'engine\Executor.ps1')
. (Join-Path $PSScriptRoot 'KernelLifecycle.ps1')
. (Join-Path $PSScriptRoot 'PackageIntegrity.ps1')
. (Join-Path $PSScriptRoot 'HostCompatibility.ps1')

function Set-SwitchTradeSetupStage([string]$Stage) {
    Set-SwitchTradeEngineStage $Stage
}

function Write-SwitchTradeSetupLog {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Stage,
        [Parameter(Mandatory)][string]$Message,
        [ValidateSet('info', 'error')][string]$Level = 'info'
    )
    $entry = [ordered]@{
        timestamp_utc = [DateTime]::UtcNow.ToString('o')
        level = $Level
        stage = $Stage
        message = Redact-SwitchTradeSetupText $Message
    }
    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    Add-Content -LiteralPath $Path -Value ($entry | ConvertTo-Json -Compress) -Encoding UTF8
}

function Redact-SwitchTradeSetupText {
    param([AllowEmptyString()][string]$Text)
    if ($null -eq $Text) { return '' }
    $redacted = [regex]::Replace($Text,
        '(?i)(authorization["'']?\s*[:=]\s*["'']?bearer\s+)[^\s,;"'']+', '$1<redacted>')
    $redacted = [regex]::Replace($redacted, '(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+', '$1<redacted>')
    $redacted = [regex]::Replace($redacted,
        '(?i)(member[_-]?token|reconnect[_-]?token|password|secret|prod[_-]?key)["'']?(\s*[:=]\s*["'']?)[^\s,;"'']+',
        '$1$2<redacted>')
    return $redacted.Replace([string][char]0, '')
}

function Enter-SwitchTradeSetupMutex {
    $created = $false
    $mutex = New-Object System.Threading.Mutex($true, 'Global\SwitchTrade.Setup', [ref]$created)
    if ($created) { return $mutex }
    try {
        if (-not $mutex.WaitOne(0)) {
            $mutex.Dispose()
            throw 'SETUP_ALREADY_RUNNING: another SwitchTrade setup action is active'
        }
    } catch [Threading.AbandonedMutexException] { }
    return $mutex
}

# ---------------------------------------------------------------------------
# Resolve invoking-user context, then resume restore (unchanged contract).
# ---------------------------------------------------------------------------
$UserProfileRoot = if ($UserProfileRoot) { [IO.Path]::GetFullPath($UserProfileRoot) } else { $env:USERPROFILE }
$LocalAppDataRoot = if ($LocalAppDataRoot) { [IO.Path]::GetFullPath($LocalAppDataRoot) } else { $env:LOCALAPPDATA }
$DesktopRoot = if ($DesktopRoot) { [IO.Path]::GetFullPath($DesktopRoot) } else { Join-Path $UserProfileRoot 'Desktop' }
if (-not $InvokingUserSid) { $InvokingUserSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value }
$StateRoot = Join-Path $LocalAppDataRoot 'SwitchTrade'
$ResumeStatePath = Join-Path $StateRoot 'setup-resume.json'
$TransactionPath = Join-Path $StateRoot 'setup-transaction.json'
$SetupLog = Join-Path $StateRoot 'logs\setup.jsonl'
$script:SwitchTradeSetupLog = $SetupLog
$ResumeRunOnce = 'SwitchTradeSetupResume'
$ResumeRegistryPath = "Registry::HKEY_USERS\$InvokingUserSid\Software\Microsoft\Windows\CurrentVersion\RunOnce"
$WasResume = $Action -eq 'Resume'
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
}

# ---------------------------------------------------------------------------
# Engine context and dispatch.
# ---------------------------------------------------------------------------
$Context = New-SwitchTradeSetupContext -Action $Action -Distro $Distro -UserProfileRoot $UserProfileRoot -LocalAppDataRoot $LocalAppDataRoot -DesktopRoot $DesktopRoot -InvokingUserSid $InvokingUserSid -InstallRoot $InstallRoot -DistroRoot $DistroRoot -BusId $BusId -UsbId $UsbId -UsbInstanceId $UsbInstanceId -AcceptGlobalKernelChange:$AcceptGlobalKernelChange -AcceptPrerequisiteChanges:$AcceptPrerequisiteChanges -AcceptVmwareRelease:$AcceptVmwareRelease -DeferHardwareSetup:$DeferHardwareSetup -AllowUnsignedPackage:$AllowUnsignedPackage -NoShortcut:$NoShortcut -PackageRoot (Split-Path -Parent $PSScriptRoot)
$script:SwitchTradeSetupLog = $Context.SetupLog
$SetupLog = $Context.SetupLog
$TransactionPath = $Context.TransactionPath

if ($Action -eq 'Audit') {
    $state = Get-SwitchTradeInstallState -Context $Context
    [pscustomobject]@{
        Windows64Bit = $state.Host.Windows64Bit
        WindowsSupported = $state.Host.WindowsSupported
        WindowsProductType = $state.Host.WindowsProductType
        WindowsBuild = $state.Host.WindowsBuild
        Architecture = $state.Host.Architecture
        PendingReboot = $state.Host.PendingReboot
        VirtualizationReady = $state.Host.VirtualizationReady
        WslInstalled = ($state.Host.WslRuntimeLaunchSafe -or $state.Host.WslFeaturesEnabled)
        WslFeaturesEnabled = $state.Host.WslFeaturesEnabled
        WslModern = $state.WslCapability.CapabilityReady
        WslVersion = if ($state.WslCapability.Version) { [string]$state.WslCapability.Version } else { 'Absent' }
        UsbipdInstalled = $state.UsbipdInstalled
        Distro = $Context.Distro
        DistroInstalled = $state.Identity.DistroExists
        DistroOwned = ($state.Identity.Classification -eq 'present_owned')
        DistroIdentity = $state.Identity.Classification
        TransactionPhase = $state.Transaction.Phase
        TransactionId = $state.Transaction.TransactionId
        TransactionRelease = $state.Transaction.ReleaseId
        InstalledRelease = $state.WindowsActive.ReleaseId
        PreviousRelease = $state.WindowsPrevious.ReleaseId
        WslActiveRelease = $state.WslActive.ReleaseId
        KernelRelease = $state.Kernel.ReleaseId
        KernelOwned = $state.Kernel.Exists
        InstallRoot = $Context.InstallRoot
        DistroRoot = $Context.DistroRoot
        FreeSpaceGB = $state.Host.FreeSpaceGB
        KernelPolicy = 'unchanged'
        ExistingWslConfig = (Test-Path -LiteralPath $Context.WslConfigPath -PathType Leaf)
        VmwareUsbArbitrator = $state.Host.VmwareUsbArbitrator
    } | Format-List
    exit
}

$Package = $null
if ($Action -eq 'Uninstall') {
    $Package = [pscustomobject]@{
        ReleaseId = ''
        ManifestSha256 = '0000000000000000000000000000000000000000000000000000000000000000'
    }
}
if ($Action -in @('Install', 'Repair', 'Update', 'Rollback')) {
    Set-SwitchTradeSetupStage 'package_integrity'
    Test-SwitchTradePackage -PackageRoot $Context.PackageRoot -AllowUnsignedPackage:$AllowUnsignedPackage | Out-Null
    $ReleaseId = Get-SwitchTradeReleaseId -ManifestPath (Join-Path $Context.PackageRoot 'manifest.json')
    $Package = New-SwitchTradePackageIdentity -ReleaseId $ReleaseId
        -ManifestSha256 (Get-FileSha256 (Join-Path $Context.PackageRoot 'manifest.json'))
}

Set-SwitchTradeSetupStage 'mutex'
$SetupMutex = Enter-SwitchTradeSetupMutex
Write-SwitchTradeSetupLog -Path $SetupLog -Stage $SetupStage -Message "setup action=$Action acquired the mutation mutex"

$state = Get-SwitchTradeInstallState -Context $Context
$plan = Resolve-SwitchTradePlan -Context $Context -State $state -Package $Package
if ($plan.Outcome -eq 'blocker') {
    $failure = New-SwitchTradeFailure -Code $plan.Code -Message $plan.Message -Stage $plan.Stage
        -Recoverable $plan.Recoverable -PrimaryAction $plan.PrimaryAction -LogPath $SetupLog
    $failure.action = $Action
    [Console]::Error.WriteLine("SWITCHTRADE_SETUP_FAILURE: $($failure | ConvertTo-Json -Compress)")
    Write-SwitchTradeSetupLog -Path $SetupLog -Stage $plan.Stage -Message "blocker $($plan.Code): $($plan.Message)" -Level error
    exit 1
}
try {
    Invoke-SwitchTradePlan -Context $Context -State $state -Package $Package -Plan $plan
} catch {
    if ([string]$_.Exception.Message -eq 'ENGINE_REBOOT_REQUIRED') {
        Write-Host 'WSL prerequisites or usbipd-win require a restart. SwitchTrade Setup will resume after sign-in.'
        exit 3010
    }
    throw
}

Write-Host "SwitchTrade $Action completed. Only the named distro and the explicitly accepted kernel selection were changed."
if ($Action -eq 'Uninstall') {
    Write-Host 'SwitchTrade was uninstalled. Its isolated WSL distribution was removed when present.'
}