[CmdletBinding()]
param(
    [string]$OutputRoot = '',
    [string]$Rootfs = '',
    [string]$DesktopExe = '',
    [string]$Kernel = '',
    [string]$KernelModules = '',
    [string]$KernelManifest = '',
    [string]$UsbipdMsi = '',
    [string]$UsbipdVersion = '5.3.0',
    [string]$RelayUrl = 'http://127.0.0.1:8788',
    [switch]$NoArchive
)

$ErrorActionPreference = 'Stop'
$Repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not $OutputRoot) { $OutputRoot = Join-Path $Repo 'artifacts' }
$Version = (& git -C $Repo rev-parse --short HEAD).Trim()
if ($LASTEXITCODE -ne 0) { throw 'cannot determine repository revision' }
$dirty = & git -C $Repo status --porcelain
if ($dirty) { throw 'refusing to package a dirty worktree; commit the beta source first' }
$Stage = Join-Path $OutputRoot "SwitchTrade-beta-$Version"

$webDist = Join-Path $Repo 'apps\web\dist-desktop'
if (-not (Test-Path -LiteralPath (Join-Path $webDist 'index.html'))) {
    throw 'web/debug frontend is not built; run pnpm build:desktop in apps/web first'
}
if (Test-Path -LiteralPath $Stage) { throw "package stage already exists: $Stage" }
New-Item -ItemType Directory -Force -Path (Join-Path $Stage 'payload\app') | Out-Null

$app = Join-Path $Stage 'payload\app'
$sourceArchive = Join-Path $Stage 'source.tar'
$runtimePaths = @('apps/web', 'bridge', 'config', 'relay', 'scripts', 'switchtrade', 'tests',
    'tools/payload_decoder.py', 'tools/pk3-tool.py', 'tools/species_map.py',
    'tools/stats.py', 'tools/basestats.py', 'tools/charmap_jp.py',
    'pytest.ini', 'requirements.txt', 'test-requirements.txt', 'README.md')
& git -C $Repo archive --format=tar --output=$sourceArchive HEAD -- @runtimePaths
if ($LASTEXITCODE -ne 0) { throw 'could not archive tracked runtime source' }
& tar -xf $sourceArchive -C $app
if ($LASTEXITCODE -ne 0) { throw 'could not extract tracked runtime source' }
Remove-Item -LiteralPath $sourceArchive
Copy-Item -LiteralPath $webDist -Destination (Join-Path $app 'apps\web\dist-desktop') -Recurse -Force
$installerArchive = Join-Path $Stage 'installer.tar'
& git -C $Repo archive --format=tar --output=$installerArchive HEAD -- installer
if ($LASTEXITCODE -ne 0) { throw 'could not archive installer source' }
& tar -xf $installerArchive -C $Stage
if ($LASTEXITCODE -ne 0) { throw 'could not extract installer source' }
Remove-Item -LiteralPath $installerArchive

if ($Rootfs) {
    $resolvedRootfs = (Resolve-Path -LiteralPath $Rootfs).Path
    $packagedRootfs = Join-Path $Stage 'payload\switchtrade-rootfs.tar.gz'
    Copy-Item -LiteralPath $resolvedRootfs -Destination $packagedRootfs
    $rootfsHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $packagedRootfs).Hash.ToLowerInvariant()
    "$rootfsHash  switchtrade-rootfs.tar.gz" |
        Set-Content -LiteralPath (Join-Path $Stage 'payload\switchtrade-rootfs.sha256') -Encoding Ascii
}

if ($DesktopExe) {
    $resolvedDesktop = (Resolve-Path -LiteralPath $DesktopExe).Path
    if ([IO.Path]::GetExtension($resolvedDesktop) -ne '.exe') { throw 'desktop artifact must be an .exe' }
    $windows = Join-Path $Stage 'windows'
    New-Item -ItemType Directory -Force -Path $windows | Out-Null
    $packagedDesktop = Join-Path $windows 'SwitchTrade.exe'
    Copy-Item -LiteralPath $resolvedDesktop -Destination $packagedDesktop
    $desktopHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $packagedDesktop).Hash.ToLowerInvariant()
    "$desktopHash  SwitchTrade.exe" |
        Set-Content -LiteralPath (Join-Path $windows 'SwitchTrade.exe.sha256') -Encoding Ascii
}

if ($Kernel -or $KernelModules -or $KernelManifest) {
    if (-not $Kernel -or -not $KernelManifest) {
        throw '-Kernel and -KernelManifest must be supplied together'
    }
    $kernelPayload = Join-Path $Stage 'payload\kernel'
    New-Item -ItemType Directory -Force -Path $kernelPayload | Out-Null
    $resolvedManifest = (Resolve-Path -LiteralPath $KernelManifest).Path
    $metadata = Get-Content -Raw -LiteralPath $resolvedManifest | ConvertFrom-Json
    $resolvedKernel = (Resolve-Path -LiteralPath $Kernel).Path
    if (-not $metadata.kernel_release -or -not $metadata.kernel_sha256) {
        throw 'kernel manifest is missing required release/checksum fields'
    }
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath $resolvedKernel).Hash.ToLowerInvariant() -ne
        ([string]$metadata.kernel_sha256).ToLowerInvariant()) {
        throw 'kernel artifact does not match its release manifest'
    }
    Copy-Item -LiteralPath $resolvedKernel -Destination (Join-Path $kernelPayload 'kernel')
    Copy-Item -LiteralPath $resolvedManifest -Destination (Join-Path $kernelPayload 'manifest.json')
    if ($KernelModules) {
        $resolvedModules = (Resolve-Path -LiteralPath $KernelModules).Path
        if (-not $metadata.modules_sha256 -or
            (Get-FileHash -Algorithm SHA256 -LiteralPath $resolvedModules).Hash.ToLowerInvariant() -ne
            ([string]$metadata.modules_sha256).ToLowerInvariant()) {
            throw 'kernel modules artifact does not match its release manifest'
        }
        Copy-Item -LiteralPath $resolvedModules -Destination (Join-Path $kernelPayload 'modules')
    }
}

if ($UsbipdMsi) {
    $prerequisiteRoot = Join-Path $Stage 'payload\prerequisites'
    New-Item -ItemType Directory -Force -Path $prerequisiteRoot | Out-Null
    $resolvedUsbipd = (Resolve-Path -LiteralPath $UsbipdMsi).Path
    $packagedUsbipd = Join-Path $prerequisiteRoot 'usbipd-win.msi'
    Copy-Item -LiteralPath $resolvedUsbipd -Destination $packagedUsbipd
    @{
        version = $UsbipdVersion
        sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $packagedUsbipd).Hash.ToLowerInvariant()
    } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $prerequisiteRoot 'usbipd-win.json') -Encoding UTF8
}

$relay = [Uri]$RelayUrl
if (-not $relay.IsAbsoluteUri -or $relay.Scheme -notin @('http', 'https')) {
    throw 'relay URL must be an absolute HTTP(S) URL'
}
@{
    schema = 1
    relay_url = $RelayUrl.TrimEnd('/')
    environment = if ($relay.IsLoopback) { 'internal-test' } else { 'private-beta' }
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Stage 'payload\release-config.json') -Encoding UTF8

$manifestArgs = @(
    (Join-Path $Repo 'scripts\write-release-manifest.py'), '--output', (Join-Path $Stage 'manifest.json')
)
& python @manifestArgs
if ($LASTEXITCODE -ne 0) { throw 'release manifest generation failed' }
$manifestPath = Join-Path $Stage 'manifest.json'
$manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
$manifest | Add-Member -NotePropertyName release_config_sha256 -NotePropertyValue `
    ((Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $Stage 'payload\release-config.json')).Hash.ToLowerInvariant())
$manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding UTF8

$setupProject = Join-Path $Repo 'installer\bootstrap\SwitchTrade.Setup.csproj'
& dotnet publish $setupProject -c Release -r win-x64 --self-contained true `
    -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true `
    -p:EnableCompressionInSingleFile=true -p:DebugType=None -p:DebugSymbols=false `
    -o (Join-Path $Stage 'setup-build')
if ($LASTEXITCODE -ne 0) { throw 'native setup bootstrapper build failed' }
Move-Item -LiteralPath (Join-Path $Stage 'setup-build\SwitchTradeSetup.exe') `
    -Destination (Join-Path $Stage 'SwitchTradeSetup.exe')
Remove-Item -LiteralPath (Join-Path $Stage 'setup-build') -Recurse -Force

if (-not $NoArchive) {
    $archive = "$Stage.zip"
    Compress-Archive -LiteralPath $Stage -DestinationPath $archive -Force
    Write-Host $archive
} else {
    Write-Host $Stage
}
