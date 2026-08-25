[CmdletBinding()]
param(
    [string]$OutputRoot = '',
    [string]$Rootfs = '',
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

if (-not (Test-Path -LiteralPath (Join-Path $Repo 'ui\dist-desktop\index.html'))) {
    throw 'desktop frontend is not built; run pnpm build:desktop in ui first'
}
if (Test-Path -LiteralPath $Stage) { throw "package stage already exists: $Stage" }
New-Item -ItemType Directory -Force -Path (Join-Path $Stage 'payload\app') | Out-Null

$app = Join-Path $Stage 'payload\app'
$sourceArchive = Join-Path $Stage 'source.tar'
$runtimePaths = @('bridge', 'config', 'relay', 'scripts', 'switchtrade', 'tests', 'ui',
    'pytest.ini', 'requirements.txt', 'test-requirements.txt', 'README.md')
& git -C $Repo archive --format=tar --output=$sourceArchive HEAD -- @runtimePaths
if ($LASTEXITCODE -ne 0) { throw 'could not archive tracked runtime source' }
& tar -xf $sourceArchive -C $app
if ($LASTEXITCODE -ne 0) { throw 'could not extract tracked runtime source' }
Remove-Item -LiteralPath $sourceArchive
Copy-Item -LiteralPath (Join-Path $Repo 'ui\dist-desktop') -Destination (Join-Path $app 'ui') -Recurse -Force
$installerArchive = Join-Path $Stage 'installer.tar'
& git -C $Repo archive --format=tar --output=$installerArchive HEAD -- installer
if ($LASTEXITCODE -ne 0) { throw 'could not archive installer source' }
& tar -xf $installerArchive -C $Stage
if ($LASTEXITCODE -ne 0) { throw 'could not extract installer source' }
Remove-Item -LiteralPath $installerArchive

if ($Rootfs) {
    $resolvedRootfs = (Resolve-Path -LiteralPath $Rootfs).Path
    Copy-Item -LiteralPath $resolvedRootfs -Destination (Join-Path $Stage 'payload\switchtrade-rootfs.tar.gz')
}

$manifestArgs = @(
    (Join-Path $Repo 'scripts\write-release-manifest.py'), '--output', (Join-Path $Stage 'manifest.json')
)
& python @manifestArgs
if ($LASTEXITCODE -ne 0) { throw 'release manifest generation failed' }

if (-not $NoArchive) {
    $archive = "$Stage.zip"
    Compress-Archive -LiteralPath $Stage -DestinationPath $archive -Force
    Write-Host $archive
} else {
    Write-Host $Stage
}
