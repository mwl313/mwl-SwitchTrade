[CmdletBinding(SupportsShouldProcess)]
param(
    [ValidateSet('Audit', 'Install', 'Repair', 'Update', 'Rollback', 'Uninstall')]
    [string]$Action = 'Audit',
    [string]$Distro = 'SwitchTrade',
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'Programs\SwitchTrade'),
    [string]$DistroRoot = (Join-Path $env:LOCALAPPDATA 'SwitchTrade\wsl'),
    [switch]$AcceptGlobalKernelChange,
    [switch]$AcceptPrerequisiteChanges,
    [switch]$AcceptVmwareRelease,
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
$KernelModules = Join-Path $PackageRoot 'payload\kernel\modules'
$KernelManifest = Join-Path $PackageRoot 'payload\kernel\manifest.json'
$StateRoot = Join-Path $env:LOCALAPPDATA 'SwitchTrade'
$UsbipdMsi = Join-Path $PackageRoot 'payload\prerequisites\usbipd-win.msi'
$UsbipdManifest = Join-Path $PackageRoot 'payload\prerequisites\usbipd-win.json'
$PreviousInstall = "$InstallRoot.previous"
. (Join-Path $PSScriptRoot 'KernelLifecycle.ps1')

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
    [pscustomobject]@{
        Windows64Bit = [Environment]::Is64BitOperatingSystem
        WslInstalled = [bool](Get-Command wsl.exe -ErrorAction SilentlyContinue)
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
    if (-not (Test-Path -LiteralPath $PreviousInstall -PathType Container)) {
        throw 'no retained SwitchTrade application version is available for rollback'
    }
    Switch-SwitchTradeKernelRollback -StateRoot $StateRoot | Out-Null
    $swap = "$InstallRoot.rollback-swap"
    if (Test-Path -LiteralPath $swap) { throw "stale rollback swap path requires repair: $swap" }
    if (Test-Path -LiteralPath $InstallRoot) { Move-Item -LiteralPath $InstallRoot -Destination $swap }
    try {
        Move-Item -LiteralPath $PreviousInstall -Destination $InstallRoot
        if (Test-Path -LiteralPath $swap) { Move-Item -LiteralPath $swap -Destination $PreviousInstall }
    } catch {
        if (-not (Test-Path -LiteralPath $InstallRoot) -and (Test-Path -LiteralPath $swap)) {
            Move-Item -LiteralPath $swap -Destination $InstallRoot
        }
        throw
    }
    Write-Host 'SwitchTrade application rollback completed; the retained kernel was switched when the prior release used one.'
    exit
}

$audit = Test-Setup
if (-not $audit.Windows64Bit) { throw 'SwitchTrade requires 64-bit Windows.' }
if ($audit.WindowsBuild -lt 26100) { throw 'SwitchTrade private beta requires Windows 11 24H2 build 26100 or newer.' }
if ($audit.FreeSpaceGB -lt 8) { throw 'SwitchTrade requires at least 8 GB of free space for safe install and rollback.' }
if (-not $audit.VirtualizationReady) { throw 'Hardware virtualization/Hyper-V is not available to WSL 2.' }
if (-not $audit.WslInstalled) {
    if (-not $AcceptPrerequisiteChanges) {
        throw 'WSL 2 is required and may require a reboot. Rerun after accepting prerequisite changes.'
    }
    & dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
    if ($LASTEXITCODE -ne 0) { throw 'could not enable Windows Subsystem for Linux' }
    & dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
    if ($LASTEXITCODE -ne 0) { throw 'could not enable Virtual Machine Platform' }
    throw 'WSL prerequisites were enabled. Restart Windows, then run SwitchTrade Setup again.'
}
if (-not $audit.UsbipdInstalled) {
    if (-not $AcceptPrerequisiteChanges) {
        throw 'usbipd-win is required. Rerun after accepting prerequisite changes.'
    }
    if (-not (Test-Path -LiteralPath $UsbipdMsi) -or -not (Test-Path -LiteralPath $UsbipdManifest)) {
        throw 'the pinned usbipd-win installer is missing from this package'
    }
    $usbipdMetadata = Get-Content -Raw -LiteralPath $UsbipdManifest | ConvertFrom-Json
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath $UsbipdMsi).Hash.ToLowerInvariant() -ne
        ([string]$usbipdMetadata.sha256).ToLowerInvariant()) {
        throw 'usbipd-win installer checksum verification failed'
    }
    $msi = Start-Process msiexec.exe -ArgumentList @('/i', $UsbipdMsi, '/qn', '/norestart') -Wait -PassThru
    if ($msi.ExitCode -notin @(0, 3010)) { throw "usbipd-win installation failed with $($msi.ExitCode)" }
}
if ($audit.VmwareUsbArbitrator -eq 'Running') {
    if (-not $AcceptVmwareRelease) {
        throw 'VMware USB Arbitrator can reclaim the Wi-Fi adapter. Rerun Repair after accepting its temporary stop.'
    }
    Stop-Service VMUSBArbService -Force
}
if (-not $audit.PayloadPresent) { throw "application payload is missing: $Payload" }
$releaseManifest = Get-Content -Raw -LiteralPath (Join-Path $PackageRoot 'manifest.json') | ConvertFrom-Json
if (-not (Test-Path -LiteralPath $ReleaseConfig -PathType Leaf) -or
    (Get-FileHash -Algorithm SHA256 -LiteralPath $ReleaseConfig).Hash.ToLowerInvariant() -ne
    ([string]$releaseManifest.release_config_sha256).ToLowerInvariant()) {
    throw 'signed installation configuration checksum verification failed'
}

if (Test-Path -LiteralPath $DesktopExe -PathType Leaf) {
    if (-not (Test-Path -LiteralPath $DesktopHash -PathType Leaf)) {
        throw "desktop checksum is missing: $DesktopHash"
    }
    $expectedDesktopHash = ((Get-Content -LiteralPath $DesktopHash -TotalCount 1) -split '\s+')[0]
    $actualDesktopHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $DesktopExe).Hash.ToLowerInvariant()
    if ($expectedDesktopHash -notmatch '^[0-9a-fA-F]{64}$' -or
        $expectedDesktopHash.ToLowerInvariant() -ne $actualDesktopHash) {
        throw 'SwitchTrade desktop checksum verification failed.'
    }
}

if (-not $audit.DistroInstalled) {
    if (-not $audit.RootfsPresent) {
        throw "the SwitchTrade distro is absent and this package has no rootfs: $Rootfs"
    }
    if (-not (Test-Path -LiteralPath $RootfsHash -PathType Leaf)) {
        throw "rootfs checksum is missing: $RootfsHash"
    }
    $expectedHash = ((Get-Content -LiteralPath $RootfsHash -TotalCount 1) -split '\s+')[0]
    $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Rootfs).Hash.ToLowerInvariant()
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
    if (Test-Path -LiteralPath $KernelModules -PathType Leaf) {
        $kernelArguments.KernelModules = $KernelModules
    }
    $kernelState = Install-SwitchTradeKernel @kernelArguments
    $runningKernel = (& wsl.exe -d $Distro -- uname -r).Trim()
    if ($LASTEXITCODE -ne 0 -or $runningKernel -ne [string]$kernelState.kernel_release) {
        throw "SwitchTrade custom kernel verification failed: expected $($kernelState.kernel_release), got $runningKernel"
    }
}

$source = Convert-ToWslPath $Payload
$provision = Convert-ToWslPath (Join-Path $PackageRoot 'installer\provision-wsl.sh')
& wsl.exe -d $Distro -u root -- bash $provision --source $source
if ($LASTEXITCODE -ne 0) { throw 'SwitchTrade WSL provisioning failed.' }

$installParent = Split-Path -Parent $InstallRoot
New-Item -ItemType Directory -Force -Path $installParent | Out-Null
$stage = Join-Path $installParent ("SwitchTrade.stage." + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $stage | Out-Null
try {
    Copy-Item -LiteralPath (Join-Path $PackageRoot 'installer') -Destination $stage -Recurse
    Copy-Item -LiteralPath $Payload -Destination $stage -Recurse
    Copy-Item -LiteralPath (Join-Path $PackageRoot 'manifest.json') -Destination $stage
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
