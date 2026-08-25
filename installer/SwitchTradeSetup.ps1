[CmdletBinding(SupportsShouldProcess)]
param(
    [ValidateSet('Audit', 'Install', 'Repair', 'Uninstall')]
    [string]$Action = 'Audit',
    [string]$Distro = 'SwitchTrade',
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'Programs\SwitchTrade'),
    [string]$DistroRoot = (Join-Path $env:LOCALAPPDATA 'SwitchTrade\wsl'),
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
    }
}

if ($Action -eq 'Audit') {
    Test-Setup | Format-List
    exit
}

if ($Action -eq 'Uninstall') {
    if (Test-Path -LiteralPath $InstallRoot) {
        if ($PSCmdlet.ShouldProcess($InstallRoot, 'Remove SwitchTrade application files')) {
            Remove-Item -LiteralPath $InstallRoot -Recurse -Force
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

$audit = Test-Setup
if (-not $audit.Windows64Bit) { throw 'SwitchTrade requires 64-bit Windows.' }
if (-not $audit.WslInstalled) { throw 'WSL is not installed. Run wsl --install, reboot if prompted, then rerun setup.' }
if (-not $audit.UsbipdInstalled) { throw 'usbipd-win is required. Install it, then rerun setup.' }
if (-not $audit.PayloadPresent) { throw "application payload is missing: $Payload" }

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

New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
Copy-Item -LiteralPath (Join-Path $PackageRoot 'installer') -Destination $InstallRoot -Recurse -Force
Copy-Item -LiteralPath $Payload -Destination $InstallRoot -Recurse -Force
Copy-Item -LiteralPath (Join-Path $PackageRoot 'manifest.json') -Destination $InstallRoot -Force
if (Test-Path -LiteralPath $DesktopExe -PathType Leaf) {
    Copy-Item -LiteralPath $DesktopExe -Destination (Join-Path $InstallRoot 'SwitchTrade.exe') -Force
}
@{ relay_url = 'http://127.0.0.1:8788' } | ConvertTo-Json |
    Set-Content -LiteralPath (Join-Path $InstallRoot 'config.json') -Encoding UTF8

$source = Convert-ToWslPath $Payload
$provision = Convert-ToWslPath (Join-Path $PackageRoot 'installer\provision-wsl.sh')
& wsl.exe -d $Distro -u root -- bash $provision --source $source
if ($LASTEXITCODE -ne 0) { throw 'SwitchTrade WSL provisioning failed.' }

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

Write-Host "SwitchTrade $Action completed. The custom/global WSL kernel configuration was not changed."
