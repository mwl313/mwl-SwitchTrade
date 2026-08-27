[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Output,
    [Parameter(Mandatory)][ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$')][string]$ReleaseId,
    [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{64}$')][string]$ContentId,
    [string]$BaseRootfs = '',
    [string]$BuilderRootfs = '',
    [string]$Modules = '',
    [string]$FirmwareDirectory = '',
    [string]$FirmwareManifest = '',
    [string]$Wheelhouse = '',
    [string]$WheelhouseManifest = '',
    [long]$SourceDateEpoch = 0
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$retained = Join-Path $repo 'artifacts\final-package-27d17b1\SwitchTrade-unsigned-private-beta-27d17b1'
if (-not $BaseRootfs) { $BaseRootfs = & (Join-Path $PSScriptRoot 'Fetch-PinnedBaseRootfs.ps1') }
if (-not $BuilderRootfs) { $BuilderRootfs = Join-Path $retained 'payload\switchtrade-rootfs.tar.gz' }
if (-not $Modules) { $Modules = Join-Path $retained 'payload\kernel\modules.tar.gz' }
if (-not $FirmwareDirectory) { $FirmwareDirectory = Join-Path $repo 'artifacts\replacement\firmware' }
if (-not $FirmwareManifest) { $FirmwareManifest = Join-Path $PSScriptRoot 'runtime\firmware-manifest.sha256' }
if (-not $Wheelhouse) { $Wheelhouse = Join-Path $repo 'artifacts\audit-wheelhouse-linux-cp312' }
if (-not $WheelhouseManifest) { $WheelhouseManifest = Join-Path $PSScriptRoot 'runtime\wheelhouse-manifest.sha256' }
if (-not $SourceDateEpoch) {
    $SourceDateEpoch = [long]((& git -C $repo show -s --format=%ct HEAD).Trim())
}
if (-not (Test-Path -LiteralPath (Join-Path $FirmwareDirectory 'rtlwifi\rtl8192eu_nic.bin'))) {
    $FirmwareDirectory = & (Join-Path $PSScriptRoot 'Fetch-PinnedFirmware.ps1') -Destination $FirmwareDirectory
}
foreach ($path in @($BaseRootfs, $BuilderRootfs, $Modules, $FirmwareDirectory, $FirmwareManifest, $Wheelhouse, $WheelhouseManifest)) {
    if (-not (Test-Path -LiteralPath $path)) { throw "Required appliance input is missing: $path" }
}
$baseDefinition = Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot 'runtime\base-rootfs.json') |
    ConvertFrom-Json
if ((Get-Item -LiteralPath $BaseRootfs).Length -ne [long]$baseDefinition.size -or
    (Get-FileHash -LiteralPath $BaseRootfs -Algorithm SHA256).Hash.ToLowerInvariant() -ne
        [string]$baseDefinition.sha256) {
    throw 'Pinned Ubuntu base rootfs verification failed.'
}
if ((Get-Item -LiteralPath $BuilderRootfs).Length -ne [long]$baseDefinition.builder_source.size -or
    (Get-FileHash -LiteralPath $BuilderRootfs -Algorithm SHA256).Hash.ToLowerInvariant() -ne
        [string]$baseDefinition.builder_source.sha256) {
    throw 'Pinned disposable-builder rootfs verification failed.'
}
$outputPath = [IO.Path]::GetFullPath($Output)
if (Test-Path -LiteralPath $outputPath) { throw "Output already exists: $outputPath" }
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $outputPath) | Out-Null

$builder = 'SwitchTradeBuilder-' + [guid]::NewGuid().ToString('N').Substring(0, 12)
$builderRoot = Join-Path $repo "artifacts\replacement\builders\$builder"
$artifactsRoot = [IO.Path]::GetFullPath((Join-Path $repo 'artifacts')).TrimEnd('\')
$resolvedBuilder = [IO.Path]::GetFullPath($builderRoot)
if (-not $resolvedBuilder.StartsWith("$artifactsRoot\", [StringComparison]::OrdinalIgnoreCase)) {
    throw "Unsafe builder path: $resolvedBuilder"
}

function Invoke-Wsl([string[]]$Arguments, [int]$TimeoutSeconds = 900, [switch]$CaptureOutput) {
    $start = [Diagnostics.ProcessStartInfo]::new()
    $start.FileName = 'wsl.exe'
    $start.UseShellExecute = $false
    $start.RedirectStandardOutput = $CaptureOutput
    $start.RedirectStandardError = $CaptureOutput
    foreach ($argument in $Arguments) { [void]$start.ArgumentList.Add($argument) }
    $process = [Diagnostics.Process]::Start($start)
    $stdout = if ($CaptureOutput) { $process.StandardOutput.ReadToEndAsync() } else { $null }
    $stderr = if ($CaptureOutput) { $process.StandardError.ReadToEndAsync() } else { $null }
    if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
        $process.Kill($true)
        throw "wsl.exe timed out after $TimeoutSeconds seconds"
    }
    $outputText = if ($CaptureOutput) { $stdout.GetAwaiter().GetResult() } else { '' }
    $errorText = if ($CaptureOutput) { $stderr.GetAwaiter().GetResult() } else { '' }
    if ($process.ExitCode -ne 0) {
        throw "wsl.exe failed with exit code $($process.ExitCode): $($errorText.Trim())"
    }
    if ($CaptureOutput) { return $outputText }
}
function Convert-ToWslPath([string]$WindowsPath) {
    # wsl.exe treats backslashes as command-line escapes even when ProcessStartInfo
    # supplies a correctly delimited argument. wslpath accepts the slash form.
    $portableWindowsPath = [IO.Path]::GetFullPath($WindowsPath).Replace([char]92, [char]47)
    $value = Invoke-Wsl @('-d', $builder, '-u', 'root', '--', 'wslpath', '-a', $portableWindowsPath) -CaptureOutput
    if (-not $value) { throw "Could not translate path: $WindowsPath" }
    return $value.Trim().Replace(([char]0).ToString(), '')
}

try {
    New-Item -ItemType Directory -Force -Path $builderRoot | Out-Null
    Invoke-Wsl @('--import', $builder, $builderRoot, ([IO.Path]::GetFullPath($BuilderRootfs)), '--version', '2')
    $script = Convert-ToWslPath (Join-Path $PSScriptRoot 'runtime\build-appliance.sh')
    $baseRootfsWsl = Convert-ToWslPath $BaseRootfs
    $repoWsl = Convert-ToWslPath $repo
    $wheelhouseWsl = Convert-ToWslPath $Wheelhouse
    $modulesWsl = Convert-ToWslPath $Modules
    $firmwareDirectoryWsl = Convert-ToWslPath $FirmwareDirectory
    $firmwareWsl = Convert-ToWslPath $FirmwareManifest
    $outputWsl = Convert-ToWslPath $outputPath
    $wheelhouseManifestWsl = Convert-ToWslPath $WheelhouseManifest
    Invoke-Wsl @('-d', $builder, '-u', 'root', '--', 'bash', $script, $repoWsl, $wheelhouseWsl,
        $modulesWsl, $firmwareDirectoryWsl, $firmwareWsl, $outputWsl, $ReleaseId, $ContentId,
        [string]$SourceDateEpoch, $wheelhouseManifestWsl, $baseRootfsWsl) 3600
    $metadata = [ordered]@{
        schema = 1; release_id = $ReleaseId; content_id = $ContentId
        source_date_epoch = $SourceDateEpoch
        sha256 = (Get-FileHash -LiteralPath $outputPath -Algorithm SHA256).Hash.ToLowerInvariant()
        size = (Get-Item -LiteralPath $outputPath).Length
    }
    $metadata | ConvertTo-Json | Set-Content -LiteralPath "$outputPath.build.json" -Encoding utf8
} finally {
    try { & wsl.exe --terminate $builder 2>$null | Out-Null } catch { }
    try { & wsl.exe --unregister $builder 2>$null | Out-Null } catch { }
    if (Test-Path -LiteralPath $resolvedBuilder) {
        $item = Get-Item -LiteralPath $resolvedBuilder -Force
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw "Refusing builder reparse point: $resolvedBuilder" }
        Remove-Item -LiteralPath $resolvedBuilder -Recurse -Force
    }
}
