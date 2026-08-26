[CmdletBinding(SupportsShouldProcess)]
param(
    [ValidateSet('Audit', 'Install', 'Repair', 'Update', 'Resume', 'Rollback', 'Uninstall')]
    [string]$Action = 'Audit',
    [string]$Distro = 'SwitchTrade',
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'Programs\SwitchTrade'),
    [string]$DistroRoot = (Join-Path $env:LOCALAPPDATA 'SwitchTrade\wsl'),
    [ValidatePattern('^$|^\d+-\d+$')][string]$BusId = '',
    [ValidatePattern('^$|^[0-9a-fA-F]{4}:[0-9a-fA-F]{4}$')][string]$UsbId = '',
    [switch]$AcceptGlobalKernelChange,
    [switch]$AcceptPrerequisiteChanges,
    [switch]$AcceptVmwareRelease,
    [switch]$DeferHardwareSetup,
    [switch]$AllowUnsignedPackage,
    [switch]$NoShortcut,
    [switch]$PurgeDistro
)

$ErrorActionPreference = 'Stop'
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
$UsbipdMsi = Join-Path $PackageRoot 'payload\prerequisites\usbipd-win.msi'
$UsbipdManifest = Join-Path $PackageRoot 'payload\prerequisites\usbipd-win.json'
$PreviousInstall = "$InstallRoot.previous"
. (Join-Path $PSScriptRoot 'KernelLifecycle.ps1')
. (Join-Path $PSScriptRoot 'PackageIntegrity.ps1')

$ResumeStatePath = Join-Path $StateRoot 'setup-resume.json'
$ResumeRunOnce = 'SwitchTradeSetupResume'
$WasResume = $Action -eq 'Resume'

function Save-SetupResume([string]$ResumeAction) {
    New-Item -ItemType Directory -Force -Path $StateRoot | Out-Null
    @{
        schema = 1; package_root = $PackageRoot; action = $ResumeAction
        distro = $Distro; install_root = $InstallRoot; distro_root = $DistroRoot
        bus_id = $BusId; usb_id = $UsbId
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
    if ([int]$resume.schema -ne 1 -or [string]$resume.package_root -ne $PackageRoot -or
        [string]$resume.action -notin @('Install', 'Repair', 'Update')) {
        throw 'SETUP_RESUME_STATE_INVALID: rerun the signed SwitchTrade setup package'
    }
    $Action = [string]$resume.action
    $Distro = [string]$resume.distro
    $InstallRoot = [string]$resume.install_root
    $DistroRoot = [string]$resume.distro_root
    $BusId = [string]$resume.bus_id
    $UsbId = [string]$resume.usb_id
    $AcceptGlobalKernelChange = [bool]$resume.accept_global_kernel_change
    $AcceptPrerequisiteChanges = [bool]$resume.accept_prerequisite_changes
    $AcceptVmwareRelease = [bool]$resume.accept_vmware_release
    $DeferHardwareSetup = [bool]$resume.defer_hardware_setup
    $NoShortcut = [bool]$resume.no_shortcut
    $PreviousInstall = "$InstallRoot.previous"
}

function Get-Distros {
    if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) { return @() }
    return @(& wsl.exe --list --quiet | ForEach-Object { $_.Trim([char]0).Trim() } | Where-Object { $_ })
}

function Convert-ToWslPath([string]$Path) {
    $resolved = (Resolve-Path -LiteralPath $Path).Path
    if ($resolved -notmatch '^([A-Za-z]):\\(.*)$') { throw "cannot map path into WSL: $resolved" }
    return "/mnt/$($Matches[1].ToLowerInvariant())/$($Matches[2].Replace('\', '/'))"
}

function Test-Setup {
    $distros = Get-Distros
    $vmware = Get-Service VMUSBArbService -ErrorAction SilentlyContinue
    $computer = Get-CimInstance Win32_ComputerSystem -ErrorAction SilentlyContinue
    $wslVersion = if (Get-Command wsl.exe -ErrorAction SilentlyContinue) {
        ((& wsl.exe --version 2>$null) -join ' ').Replace([string][char]0, '').Trim()
    } else { 'Absent' }
    [pscustomobject]@{
        Windows64Bit = [Environment]::Is64BitOperatingSystem
        WslInstalled = [bool](Get-Command wsl.exe -ErrorAction SilentlyContinue)
        WslVersion = $wslVersion
        UsbipdInstalled = [bool](Get-Command usbipd.exe -ErrorAction SilentlyContinue)
        DistroInstalled = $distros -contains $Distro
        PayloadPresent = Test-Path -LiteralPath $Payload -PathType Container
        RootfsPresent = Test-Path -LiteralPath $Rootfs -PathType Leaf
        InstallRoot = $InstallRoot
        Distro = $Distro
        KernelPolicy = 'unchanged'
        ExistingWslConfig = Test-Path -LiteralPath (Join-Path $env:USERPROFILE '.wslconfig')
        WindowsBuild = [Environment]::OSVersion.Version.Build
        Architecture = [Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
        FreeSpaceGB = [math]::Round((Get-PSDrive -Name ([IO.Path]::GetPathRoot($InstallRoot).Substring(0,1))).Free / 1GB, 1)
        PendingReboot = Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired'
        VirtualizationReady = [bool]($computer -and $computer.HypervisorPresent)
        VmwareUsbArbitrator = if ($vmware) { [string]$vmware.Status } else { 'Absent' }
        KernelBundlePresent = (Test-Path -LiteralPath $Kernel) -and (Test-Path -LiteralPath $KernelManifest)
    }
}

if ($Action -eq 'Audit') {
    Test-Setup | Format-List
    exit
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
        throw 'no retained SwitchTrade application version is available for rollback'
    }
    $swap = "$InstallRoot.rollback-swap"
    if (Test-Path -LiteralPath $swap) { throw "stale rollback swap path requires repair: $swap" }
    $runtimeRolledBack = $false
    $kernelRolledBack = $false
    try {
        if ((Get-Distros) -contains $Distro) {
            & wsl.exe --terminate $Distro 2>$null
            $runtimeProvision = Convert-ToWslPath (Join-Path $PSScriptRoot 'provision-wsl.sh')
            & wsl.exe -d $Distro -u root -- bash $runtimeProvision --rollback
            if ($LASTEXITCODE -ne 0) { throw 'the retained SwitchTrade WSL runtime could not be activated' }
            $runtimeRolledBack = $true
        }
        $kernelRolledBack = Switch-SwitchTradeKernelRollback -StateRoot $StateRoot
        if (Test-Path -LiteralPath $InstallRoot) {
            Move-Item -LiteralPath $InstallRoot -Destination $swap
        }
        Move-Item -LiteralPath $PreviousInstall -Destination $InstallRoot
        if (Test-Path -LiteralPath $swap) { Move-Item -LiteralPath $swap -Destination $PreviousInstall }
    } catch {
        $failure = $_
        if (-not (Test-Path -LiteralPath $InstallRoot) -and (Test-Path -LiteralPath $swap)) {
            Move-Item -LiteralPath $swap -Destination $InstallRoot
        }
        try {
            if ($kernelRolledBack) { Switch-SwitchTradeKernelRollback -StateRoot $StateRoot | Out-Null }
            if ($runtimeRolledBack) {
                & wsl.exe --terminate $Distro 2>$null
                & wsl.exe -d $Distro -u root -- bash $runtimeProvision --rollback
                if ($LASTEXITCODE -ne 0) { throw 'WSL runtime rollback recovery failed' }
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
Test-SwitchTradePackage -PackageRoot $PackageRoot -AllowUnsignedPackage:$AllowUnsignedPackage | Out-Null
if (-not $audit.Windows64Bit) { throw 'SwitchTrade requires 64-bit Windows.' }
if ($audit.WindowsBuild -lt 26100) { throw 'SwitchTrade private beta requires Windows 11 24H2 build 26100 or newer.' }
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
    if ($LASTEXITCODE -ne 0) { throw 'could not enable Windows Subsystem for Linux' }
    & dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
    if ($LASTEXITCODE -ne 0) { throw 'could not enable Virtual Machine Platform' }
    Save-SetupResume -ResumeAction $Action
    Write-Host 'WSL prerequisites were enabled. Restart Windows; SwitchTrade Setup will resume after sign-in.'
    exit 3010
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
if ($audit.VmwareUsbArbitrator -eq 'Running') {
    if (-not $AcceptVmwareRelease) {
        throw 'VMware USB Arbitrator can reclaim the Wi-Fi adapter. Rerun Repair after accepting its temporary stop.'
    }
    Stop-Service VMUSBArbService -Force
}
if (-not $audit.DistroInstalled) {
    if (-not $audit.RootfsPresent) {
        throw "the SwitchTrade distro is absent and this package has no rootfs: $Rootfs"
    }
    if (-not (Test-Path -LiteralPath $RootfsHash -PathType Leaf)) {
        throw "rootfs checksum is missing: $RootfsHash"
    }
    $expectedHash = ((Get-Content -LiteralPath $RootfsHash -TotalCount 1) -split '\s+')[0]
    $actualHash = Get-FileSha256 $Rootfs
    if ($expectedHash -notmatch '^[0-9a-fA-F]{64}$' -or $expectedHash.ToLowerInvariant() -ne $actualHash) {
        throw 'SwitchTrade rootfs checksum verification failed.'
    }
    New-Item -ItemType Directory -Force -Path $DistroRoot | Out-Null
    & wsl.exe --import $Distro $DistroRoot $Rootfs --version 2
    if ($LASTEXITCODE -ne 0) { throw "failed to import the isolated $Distro distribution" }
}

if ((Test-Path -LiteralPath $Kernel -PathType Leaf) -and
    (Test-Path -LiteralPath $KernelManifest -PathType Leaf)) {
    $kernelArguments = @{
        Kernel = $Kernel; Manifest = $KernelManifest; StateRoot = $StateRoot
        AcceptGlobalKernelChange = $AcceptGlobalKernelChange
    }
    if ($KernelModules -and (Test-Path -LiteralPath $KernelModules -PathType Leaf)) {
        $kernelArguments.KernelModules = $KernelModules
    }
    $kernelState = Install-SwitchTradeKernel @kernelArguments
    $kernelOutput = ((& wsl.exe -d $Distro -- uname -r 2>&1) -join "`n").Trim()
    $kernelExit = $LASTEXITCODE
    if ($kernelExit -ne 0 -or $kernelOutput -ne [string]$kernelState.kernel_release) {
        try { Restore-SwitchTradeKernel -StateRoot $StateRoot | Out-Null } catch { }
        if ($kernelOutput -match '(?i)policy|blocked|access.+denied|administrator') {
            throw "CUSTOM_KERNEL_BLOCKED_BY_POLICY: this managed PC is unsupported by the private beta. $kernelOutput"
        }
        throw "CUSTOM_KERNEL_START_FAILED: restored the previous WSL configuration; expected $($kernelState.kernel_release), got $kernelOutput"
    }
    if ($KernelModules -and $kernelState.modules_format -eq 'archive') {
        $modulesWsl = Convert-ToWslPath $KernelModules
        $extractCommand = 'set -eu; mkdir -p /lib/modules; tar -xzf "{0}" -C /lib/modules; depmod -a "{1}"' -f `
            $modulesWsl, [string]$kernelState.kernel_release
        & wsl.exe -d $Distro -u root -- sh -lc $extractCommand
        if ($LASTEXITCODE -ne 0) { throw 'KERNEL_MODULE_INSTALL_FAILED: could not install the matching module archive' }
    }
    if ($KernelModules) {
        $moduleVerify = 'set -eu; test "$(uname -r)" = "{0}"; test "$(modinfo -F vermagic rtl8xxxu | awk ''{{print $1}}'')" = "{0}"; modinfo -F firmware rtl8xxxu | while IFS= read -r fw; do test -z "$fw" || test -f "/lib/firmware/$fw"; done' -f `
            [string]$kernelState.kernel_release
        & wsl.exe -d $Distro -u root -- sh -lc $moduleVerify
        if ($LASTEXITCODE -ne 0) {
            throw 'KERNEL_ABI_OR_FIRMWARE_MISMATCH: running kernel, rtl8xxxu module ABI, and firmware must come from one release'
        }
    }
}

$source = Convert-ToWslPath $Payload
$provision = Convert-ToWslPath (Join-Path $PackageRoot 'installer\provision-wsl.sh')
& wsl.exe -d $Distro -u root -- bash $provision --source $source
if ($LASTEXITCODE -ne 0) { throw 'SwitchTrade WSL provisioning failed.' }

if ($DeferHardwareSetup) {
    Write-Host 'Wi-Fi adapter setup was deferred. Select an adapter in SwitchTrade Settings, then run Setup Repair once if binding is required.'
} else {
    $radioPreflight = Join-Path $Payload 'scripts\windows\wsl-radio-preflight.ps1'
    $profileFile = Join-Path $Payload 'config\wsl-radio-hardware.tsv'
    $preflightArguments = @{
        Distro = $Distro; ProfileFile = $profileFile; Prepare = $true; AutoAttach = $true
    }
    if ($BusId) { $preflightArguments.BusId = $BusId }
    if ($UsbId) { $preflightArguments.UsbId = @($UsbId) }
    & $radioPreflight @preflightArguments
    if ($LASTEXITCODE -ne 0) { throw 'SwitchTrade USB/WSL ownership preflight failed.' }
    $wslHealthArguments = @(
        '-d', $Distro, '-u', 'root', '--cd', '/opt/switchtrade', '--',
        './scripts/wsl-radio-prepare.sh', '--role', 'guest',
        '--health-channels', '1,6,11', '--target-channel', '6'
    )
    if ($UsbId) { $wslHealthArguments += @('--usb-id', $UsbId.ToLowerInvariant()) }
    $wslHealthArguments += @('--', 'true')
    & wsl.exe @wslHealthArguments
    if ($LASTEXITCODE -ne 0) { throw 'SwitchTrade driver/RX health gate failed.' }
}

$installParent = Split-Path -Parent $InstallRoot
New-Item -ItemType Directory -Force -Path $installParent | Out-Null
$stage = Join-Path $installParent ("SwitchTrade.stage." + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $stage | Out-Null
try {
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
    if (Test-Path -LiteralPath $PreviousInstall) {
        Remove-Item -LiteralPath $PreviousInstall -Recurse -Force
    }
    if (Test-Path -LiteralPath $InstallRoot) {
        Move-Item -LiteralPath $InstallRoot -Destination $PreviousInstall
    }
    Move-Item -LiteralPath $stage -Destination $InstallRoot
} catch {
    if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
    if (-not (Test-Path -LiteralPath $InstallRoot) -and (Test-Path -LiteralPath $PreviousInstall)) {
        Move-Item -LiteralPath $PreviousInstall -Destination $InstallRoot
    }
    throw
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
