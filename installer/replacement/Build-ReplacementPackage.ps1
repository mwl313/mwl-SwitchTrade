[CmdletBinding()]
param(
    [string]$ReleaseId = '',
    [string]$ProductVersion = '0.2.0',
    [string]$OutputDirectory = '',
    [string]$RuntimeWsl = '',
    [string]$CertificateThumbprint = '',
    [switch]$AllowDirtyForDevelopment
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
if (-not $AllowDirtyForDevelopment) {
    & git -C $repo diff --quiet
    $worktreeDirty = $LASTEXITCODE -ne 0
    & git -C $repo diff --cached --quiet
    $indexDirty = $LASTEXITCODE -ne 0
    if ($worktreeDirty -or $indexDirty) {
        throw 'Release builds require a clean tracked worktree. Commit changes or use -AllowDirtyForDevelopment for an internal build.'
    }
}
if (-not $ReleaseId) { $ReleaseId = 'beta-' + ((& git -C $repo rev-parse --short=12 HEAD).Trim()) }
if ($ReleaseId -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$') { throw 'Invalid release ID.' }
if ($ProductVersion -notmatch '^\d+\.\d+\.\d+$') { throw 'ProductVersion must be an MSI-compatible three-part version.' }
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $repo "artifacts\replacement\release-$ReleaseId" }
$output = [IO.Path]::GetFullPath($OutputDirectory)
$artifacts = [IO.Path]::GetFullPath((Join-Path $repo 'artifacts')).TrimEnd('\') + '\'
if (-not $output.StartsWith($artifacts, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Replacement release output must be inside the repository artifacts directory.'
}
if (Test-Path -LiteralPath $output) {
    if (@(Get-ChildItem -LiteralPath $output -Force).Count -gt 0) {
        throw "Replacement release output is not empty: $output"
    }
}
New-Item -ItemType Directory -Force -Path $output | Out-Null

function Invoke-Checked([string]$FileName, [string[]]$Arguments) {
    $start = [Diagnostics.ProcessStartInfo]::new()
    $start.FileName = $FileName
    $start.UseShellExecute = $false
    foreach ($argument in $Arguments) { [void]$start.ArgumentList.Add($argument) }
    $process = [Diagnostics.Process]::Start($start)
    $process.WaitForExit()
    if ($process.ExitCode -ne 0) { throw "$FileName failed with exit code $($process.ExitCode)." }
}

function Get-RuntimeContentId {
    $roots = @('switchtrade', 'bridge', 'tools', 'config', 'requirements.txt',
        'scripts/run-beta-endpoint.sh', 'scripts/wsl-radio-prepare.sh',
        'scripts/radio-health-gate.sh',
        'payload/release-config.json', 'installer/replacement/runtime/build-appliance.sh',
        'installer/replacement/runtime/base-rootfs.json',
        'installer/replacement/runtime/firmware-manifest.sha256',
        'installer/replacement/runtime/wheelhouse-manifest.sha256')
    $files = @(& git -C $repo ls-files -- $roots) | Where-Object { $_ }
    $hash = [Security.Cryptography.IncrementalHash]::CreateHash(
        [Security.Cryptography.HashAlgorithmName]::SHA256)
    try {
        foreach ($relative in $files | Sort-Object) {
            $name = [Text.Encoding]::UTF8.GetBytes(($relative.Replace('\', '/') + "`0"))
            $hash.AppendData($name)
            $hash.AppendData([IO.File]::ReadAllBytes((Join-Path $repo $relative)))
        }
        return [Convert]::ToHexString($hash.GetHashAndReset()).ToLowerInvariant()
    } finally { $hash.Dispose() }
}

$contentId = Get-RuntimeContentId
$prerequisites = & (Join-Path $PSScriptRoot 'Fetch-PinnedPrerequisites.ps1')
$runtimeName = "SwitchTrade-$ReleaseId.wsl"
$runtimeTarget = Join-Path $output $runtimeName
$runtimeBuild = "$runtimeTarget.build.json"
if ($RuntimeWsl) {
    $runtimeSource = [IO.Path]::GetFullPath($RuntimeWsl)
    if (-not (Test-Path -LiteralPath "$runtimeSource.build.json" -PathType Leaf)) {
        throw 'An explicitly supplied runtime must include its .build.json metadata.'
    }
    Copy-Item -LiteralPath $runtimeSource -Destination $runtimeTarget -Force
    Copy-Item -LiteralPath "$runtimeSource.build.json" -Destination $runtimeBuild -Force
} elseif (-not (Test-Path -LiteralPath $runtimeTarget)) {
    & (Join-Path $PSScriptRoot 'Build-ImmutableWsl.ps1') -Output $runtimeTarget `
        -ReleaseId $ReleaseId -ContentId $contentId
}
$runtimeMetadata = Get-Content -Raw -LiteralPath $runtimeBuild | ConvertFrom-Json
if ([string]$runtimeMetadata.release_id -ne $ReleaseId -or
    [long]$runtimeMetadata.size -ne (Get-Item -LiteralPath $runtimeTarget).Length -or
    [string]$runtimeMetadata.sha256 -ne
        (Get-FileHash -LiteralPath $runtimeTarget -Algorithm SHA256).Hash.ToLowerInvariant()) {
    throw 'The immutable runtime metadata does not match the requested release or archive.'
}
$contentId = [string]$runtimeMetadata.content_id

$publish = Join-Path $output 'publish'
$desktop = Join-Path $publish 'desktop'
$provisioner = Join-Path $publish 'provisioner'
$prerequisite = Join-Path $publish 'prerequisite'
Invoke-Checked 'dotnet' @('publish', (Join-Path $repo 'apps\desktop\SwitchTrade.Desktop\SwitchTrade.Desktop.csproj'),
    '-c', 'Release', '-r', 'win-x64', '--self-contained', 'true',
    '-p:PublishSingleFile=true', '-p:IncludeNativeLibrariesForSelfExtract=true',
    '-p:EnableCompressionInSingleFile=true', '-p:DebugType=None', '-p:DebugSymbols=false', '-o', $desktop)
Invoke-Checked 'dotnet' @('publish', (Join-Path $PSScriptRoot 'SwitchTrade.Provisioner\SwitchTrade.Provisioner.csproj'),
    '-c', 'Release', '-o', $provisioner)
Invoke-Checked 'dotnet' @('publish', (Join-Path $PSScriptRoot 'SwitchTrade.Prerequisites\SwitchTrade.Prerequisites.csproj'),
    '-c', 'Release', '-o', $prerequisite)

$desktopExe = Join-Path $desktop 'SwitchTrade.exe'
$provisionerExe = Join-Path $provisioner 'SwitchTradeProvisioner.exe'
$prerequisiteExe = Join-Path $prerequisite 'SwitchTradePrerequisites.exe'
Invoke-Checked $desktopExe @('--self-test')
Invoke-Checked $prerequisiteExe @('--self-test')

$package = Join-Path $output 'package'
$payload = Join-Path $package 'payload'
$kernelDirectory = Join-Path $payload 'kernel'
New-Item -ItemType Directory -Force -Path $kernelDirectory | Out-Null
$packagedRuntime = Join-Path $payload $runtimeName
Copy-Item -LiteralPath $runtimeTarget -Destination $packagedRuntime -Force
$retained = Join-Path $repo 'artifacts\final-package-27d17b1\SwitchTrade-unsigned-private-beta-27d17b1'
$kernelSource = Join-Path $retained 'payload\kernel\kernel'
$kernelMetadata = Get-Content -Raw -LiteralPath (Join-Path $retained 'payload\kernel\manifest.json') | ConvertFrom-Json
$kernelTarget = Join-Path $kernelDirectory 'kernel'
$modulesSource = Join-Path $retained 'payload\kernel\modules.tar.gz'
$modulesTarget = Join-Path $kernelDirectory 'modules.tar.gz'
$firmwareManifestSource = Join-Path $PSScriptRoot 'runtime\firmware-manifest.sha256'
$firmwareManifestTarget = Join-Path $kernelDirectory 'firmware-manifest.sha256'
Copy-Item -LiteralPath $kernelSource -Destination $kernelTarget -Force
Copy-Item -LiteralPath $modulesSource -Destination $modulesTarget -Force
Copy-Item -LiteralPath $firmwareManifestSource -Destination $firmwareManifestTarget -Force
$relay = Get-Content -Raw -LiteralPath (Join-Path $repo 'payload\release-config.json') | ConvertFrom-Json

function Payload([string]$Root, [string]$Path) {
    $full = Join-Path $Root $Path
    $item = Get-Item -LiteralPath $full
    return [ordered]@{
        path = $Path.Replace('\', '/')
        size = $item.Length
        sha256 = (Get-FileHash -LiteralPath $full -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}
$manifest = [ordered]@{
    schema = 1
    release_id = $ReleaseId
    version = $ProductVersion
    architecture = 'x64'
    minimum_windows_build = 19045
    minimum_wsl_version = '2.4.4'
    control_contract = 'app-readiness.v1'
    relay_url = [string]$relay.relay_url
    runtime_content_id = $contentId
    kernel = [ordered]@{
        release = [string]$kernelMetadata.kernel_release
        primary_driver = [string]$kernelMetadata.primary_driver
        driver_profiles = @('0bda:818b')
    }
    payloads = [ordered]@{
        runtime = Payload $package ("payload\$runtimeName")
        kernel = Payload $package 'payload\kernel\kernel'
        kernel_modules = Payload $package 'payload\kernel\modules.tar.gz'
        firmware_manifest = Payload $package 'payload\kernel\firmware-manifest.sha256'
    }
}
$manifestPath = Join-Path $package 'release-manifest.json'
$manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding utf8

$wixOutput = Join-Path $output 'wix'
$desktopProject = Join-Path $PSScriptRoot 'wix\Desktop\SwitchTrade.Desktop.wixproj'
Invoke-Checked 'dotnet' @('build', $desktopProject, '-c', 'Release',
    "-p:ProductVersion=$ProductVersion", "-p:ReleaseId=$ReleaseId",
    "-p:DesktopExe=$desktopExe", "-p:ProvisionerExe=$provisionerExe",
    "-p:ReleaseManifest=$manifestPath", '-o', $wixOutput)
$desktopMsi = Join-Path $wixOutput 'SwitchTrade.Desktop.msi'

$definition = Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot 'prerequisites.json') | ConvertFrom-Json
$wslMsi = Join-Path $prerequisites ([string]$definition.packages.wsl.file)
$usbipdMsi = Join-Path $prerequisites ([string]$definition.packages.usbipd.file)
$bundleOutput = Join-Path $output 'bundle'
$bundleProject = Join-Path $PSScriptRoot 'wix\Bundle\SwitchTrade.Bundle.wixproj'
Invoke-Checked 'dotnet' @('build', $bundleProject, '-c', 'Release',
    "-p:ProductVersion=$ProductVersion", "-p:ReleaseId=$ReleaseId",
    "-p:IconFile=$(Join-Path $repo 'assets\branding\SwitchTrade.ico')",
    "-p:PrerequisiteExe=$prerequisiteExe", "-p:WslMsi=$wslMsi", "-p:UsbipdMsi=$usbipdMsi",
    "-p:DesktopMsi=$desktopMsi", "-p:ProvisionerExe=$provisionerExe",
    "-p:ReleaseManifest=$manifestPath", "-p:RuntimeWsl=$packagedRuntime",
    "-p:RuntimeFileName=$runtimeName", "-p:KernelFile=$kernelTarget",
    "-p:ModulesFile=$modulesTarget", "-p:FirmwareManifest=$firmwareManifestTarget", '-o', $bundleOutput)

$setup = Join-Path $output 'SwitchTradeSetup.exe'
Copy-Item -LiteralPath (Join-Path $bundleOutput 'SwitchTrade.Bundle.exe') -Destination $setup -Force
if ($CertificateThumbprint) {
    $signTool = (Get-Command signtool.exe -ErrorAction Stop).Source
    Invoke-Checked $signTool @('sign', '/sha1', $CertificateThumbprint, '/fd', 'SHA256',
        '/tr', 'http://timestamp.digicert.com', '/td', 'SHA256', $setup)
}
$result = [ordered]@{
    schema = 1
    release_id = $ReleaseId
    version = $ProductVersion
    setup = $setup
    size = (Get-Item -LiteralPath $setup).Length
    sha256 = (Get-FileHash -LiteralPath $setup -Algorithm SHA256).Hash.ToLowerInvariant()
    signed = [bool]$CertificateThumbprint
}
$result | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $output 'build-result.json') -Encoding utf8
$result | ConvertTo-Json
