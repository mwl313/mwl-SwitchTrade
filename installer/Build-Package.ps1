[CmdletBinding()]
param(
    [string]$OutputRoot = '',
    [string]$Rootfs = '',
    [string]$DesktopExe = '',
    [string]$Kernel = '',
    [string]$KernelModules = '',
    [string]$KernelManifest = '',
    [string]$KernelManifestSignature = '',
    [string]$UsbipdMsi = '',
    [string]$UsbipdVersion = '5.3.0',
    [string]$RelayUrl = 'http://127.0.0.1:8788',
    [string]$Notices = '',
    [string]$SigningCertificateThumbprint = '',
    [string]$TimestampUrl = 'http://timestamp.digicert.com',
    [switch]$Release,
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
. (Join-Path $PSScriptRoot 'PackageIntegrity.ps1')

if ($Release) {
    $missing = @()
    foreach ($item in @{
        Rootfs = $Rootfs; DesktopExe = $DesktopExe; Kernel = $Kernel
        KernelModules = $KernelModules; KernelManifest = $KernelManifest
        KernelManifestSignature = $KernelManifestSignature; UsbipdMsi = $UsbipdMsi
        Notices = $Notices; SigningCertificateThumbprint = $SigningCertificateThumbprint
    }.GetEnumerator()) {
        if (-not $item.Value) { $missing += $item.Key }
    }
    if ($missing) { throw "release package inputs are missing: $($missing -join ', ')" }
}

if (Test-Path -LiteralPath $Stage) { throw "package stage already exists: $Stage" }
New-Item -ItemType Directory -Force -Path (Join-Path $Stage 'payload\app') | Out-Null

$app = Join-Path $Stage 'payload\app'
$sourceArchive = Join-Path $Stage 'source.tar'
$runtimePaths = @('bridge', 'config', 'relay', 'scripts', 'switchtrade', 'tests',
    'tools/payload_decoder.py', 'tools/pk3-tool.py', 'tools/species_map.py',
    'tools/stats.py', 'tools/basestats.py', 'tools/charmap_jp.py',
    'pytest.ini', 'requirements.txt', 'test-requirements.txt', 'README.md')
& git -C $Repo archive --format=tar --output=$sourceArchive HEAD -- @runtimePaths
if ($LASTEXITCODE -ne 0) { throw 'could not archive tracked runtime source' }
& tar -xf $sourceArchive -C $app
if ($LASTEXITCODE -ne 0) { throw 'could not extract tracked runtime source' }
Remove-Item -LiteralPath $sourceArchive
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
    if ($KernelManifestSignature) {
        $resolvedKernelSignature = (Resolve-Path -LiteralPath $KernelManifestSignature).Path
        Test-DetachedCmsSignature -ContentPath $resolvedManifest -SignaturePath $resolvedKernelSignature | Out-Null
        Copy-Item -LiteralPath $resolvedKernelSignature -Destination (Join-Path $kernelPayload 'manifest.json.p7s')
    } elseif ($Release) {
        throw 'the release kernel manifest requires a trusted detached signature'
    }
    if ($KernelModules) {
        $resolvedModules = (Resolve-Path -LiteralPath $KernelModules).Path
        if (-not $metadata.modules_sha256 -or
            (Get-FileHash -Algorithm SHA256 -LiteralPath $resolvedModules).Hash.ToLowerInvariant() -ne
            ([string]$metadata.modules_sha256).ToLowerInvariant()) {
            throw 'kernel modules artifact does not match its release manifest'
        }
        $extension = [IO.Path]::GetExtension($resolvedModules).ToLowerInvariant()
        $moduleName = if ($extension -in @('.vhd', '.vhdx')) { "modules$extension" } else { 'modules.tar.gz' }
        if ($moduleName -eq 'modules.tar.gz' -and $resolvedModules -notmatch '(?i)(\.tar\.gz|\.tgz)$') {
            throw 'kernel modules must be a WSL modules VHD/VHDX or a gzip-compressed tar archive'
        }
        Copy-Item -LiteralPath $resolvedModules -Destination (Join-Path $kernelPayload $moduleName)
    }
}

if ($Notices) {
    $resolvedNotices = (Resolve-Path -LiteralPath $Notices).Path
    if (-not (Test-Path -LiteralPath $resolvedNotices -PathType Leaf)) { throw 'license notices must be a file' }
    Copy-Item -LiteralPath $resolvedNotices -Destination (Join-Path $Stage 'THIRD-PARTY-NOTICES.txt')
} elseif ($Release) {
    throw 'release packages require approved license/legal notices'
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
if ($Release -and ($relay.Scheme -ne 'https' -or $relay.IsLoopback)) {
    throw 'release packages require a reachable non-loopback HTTPS relay URL'
}
@{
    schema = 1
    relay_url = $RelayUrl.TrimEnd('/')
    environment = if ($relay.IsLoopback) { 'internal-test' } else { 'private-beta' }
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Stage 'payload\release-config.json') -Encoding UTF8

$setupProject = Join-Path $Repo 'installer\bootstrap\SwitchTrade.Setup.csproj'
& dotnet publish $setupProject -c Release -r win-x64 --self-contained true `
    -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true `
    -p:EnableCompressionInSingleFile=true -p:DebugType=None -p:DebugSymbols=false `
    -o (Join-Path $Stage 'setup-build')
if ($LASTEXITCODE -ne 0) { throw 'native setup bootstrapper build failed' }
Move-Item -LiteralPath (Join-Path $Stage 'setup-build\SwitchTradeSetup.exe') `
    -Destination (Join-Path $Stage 'SwitchTradeSetup.exe')
Remove-Item -LiteralPath (Join-Path $Stage 'setup-build') -Recurse -Force

$certificate = $null
if ($SigningCertificateThumbprint) {
    $thumbprint = $SigningCertificateThumbprint.Replace(' ', '').ToUpperInvariant()
    $certificate = Get-ChildItem Cert:\CurrentUser\My, Cert:\LocalMachine\My -CodeSigningCert |
        Where-Object { $_.Thumbprint -eq $thumbprint } | Select-Object -First 1
    if (-not $certificate -or -not $certificate.HasPrivateKey) {
        throw 'the requested code-signing certificate with private key was not found'
    }
    $signTargets = @((Join-Path $Stage 'SwitchTradeSetup.exe'))
    if (Test-Path -LiteralPath (Join-Path $Stage 'windows\SwitchTrade.exe')) {
        $signTargets += (Join-Path $Stage 'windows\SwitchTrade.exe')
    }
    foreach ($target in $signTargets) {
        $signature = Set-AuthenticodeSignature -LiteralPath $target -Certificate $certificate `
            -HashAlgorithm SHA256 -TimestampServer $TimestampUrl
        if ($signature.Status -ne 'Valid') { throw "Authenticode signing failed for ${target}: $($signature.StatusMessage)" }
    }
}
if ($Release -and -not $certificate) { throw 'release packages must be Authenticode signed' }

if (Test-Path -LiteralPath (Join-Path $Stage 'windows\SwitchTrade.exe')) {
    $packagedDesktop = Join-Path $Stage 'windows\SwitchTrade.exe'
    $desktopHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $packagedDesktop).Hash.ToLowerInvariant()
    "$desktopHash  SwitchTrade.exe" |
        Set-Content -LiteralPath (Join-Path $Stage 'windows\SwitchTrade.exe.sha256') -Encoding Ascii
}

$manifestPath = Join-Path $Stage 'manifest.json'
$manifestArgs = @(
    (Join-Path $Repo 'scripts\write-release-manifest.py'), '--output', $manifestPath,
    '--package-root', $Stage, '--release-id', "beta-$Version"
)
if ($Release) { $manifestArgs += '--signature-required' }
& python @manifestArgs
if ($LASTEXITCODE -ne 0) { throw 'release manifest generation failed' }
if ($certificate) {
    Add-Type -AssemblyName System.Security
    $content = [Security.Cryptography.Pkcs.ContentInfo]::new([IO.File]::ReadAllBytes($manifestPath))
    $signed = [Security.Cryptography.Pkcs.SignedCms]::new($content, $true)
    $signer = [Security.Cryptography.Pkcs.CmsSigner]::new($certificate)
    $signer.IncludeOption = [Security.Cryptography.X509Certificates.X509IncludeOption]::EndCertOnly
    $signed.ComputeSignature($signer)
    $signaturePath = Join-Path $Stage 'manifest.json.p7s'
    [IO.File]::WriteAllBytes($signaturePath, $signed.Encode())
    Test-DetachedCmsSignature -ContentPath $manifestPath -SignaturePath $signaturePath | Out-Null
}
Test-SwitchTradePackage -PackageRoot $Stage -AllowUnsignedPackage:(!$Release) | Out-Null

if (-not $NoArchive) {
    $archive = "$Stage.zip"
    Compress-Archive -LiteralPath $Stage -DestinationPath $archive -Force
    Write-Host $archive
} else {
    Write-Host $Stage
}
