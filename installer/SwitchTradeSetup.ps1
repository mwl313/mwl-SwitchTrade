[CmdletBinding(SupportsShouldProcess)]
param(
    [ValidateSet('Audit', 'Install', 'Repair', 'Update', 'Resume', 'Rollback', 'Uninstall')]
    [string]$Action = 'Audit',
    [string]$Distro = 'SwitchTrade',
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'Programs\SwitchTrade'),
    [string]$DistroRoot = (Join-Path $env:LOCALAPPDATA 'SwitchTrade\wsl'),
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
    if ($SetupLog) {
        try { Write-SwitchTradeSetupLog -Path $SetupLog -Stage $SetupStage -Message ($_ | Out-String) -Level error } catch { }
    }
    [Console]::Error.WriteLine("SWITCHTRADE_SETUP_ERROR: $message")
    $failure = [ordered]@{
        code = $code; message = Redact-SwitchTradeSetupText $message; stage = $SetupStage
        recoverable = $true; primary_action = 'Run Setup Repair'; action = $Action
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
$StateRoot = Join-Path $env:LOCALAPPDATA 'SwitchTrade'
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
        schema = 2; package_root = $PackageRoot; action = $ResumeAction
        distro = $Distro; install_root = $InstallRoot; distro_root = $DistroRoot
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
    New-Item -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce' -Force | Out-Null
    Set-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce' `
        -Name $ResumeRunOnce -Value $command
}

function Clear-SetupResume {
    if (Test-Path -LiteralPath $ResumeStatePath -PathType Leaf) {
        Remove-Item -LiteralPath $ResumeStatePath -Force
    }
    Remove-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce' `
        -Name $ResumeRunOnce -ErrorAction SilentlyContinue
}

if ($WasResume) {
    if (-not (Test-Path -LiteralPath $ResumeStatePath -PathType Leaf)) {
        throw 'SETUP_RESUME_STATE_MISSING: rerun the signed SwitchTrade setup package'
    }
    $resume = Get-Content -Raw -LiteralPath $ResumeStatePath | ConvertFrom-Json
    if ([int]$resume.schema -ne 2 -or [string]$resume.package_root -ne $PackageRoot -or
        [string]$resume.action -notin @('Install', 'Repair', 'Update')) {
        throw 'SETUP_RESUME_STATE_INVALID: rerun the signed SwitchTrade setup package'
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
    $output = @(& wsl.exe --list --quiet 2>$null)
    if ($LASTEXITCODE -ne 0) { return @() }
    return @($output | ForEach-Object { $_.Trim([char]0).Trim() } | Where-Object { $_ })
}

function Convert-ToWslPath([string]$Path) {
    $resolved = (Resolve-Path -LiteralPath $Path).Path
    if ($resolved -notmatch '^([A-Za-z]):\\(.*)$') { throw "cannot map path into WSL: $resolved" }
    return "/mnt/$($Matches[1].ToLowerInvariant())/$($Matches[2].Replace('\', '/'))"
}

function Test-SwitchTradeDistroOwned {
    param([Parameter(Mandatory)][string]$Name)
    $raw = ((& wsl.exe -d $Name -u root -- cat /etc/switchtrade-distro.json 2>$null) -join '')
    if ($LASTEXITCODE -ne 0 -or -not $raw) { return $false }
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
    $output = @(& wsl.exe @Arguments 2>&1)
    $exitCode = $LASTEXITCODE
    foreach ($line in $output) {
        Write-SwitchTradeSetupLog -Path $SetupLog -Stage $Stage -Message ([string]$line)
    }
    if ($exitCode -ne 0) {
        throw "${FailureCode}: $((@($output | ForEach-Object { [string]$_ }) -join "`n").Trim())"
    }
    return $output
}

function Resolve-StableUsbBusId {
    if (-not $UsbInstanceId) { return $BusId }
    $script:SetupStage = 'usb_identity'
    $raw = ((& usbipd.exe state 2>&1) -join "`n")
    if ($LASTEXITCODE -ne 0) { throw "USBIPD_STATE_FAILED: $raw" }
    $state = $raw | ConvertFrom-Json
    $device = Resolve-SwitchTradeUsbDeviceFromState -State $state -InstanceId $UsbInstanceId -UsbId $UsbId
    return [string]$device.BusId
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
        & wsl.exe --terminate $Distro 2>$null | Out-Null
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
    if ($wslCommandPresent) {
        & wsl.exe --status 2>$null | Out-Null
        $wslStatusExit = $LASTEXITCODE
        $versionOutput = @(& wsl.exe --version 2>$null)
        $wslVersionExit = $LASTEXITCODE
        if ($wslVersionExit -eq 0) {
            $wslVersion = ($versionOutput -join ' ').Replace([string][char]0, '').Trim()
        }
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
        WslModern = $wslCommandPresent -and $wslVersionExit -eq 0 -and [bool]$wslVersion
        WslVersion = $wslVersion
        UsbipdInstalled = [bool](Get-Command usbipd.exe -ErrorAction SilentlyContinue)
        DistroInstalled = $distros -contains $Distro
        PayloadPresent = Test-Path -LiteralPath $Payload -PathType Container
        RootfsPresent = Test-Path -LiteralPath $Rootfs -PathType Leaf
        InstallRoot = $InstallRoot
        Distro = $Distro
        KernelPolicy = 'unchanged'
        ExistingWslConfig = Test-Path -LiteralPath (Join-Path $env:USERPROFILE '.wslconfig')
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
if ($namedDistroExists) { Assert-SwitchTradeDistroOwned -Name $Distro }
if (Test-Path -LiteralPath $TransactionPath -PathType Leaf) {
    $staleTransaction = Get-Content -Raw -LiteralPath $TransactionPath | ConvertFrom-Json
    if ([string]$staleTransaction.phase -notin @('completed', 'compensated')) {
        throw "SETUP_TRANSACTION_INCOMPLETE: transaction $($staleTransaction.transaction_id) stopped at $($staleTransaction.phase); run the matching package Repair"
    }
}

if ($Action -eq 'Uninstall') {
    Clear-SetupResume
    Restore-SwitchTradeKernel -StateRoot $StateRoot | Out-Null
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
            & wsl.exe --unregister $Distro
            if ($LASTEXITCODE -ne 0) { throw "failed to unregister $Distro" }
        }
    }
    $shortcutPath = Join-Path $env:USERPROFILE 'Desktop\SwitchTrade.lnk'
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
        & wsl.exe --terminate $Distro 2>$null | Out-Null
        Invoke-LoggedWsl -Arguments @('-d', $Distro, '-u', 'root', '--', 'bash', $runtimeProvision,
            '--rollback', '--release-id', $rollbackRelease) `
            -FailureCode 'ROLLBACK_RUNTIME_COMMIT_FAILED' -Stage $SetupStage | Out-Null
        $runtimeRolledBack = $true
        $kernelRolledBack = Switch-SwitchTradeKernelRollback -StateRoot $StateRoot `
            -ExpectedReleaseId $rollbackRelease
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
                Switch-SwitchTradeKernelRollback -StateRoot $StateRoot -ExpectedReleaseId $activeRelease | Out-Null
            }
            if ($runtimeRolledBack) {
                & wsl.exe --terminate $Distro 2>$null
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
    & dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
    if ($LASTEXITCODE -notin @(0, 3010)) { throw 'could not enable Windows Subsystem for Linux' }
    & dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
    if ($LASTEXITCODE -notin @(0, 3010)) { throw 'could not enable Virtual Machine Platform' }
    Save-SetupResume -ResumeAction $Action
    Write-Host 'WSL prerequisites were enabled. Restart Windows; SwitchTrade Setup will resume after sign-in.'
    exit 3010
}
if (-not $audit.WslModern) {
    if (-not $AcceptPrerequisiteChanges) {
        throw 'The current Microsoft Store version of WSL 2 is required. Rerun after accepting prerequisite changes.'
    }
    & wsl.exe --update --web-download
    if ($LASTEXITCODE -ne 0) {
        & wsl.exe --update
    }
    if ($LASTEXITCODE -ne 0) {
        throw 'WSL_UPDATE_FAILED: install the current Microsoft Store WSL package, restart Windows, and run Setup again.'
    }
    & wsl.exe --version 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw 'WSL_UPDATE_INCOMPLETE: restart Windows and run Setup again.'
    }
}
if (-not $audit.UsbipdInstalled) {
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
    $msi = Start-Process msiexec.exe -ArgumentList @('/i', $UsbipdMsi, '/qn', '/norestart') -Wait -PassThru
    if ($msi.ExitCode -notin @(0, 3010)) { throw "usbipd-win installation failed with $($msi.ExitCode)" }
    if ($msi.ExitCode -eq 3010) {
        Save-SetupResume -ResumeAction $Action
        Write-Host 'usbipd-win requires a restart. SwitchTrade Setup will resume after sign-in.'
        exit 3010
    }
}
$installParent = Split-Path -Parent $InstallRoot
New-Item -ItemType Directory -Force -Path $installParent | Out-Null
$stage = Join-Path $installParent ("SwitchTrade.stage." + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $stage | Out-Null
$priorReleaseId = ''
if (Test-Path -LiteralPath $InstallRoot -PathType Container) {
    $priorReleaseId = Get-InstalledWindowsReleaseId -Root $InstallRoot
    if (-not $priorReleaseId) {
        throw 'INSTALLED_RELEASE_ID_MISSING: existing application files are not a committed SwitchTrade release'
    }
    Test-WindowsReleaseTree -Root $InstallRoot -ExpectedReleaseId $priorReleaseId | Out-Null
}
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
    -PriorReleaseId $priorReleaseId -WindowsStage $stage
try {
    $SetupStage = 'windows_stage'
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
        & wsl.exe --import $Distro $DistroRoot $Rootfs --version 2
        if ($LASTEXITCODE -ne 0) { throw "DISTRO_IMPORT_FAILED: failed to import isolated distro $Distro" }
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
        $kernelOutput = ((& wsl.exe -d $Distro -- uname -r 2>&1) -join "`n").Trim()
        if ($LASTEXITCODE -ne 0 -or $kernelOutput -ne [string]$kernelState.kernel_release) {
            if ($kernelOutput -match '(?i)policy|blocked|access.+denied|administrator') {
                throw "CUSTOM_KERNEL_BLOCKED_BY_POLICY: this managed PC is unsupported by the private beta. $kernelOutput"
            }
            throw "CUSTOM_KERNEL_START_FAILED: expected $($kernelState.kernel_release), got $kernelOutput"
        }
        if ($KernelModules -and $kernelState.modules_format -eq 'archive') {
            $modulesWsl = Convert-ToWslPath $KernelModules
            $extractCommand = 'set -eu; if ! command -v depmod >/dev/null 2>&1 || ! command -v modinfo >/dev/null 2>&1; then export DEBIAN_FRONTEND=noninteractive; apt-get update; apt-get install -y --no-install-recommends kmod; rm -rf /var/lib/apt/lists/*; fi; mkdir -p /lib/modules; tar -xzf "{0}" -C /lib/modules; depmod -a "{1}"' -f `
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
            & wsl.exe -d $Distro -u root -- bash $provision --validate-candidate `
                --release-id $ReleaseId 2>$null | Out-Null
            $wslStaged = $LASTEXITCODE -eq 0
        }
        if ($wslCommitAttempted -and -not $wslCommitted) {
            & wsl.exe -d $Distro -u root -- bash $provision --validate-active `
                --release-id $ReleaseId 2>$null | Out-Null
            $wslCommitted = $LASTEXITCODE -eq 0
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
                        -ExpectedReleaseId $priorReleaseId | Out-Null
                } else {
                    Restore-SwitchTradeKernel -StateRoot $StateRoot | Out-Null
                }
            } elseif ($currentKernelRelease -and $currentKernelRelease -ne $priorReleaseId) {
                throw "KERNEL_COMPENSATION_RELEASE_MISMATCH: expected $priorReleaseId, found $currentKernelRelease"
            }
        }
        if ($distroImported) {
            Assert-SwitchTradeDistroOwned -Name $Distro
            & wsl.exe --unregister $Distro
            if ($LASTEXITCODE -ne 0) { throw 'DISTRO_IMPORT_COMPENSATION_FAILED' }
        }
        if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
        Set-SwitchTradeTransactionPhase -Path $TransactionPath -Phase 'compensated' | Out-Null
    } catch {
        throw "SETUP_COMPENSATION_FAILED: $($transactionFailure.Exception.Message); compensation: $($_.Exception.Message)"
    }
    throw $transactionFailure
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
    }
    if ($BusId) { $preflightArguments.BusId = $BusId }
    if ($UsbId) { $preflightArguments.UsbId = @($UsbId) }
    & $radioPreflight @preflightArguments
    if ($LASTEXITCODE -ne 0) { throw 'USB_OWNERSHIP_PREFLIGHT_FAILED: reconnect the selected adapter and run Setup Repair' }
    $wslHealthArguments = @(
        '-d', $Distro, '-u', 'root', '--cd', '/opt/switchtrade', '--',
        './scripts/wsl-radio-prepare.sh', '--role', 'guest',
        '--health-channels', '1,6,11', '--target-channel', '6'
    )
    if ($UsbId) { $wslHealthArguments += @('--usb-id', $UsbId.ToLowerInvariant()) }
    $wslHealthArguments += @('--', 'true')
    Invoke-LoggedWsl -Arguments $wslHealthArguments -FailureCode 'RADIO_RX_HEALTH_FAILED' `
        -Stage $SetupStage | Out-Null
}

if (-not $NoShortcut) {
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut((Join-Path $env:USERPROFILE 'Desktop\SwitchTrade.lnk'))
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
