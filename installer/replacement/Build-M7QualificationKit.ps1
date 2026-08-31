[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$OutputDirectory,
    [Parameter(Mandatory)][ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$')][string]$ReleaseId,
    [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{40}$')][string]$SourceSha
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$output = [IO.Path]::GetFullPath($OutputDirectory)
$artifactsRoot = [IO.Path]::GetFullPath((Join-Path $repo 'artifacts')).TrimEnd('\') + '\'
if (-not $output.StartsWith($artifactsRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Qualification output must be inside the repository artifacts directory.'
}
if (Test-Path -LiteralPath $output) {
    if (@(Get-ChildItem -LiteralPath $output -Force).Count -gt 0) {
        throw "Qualification output is not empty: $output"
    }
} else {
    New-Item -ItemType Directory -Path $output | Out-Null
}

$actualSource = ((& git -C $repo rev-parse HEAD) | Out-String).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $actualSource -ne $SourceSha) {
    throw 'Qualification source identity does not match HEAD.'
}
if ($ReleaseId -ne "beta-$($SourceSha.Substring(0, 12))") {
    throw 'Qualification release ID must be derived from the exact source commit.'
}
& git -C $repo diff --quiet
$worktreeDirty = $LASTEXITCODE -ne 0
& git -C $repo diff --cached --quiet
$indexDirty = $LASTEXITCODE -ne 0
if ($worktreeDirty -or $indexDirty) {
    throw 'Qualification kits require a clean tracked worktree.'
}

$version = (Get-Content -Raw -LiteralPath (Join-Path $repo 'switchtrade\VERSION')).Trim()
$auditPython = Join-Path $repo '.audit-venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $auditPython -PathType Leaf)) {
    throw 'The pinned qualification build environment is missing.'
}
$pythonIdentity = @(& $auditPython -c (
    'import json,sys,sysconfig; print(json.dumps({' +
    '"version":".".join(map(str,sys.version_info[:3])),"base_prefix":sys.base_prefix,' +
    '"site":sysconfig.get_path("purelib")}))'
)) -join "`n"
if ($LASTEXITCODE -ne 0) { throw 'Could not inspect the qualification Python environment.' }
$pythonIdentity = $pythonIdentity | ConvertFrom-Json
if ([string]$pythonIdentity.version -ne '3.12.14') {
    throw "Qualification Python changed: expected 3.12.14, found $($pythonIdentity.version)."
}
$pythonBase = [IO.Path]::GetFullPath([string]$pythonIdentity.base_prefix)
$sitePackages = [IO.Path]::GetFullPath([string]$pythonIdentity.site)
foreach ($path in @($pythonBase, $sitePackages)) {
    if (-not (Test-Path -LiteralPath $path -PathType Container)) {
        throw "Qualification Python input is missing: $path"
    }
}

$kit = Join-Path $output 'kit'
$kitPython = Join-Path $kit 'python'
$kitSource = Join-Path $kit 'source'
New-Item -ItemType Directory -Path $kitPython,$kitSource | Out-Null
Get-ChildItem -LiteralPath $pythonBase -Force | Copy-Item -Destination $kitPython -Recurse -Force
$kitSite = Join-Path $kitPython 'Lib\site-packages'
if (Test-Path -LiteralPath $kitSite) {
    $resolvedSite = [IO.Path]::GetFullPath($kitSite)
    $kitPrefix = [IO.Path]::GetFullPath($kit).TrimEnd('\') + '\'
    if (-not $resolvedSite.StartsWith($kitPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Qualification Python cleanup escaped the kit root.'
    }
    Remove-Item -LiteralPath $resolvedSite -Recurse -Force
}
New-Item -ItemType Directory -Path $kitSite | Out-Null

$copyDependencies = @'
import importlib.metadata as metadata
import json
import pathlib
import shutil
import sys

requirements = pathlib.Path(sys.argv[1])
source_site = pathlib.Path(sys.argv[2]).resolve()
target_site = pathlib.Path(sys.argv[3]).resolve()
locked = {}
for raw in requirements.read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if line and not line.startswith("#"):
        name, version = line.split("==", 1)
        locked[name.casefold().replace("_", "-")] = version
copied = {}
for name, expected in sorted(locked.items()):
    dist = metadata.distribution(name)
    if dist.version != expected:
        raise SystemExit(f"dependency mismatch: {name} expected {expected}, found {dist.version}")
    copied[name] = expected
    for relative in dist.files or ():
        source = pathlib.Path(dist.locate_file(relative)).resolve()
        try:
            inside = source.relative_to(source_site)
        except ValueError:
            continue
        if not source.is_file():
            continue
        target = target_site / inside
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.read_bytes() != source.read_bytes():
            raise SystemExit(f"dependency file collision: {inside.as_posix()}")
        shutil.copy2(source, target)
print(json.dumps(copied, sort_keys=True, separators=(",", ":")))
'@
$dependencyJson = @(& $auditPython -c $copyDependencies (
    Join-Path $repo 'bridge\requirements.txt') $sitePackages $kitSite) -join "`n"
if ($LASTEXITCODE -ne 0) { throw 'Could not assemble the qualification dependency closure.' }
$dependencies = $dependencyJson | ConvertFrom-Json

$tracked = @(& git -C $repo ls-files -- 'switchtrade' 'bridge/requirements.txt') | Where-Object { $_ }
if ($LASTEXITCODE -ne 0 -or $tracked.Count -eq 0) {
    throw 'Could not enumerate the qualification source closure.'
}
foreach ($relative in $tracked) {
    $source = Join-Path $repo $relative
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { continue }
    $target = Join-Path $kitSource $relative
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
    Copy-Item -LiteralPath $source -Destination $target -Force
}
Copy-Item -LiteralPath (Join-Path $repo 'scripts\windows\Invoke-M7DistributedHarness.ps1') `
    -Destination (Join-Path $kit 'Invoke-M7DistributedHarness.ps1') -Force

$kitProbe = @'
import importlib.metadata as metadata
import importlib.util
import json

names = ("trio", "websockets", "switchtrade.connection.distributed_harness")
missing = [name for name in names if importlib.util.find_spec(name) is None]
print(json.dumps({
    "missing": missing,
    "trio": metadata.version("trio") if "trio" not in missing else None,
    "websockets": metadata.version("websockets") if "websockets" not in missing else None,
}, sort_keys=True, separators=(",", ":")))
'@
Push-Location -LiteralPath $kitSource
try {
    $kitProbeJson = @(& (Join-Path $kitPython 'python.exe') -c $kitProbe) -join "`n"
} finally {
    Pop-Location
}
if ($LASTEXITCODE -ne 0) { throw 'The packaged qualification environment cannot import its source.' }
$kitProbeResult = $kitProbeJson | ConvertFrom-Json
if (@($kitProbeResult.missing).Count -ne 0 -or
    [string]$kitProbeResult.trio -ne '0.33.0' -or
    [string]$kitProbeResult.websockets -ne '17.0.1') {
    throw 'The packaged qualification environment does not match the locked runtime.'
}

$artifactRows = @()
foreach ($file in Get-ChildItem -LiteralPath $kit -Recurse -File -Force | Sort-Object FullName) {
    $relative = $file.FullName.Substring($kit.TrimEnd('\').Length + 1).Replace('\', '/')
    $artifactRows += [ordered]@{
        path = $relative
        size = $file.Length
        sha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}
$requirementsHash = (Get-FileHash -LiteralPath (
    Join-Path $kitSource 'bridge\requirements.txt') -Algorithm SHA256).Hash.ToLowerInvariant()
$manifest = [ordered]@{
    contract_version = 'm7-qualification-kit.v1'
    schema = 1
    source_sha = $SourceSha
    release_id = $ReleaseId
    version = $version
    source_root = 'source'
    interpreter = 'python/python.exe'
    python_version = [string]$pythonIdentity.version
    requirements_sha256 = $requirementsHash
    dependencies = $dependencies
    artifacts = $artifactRows
}
$manifestPath = Join-Path $kit 'qualification-manifest.json'
$manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding utf8

$archive = Join-Path $output "SwitchTrade-M7-Qualification-$version.zip"
$sourceEpoch = [long](((& git -C $repo show -s --format=%ct $SourceSha) | Out-String).Trim())
$zipProgram = @'
import datetime
import pathlib
import sys
import zipfile

root = pathlib.Path(sys.argv[1]).resolve()
archive = pathlib.Path(sys.argv[2]).resolve()
epoch = int(sys.argv[3])
stamp = datetime.datetime.fromtimestamp(max(epoch, 315532800), datetime.timezone.utc)
stamp = (stamp.year, stamp.month, stamp.day, stamp.hour, stamp.minute, stamp.second)
with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as output:
    for path in sorted(value for value in root.rglob("*") if value.is_file()):
        relative = path.relative_to(root).as_posix()
        info = zipfile.ZipInfo(relative, stamp)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o100644 << 16
        output.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
'@
& $auditPython -c $zipProgram $kit $archive $sourceEpoch
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $archive -PathType Leaf)) {
    throw 'Could not create the qualification archive.'
}

[pscustomobject]@{
    contract_version = 'm7-qualification-kit-build.v1'
    source_sha = $SourceSha
    release_id = $ReleaseId
    version = $version
    archive = $archive
    size = (Get-Item -LiteralPath $archive).Length
    sha256 = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
    manifest_sha256 = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
}
