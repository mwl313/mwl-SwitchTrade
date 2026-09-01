[CmdletBinding()]
param(
    [string]$ReleaseId = '',
    [string]$OutputDirectory = '',
    [string]$RuntimeWsl = '',
    [string]$KernelArtifact = '',
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
$versionFile = Join-Path $repo 'switchtrade\VERSION'
$applicationVersion = (Get-Content -Raw -LiteralPath $versionFile).Trim()
$versionMatch = [regex]::Match(
    $applicationVersion, '^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*)?$')
if (-not $versionMatch.Success) { throw 'switchtrade/VERSION is not a valid application version.' }
$ProductVersion = "$($versionMatch.Groups[1].Value).$($versionMatch.Groups[2].Value).$($versionMatch.Groups[3].Value)"
$parsedProductVersion = [version]$ProductVersion
if ($parsedProductVersion.Major -gt 255 -or $parsedProductVersion.Minor -gt 255 -or
    $parsedProductVersion.Build -gt 65535) {
    throw 'switchtrade/VERSION cannot be represented by MSI.'
}
$historicalVersion = [version]'0.0.0'
foreach ($commit in @(& git -C $repo log --format=%H --all -- switchtrade/VERSION)) {
    $candidate = (& git -C $repo show "${commit}:switchtrade/VERSION" 2>$null | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) { continue }
    $candidateMatch = [regex]::Match($candidate, '^(\d+)\.(\d+)\.(\d+)(?:-.+)?$')
    if ($candidateMatch.Success) {
        $candidateVersion = [version]"$($candidateMatch.Groups[1].Value).$($candidateMatch.Groups[2].Value).$($candidateMatch.Groups[3].Value)"
        if ($candidateVersion -gt $historicalVersion) { $historicalVersion = $candidateVersion }
    }
}
if ($parsedProductVersion -lt $historicalVersion) {
    throw "switchtrade/VERSION would downgrade the installer from $historicalVersion to $ProductVersion."
}
if (-not $ReleaseId) { $ReleaseId = 'beta-' + ((& git -C $repo rev-parse --short=12 HEAD).Trim()) }
if ($ReleaseId -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$') { throw 'Invalid release ID.' }
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
$kernelArtifactPath = if ($KernelArtifact) {
    [IO.Path]::GetFullPath($KernelArtifact)
} else {
    [IO.Path]::GetFullPath((Join-Path $repo 'artifacts\kernel-production'))
}

function Get-NormalizedFirmwareManifest([string]$Path) {
    $records = @()
    $seen = @{}
    foreach ($raw in Get-Content -LiteralPath $Path) {
        $line = $raw.Trim()
        if (-not $line) { continue }
        $match = [regex]::Match($line, '^(?<hash>[0-9A-Fa-f]{64})\s+\*?(?<path>firmware/[A-Za-z0-9._/-]+)$')
        if (-not $match.Success) { throw "Malformed firmware manifest record in ${Path}: $line" }
        $relative = $match.Groups['path'].Value.Replace('\', '/')
        if ($relative.Contains('/../') -or $relative.EndsWith('/..') -or $seen.ContainsKey($relative)) {
            throw "Unsafe or duplicate firmware manifest path in ${Path}: $relative"
        }
        $seen[$relative] = $true
        $records += ($match.Groups['hash'].Value.ToLowerInvariant() + '  ' + $relative)
    }
    if ($records.Count -eq 0) { throw "Firmware manifest is empty: $Path" }
    return @($records)
}
if (-not (Test-Path -LiteralPath $kernelArtifactPath -PathType Container)) {
    throw "The verified production kernel artifact is missing: $kernelArtifactPath"
}
$kernelVerification = & python (Join-Path $repo 'scripts\verify-kernel-artifact.py') $kernelArtifactPath
if ($LASTEXITCODE -ne 0) { throw 'The production kernel artifact failed verification.' }
$kernelMetadata = Get-Content -Raw -LiteralPath (Join-Path $kernelArtifactPath 'manifest.json') |
    ConvertFrom-Json
$kernelSource = Join-Path $kernelArtifactPath 'bzImage-wsl-st'
$moduleCandidates = @(Get-ChildItem -LiteralPath $kernelArtifactPath -Filter 'modules-*.tar.gz' -File)
if ($moduleCandidates.Count -ne 1) { throw 'The production kernel artifact must contain one module archive.' }
$modulesSource = $moduleCandidates[0].FullName
$firmwareManifestSource = Join-Path $PSScriptRoot 'runtime\firmware-manifest.sha256'
$kernelFirmwareManifest = Join-Path $kernelArtifactPath 'firmware-manifest.sha256'
$sourceFirmwareContract = @(Get-NormalizedFirmwareManifest $firmwareManifestSource)
$kernelFirmwareContract = @(Get-NormalizedFirmwareManifest $kernelFirmwareManifest)
if ($sourceFirmwareContract.Count -ne $kernelFirmwareContract.Count -or
    (Compare-Object -ReferenceObject $sourceFirmwareContract -DifferenceObject $kernelFirmwareContract)) {
    throw 'The production kernel artifact firmware contract differs from this release source.'
}
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
        -ReleaseId $ReleaseId -ContentId $contentId -Modules $modulesSource `
        -FirmwareManifest $firmwareManifestSource
}
$runtimeMetadata = Get-Content -Raw -LiteralPath $runtimeBuild | ConvertFrom-Json
if ([string]$runtimeMetadata.release_id -ne $ReleaseId -or
    [string]$runtimeMetadata.content_id -ne $contentId -or
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
$kernelTarget = Join-Path $kernelDirectory 'kernel'
$modulesTarget = Join-Path $kernelDirectory 'modules.tar.gz'
$driverProfiles = @()
$driverModules = @()
foreach ($line in Get-Content -LiteralPath (Join-Path $repo 'config\wsl-radio-hardware.tsv')) {
    if (-not $line -or $line.StartsWith('#')) { continue }
    $columns = @($line -split "`t")
    if ($columns.Count -ne 13 -or $columns[6] -ne 'yes') {
        throw 'The production hardware matrix contains a malformed or non-automatic profile.'
    }
    $driverProfiles += $columns[0]
    $driverModules += @($columns[3] -split ',')
}
$driverProfiles = @($driverProfiles | Sort-Object -Unique)
$driverModules = @($driverModules | Sort-Object -Unique)
if (-not $driverProfiles -or -not $driverModules) { throw 'The production hardware matrix is empty.' }
$moduleEntries = @(& tar -tzf $modulesSource)
if ($LASTEXITCODE -ne 0) { throw 'The kernel module archive cannot be inspected.' }
foreach ($driver in $driverModules) {
    $moduleName = ($driver.Replace('-', '_') + '.ko')
    $modulePattern = [regex]::Escape($moduleName) + '(?:\.(?:xz|zst|gz))?$'
    if (-not @($moduleEntries | Where-Object { $_ -match $modulePattern })) {
        throw "The kernel module archive does not support matrix driver: $driver"
    }
}
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
    version = $applicationVersion
    architecture = 'x64'
    minimum_windows_build = 19045
    minimum_wsl_version = '2.4.4'
    control_contract = 'local-app-readiness.v2'
    relay_url = [string]$relay.relay_url
    runtime_content_id = $contentId
    kernel = [ordered]@{
        release = [string]$kernelMetadata.kernel_release
        primary_driver = [string]$kernelMetadata.primary_driver
        driver_profiles = $driverProfiles
        driver_modules = $driverModules
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
    '-t:Rebuild',
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
    '-t:Rebuild',
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
$sourceSha = ((& git -C $repo rev-parse HEAD) | Out-String).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $ReleaseId -ne "beta-$($sourceSha.Substring(0, 12))") {
    throw 'Release ID must identify the exact source commit before qualification packaging.'
}
$qualificationResult = & (Join-Path $PSScriptRoot 'Build-M7QualificationKit.ps1') `
    -OutputDirectory (Join-Path $output 'qualification') -ReleaseId $ReleaseId -SourceSha $sourceSha
$result = [ordered]@{
    schema = 1
    release_id = $ReleaseId
    version = $applicationVersion
    product_version = $ProductVersion
    release_tag = "v$applicationVersion"
    setup = $setup
    size = (Get-Item -LiteralPath $setup).Length
    sha256 = (Get-FileHash -LiteralPath $setup -Algorithm SHA256).Hash.ToLowerInvariant()
    signed = [bool]$CertificateThumbprint
    qualification = [ordered]@{
        contract_version = [string]$qualificationResult.contract_version
        source_sha = [string]$qualificationResult.source_sha
        release_id = [string]$qualificationResult.release_id
        archive = [IO.Path]::GetRelativePath($output, [string]$qualificationResult.archive).Replace('\', '/')
        size = [long]$qualificationResult.size
        sha256 = [string]$qualificationResult.sha256
        manifest_sha256 = [string]$qualificationResult.manifest_sha256
    }
}
$result | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $output 'build-result.json') -Encoding utf8
$result | ConvertTo-Json
