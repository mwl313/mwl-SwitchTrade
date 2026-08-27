# SwitchTrade installer engine: state inspector (read-only normalized snapshot)
#
# Handoff 8.1: one read-only component collects a normalized snapshot and distinguishes
# absent / present / invalid / incompatible / foreign / inaccessible / timed_out / unknown.
# It must never "repair while inspecting". Every probe is routed through PlatformOps.
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot 'PlatformOps.ps1')

function Get-FileSha256 {
    param([Parameter(Mandatory)][string]$Path)
    $stream = [IO.File]::OpenRead((Resolve-Path -LiteralPath $Path).ProviderPath)
    try {
        $hash = [Security.Cryptography.SHA256]::Create()
        try { return ([BitConverter]::ToString($hash.ComputeHash($stream)) -replace '-', '').ToLowerInvariant() }
        finally { $hash.Dispose() }
    } finally { $stream.Dispose() }
}

# Build the immutable context every engine component consumes (no script-level variables).
function New-SwitchTradeSetupContext {
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
        [string]$BusId = '',
        [string]$UsbId = '',
        [string]$UsbInstanceId = '',
        [switch]$AcceptGlobalKernelChange,
        [switch]$AcceptPrerequisiteChanges,
        [switch]$AcceptVmwareRelease,
        [switch]$DeferHardwareSetup,
        [switch]$AllowUnsignedPackage,
        [switch]$NoShortcut,
        [Parameter(Mandatory)][string]$PackageRoot
    )
    $resolvedProfile = if ($UserProfileRoot) { [IO.Path]::GetFullPath($UserProfileRoot) } else { $env:USERPROFILE }
    $resolvedLocal = if ($LocalAppDataRoot) { [IO.Path]::GetFullPath($LocalAppDataRoot) } else { $env:LOCALAPPDATA }
    $resolvedDesktop = if ($DesktopRoot) { [IO.Path]::GetFullPath($DesktopRoot) } else { Join-Path $resolvedProfile 'Desktop' }
    $sid = if ($InvokingUserSid) { $InvokingUserSid } else { [Security.Principal.WindowsIdentity]::GetCurrent().User.Value }
    if ($sid -notmatch '^S-1-5-21-(?:\d+-){3}\d+$') { throw 'INVOKING_USER_CONTEXT_INVALID' }
    $resolvedInstall = if ($InstallRoot) { [IO.Path]::GetFullPath($InstallRoot) } else { Join-Path $resolvedLocal 'Programs\SwitchTrade' }
    $resolvedDistro = if ($DistroRoot) { [IO.Path]::GetFullPath($DistroRoot) } else { Join-Path $resolvedLocal 'SwitchTrade\wsl' }
    $stateRoot = Join-Path $resolvedLocal 'SwitchTrade'
    return [pscustomobject]@{
        Action = $Action
        Distro = $Distro
        UserProfileRoot = $resolvedProfile
        LocalAppDataRoot = $resolvedLocal
        DesktopRoot = $resolvedDesktop
        InvokingUserSid = $sid
        InstallRoot = $resolvedInstall
        PreviousInstall = $resolvedInstall + '.previous'
        RollbackSwap = $resolvedInstall + '.rollback-swap'
        DistroRoot = $resolvedDistro
        PackageRoot = [IO.Path]::GetFullPath($PackageRoot)
        StateRoot = $stateRoot
        TransactionPath = Join-Path $stateRoot 'setup-transaction.json'
        ResumeStatePath = Join-Path $stateRoot 'setup-resume.json'
        KernelStatePath = Join-Path $stateRoot 'kernel-state.json'
        SetupLog = Join-Path $stateRoot 'logs\setup.jsonl'
        WslConfigPath = Join-Path $resolvedProfile '.wslconfig'
        BusId = $BusId
        UsbId = $UsbId
        UsbInstanceId = $UsbInstanceId
        AcceptGlobalKernelChange = [bool]$AcceptGlobalKernelChange
        AcceptPrerequisiteChanges = [bool]$AcceptPrerequisiteChanges
        AcceptVmwareRelease = [bool]$AcceptVmwareRelease
        DeferHardwareSetup = [bool]$DeferHardwareSetup
        AllowUnsignedPackage = [bool]$AllowUnsignedPackage
        NoShortcut = [bool]$NoShortcut
    }
}

function Read-SwitchTradeJsonFile {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    try { return (Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json) }
    catch { return $null }
}

# Distro identity classification: absent | present_owned | present_generic | present_foreign |
# present_invalid | unknown | registration_disagree | enumeration_timed_out.
function Get-SwitchTradeDistroIdentityState {
    param(
        [Parameter(Mandatory)]$Context,
        [string]$ExpectedInstallId = ''
    )
    $identity = [ordered]@{
        Classification = 'unknown'
        DistroExists = $false
        EnumerationKnown = $false
        RegistrationExists = $false
        BasePath = ''
        MarkerMissing = $false
        MarkerValid = $false
        InstallId = ''
    }
    $launchSafe = Test-SwitchTradeWslRuntimeLaunchSafe
    $enumerated = $null
    if ($launchSafe) {
        try {
            $list = Invoke-SwitchTradeWsl -Arguments @('--list', '--quiet') -TimeoutSeconds 15
            if ($list.ExitCode -ne 0) { throw 'nonzero exit' }
            $enumerated = @($list.Output -split "\r?\n" | ForEach-Object { $_.Trim() } | Where-Object { $_ })
            $identity.EnumerationKnown = $true
        } catch {
            $identity.EnumerationKnown = $false
            $identity.Classification = 'enumeration_timed_out'
        }
    }
    if ($identity.Classification -eq 'unknown' -and -not $launchSafe) {
        $identity.Classification = 'unknown'
    }
    if ($identity.EnumerationKnown) {
        $identity.DistroExists = $enumerated -contains $Context.Distro
        $registration = Get-SwitchTradeDistroRegistrationState -Context $Context
        $identity.RegistrationExists = $registration.Exists
        $identity.BasePath = $registration.BasePath
        if ($identity.DistroExists -ne $identity.RegistrationExists) {
            $identity.Classification = 'registration_disagree'
        } elseif (-not $identity.DistroExists) {
            $identity.Classification = 'absent'
        } else {
            $marker = Get-SwitchTradeDistroMarkerProbe -Distro $Context.Distro -TimeoutSeconds 20
            $identity.MarkerMissing = $marker.Missing
            $identity.MarkerValid = $marker.Valid
            $identity.InstallId = $marker.InstallId
            if (-not $marker.Missing -and -not $marker.Valid) {
                $identity.Classification = 'present_invalid'
            } elseif ($marker.Missing) {
                $identity.Classification = 'present_generic'
            } elseif ($ExpectedInstallId -and $marker.InstallId -cne $ExpectedInstallId) {
                $identity.Classification = 'present_foreign'
            } elseif ($marker.InstallId) {
                $identity.Classification = 'present_owned'
            } else {
                $identity.Classification = 'present_generic'
            }
        }
    }
    return [pscustomobject]$identity
}

function Get-SwitchTradeDistroRegistrationState {
    param([Parameter(Mandatory)]$Context)
    $root = "Registry::HKEY_USERS\$($Context.InvokingUserSid)\Software\Microsoft\Windows\CurrentVersion\Lxss"
    if (-not (Test-Path -LiteralPath $root)) {
        return [pscustomobject]@{ Exists = $false; BasePath = ''; Known = $true }
    }
    try {
        $matches = @(Get-ChildItem -LiteralPath $root -ErrorAction Stop | ForEach-Object {
            $value = Get-ItemProperty -LiteralPath $_.PSPath -ErrorAction Stop
            if ([string]$value.DistributionName -ieq $Context.Distro) { $value }
        })
    } catch {
        return [pscustomobject]@{ Exists = $false; BasePath = ''; Known = $false }
    }
    if ($matches.Count -eq 0) {
        return [pscustomobject]@{ Exists = $false; BasePath = ''; Known = $true }
    }
    if ($matches.Count -ne 1 -or -not [string]$matches[0].BasePath) {
        return [pscustomobject]@{ Exists = $true; BasePath = ''; Known = $false }
    }
    $basePath = [Environment]::ExpandEnvironmentVariables([string]$matches[0].BasePath)
    if ($basePath.StartsWith('\\?\UNC\', [StringComparison]::OrdinalIgnoreCase)) {
        $basePath = '\\' + $basePath.Substring(8)
    } elseif ($basePath.StartsWith('\\?\', [StringComparison]::OrdinalIgnoreCase)) {
        $basePath = $basePath.Substring(4)
    }
    return [pscustomobject]@{
        Exists = $true
        BasePath = [IO.Path]::GetFullPath($basePath).TrimEnd('\')
        Known = $true
    }
}

function Test-SwitchTradeWslRuntimeLaunchSafe {
    $programFilesRuntime = Join-Path $env:ProgramFiles 'WSL\wsl.exe'
    if (Test-Path -LiteralPath $programFilesRuntime -PathType Leaf) { return $true }
    if (Get-Service WslService -ErrorAction SilentlyContinue) { return $true }
    if (Get-AppxPackage -Name MicrosoftCorporationII.WindowsSubsystemForLinux -ErrorAction SilentlyContinue) { return $true }
    return $false
}

# Normalized transaction state: absent | present | corrupt | legacy | future_schema.
function Get-SwitchTradeTransactionState {
    param([Parameter(Mandatory)]$Context)
    $state = [ordered]@{
        Classification = 'absent'
        Transaction = $null
        Phase = ''
        Schema = 0
        TransactionId = ''
        ReleaseId = ''
    }
    if (-not (Test-Path -LiteralPath $Context.TransactionPath -PathType Leaf)) {
        return [pscustomobject]$state
    }
    $transaction = Read-SwitchTradeJsonFile -Path $Context.TransactionPath
    if (-not $transaction) {
        $state.Classification = 'corrupt'
        return [pscustomobject]$state
    }
    $state.Transaction = $transaction
    $state.Schema = [int]$transaction.schema
    $state.Phase = [string]$transaction.phase
    $state.TransactionId = [string]$transaction.transaction_id
    $state.ReleaseId = [string]$transaction.release_id
    if ($state.Schema -lt 3) { $state.Classification = 'legacy' }
    elseif ($state.Schema -gt 3) { $state.Classification = 'future_schema' }
    elseif ($state.Phase -in @('completed', 'compensated', 'uninstalled')) { $state.Classification = 'terminal' }
    else { $state.Classification = 'present' }
    return [pscustomobject]$state
}

# Windows release tree probe: absent | present (with release id + integrity) | invalid.
function Get-SwitchTradeWindowsTreeState {
    param([Parameter(Mandatory)][string]$Root)
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) {
        return [pscustomobject]@{ Exists = $false; Valid = $false; ReleaseId = ''; IntegritySha256 = '' }
    }
    $markerPath = Join-Path $Root '.switchtrade-release.json'
    $integrityPath = Join-Path $Root '.switchtrade-integrity.json'
    if (-not (Test-Path -LiteralPath $markerPath -PathType Leaf)) {
        return [pscustomobject]@{ Exists = $true; Valid = $false; ReleaseId = ''; IntegritySha256 = '' }
    }
    $marker = Read-SwitchTradeJsonFile -Path $markerPath
    $release = if ($marker) { [string]$marker.release_id } else { '' }
    $integrity = if (Test-Path -LiteralPath $integrityPath -PathType Leaf) { Get-FileSha256 $integrityPath } else { '' }
    $valid = $release -match '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$' -and $integrity -match '^[0-9a-f]{64}$'
    return [pscustomobject]@{
        Exists = $true; Valid = $valid
        ReleaseId = $(if ($valid) { $release } else { '' })
        IntegritySha256 = $(if ($valid) { $integrity } else { '' })
    }
}

# Kernel ownership state: absent | present | invalid.
function Get-SwitchTradeKernelState {
    param([Parameter(Mandatory)]$Context)
    $path = $Context.KernelStatePath
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        return [pscustomobject]@{ Exists = $false; Valid = $false; ReleaseId = ''; State = $null }
    }
    $state = Read-SwitchTradeJsonFile -Path $path
    if (-not $state) {
        return [pscustomobject]@{ Exists = $true; Valid = $false; ReleaseId = ''; State = $null }
    }
    $release = if ($state.PSObject.Properties.Name -contains 'package_release_id') { [string]$state.package_release_id } else { '' }
    $kernelOk = ($state.PSObject.Properties.Name -contains 'kernel_path') -and
        (Test-Path -LiteralPath ([string]$state.kernel_path) -PathType Leaf) -and
        ($state.PSObject.Properties.Name -contains 'kernel_sha256') -and
        (Get-FileSha256 ([string]$state.kernel_path)) -eq [string]$state.kernel_sha256
    $modulesOk = $true
    if ($state.PSObject.Properties.Name -contains 'modules_path' -and [string]$state.modules_path) {
        $modulesOk = (Test-Path -LiteralPath ([string]$state.modules_path) -PathType Leaf) -and
            ($state.PSObject.Properties.Name -contains 'modules_sha256') -and
            (Get-FileSha256 ([string]$state.modules_path)) -eq [string]$state.modules_sha256
    }
    $valid = $release -match '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$' -and $kernelOk -and $modulesOk
    return [pscustomobject]@{
        Exists = $true; Valid = $valid
        ReleaseId = $(if ($valid) { $release } else { '' })
        State = $state
    }
}

# Host audit facts (read-only).
function Get-SwitchTradeHostState {
    $computer = Get-CimInstance Win32_ComputerSystem -ErrorAction SilentlyContinue
    $operatingSystem = Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue
    $processors = @(Get-CimInstance Win32_Processor -ErrorAction SilentlyContinue)
    $architecture = [Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
    $windowsBuild = if ($operatingSystem) { [int]$operatingSystem.BuildNumber } else { [Environment]::OSVersion.Version.Build }
    $productType = if ($operatingSystem) { [int]$operatingSystem.ProductType } else { 0 }
    $firmwareVirtualization = [bool]($processors | Where-Object { $_.VirtualizationFirmwareEnabled } | Select-Object -First 1)
    $vmware = Get-Service VMUSBArbService -ErrorAction SilentlyContinue
    $wslFeature = $null
    $vmFeature = $null
    try {
        $wslFeature = Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Windows-Subsystem-Linux -ErrorAction Stop
        $vmFeature = Get-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform -ErrorAction Stop
    } catch { }
    $featuresEnabled = $wslFeature -and $vmFeature -and
        [string]$wslFeature.State -in @('Enabled', 'EnablePending') -and
        [string]$vmFeature.State -in @('Enabled', 'EnablePending')
    $root = (Get-PSDrive -Name ([IO.Path]::GetPathRoot($env:LOCALAPPDATA).Substring(0, 1)) -ErrorAction SilentlyContinue)
    return [pscustomobject]@{
        Windows64Bit = [Environment]::Is64BitOperatingSystem
        WindowsSupported = $productType -eq 1 -and $architecture -eq 'X64' -and $windowsBuild -ge 19045
        WindowsProductType = $productType
        WindowsBuild = $windowsBuild
        Architecture = $architecture
        PendingReboot = Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired'
        VirtualizationReady = [bool](($computer -and $computer.HypervisorPresent) -or $firmwareVirtualization)
        WslCommandPresent = [bool](Get-Command wsl.exe -ErrorAction SilentlyContinue)
        WslRuntimeLaunchSafe = (Test-SwitchTradeWslRuntimeLaunchSafe)
        WslFeaturesEnabled = [bool]$featuresEnabled
        WslVersion = ''
        WslCapabilityReady = $false
        VmwareUsbArbitrator = if ($vmware) { [string]$vmware.Status } else { 'Absent' }
        FreeSpaceGB = if ($root) { [math]::Round($root.Free / 1GB, 1) } else { 0 }
    }
}

# WSL runtime version + capability probe (read-only).
function Get-SwitchTradeWslCapabilityState {
    param($HostState)
    $state = [ordered]@{
        Version = ''; MinimumMet = $false; CapabilityReady = $false
        ProbeFailed = $false; Output = ''
    }
    if (-not $HostState.WslRuntimeLaunchSafe) { return [pscustomobject]$state }
    $versionProbe = Invoke-SwitchTradeWsl -Arguments @('--version') -TimeoutSeconds 15
    if ($versionProbe.ExitCode -ne 0) {
        $state.ProbeFailed = $true
        return [pscustomobject]$state
    }
    $versionText = ($versionProbe.Output + "`n" + $versionProbe.Error).Trim()
    $state.Output = $versionText
    $match = [regex]::Match($versionText, '(?<!\d)(\d+\.\d+(?:\.\d+){0,2})(?!\d)')
    if ($match.Success) {
        try { $state.Version = [version]$match.Groups[1].Value } catch { }
    }
    if ($state.Version -and $state.Version -ge [version]'2.2.4.0') { $state.MinimumMet = $true }
    $helpProbe = Invoke-SwitchTradeWsl -Arguments @('--help') -TimeoutSeconds 15
    # The Store runtime exits nonzero from --help on some builds; capability evidence is the
    # text itself, never the exit code (localized text never drives control flow).
    $helpText = ($helpProbe.Output + "`n" + $helpProbe.Error).Trim()
    $state.CapabilityReady = $state.MinimumMet -and
        $helpText.Contains('--import') -and $helpText.Contains('--distribution') -and
        $helpText.Contains('--cd') -and $helpText.Contains('--version')
    return [pscustomobject]$state
}

# The complete normalized snapshot.
function Get-SwitchTradeInstallState {
    param([Parameter(Mandatory)]$Context)
    $hostState = Get-SwitchTradeHostState
    $wslCapability = Get-SwitchTradeWslCapabilityState -HostState $hostState
    $identity = Get-SwitchTradeDistroIdentityState -Context $Context
    $transaction = Get-SwitchTradeTransactionState -Context $Context
    $windowsActive = Get-SwitchTradeWindowsTreeState -Root $Context.InstallRoot
    $windowsPrevious = Get-SwitchTradeWindowsTreeState -Root $Context.PreviousInstall
    $windowsSwap = Get-SwitchTradeWindowsTreeState -Root $Context.RollbackSwap
    $kernel = Get-SwitchTradeKernelState -Context $Context
    $wslActive = $wslCandidate = $wslPrevious = $wslCommitSwap = $wslRollbackSwap = $null
    if ($identity.DistroExists) {
        $wslActive = Get-SwitchTradeWslRuntimeLocationProbe -Distro $Context.Distro -Location active
        $wslCandidate = Get-SwitchTradeWslRuntimeLocationProbe -Distro $Context.Distro -Location candidate
        $wslPrevious = Get-SwitchTradeWslRuntimeLocationProbe -Distro $Context.Distro -Location previous
        $wslCommitSwap = Get-SwitchTradeWslRuntimeLocationProbe -Distro $Context.Distro -Location commit_swap
        $wslRollbackSwap = Get-SwitchTradeWslRuntimeLocationProbe -Distro $Context.Distro -Location rollback_swap
    } else {
        $empty = [pscustomobject]@{ Exists = $false; Valid = $true; ReleaseId = ''; IntegritySha256 = '' }
        $wslActive = $wslCandidate = $wslPrevious = $wslCommitSwap = $wslRollbackSwap = $empty
    }
    $stageParent = Split-Path -Parent $Context.InstallRoot
    $stageExists = $false
    if ($transaction.Transaction) {
        $recordedStage = [string]$transaction.Transaction.windows_stage
        if ($recordedStage) {
            $stageExists = (Test-Path -LiteralPath $recordedStage -PathType Container)
        }
    }
    $usbipdCommand = Get-Command usbipd.exe -ErrorAction SilentlyContinue
    $resume = Read-SwitchTradeJsonFile -Path $Context.ResumeStatePath
    return [pscustomobject]@{
        Context = $Context
        Host = $hostState
        WslCapability = $wslCapability
        Identity = $identity
        Transaction = $transaction
        WindowsActive = $windowsActive
        WindowsPrevious = $windowsPrevious
        WindowsSwap = $windowsSwap
        WindowsStageExists = $stageExists
        Kernel = $kernel
        WslActive = $wslActive
        WslCandidate = $wslCandidate
        WslPrevious = $wslPrevious
        WslCommitSwap = $wslCommitSwap
        WslRollbackSwap = $wslRollbackSwap
        Resume = $resume
        UsbipdInstalled = [bool]$usbipdCommand
        UsbipdPath = if ($usbipdCommand) { $usbipdCommand.Source } else { '' }
        StageParent = $stageParent
        Correlations = [ordered]@{}
    }
}