[CmdletBinding()]
param(
    [Parameter(Mandatory, Position = 0)]
    [ValidateSet('preflight', 'create', 'join', 'status', 'continue', 'cancel', 'recover')]
    [string]$Command,
    [string]$StateRoot = '',
    [ValidateSet('a_room_joiner', 'b_ap_host')]
    [string]$Role = '',
    [ValidateSet('end', 'stop', 'leave', 'close')]
    [string]$Action = '',
    [string]$Invitation = '',
    [string]$TestId = '',
    [string]$RunId = '',
    [ValidateSet(
        'PAIRING_CONFIRMED', 'CREATE_SWITCH_ROOM', 'JOIN_SWITCH_GROUP',
        'D_ACTION_CONFIRMED', 'ROOM_FINALIZATION_CONFIRMED',
        'RECOVERY_FINALIZATION_CONFIRMED')]
    [string]$Checkpoint = '',
    [string]$Distro = '',
    [string]$SelectionFile = '',
    [string]$RuntimeRoot = '/opt/switchtrade',
    [string]$RelayUrl = 'https://relay.pangyostonefist.org',
    [ValidateRange(1, 3600)]
    [int]$TimeoutSeconds = 300,
    [switch]$AllowDirtyForDevelopment
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$python = Join-Path $repo '.audit-venv\Scripts\python.exe'
$module = Join-Path $repo 'switchtrade\connection\distributed_harness.py'

function Fail([string]$Code) {
    throw $Code
}

function Invoke-Captured([string]$FileName, [string[]]$Arguments) {
    $output = @(& $FileName @Arguments 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "$FileName failed with exit code $LASTEXITCODE."
    }
    return (($output -join "`n").Trim())
}

function Get-ControlState([string]$Root) {
    $path = Join-Path $Root 'distributed-control-state.json'
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        Fail 'DISTRIBUTED_CONTROL_STATE_INVALID'
    }
    try {
        $value = Get-Content -Raw -LiteralPath $path -Encoding utf8 | ConvertFrom-Json
    } catch {
        Fail 'DISTRIBUTED_CONTROL_STATE_INVALID'
    }
    if ($value.PSObject.Properties.Name -notcontains 'source_sha') {
        Fail 'DISTRIBUTED_CONTROL_STATE_INVALID'
    }
    return $value
}

function Get-StringSha256([string]$Value) {
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = $algorithm.ComputeHash([Text.Encoding]::UTF8.GetBytes($Value))
        return ([BitConverter]::ToString($bytes) -replace '-', '').ToLowerInvariant()
    } finally {
        $algorithm.Dispose()
    }
}

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    Fail 'DISTRIBUTED_QUALIFICATION_INTERPRETER_MISSING'
}
if (-not (Test-Path -LiteralPath $module -PathType Leaf)) {
    Fail 'DISTRIBUTED_QUALIFICATION_SOURCE_MISSING'
}

$source = (Invoke-Captured 'git.exe' @('-C', $repo, 'rev-parse', 'HEAD')).ToLowerInvariant()
if ($source -notmatch '^[0-9a-f]{40}$') {
    Fail 'DISTRIBUTED_SOURCE_IDENTITY_INVALID'
}
$expectedRelease = "beta-$($source.Substring(0, 12))"

$environmentProbe = @'
import hashlib,importlib.metadata,importlib.util,json,pathlib,sys
root=pathlib.Path(sys.argv[1]).resolve()
required=('trio','websockets','switchtrade.connection.distributed_harness')
missing=[name for name in required if importlib.util.find_spec(name) is None]
module=importlib.util.find_spec('switchtrade.connection.distributed_harness')
origin=None if module is None or module.origin is None else str(pathlib.Path(module.origin).resolve())
lock=root/'bridge/requirements.txt'
pins={}
for raw in lock.read_text(encoding='utf-8').splitlines():
    line=raw.strip()
    if line and not line.startswith('#') and '==' in line:
        name,value=line.split('==',1); pins[name.casefold()]=value
versions={name:importlib.metadata.version(name) for name in ('trio','websockets') if name not in missing}
mismatches={name:{'expected':pins.get(name),'actual':versions.get(name)} for name in versions if pins.get(name)!=versions.get(name)}
print(json.dumps({'missing':missing,'mismatches':mismatches,'origin':origin,
 'expected':str((root/'switchtrade/connection/distributed_harness.py').resolve()),
 'requirements_sha256':hashlib.sha256(lock.read_bytes()).hexdigest()},sort_keys=True))
'@
Push-Location -LiteralPath $repo
try {
    $probeText = Invoke-Captured $python @('-c', $environmentProbe, $repo)
} finally {
    Pop-Location
}
try {
    $probe = $probeText | ConvertFrom-Json
} catch {
    Fail 'DISTRIBUTED_QUALIFICATION_ENVIRONMENT_INVALID'
}
if ($probe.PSObject.Properties.Name -notcontains 'missing' -or
    $probe.PSObject.Properties.Name -notcontains 'origin' -or
    $probe.PSObject.Properties.Name -notcontains 'expected' -or
    $probe.PSObject.Properties.Name -notcontains 'mismatches' -or
    $probe.PSObject.Properties.Name -notcontains 'requirements_sha256' -or
    @($probe.missing).Count -ne 0 -or
    @($probe.mismatches.PSObject.Properties).Count -ne 0 -or
    -not [string]::Equals([string]$probe.origin, [string]$probe.expected,
        [StringComparison]::OrdinalIgnoreCase)) {
    Fail 'DISTRIBUTED_QUALIFICATION_ENVIRONMENT_INVALID'
}

if ($AllowDirtyForDevelopment -and $Command -ne 'preflight') {
    Fail 'DISTRIBUTED_DIRTY_OVERRIDE_PREFLIGHT_ONLY'
}
if ($Command -ne 'status' -and -not $AllowDirtyForDevelopment) {
    $dirty = @(& git.exe -C $repo status --porcelain --untracked-files=all 2>&1)
    if ($LASTEXITCODE -ne 0) { Fail 'DISTRIBUTED_SOURCE_IDENTITY_INVALID' }
    if (($dirty -join "`n").Trim()) {
        Fail 'DISTRIBUTED_QUALIFICATION_SOURCE_DIRTY'
    }
}

if ($Command -ne 'preflight') {
    if (-not $StateRoot) { Fail 'DISTRIBUTED_STATE_ROOT_REQUIRED' }
    $StateRoot = [IO.Path]::GetFullPath($StateRoot)
}

if ($Command -in @('continue', 'cancel')) {
    $state = Get-ControlState $StateRoot
    if ([string]$state.source_sha -ne $source) {
        Fail 'DISTRIBUTED_CONTROL_SOURCE_MISMATCH'
    }
}

$needsRuntime = $Command -in @('preflight', 'create', 'join', 'recover')
if ($needsRuntime) {
    if (-not $Distro) {
        $names = @((@(& wsl.exe --list --quiet) -replace ([char]0), '') |
            ForEach-Object { $_.Trim() } |
            Where-Object { $_ -like "SwitchTrade-$expectedRelease-*" })
        if ($LASTEXITCODE -ne 0) { Fail 'DISTRIBUTED_WSL_INVENTORY_UNAVAILABLE' }
        $matches = @()
        foreach ($name in $names) {
            $markerText = @(& wsl.exe -d $name -u root --cd $RuntimeRoot --
                cat "$RuntimeRoot/.switchtrade-release.json" 2>$null)
            if ($LASTEXITCODE -ne 0) { continue }
            try {
                $marker = (($markerText -join "`n") -replace ([char]0), '') | ConvertFrom-Json
                if ([string]$marker.release_id -eq $expectedRelease) { $matches += $name }
            } catch {}
        }
        if ($matches.Count -ne 1) { Fail 'DISTRIBUTED_WSL_IDENTITY_AMBIGUOUS' }
        $Distro = $matches[0]
    }
    $markerText = Invoke-Captured 'wsl.exe' @(
        '-d', $Distro, '-u', 'root', '--cd', $RuntimeRoot, '--',
        'cat', "$RuntimeRoot/.switchtrade-release.json")
    try {
        $marker = ($markerText -replace ([char]0), '') | ConvertFrom-Json
    } catch {
        Fail 'DISTRIBUTED_WSL_RELEASE_INVALID'
    }
    if ($marker.PSObject.Properties.Name -notcontains 'release_id' -or
        [string]$marker.release_id -ne $expectedRelease) {
        Fail 'DISTRIBUTED_SOURCE_RUNTIME_MISMATCH'
    }

    if (-not $SelectionFile) {
        if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
            Fail 'P0_ADAPTER_SELECTION_INVALID'
        }
        $SelectionFile = Join-Path $env:LOCALAPPDATA 'SwitchTrade\runtime\hardware-selection.json'
    }
    $SelectionFile = [IO.Path]::GetFullPath($SelectionFile)
    if (-not (Test-Path -LiteralPath $SelectionFile -PathType Leaf)) {
        Fail 'P0_ADAPTER_SELECTION_INVALID'
    }
    try {
        $selection = Get-Content -Raw -LiteralPath $SelectionFile -Encoding utf8 | ConvertFrom-Json
    } catch {
        Fail 'P0_ADAPTER_SELECTION_INVALID'
    }
    if ($selection.PSObject.Properties.Name -notcontains 'schema' -or
        $selection.PSObject.Properties.Name -notcontains 'usb_id' -or
        $selection.PSObject.Properties.Name -notcontains 'instance_id' -or
        [int]$selection.schema -ne 1 -or [string]$selection.usb_id -ne '0bda:818b' -or
        [string]::IsNullOrWhiteSpace([string]$selection.instance_id)) {
        Fail 'P0_ADAPTER_SELECTION_INVALID'
    }
}

if ($Command -eq 'preflight') {
    [ordered]@{
        status = 'ready'
        source_sha = $source
        release = $expectedRelease
        distro = $Distro
        interpreter = (Get-FileHash -LiteralPath $python -Algorithm SHA256).Hash.ToLowerInvariant()
        requirements = [string]$probe.requirements_sha256
        selection_identity = Get-StringSha256 (
            ([string]$selection.instance_id).ToLowerInvariant())
        control = 'distributed-control-state.v1'
    } | ConvertTo-Json
    exit 0
}

$arguments = @(
    '-m', 'switchtrade.connection.distributed_harness',
    '--state-root', $StateRoot,
    '--runtime-root', $RuntimeRoot,
    '--timeout', [string]$TimeoutSeconds
)
if ($needsRuntime) {
    $arguments += @('--distro', $Distro, '--selection-file', $SelectionFile, '--relay-url', $RelayUrl)
}
$arguments += $Command
switch ($Command) {
    'create' {
        if (-not $Role -or -not $Action) { Fail 'DISTRIBUTED_CREATE_ARGUMENTS_REQUIRED' }
        $arguments += @('--role', $Role, '--action', $Action)
    }
    'join' {
        if (-not $Invitation) { Fail 'DISTRIBUTED_INVITATION_REQUIRED' }
        $arguments += @('--invitation', $Invitation)
    }
    'continue' {
        if (-not $TestId -or -not $Checkpoint) {
            Fail 'DISTRIBUTED_CONTROL_ARGUMENTS_REQUIRED'
        }
        $arguments += @('--test-id', $TestId, '--checkpoint', $Checkpoint)
        if ($RunId) { $arguments += @('--run-id', $RunId) }
    }
    'cancel' {
        if (-not $TestId) { Fail 'DISTRIBUTED_CONTROL_ARGUMENTS_REQUIRED' }
        $arguments += @('--test-id', $TestId)
        if ($RunId) { $arguments += @('--run-id', $RunId) }
    }
}

Push-Location -LiteralPath $repo
try {
    & $python @arguments
    $exitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $exitCode
