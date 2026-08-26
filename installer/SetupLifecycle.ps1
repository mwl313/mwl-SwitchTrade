Set-StrictMode -Version Latest

$script:SwitchTradeReleaseMarker = '.switchtrade-release.json'

function Get-SwitchTradeReleaseId {
    param([Parameter(Mandatory)][string]$ManifestPath)
    if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) {
        throw 'PACKAGE_MANIFEST_MISSING'
    }
    $manifest = Get-Content -Raw -LiteralPath $ManifestPath | ConvertFrom-Json
    $releaseId = [string]$manifest.release_id
    if ([int]$manifest.schema -ne 2 -or $releaseId -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$') {
        throw 'PACKAGE_RELEASE_ID_INVALID: manifest release_id is missing or invalid'
    }
    return $releaseId
}

function Write-AtomicJson {
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)]$Value)
    $parent = Split-Path -Parent $Path
    if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    $temporary = "$Path.tmp.$([guid]::NewGuid().ToString('N'))"
    try {
        $Value | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $temporary -Encoding UTF8
        Move-Item -LiteralPath $temporary -Destination $Path -Force
    } finally {
        if (Test-Path -LiteralPath $temporary -PathType Leaf) {
            Remove-Item -LiteralPath $temporary -Force
        }
    }
}

function Redact-SwitchTradeSetupText {
    param([AllowEmptyString()][string]$Text)
    if ($null -eq $Text) { return '' }
    $redacted = [regex]::Replace($Text,
        '(?i)(authorization["'']?\s*[:=]\s*["'']?bearer\s+)[^\s,;"'']+', '$1<redacted>')
    $redacted = [regex]::Replace($redacted, '(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+', '$1<redacted>')
    $redacted = [regex]::Replace($redacted,
        '(?i)(member[_-]?token|reconnect[_-]?token|password|secret|prod[_-]?key)["'']?(\s*[:=]\s*["'']?)[^\s,;"'']+',
        '$1$2<redacted>')
    return $redacted.Replace([string][char]0, '')
}

function Write-SwitchTradeSetupLog {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Stage,
        [Parameter(Mandatory)][string]$Message,
        [ValidateSet('info', 'error')][string]$Level = 'info'
    )
    $entry = [ordered]@{
        timestamp_utc = [DateTime]::UtcNow.ToString('o')
        level = $Level
        stage = $Stage
        message = Redact-SwitchTradeSetupText $Message
    }
    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    Add-Content -LiteralPath $Path -Value ($entry | ConvertTo-Json -Compress) -Encoding UTF8
}

function New-SwitchTradeTransaction {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Action,
        [Parameter(Mandatory)][string]$ReleaseId,
        [string]$PriorReleaseId = '',
        [string]$WindowsStage = ''
    )
    $state = [ordered]@{
        schema = 1
        transaction_id = [guid]::NewGuid().ToString('N')
        action = $Action
        release_id = $ReleaseId
        prior_release_id = $PriorReleaseId
        phase = 'created'
        windows_stage = $WindowsStage
        distro_imported = $false
        wsl_staged = $false
        kernel_applied = $false
        wsl_committed = $false
        windows_committed = $false
        started_utc = [DateTime]::UtcNow.ToString('o')
    }
    Write-AtomicJson -Path $Path -Value $state
    return $state
}

function Set-SwitchTradeTransactionPhase {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Phase,
        [hashtable]$Fields = @{}
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw 'SETUP_TRANSACTION_MISSING: transaction state disappeared'
    }
    $state = Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json
    $state.phase = $Phase
    foreach ($key in $Fields.Keys) {
        if ($state.PSObject.Properties.Name -contains $key) {
            $state.$key = $Fields[$key]
        } else {
            $state | Add-Member -NotePropertyName $key -NotePropertyValue $Fields[$key]
        }
    }
    Write-AtomicJson -Path $Path -Value $state
    return $state
}

function Get-InstalledWindowsReleaseId {
    param([Parameter(Mandatory)][string]$Root)
    $marker = Join-Path $Root $script:SwitchTradeReleaseMarker
    if (-not (Test-Path -LiteralPath $marker -PathType Leaf)) { return '' }
    try {
        $value = Get-Content -Raw -LiteralPath $marker | ConvertFrom-Json
        return [string]$value.release_id
    } catch { return '' }
}

function Write-WindowsReleaseMarker {
    param([Parameter(Mandatory)][string]$Root, [Parameter(Mandatory)][string]$ReleaseId)
    Write-AtomicJson -Path (Join-Path $Root $script:SwitchTradeReleaseMarker) -Value ([ordered]@{
        schema = 1; release_id = $ReleaseId
    })
}

function Test-WindowsReleaseTree {
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][string]$ExpectedReleaseId
    )
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) {
        throw "ROLLBACK_WINDOWS_MISSING: $Root"
    }
    $manifestPath = Join-Path $Root 'manifest.json'
    $configPath = Join-Path $Root 'config.json'
    $releaseId = Get-SwitchTradeReleaseId -ManifestPath $manifestPath
    $markerRelease = Get-InstalledWindowsReleaseId -Root $Root
    if ($releaseId -ne $ExpectedReleaseId -or $markerRelease -ne $ExpectedReleaseId) {
        throw "ROLLBACK_RELEASE_MISMATCH: expected $ExpectedReleaseId, Windows has $releaseId/$markerRelease"
    }
    $manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
    $property = $manifest.artifact_hashes.PSObject.Properties['payload/release-config.json']
    if (-not $property -or -not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
        throw 'ROLLBACK_WINDOWS_CONFIG_MISSING: retained relay configuration is incomplete'
    }
    $actual = Get-FileSha256 $configPath
    if ($actual -ne ([string]$property.Value).ToLowerInvariant()) {
        throw 'ROLLBACK_WINDOWS_HASH_MISMATCH: retained relay configuration is corrupt'
    }
    return $true
}

function Enter-SwitchTradeSetupMutex {
    $created = $false
    $mutex = New-Object System.Threading.Mutex($true, 'Global\SwitchTrade.Setup', [ref]$created)
    if ($created) { return $mutex }
    try {
        if (-not $mutex.WaitOne(0)) {
            $mutex.Dispose()
            throw 'SETUP_ALREADY_RUNNING: another SwitchTrade setup action is active'
        }
    } catch [Threading.AbandonedMutexException] { }
    return $mutex
}

function Commit-SwitchTradeWindowsRelease {
    param(
        [Parameter(Mandatory)][string]$Candidate,
        [Parameter(Mandatory)][string]$Active,
        [Parameter(Mandatory)][string]$Previous,
        [Parameter(Mandatory)][string]$ExpectedReleaseId,
        [ValidateSet('', 'after_active_retained', 'after_candidate_activated')]
        [string]$FaultAfter = ''
    )
    Test-WindowsReleaseTree -Root $Candidate -ExpectedReleaseId $ExpectedReleaseId | Out-Null
    $priorRelease = ''
    if (Test-Path -LiteralPath $Active -PathType Container) {
        $priorRelease = Get-InstalledWindowsReleaseId -Root $Active
        Test-WindowsReleaseTree -Root $Active -ExpectedReleaseId $priorRelease | Out-Null
    }
    if (Test-Path -LiteralPath $Previous) {
        $retainedRelease = Get-InstalledWindowsReleaseId -Root $Previous
        Test-WindowsReleaseTree -Root $Previous -ExpectedReleaseId $retainedRelease | Out-Null
        Remove-Item -LiteralPath $Previous -Recurse -Force
    }
    $movedActive = $false
    $candidateActivated = $false
    try {
        if ($priorRelease) {
            Move-Item -LiteralPath $Active -Destination $Previous
            $movedActive = $true
            if ($FaultAfter -eq 'after_active_retained') { throw 'INJECTED_AFTER_ACTIVE_RETAINED' }
        }
        Move-Item -LiteralPath $Candidate -Destination $Active
        $candidateActivated = $true
        if ($FaultAfter -eq 'after_candidate_activated') { throw 'INJECTED_AFTER_CANDIDATE_ACTIVATED' }
        Test-WindowsReleaseTree -Root $Active -ExpectedReleaseId $ExpectedReleaseId | Out-Null
    } catch {
        if ($candidateActivated -and (Test-Path -LiteralPath $Active) -and
            -not (Test-Path -LiteralPath $Candidate)) {
            Move-Item -LiteralPath $Active -Destination $Candidate
        }
        if ($movedActive -and -not (Test-Path -LiteralPath $Active) -and
            (Test-Path -LiteralPath $Previous)) {
            Move-Item -LiteralPath $Previous -Destination $Active
        }
        throw
    }
    return $priorRelease
}

function Switch-SwitchTradeWindowsRollback {
    param(
        [Parameter(Mandatory)][string]$Active,
        [Parameter(Mandatory)][string]$Previous,
        [Parameter(Mandatory)][string]$ExpectedReleaseId
    )
    Test-WindowsReleaseTree -Root $Previous -ExpectedReleaseId $ExpectedReleaseId | Out-Null
    $activeRelease = Get-InstalledWindowsReleaseId -Root $Active
    Test-WindowsReleaseTree -Root $Active -ExpectedReleaseId $activeRelease | Out-Null
    $swap = "$Active.rollback-swap"
    if (Test-Path -LiteralPath $swap) { throw 'ROLLBACK_WINDOWS_SWAP_STALE' }
    $swapped = $false
    Move-Item -LiteralPath $Active -Destination $swap
    try {
        Move-Item -LiteralPath $Previous -Destination $Active
        Move-Item -LiteralPath $swap -Destination $Previous
        $swapped = $true
        Test-WindowsReleaseTree -Root $Active -ExpectedReleaseId $ExpectedReleaseId | Out-Null
    } catch {
        if ($swapped) {
            Move-Item -LiteralPath $Active -Destination $swap
            Move-Item -LiteralPath $Previous -Destination $Active
            Move-Item -LiteralPath $swap -Destination $Previous
        } elseif (Test-Path -LiteralPath $swap) {
            if ((Test-Path -LiteralPath $Active) -and -not (Test-Path -LiteralPath $Previous)) {
                Move-Item -LiteralPath $Active -Destination $Previous
            }
            if (-not (Test-Path -LiteralPath $Active)) {
                Move-Item -LiteralPath $swap -Destination $Active
            }
        }
        throw
    }
    return $activeRelease
}

function Resolve-SwitchTradeUsbDeviceFromState {
    param(
        [Parameter(Mandatory)]$State,
        [Parameter(Mandatory)][string]$InstanceId,
        [string]$UsbId = ''
    )
    $device = @($State.Devices | Where-Object { [string]$_.InstanceId -ceq $InstanceId }) |
        Select-Object -First 1
    if (-not $device -or [string]$device.BusId -notmatch '^\d+-\d+$') {
        throw 'USB_DEVICE_INSTANCE_NOT_FOUND: reconnect the selected adapter and run Setup Repair'
    }
    $match = [regex]::Match([string]$device.InstanceId, 'VID_([0-9A-F]{4})&PID_([0-9A-F]{4})',
        [Text.RegularExpressions.RegexOptions]::IgnoreCase)
    $currentUsbId = if ($match.Success) {
        "$($match.Groups[1].Value):$($match.Groups[2].Value)".ToLowerInvariant()
    } else { '' }
    if ($UsbId -and $currentUsbId -ne $UsbId.ToLowerInvariant()) {
        throw 'USB_DEVICE_IDENTITY_MISMATCH: the saved adapter identity no longer matches the selected hardware'
    }
    return $device
}
