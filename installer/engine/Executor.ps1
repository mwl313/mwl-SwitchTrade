# SwitchTrade installer engine: transaction executor (reassembled)
#
# Handoff 8.3: each mutating step revalidates the identity it is about to mutate, persists
# intent/checkpoint before irreversible mutation, uses bounded cancellable subprocesses,
# records structured progress + correlation id, persists completion before advancing, and is
# idempotent on replay. Compensation is explicit persisted work (recovery plans), never a
# best-effort catch block.
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot 'PlatformOps.ps1')
. (Join-Path $PSScriptRoot 'StateInspector.ps1')
. (Join-Path $PSScriptRoot 'Planner.ps1')
. (Join-Path $PSScriptRoot '..\KernelLifecycle.ps1')

$script:SwitchTradeReleaseMarker = '.switchtrade-release.json'
$script:SwitchTradeCorrelationId = [guid]::NewGuid().ToString('N')
$script:SwitchTradeSetupLog = ''
$script:SwitchTradeSetupStage = 'initialize'

function Set-SwitchTradeEngineStage {
    param([Parameter(Mandatory)][string]$Stage)
    $script:SwitchTradeSetupStage = $Stage
    if ($script:SwitchTradeSetupLog) {
        try { Write-SwitchTradeEngineLog -Stage $Stage -Message 'entered engine stage' } catch { }
    }
    if ($env:SWITCHTRADE_SETUP_PROGRESS -eq '1') {
        [Console]::Out.WriteLine("SWITCHTRADE_SETUP_PROGRESS: $Stage")
        [Console]::Out.Flush()
    }
}

function Write-SwitchTradeEngineLog {
    param(
        [Parameter(Mandatory)][string]$Stage,
        [Parameter(Mandatory)][string]$Message,
        [ValidateSet('info', 'error')][string]$Level = 'info'
    )
    $entry = [ordered]@{
        timestamp_utc = [DateTime]::UtcNow.ToString('o')
        level = $Level
        stage = $Stage
        message = Redact-SwitchTradeEngineText $Message
        correlation_id = $script:SwitchTradeCorrelationId
    }
    if (-not $script:SwitchTradeSetupLog) { return }
    $parent = Split-Path -Parent $script:SwitchTradeSetupLog
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    Add-Content -LiteralPath $script:SwitchTradeSetupLog -Value ($entry | ConvertTo-Json -Compress) -Encoding UTF8
}

function Redact-SwitchTradeEngineText {
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

function Write-AtomicJson {
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)]$Value)
    $parent = Split-Path -Parent $Path
    if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    $temporary = "$Path.tmp.$([guid]::NewGuid().ToString('N'))"
    try {
        $Value | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $temporary -Encoding UTF8
        Move-Item -LiteralPath $temporary -Destination $Path -Force
    } finally {
        if (Test-Path -LiteralPath $temporary -PathType Leaf) {
            Remove-Item -LiteralPath $temporary -Force
        }
    }
}

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

function Write-SwitchTradeTreeIntegrity {
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][string]$ReleaseId
    )
    $rootPath = [IO.Path]::GetFullPath($Root).TrimEnd('\')
    $integrityPath = Join-Path $rootPath '.switchtrade-integrity.json'
    if (@(Get-ChildItem -LiteralPath $rootPath -Recurse -Force |
            Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count) {
        throw 'INSTALL_INTEGRITY_REPARSE_POINT: release tree cannot be redirected'
    }
    $artifacts = [ordered]@{}
    foreach ($item in @(Get-ChildItem -LiteralPath $rootPath -File -Recurse -Force |
            Where-Object { $_.FullName -ne $integrityPath } | Sort-Object FullName)) {
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw 'INSTALL_INTEGRITY_REPARSE_POINT: release files cannot be redirected'
        }
        $relative = $item.FullName.Substring($rootPath.Length + 1).Replace('\', '/')
        $artifacts[$relative] = Get-FileSha256 $item.FullName
    }
    Write-AtomicJson -Path $integrityPath -Value ([ordered]@{
        schema = 1; release_id = $ReleaseId; artifact_hashes = $artifacts
    })
    return Get-FileSha256 $integrityPath
}

function Test-SwitchTradeTreeIntegrity {
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][string]$ExpectedReleaseId,
        [Parameter(Mandatory)][ValidatePattern('^[0-9a-fA-F]{64}$')]
        [string]$ExpectedIntegritySha256
    )
    $rootPath = [IO.Path]::GetFullPath($Root).TrimEnd('\')
    $rootItem = Get-Item -LiteralPath $rootPath -Force
    if ($rootItem.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw 'INSTALL_INTEGRITY_REPARSE_POINT: release root cannot be redirected'
    }
    $integrityPath = Join-Path $rootPath '.switchtrade-integrity.json'
    if (@(Get-ChildItem -LiteralPath $rootPath -Recurse -Force |
            Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count) {
        throw 'INSTALL_INTEGRITY_REPARSE_POINT: release tree cannot be redirected'
    }
    if (-not (Test-Path -LiteralPath $integrityPath -PathType Leaf) -or
            (Get-FileSha256 $integrityPath) -ne $ExpectedIntegritySha256.ToLowerInvariant()) {
        throw 'INSTALL_INTEGRITY_MANIFEST_MISMATCH: release integrity anchor changed'
    }
    try { $integrity = Get-Content -Raw -LiteralPath $integrityPath | ConvertFrom-Json }
    catch { throw 'INSTALL_INTEGRITY_MANIFEST_INVALID: release integrity manifest is unreadable' }
    if ([int]$integrity.schema -ne 1 -or [string]$integrity.release_id -ne $ExpectedReleaseId -or
            -not $integrity.artifact_hashes) {
        throw 'INSTALL_INTEGRITY_MANIFEST_INVALID: release integrity identity is invalid'
    }
    $expected = @{}
    foreach ($property in $integrity.artifact_hashes.PSObject.Properties) {
        $relative = ([string]$property.Name).Replace('/', '\')
        if ([IO.Path]::IsPathRooted($relative) -or $relative -match '(^|\\)\.\.(\\|$)') {
            throw 'INSTALL_INTEGRITY_PATH_INVALID: release manifest contains an unsafe path'
        }
        $expected[$relative.ToLowerInvariant()] = ([string]$property.Value).ToLowerInvariant()
    }
    $actual = @{}
    foreach ($item in @(Get-ChildItem -LiteralPath $rootPath -File -Recurse -Force |
            Where-Object { $_.FullName -ne $integrityPath })) {
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw 'INSTALL_INTEGRITY_REPARSE_POINT: release files cannot be redirected'
        }
        $relative = $item.FullName.Substring($rootPath.Length + 1).ToLowerInvariant()
        $actual[$relative] = Get-FileSha256 $item.FullName
    }
    if ($actual.Count -ne $expected.Count) {
        throw 'INSTALL_INTEGRITY_ARTIFACT_SET_MISMATCH: release file set changed'
    }
    foreach ($relative in $expected.Keys) {
        if (-not $actual.ContainsKey($relative) -or $actual[$relative] -ne $expected[$relative]) {
            throw "INSTALL_INTEGRITY_ARTIFACT_MISMATCH: $relative"
        }
    }
    return $true
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

function New-SwitchTradeTransaction {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Action,
        [Parameter(Mandatory)][string]$ReleaseId,
        [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{32}$')][string]$InstallId,
        [Parameter(Mandatory)][string]$DistroBasePath,
        [string]$PriorReleaseId = '',
        [string]$WindowsStage = '',
        [string]$PackageRoot = '',
        [string]$InstallRoot = '',
        [string]$PreviousInstall = '',
        [string]$DistroName = '',
        [string]$DistroRoot = '',
        [bool]$DistroExistedBefore = $false,
        [bool]$DistroOwnedBefore = $false,
        [string]$WslPriorReleaseId = '',
        [string]$KernelPriorReleaseId = '',
        [string]$KernelStatePath = '',
        [string]$KernelPriorPath = '',
        [string]$KernelPriorModulesPath = '',
        [bool]$KernelChangeExpected = $false,
        [string]$WindowsPriorIntegritySha256 = '',
        [string]$WslPriorIntegritySha256 = '',
        [ValidatePattern('^$|^[0-9a-fA-F]{64}$')][string]$PackageManifestSha256 = ''
    )
    $state = [ordered]@{
        schema = 3
        transaction_id = [guid]::NewGuid().ToString('N')
        action = $Action
        release_id = $ReleaseId
        prior_release_id = $PriorReleaseId
        phase = 'created'
        windows_stage = $WindowsStage
        package_root = $PackageRoot
        package_manifest_sha256 = $PackageManifestSha256.ToLowerInvariant()
        install_root = $InstallRoot
        previous_install = $PreviousInstall
        distro_name = $DistroName
        distro_root = $DistroRoot
        distro_existed_before = $DistroExistedBefore
        distro_owned_before = $DistroOwnedBefore
        wsl_prior_release_id = $WslPriorReleaseId
        wsl_active_path = '/opt/switchtrade'
        wsl_candidate_path = '/opt/switchtrade.candidate'
        wsl_previous_path = '/opt/switchtrade.previous'
        wsl_commit_swap_path = '/opt/switchtrade.commit-swap'
        wsl_rollback_swap_path = '/opt/switchtrade.rollback-swap'
        kernel_prior_release_id = $KernelPriorReleaseId
        kernel_state_path = $KernelStatePath
        kernel_prior_path = $KernelPriorPath
        kernel_prior_modules_path = $KernelPriorModulesPath
        kernel_change_expected = $KernelChangeExpected
        install_id = $InstallId
        distro_base_path = $DistroBasePath
        windows_integrity_sha256 = ''
        wsl_integrity_sha256 = ''
        windows_prior_integrity_sha256 = $WindowsPriorIntegritySha256
        wsl_prior_integrity_sha256 = $WslPriorIntegritySha256
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

function Assert-SwitchTradeRecordedPath {
    param(
        [Parameter(Mandatory)][string]$Recorded,
        [Parameter(Mandatory)][string]$Expected,
        [Parameter(Mandatory)][string]$Code
    )
    $recordedPath = [IO.Path]::GetFullPath($Recorded).TrimEnd('\')
    $expectedPath = [IO.Path]::GetFullPath($Expected).TrimEnd('\')
    if (-not [string]::Equals($recordedPath, $expectedPath,
            [StringComparison]::OrdinalIgnoreCase)) {
        throw "$Code`: recorded path does not match this installation"
    }
    return $recordedPath
}

function Assert-SwitchTradeRecordedStagePath {
    param(
        [Parameter(Mandatory)][string]$Recorded,
        [Parameter(Mandatory)][string]$InstallRoot
    )
    $stage = [IO.Path]::GetFullPath($Recorded).TrimEnd('\')
    $parent = [IO.Path]::GetFullPath((Split-Path -Parent $InstallRoot)).TrimEnd('\')
    if (-not [string]::Equals((Split-Path -Parent $stage).TrimEnd('\'), $parent,
            [StringComparison]::OrdinalIgnoreCase) -or
        (Split-Path -Leaf $stage) -notmatch '^SwitchTrade\.stage\.[0-9a-f]{32}$') {
        throw 'SETUP_TRANSACTION_PATH_INVALID: recorded Windows stage is outside the installation boundary'
    }
    return $stage
}

function Remove-SwitchTradeRecoveryTree {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$ReparseCode
    )
    if (-not (Test-Path -LiteralPath $Path)) { return $false }
    $item = Get-Item -LiteralPath $Path -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "${ReparseCode}: refusing to remove a redirected recovery path"
    }
    Remove-Item -LiteralPath $Path -Recurse -Force
    return $true
}

function Move-SwitchTradeOrphanedWindowsTree {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$RecoveryRoot
    )
    if (-not (Test-Path -LiteralPath $Path)) { return '' }
    $item = Get-Item -LiteralPath $Path -Force
    if (-not $item.PSIsContainer -or
            ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'ORPHANED_INSTALL_PATH_INVALID: reserved recovery path is not a regular directory'
    }
    New-Item -ItemType Directory -Force -Path $RecoveryRoot | Out-Null
    $target = Join-Path $RecoveryRoot ("windows-orphan-$([DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ'))-$([guid]::NewGuid().ToString('N'))")
    Move-Item -LiteralPath $Path -Destination $target
    return $target
}

function Assert-SwitchTradeTransactionPackage {
    param(
        [Parameter(Mandatory)]$Transaction,
        [Parameter(Mandatory)][string]$PackageRoot,
        [Parameter(Mandatory)][string]$ReleaseId
    )
    $expectedRelease = [string]$Transaction.release_id
    $expectedRoot = [string]$Transaction.package_root
    $expectedManifestSha256 = if ($Transaction.PSObject.Properties.Name -contains 'package_manifest_sha256') {
        [string]$Transaction.package_manifest_sha256
    } else { '' }
    if ([string]$Transaction.phase -match '^rollback_') {
        $journal = Assert-SwitchTradeRollbackJournal -Transaction $Transaction
        $rollbackPackage = $journal.initiating_package
        $expectedRelease = [string]$rollbackPackage.release_id
        $expectedRoot = [string]$rollbackPackage.root
        $expectedManifestSha256 = [string]$rollbackPackage.manifest_sha256
    }
    $rootMatches = [string]::Equals(
                [IO.Path]::GetFullPath($expectedRoot).TrimEnd('\'),
                [IO.Path]::GetFullPath($PackageRoot).TrimEnd('\'),
                [StringComparison]::OrdinalIgnoreCase)
    if ($expectedRelease -ne $ReleaseId -or (-not $expectedManifestSha256 -and -not $rootMatches)) {
        throw 'SETUP_TRANSACTION_PACKAGE_MISMATCH: rerun Repair from the same verified package version that started the transaction'
    }
    if ($expectedManifestSha256 -and
            (Get-FileSha256 (Join-Path $PackageRoot 'manifest.json')) -ne $expectedManifestSha256) {
        throw 'SETUP_TRANSACTION_PACKAGE_MISMATCH: package manifest identity changed'
    }
}

function Assert-SwitchTradeRollbackJournal {
    param([Parameter(Mandatory)]$Transaction)
    $hasJournal = $Transaction.PSObject.Properties.Name -contains 'rollback_journal'
    if ([int]$Transaction.schema -ne 3 -or
            [string]$Transaction.phase -notmatch '^rollback_(prepared|wsl_committed|kernel_committed|windows_committed|recovering_source|recovering_target)$' -or
            -not $hasJournal -or -not $Transaction.rollback_journal -or
            [int]$Transaction.rollback_journal.schema -ne 2) {
        throw 'ROLLBACK_JOURNAL_INVALID: rollback intent is missing or not recoverable'
    }
    $journal = $Transaction.rollback_journal
    if ([string]$journal.source.release_id -ne [string]$Transaction.release_id -or
            [string]$journal.target.release_id -ne [string]$Transaction.prior_release_id -or
            [string]$journal.target.release_id -ne [string]$Transaction.wsl_prior_release_id) {
        throw 'ROLLBACK_JOURNAL_RELEASE_MISMATCH'
    }
    if ($journal.PSObject.Properties.Name -notcontains 'initiating_package' -or
            -not $journal.initiating_package -or
            [string]$journal.initiating_package.release_id -ne [string]$journal.source.release_id -or
            -not [string]$journal.initiating_package.root -or
            [string]$journal.initiating_package.manifest_sha256 -notmatch '^[0-9a-f]{64}$') {
        throw 'ROLLBACK_JOURNAL_PACKAGE_INVALID'
    }
    foreach ($axis in @($journal.source, $journal.target)) {
        if (-not [string]$axis.release_id -or -not [string]$axis.kernel_path) {
            throw 'ROLLBACK_JOURNAL_KERNEL_IDENTITY_INVALID'
        }
        foreach ($anchor in @([string]$axis.windows_integrity_sha256,
                [string]$axis.wsl_integrity_sha256, [string]$axis.kernel_sha256)) {
            if ($anchor -notmatch '^[0-9a-f]{64}$') { throw 'ROLLBACK_JOURNAL_ANCHOR_INVALID' }
        }
        if ([string]$axis.modules_path -and
                [string]$axis.modules_sha256 -notmatch '^[0-9a-f]{64}$') {
            throw 'ROLLBACK_JOURNAL_MODULE_ANCHOR_INVALID'
        }
    }
    return $journal
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
        [Parameter(Mandatory)][string]$ExpectedReleaseId,
        [string]$ExpectedActiveReleaseId = ''
    )
    $swap = "$Active.rollback-swap"
    if (Test-Path -LiteralPath $swap) {
        $swapRelease = Get-InstalledWindowsReleaseId -Root $swap
        if (-not $ExpectedActiveReleaseId) { $ExpectedActiveReleaseId = $swapRelease }
        Test-WindowsReleaseTree -Root $swap -ExpectedReleaseId $ExpectedActiveReleaseId | Out-Null
        if (-not (Test-Path -LiteralPath $Active)) {
            Test-WindowsReleaseTree -Root $Previous -ExpectedReleaseId $ExpectedReleaseId | Out-Null
            Move-Item -LiteralPath $Previous -Destination $Active
        }
        if (-not (Test-Path -LiteralPath $Previous)) {
            Test-WindowsReleaseTree -Root $Active -ExpectedReleaseId $ExpectedReleaseId | Out-Null
            Move-Item -LiteralPath $swap -Destination $Previous
        }
        if (Test-Path -LiteralPath $swap) { throw 'ROLLBACK_WINDOWS_SWAP_STALE' }
        return $ExpectedActiveReleaseId
    }
    Test-WindowsReleaseTree -Root $Previous -ExpectedReleaseId $ExpectedReleaseId | Out-Null
    $activeRelease = Get-InstalledWindowsReleaseId -Root $Active
    if ($ExpectedActiveReleaseId -and $activeRelease -ne $ExpectedActiveReleaseId) {
        throw 'ROLLBACK_WINDOWS_ACTIVE_RELEASE_MISMATCH'
    }
    Test-WindowsReleaseTree -Root $Active -ExpectedReleaseId $activeRelease | Out-Null
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

function Get-SwitchTradeTrustedInstalledAnchors {
    param(
        [Parameter(Mandatory)]$Transaction,
        [Parameter(Mandatory)][string]$ReleaseId
    )
    if ([int]$Transaction.schema -ne 3) {
        throw 'INSTALLED_INTEGRITY_ANCHOR_MISSING: prior release has no trusted schema 3 transaction'
    }
    if ([string]$Transaction.phase -eq 'completed' -and
            [string]$Transaction.release_id -eq $ReleaseId) {
        $windows = [string]$Transaction.windows_integrity_sha256
        $wsl = [string]$Transaction.wsl_integrity_sha256
    } elseif ([string]$Transaction.phase -eq 'compensated' -and
            [string]$Transaction.prior_release_id -eq $ReleaseId) {
        $windows = [string]$Transaction.windows_prior_integrity_sha256
        $wsl = [string]$Transaction.wsl_prior_integrity_sha256
    } else {
        throw 'INSTALLED_INTEGRITY_ANCHOR_MISSING: transaction does not anchor the active prior release'
    }
    if ($windows -notmatch '^[0-9a-f]{64}$' -or $wsl -notmatch '^[0-9a-f]{64}$') {
        throw 'INSTALLED_INTEGRITY_ANCHOR_MISSING: trusted release anchors are invalid'
    }
    return [pscustomobject]@{ Windows = $windows; Wsl = $wsl }
}

function Assert-SwitchTradeDistroMutationIdentity {
    param(
        [Parameter(Mandatory)]$Transaction,
        [Parameter(Mandatory)][string]$DistroName,
        [Parameter(Mandatory)][string]$DistroRoot,
        [Parameter(Mandatory)]$Actual
    )
    if (-not [bool]$Actual.EnumerationKnown) {
        throw 'WSL_DISTRO_ENUMERATION_UNKNOWN: destructive distribution state is unknown'
    }
    if ([int]$Transaction.schema -ne 3 -or [string]$Transaction.phase -ne 'completed' -or
            [string]$Transaction.distro_name -cne $DistroName -or
            [string]$Transaction.install_id -notmatch '^[0-9a-f]{32}$') {
        throw 'INSTALLED_DISTRO_IDENTITY_MISSING: destructive distro actions require a completed identity transaction'
    }
    Assert-SwitchTradeRecordedPath -Recorded ([string]$Transaction.distro_base_path) -Expected $DistroRoot -Code 'INSTALLED_DISTRO_PATH_MISMATCH' | Out-Null
    if (-not [bool]$Actual.DistroExists -or -not [bool]$Actual.RegistrationExists) {
        throw 'INSTALLED_DISTRO_MISSING: the recorded distribution is not currently registered'
    }
    if (-not [string]::Equals(
            [IO.Path]::GetFullPath([string]$Actual.BasePath).TrimEnd('\'),
            [IO.Path]::GetFullPath([string]$Transaction.distro_base_path).TrimEnd('\'),
            [StringComparison]::OrdinalIgnoreCase) -or
            -not [bool]$Actual.MarkerValid -or
            [string]$Actual.InstallId -cne [string]$Transaction.install_id) {
        throw 'INSTALLED_DISTRO_IDENTITY_CHANGED: registered BasePath or install identity changed'
    }
    return $true
}

function New-SwitchTradeRollbackJournal {
    param(
        [Parameter(Mandatory)]$Transaction,
        [Parameter(Mandatory)]$KernelState,
        [Parameter(Mandatory)][string]$PackageRoot,
        [Parameter(Mandatory)][string]$PackageReleaseId,
        [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{64}$')]
        [string]$PackageManifestSha256
    )
    if ([int]$Transaction.schema -ne 3 -or [string]$Transaction.phase -ne 'completed') {
        throw 'ROLLBACK_TRANSACTION_NOT_COMPLETED'
    }
    $sourceRelease = [string]$Transaction.release_id
    $targetRelease = [string]$Transaction.prior_release_id
    if (-not $sourceRelease -or -not $targetRelease -or
            [string]$Transaction.wsl_prior_release_id -ne $targetRelease -or
            [string]$KernelState.package_release_id -ne $sourceRelease -or
            [string]$KernelState.rollback_package_release_id -ne $targetRelease -or
            $PackageReleaseId -ne $sourceRelease) {
        throw 'ROLLBACK_JOURNAL_RELEASE_MISMATCH'
    }
    $packagePath = [IO.Path]::GetFullPath($PackageRoot).TrimEnd('\')
    $packageManifest = Join-Path $packagePath 'manifest.json'
    if (-not (Test-Path -LiteralPath $packageManifest -PathType Leaf) -or
            (Get-FileSha256 $packageManifest) -ne $PackageManifestSha256) {
        throw 'ROLLBACK_JOURNAL_PACKAGE_MISMATCH'
    }
    foreach ($anchor in @([string]$Transaction.windows_integrity_sha256,
            [string]$Transaction.windows_prior_integrity_sha256,
            [string]$Transaction.wsl_integrity_sha256,
            [string]$Transaction.wsl_prior_integrity_sha256,
            [string]$KernelState.kernel_sha256,
            [string]$KernelState.rollback_kernel_sha256)) {
        if ($anchor -notmatch '^[0-9a-f]{64}$') { throw 'ROLLBACK_JOURNAL_ANCHOR_INVALID' }
    }
    foreach ($artifact in @(
            [pscustomobject]@{ Path = [string]$KernelState.kernel_path; Hash = [string]$KernelState.kernel_sha256 },
            [pscustomobject]@{ Path = [string]$KernelState.rollback_kernel_path; Hash = [string]$KernelState.rollback_kernel_sha256 },
            [pscustomobject]@{ Path = [string]$KernelState.modules_path; Hash = [string]$KernelState.modules_sha256 },
            [pscustomobject]@{ Path = [string]$KernelState.rollback_modules_path; Hash = [string]$KernelState.rollback_modules_sha256 })) {
        if ($artifact.Path -and
                (-not (Test-Path -LiteralPath $artifact.Path -PathType Leaf) -or
                 (Get-FileSha256 $artifact.Path) -ne $artifact.Hash)) {
            throw 'ROLLBACK_JOURNAL_KERNEL_ARTIFACT_MISMATCH'
        }
    }
    return [ordered]@{
        schema = 2
        source_action = [string]$Transaction.action
        initiating_package = [ordered]@{
            root = $packagePath
            release_id = $PackageReleaseId
            manifest_sha256 = $PackageManifestSha256
        }
        source = [ordered]@{
            release_id = $sourceRelease
            windows_integrity_sha256 = [string]$Transaction.windows_integrity_sha256
            wsl_integrity_sha256 = [string]$Transaction.wsl_integrity_sha256
            kernel_path = [string]$KernelState.kernel_path
            modules_path = [string]$KernelState.modules_path
            kernel_release = [string]$KernelState.kernel_release
            modules_format = [string]$KernelState.modules_format
            kernel_sha256 = [string]$KernelState.kernel_sha256
            modules_sha256 = [string]$KernelState.modules_sha256
        }
        target = [ordered]@{
            release_id = $targetRelease
            windows_integrity_sha256 = [string]$Transaction.windows_prior_integrity_sha256
            wsl_integrity_sha256 = [string]$Transaction.wsl_prior_integrity_sha256
            kernel_path = [string]$KernelState.rollback_kernel_path
            modules_path = [string]$KernelState.rollback_modules_path
            kernel_release = [string]$KernelState.rollback_kernel_release
            modules_format = [string]$KernelState.rollback_modules_format
            kernel_sha256 = [string]$KernelState.rollback_kernel_sha256
            modules_sha256 = [string]$KernelState.rollback_modules_sha256
        }
    }
}

function Get-SwitchTradeRollbackPublishedState {
    param(
        [Parameter(Mandatory)]$Transaction,
        [Parameter(Mandatory)][ValidateSet('source', 'target')][string]$Direction
    )
    $journal = Assert-SwitchTradeRollbackJournal -Transaction $Transaction
    $active = $journal.$Direction
    $prior = if ($Direction -eq 'source') { $journal.target } else { $journal.source }
    $state = $Transaction | ConvertTo-Json -Depth 12 | ConvertFrom-Json
    $state.action = if ($Direction -eq 'source') { [string]$journal.source_action } else { 'Rollback' }
    $state.release_id = [string]$active.release_id
    $state.prior_release_id = [string]$prior.release_id
    $state.wsl_prior_release_id = [string]$prior.release_id
    $state.kernel_prior_release_id = [string]$prior.release_id
    $state.kernel_prior_path = [string]$prior.kernel_path
    $state.kernel_prior_modules_path = [string]$prior.modules_path
    $state.windows_integrity_sha256 = [string]$active.windows_integrity_sha256
    $state.windows_prior_integrity_sha256 = [string]$prior.windows_integrity_sha256
    $state.wsl_integrity_sha256 = [string]$active.wsl_integrity_sha256
    $state.wsl_prior_integrity_sha256 = [string]$prior.wsl_integrity_sha256
    $state.rollback_journal = $null
    $state.phase = 'completed'
    return $state
}

function Stop-SwitchTradeUsbWatcher {
    param([Parameter(Mandatory)][string]$StateRoot)
    $stateFile = Join-Path $StateRoot 'usb-watcher.json'
    if (-not (Test-Path -LiteralPath $stateFile -PathType Leaf)) { return $false }
    try { $state = Get-Content -Raw -LiteralPath $stateFile | ConvertFrom-Json }
    catch {
        Remove-Item -LiteralPath $stateFile -Force
        return $false
    }
    if ([int]$state.schema -ne 1 -or [int]$state.pid -le 0) {
        Remove-Item -LiteralPath $stateFile -Force
        return $false
    }
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $([int]$state.pid)" -ErrorAction SilentlyContinue
    if ($process) {
        $expectedScript = [regex]::Escape('UsbAutoAttachWatcher.ps1')
        $expectedState = [regex]::Escape([IO.Path]::GetFullPath($stateFile))
        if ([string]$process.CommandLine -notmatch $expectedScript -or
            [string]$process.CommandLine -notmatch $expectedState) {
            Remove-Item -LiteralPath $stateFile -Force
            return $false
        }
        Stop-Process -Id ([int]$state.pid) -Force -ErrorAction Stop
    }
    Remove-Item -LiteralPath $stateFile -Force
    return $true
}

function Clear-SwitchTradeResume {
    param([Parameter(Mandatory)]$Context)
    if (Test-Path -LiteralPath $Context.ResumeStatePath -PathType Leaf) {
        Remove-Item -LiteralPath $Context.ResumeStatePath -Force
    }
    $resumeRegistryPath = "Registry::HKEY_USERS\$($Context.InvokingUserSid)\Software\Microsoft\Windows\CurrentVersion\RunOnce"
    Remove-ItemProperty -Path $resumeRegistryPath -Name 'SwitchTradeSetupResume' -ErrorAction SilentlyContinue
}

function Save-SwitchTradeResume {
    param(
        [Parameter(Mandatory)]$Context,
        [Parameter(Mandatory)][string]$ResumeAction
    )
    if ($Context.BusId -and -not $Context.UsbInstanceId) {
        throw 'USB_STABLE_ID_REQUIRED: reselect the adapter before scheduling setup resume'
    }
    if ($Context.UsbInstanceId -and ($Context.UsbInstanceId.ToCharArray() | Where-Object { [char]::IsControl($_) })) {
        throw 'USB_STABLE_ID_INVALID: the adapter instance identity contains invalid characters'
    }
    New-Item -ItemType Directory -Force -Path $Context.StateRoot | Out-Null
    @{
        schema = 3; package_root = $Context.PackageRoot; action = $ResumeAction
        distro = $Context.Distro; install_root = $Context.InstallRoot; distro_root = $Context.DistroRoot
        user_profile_root = $Context.UserProfileRoot; local_app_data_root = $Context.LocalAppDataRoot
        desktop_root = $Context.DesktopRoot; invoking_user_sid = $Context.InvokingUserSid
        bus_id = $Context.BusId; usb_id = $Context.UsbId; usb_instance_id = $Context.UsbInstanceId
        accept_global_kernel_change = $Context.AcceptGlobalKernelChange
        accept_prerequisite_changes = $Context.AcceptPrerequisiteChanges
        accept_vmware_release = $Context.AcceptVmwareRelease
        defer_hardware_setup = $Context.DeferHardwareSetup
        no_shortcut = $Context.NoShortcut
    } | ConvertTo-Json | Set-Content -LiteralPath $Context.ResumeStatePath -Encoding UTF8
    $setupExe = Join-Path $Context.PackageRoot 'SwitchTradeSetup.exe'
    if (-not (Test-Path -LiteralPath $setupExe -PathType Leaf)) {
        throw 'SETUP_RESUME_UNAVAILABLE: the native setup executable is missing'
    }
    $command = "`"$setupExe`" resume"
    $resumeRegistryPath = "Registry::HKEY_USERS\$($Context.InvokingUserSid)\Software\Microsoft\Windows\CurrentVersion\RunOnce"
    New-Item -Path $resumeRegistryPath -Force | Out-Null
    Set-ItemProperty -Path $resumeRegistryPath -Name 'SwitchTradeSetupResume' -Value $command
}

function Assert-SwitchTradePlanPrecondition {
    param([Parameter(Mandatory)][bool]$Condition, [Parameter(Mandatory)][string]$Code, [Parameter(Mandatory)][string]$Message)
    if (-not $Condition) {
        throw "${Code}: $Message"
    }
}

function Invoke-SwitchTradeRequirePrerequisites {
    param([Parameter(Mandatory)]$Context, [Parameter(Mandatory)]$State, [Parameter(Mandatory)]$Package)
    Set-SwitchTradeEngineStage 'prerequisite_inspection'
    $hostState = $State.Host
    Assert-SwitchTradePlanPrecondition $hostState.WindowsSupported 'HOST_UNSUPPORTED' 'SwitchTrade requires Windows 10 22H2 x64 (build 19045) or Windows 11 x64.'
    Assert-SwitchTradePlanPrecondition ($hostState.FreeSpaceGB -ge 8) 'HOST_FREE_SPACE' 'SwitchTrade requires at least 8 GB of free space for safe install and rollback.'
    Assert-SwitchTradePlanPrecondition $hostState.VirtualizationReady 'HOST_VIRTUALIZATION' 'Hardware virtualization/Hyper-V is not available to WSL 2.'
    Assert-SwitchTradePlanPrecondition (Test-Path -LiteralPath (Join-Path $Context.PackageRoot 'payload\app') -PathType Container) 'PAYLOAD_MISSING' "application payload is missing: $(Join-Path $Context.PackageRoot 'payload\app')"
    Assert-SwitchTradePlanPrecondition (Test-Path -LiteralPath (Join-Path $Context.PackageRoot 'payload\release-config.json') -PathType Leaf) 'RELEASE_CONFIG_MISSING' 'signed installation configuration is missing'
    Assert-SwitchTradePlanPrecondition (-not $hostState.PendingReboot) 'WINDOWS_RESTART_PENDING' 'restart Windows before installing or repairing SwitchTrade'
    $desktopExe = Join-Path $Context.PackageRoot 'windows\SwitchTrade.exe'
    $desktopHash = Join-Path $Context.PackageRoot 'windows\SwitchTrade.exe.sha256'
    if (Test-Path -LiteralPath $desktopExe -PathType Leaf) {
        Assert-SwitchTradePlanPrecondition (Test-Path -LiteralPath $desktopHash -PathType Leaf) 'DESKTOP_HASH_MISSING' "desktop checksum is missing: $desktopHash"
        $expected = ((Get-Content -LiteralPath $desktopHash -TotalCount 1) -split '\s+')[0]
        Assert-SwitchTradePlanPrecondition ($expected -match '^[0-9a-fA-F]{64}$' -and
            $expected.ToLowerInvariant() -eq (Get-FileSha256 $desktopExe)) 'DESKTOP_HASH_MISMATCH' 'SwitchTrade desktop checksum verification failed.'
    }
}

function Invoke-SwitchTradeEnsureWsl {
    param([Parameter(Mandatory)]$Context, [Parameter(Mandatory)]$State)
    Set-SwitchTradeEngineStage 'prerequisites_enable'
    if (-not ($State.Host.WslRuntimeLaunchSafe -or $State.Host.WslFeaturesEnabled)) {
        Assert-SwitchTradePlanPrecondition $Context.AcceptPrerequisiteChanges 'PREREQUISITE_CONSENT_REQUIRED' 'WSL 2 is required and may require a reboot. Rerun after accepting prerequisite changes.'
        Assert-SwitchTradePlanPrecondition (Test-Path -LiteralPath (Join-Path $Context.PackageRoot 'SwitchTradeSetup.exe') -PathType Leaf) 'SETUP_RESUME_UNAVAILABLE' 'use the complete native setup package before enabling WSL'
        $dismWsl = Invoke-SwitchTradeProcess -FilePath 'dism.exe' -Arguments @('/online', '/enable-feature', '/featurename:Microsoft-Windows-Subsystem-Linux', '/all', '/norestart') -TimeoutSeconds 600
        Assert-SwitchTradePlanPrecondition ($dismWsl.ExitCode -in @(0, 3010)) 'WSL_FEATURE_ENABLE_FAILED' "dism exited $($dismWsl.ExitCode): $($dismWsl.Error)"
        $dismVm = Invoke-SwitchTradeProcess -FilePath 'dism.exe' -Arguments @('/online', '/enable-feature', '/featurename:VirtualMachinePlatform', '/all', '/norestart') -TimeoutSeconds 600
        Assert-SwitchTradePlanPrecondition ($dismVm.ExitCode -in @(0, 3010)) 'VIRTUAL_MACHINE_PLATFORM_ENABLE_FAILED' "dism exited $($dismVm.ExitCode): $($dismVm.Error)"
        Save-SwitchTradeResume -Context $Context -ResumeAction $Context.Action
        return 'reboot_required'
    }
    if (-not $State.WslCapability.CapabilityReady) {
        Assert-SwitchTradePlanPrecondition $Context.AcceptPrerequisiteChanges 'PREREQUISITE_CONSENT_REQUIRED' 'The current Microsoft Store version of WSL 2 is required. Rerun after accepting prerequisite changes.'
        $wslUpdate = Invoke-SwitchTradeWsl -Arguments @('--update', '--web-download') -TimeoutSeconds 600
        if ($wslUpdate.ExitCode -ne 0) {
            $wslUpdate = Invoke-SwitchTradeWsl -Arguments @('--update') -TimeoutSeconds 600
        }
        Assert-SwitchTradePlanPrecondition ($wslUpdate.ExitCode -eq 0) 'WSL_UPDATE_FAILED' 'install the current Microsoft Store WSL package, restart Windows, and run Setup again.'
    }
    return 'ready'
}

function Invoke-SwitchTradeEnsureUsbipd {
    param([Parameter(Mandatory)]$Context, [Parameter(Mandatory)]$State)
    Set-SwitchTradeEngineStage 'usbipd_install'
    if ($State.UsbipdInstalled) { return 'ready' }
    Assert-SwitchTradePlanPrecondition $Context.AcceptPrerequisiteChanges 'PREREQUISITE_CONSENT_REQUIRED' 'usbipd-win is required. Rerun after accepting prerequisite changes.'
    Assert-SwitchTradePlanPrecondition (Test-Path -LiteralPath (Join-Path $Context.PackageRoot 'SwitchTradeSetup.exe') -PathType Leaf) 'SETUP_RESUME_UNAVAILABLE' 'use the complete native setup package before installing usbipd-win'
    $usbipdMsi = Join-Path $Context.PackageRoot 'payload\prerequisites\usbipd-win.msi'
    $usbipdManifest = Join-Path $Context.PackageRoot 'payload\prerequisites\usbipd-win.json'
    Assert-SwitchTradePlanPrecondition ((Test-Path -LiteralPath $usbipdMsi -PathType Leaf) -and (Test-Path -LiteralPath $usbipdManifest -PathType Leaf)) 'USBIPD_PACKAGE_MISSING' 'the pinned usbipd-win installer is missing from this package'
    $usbipdMetadata = Get-Content -Raw -LiteralPath $usbipdManifest | ConvertFrom-Json
    Assert-SwitchTradePlanPrecondition ((Get-FileSha256 $usbipdMsi) -eq ([string]$usbipdMetadata.sha256).ToLowerInvariant()) 'USBIPD_HASH_MISMATCH' 'usbipd-win installer checksum verification failed'
    $msi = Invoke-SwitchTradeProcess -FilePath 'msiexec.exe' -Arguments @('/i', $usbipdMsi, '/qn', '/norestart') -TimeoutSeconds 600
    Assert-SwitchTradePlanPrecondition ($msi.ExitCode -in @(0, 3010)) 'USBIPD_INSTALL_FAILED' "exit $($msi.ExitCode) $($msi.Error)"
    if ($msi.ExitCode -eq 3010) {
        Save-SwitchTradeResume -Context $Context -ResumeAction $Context.Action
        return 'reboot_required'
    }
    return 'ready'
}

function Invoke-SwitchTradeCreateTransaction {
    param([Parameter(Mandatory)]$Context, [Parameter(Mandatory)]$State, [Parameter(Mandatory)]$Package)
    Set-SwitchTradeEngineStage 'transaction'
    $identity = $State.Identity
    $priorReleaseId = $State.WindowsActive.ReleaseId
    $wslPriorReleaseId = $State.WslActive.ReleaseId
    $kernelState = $State.Kernel
    $kernelPriorReleaseId = if ($kernelState.Exists) { $kernelState.ReleaseId } else { '' }
    $kernelPriorPath = ''
    $kernelPriorModulesPath = ''
    $windowsPriorIntegrity = ''
    $wslPriorIntegrity = ''
    if ($priorReleaseId) {
        $installedAnchors = Get-SwitchTradeTrustedInstalledAnchors -Transaction $State.Transaction.Transaction -ReleaseId $priorReleaseId
        $windowsPriorIntegrity = $installedAnchors.Windows
        $wslPriorIntegrity = $installedAnchors.Wsl
    }
    if ($kernelState.State) {
        $kernelPriorPath = if ($kernelState.State.PSObject.Properties.Name -contains 'kernel_path') { [string]$kernelState.State.kernel_path } else { '' }
        $kernelPriorModulesPath = if ($kernelState.State.PSObject.Properties.Name -contains 'modules_path') { [string]$kernelState.State.modules_path } else { '' }
    }
    $installId = if ($identity.DistroExists -and $State.Transaction.Transaction -and [string]$State.Transaction.Transaction.install_id) {
        [string]$State.Transaction.Transaction.install_id
    } elseif (-not $identity.DistroExists) { [guid]::NewGuid().ToString('N') } else { '' }
    if ($identity.DistroExists -and -not $installId) {
        throw 'INSTALLED_DISTRO_IDENTITY_MISSING: run a signed migration package before mutating this distribution'
    }
    $kernelChangeExpected = (Test-Path -LiteralPath (Join-Path $Context.PackageRoot 'payload\kernel\kernel') -PathType Leaf) -and
        (Test-Path -LiteralPath (Join-Path $Context.PackageRoot 'payload\kernel\manifest.json') -PathType Leaf)
    $stage = Join-Path $State.StageParent ("SwitchTrade.stage." + [guid]::NewGuid().ToString('N'))
    $transactionParameters = @{
        Path = $Context.TransactionPath
        Action = $Context.Action
        ReleaseId = $Package.ReleaseId
        PriorReleaseId = $priorReleaseId
        WindowsStage = $stage
        PackageRoot = $Context.PackageRoot
        InstallRoot = $Context.InstallRoot
        PreviousInstall = $Context.PreviousInstall
        DistroName = $Context.Distro
        DistroRoot = $Context.DistroRoot
        DistroExistedBefore = $identity.DistroExists
        DistroOwnedBefore = ($identity.Classification -eq 'present_owned')
        WslPriorReleaseId = $wslPriorReleaseId
        KernelPriorReleaseId = $kernelPriorReleaseId
        KernelStatePath = $Context.KernelStatePath
        KernelPriorPath = $kernelPriorPath
        KernelPriorModulesPath = $kernelPriorModulesPath
        KernelChangeExpected = $kernelChangeExpected
        InstallId = $installId
        DistroBasePath = $Context.DistroRoot
        PackageManifestSha256 = $Package.ManifestSha256
        WindowsPriorIntegritySha256 = $windowsPriorIntegrity
        WslPriorIntegritySha256 = $wslPriorIntegrity
    }
    return New-SwitchTradeTransaction @transactionParameters
}

function Invoke-SwitchTradeStageWindows {
    param([Parameter(Mandatory)]$Context, [Parameter(Mandatory)]$Transaction)
    Set-SwitchTradeEngineStage 'windows_stage'
    $stage = [string]$Transaction.windows_stage
    New-Item -ItemType Directory -Path $stage | Out-Null
    Copy-Item -LiteralPath (Join-Path $Context.PackageRoot 'installer') -Destination $stage -Recurse
    Copy-Item -LiteralPath (Join-Path $Context.PackageRoot 'payload\app') -Destination $stage -Recurse
    Copy-Item -LiteralPath (Join-Path $Context.PackageRoot 'manifest.json') -Destination $stage
    if (Test-Path -LiteralPath (Join-Path $Context.PackageRoot 'manifest.json.p7s') -PathType Leaf) {
        Copy-Item -LiteralPath (Join-Path $Context.PackageRoot 'manifest.json.p7s') -Destination $stage
    }
    Copy-Item -LiteralPath (Join-Path $Context.PackageRoot 'payload\release-config.json') -Destination (Join-Path $stage 'config.json')
    $desktopExe = Join-Path $Context.PackageRoot 'windows\SwitchTrade.exe'
    if (Test-Path -LiteralPath $desktopExe -PathType Leaf) {
        Copy-Item -LiteralPath $desktopExe -Destination (Join-Path $stage 'SwitchTrade.exe')
    }
    Write-WindowsReleaseMarker -Root $stage -ReleaseId ([string]$Transaction.release_id)
    Test-WindowsReleaseTree -Root $stage -ExpectedReleaseId ([string]$Transaction.release_id) | Out-Null
    return Write-SwitchTradeTreeIntegrity -Root $stage -ReleaseId ([string]$Transaction.release_id)
}

function Invoke-SwitchTradeEnsureDistro {
    param([Parameter(Mandatory)]$Context, [Parameter(Mandatory)]$Transaction, [Parameter(Mandatory)]$State)
    Set-SwitchTradeEngineStage 'distro_identity'
    $identity = $State.Identity
    $installId = [string]$Transaction.install_id
    if (-not $identity.DistroExists) {
        $rootfs = Join-Path $Context.PackageRoot 'payload\switchtrade-rootfs.tar.gz'
        $rootfsHash = Join-Path $Context.PackageRoot 'payload\switchtrade-rootfs.sha256'
        Assert-SwitchTradePlanPrecondition (Test-Path -LiteralPath $rootfs -PathType Leaf) 'ROOTFS_MISSING' "rootfs is missing: $rootfs"
        Assert-SwitchTradePlanPrecondition (Test-Path -LiteralPath $rootfsHash -PathType Leaf) 'ROOTFS_HASH_MISSING' "rootfs checksum is missing: $rootfsHash"
        $expectedHash = ((Get-Content -LiteralPath $rootfsHash -TotalCount 1) -split '\s+')[0]
        Assert-SwitchTradePlanPrecondition ($expectedHash -match '^[0-9a-fA-F]{64}$' -and
            $expectedHash.ToLowerInvariant() -eq (Get-FileSha256 $rootfs)) 'ROOTFS_HASH_MISMATCH' 'SwitchTrade rootfs checksum verification failed'
        New-Item -ItemType Directory -Force -Path $Context.DistroRoot | Out-Null
        $transaction = Set-SwitchTradeTransactionPhase -Path $Context.TransactionPath -Phase 'importing_distro'
        $import = Invoke-SwitchTradeWsl -Arguments @('--import', $Context.Distro, $Context.DistroRoot, $rootfs, '--version', '2') -TimeoutSeconds 600
        if ($import.ExitCode -ne 0) {
            throw "DISTRO_IMPORT_FAILED: $($import.Error)"
        }
        $registration = Get-SwitchTradeDistroRegistrationState -Context $Context
        Assert-SwitchTradePlanPrecondition ($registration.Exists -and
            [string]::Equals($registration.BasePath, [IO.Path]::GetFullPath($Context.DistroRoot).TrimEnd('\'),
                [StringComparison]::OrdinalIgnoreCase)) 'DISTRO_IMPORT_BASE_PATH_MISMATCH' 'imported distribution registration changed'
        Set-SwitchTradeDistroMarker -Distro $Context.Distro -InstallId $installId | Out-Null
        Set-SwitchTradeTransactionPhase -Path $Context.TransactionPath -Phase 'distro_imported' -Fields @{ distro_imported = $true } | Out-Null
        $probe = Get-SwitchTradeDistroMarkerProbe -Distro $Context.Distro
        Assert-SwitchTradePlanPrecondition ($probe.Valid -and $probe.InstallId -ceq $installId) 'DISTRO_INSTALL_ID_WRITE_FAILED' 'installed distribution marker verification failed'
        return
    }
    Assert-SwitchTradePlanPrecondition ($identity.Classification -eq 'present_owned' -and $identity.InstallId -ceq $installId) 'DISTRO_NAME_COLLISION' "'$($Context.Distro)' exists but is not owned by SwitchTrade Setup; choose another distro name"
}

function Invoke-SwitchTradeProvisionStage {
    param([Parameter(Mandatory)]$Context, [Parameter(Mandatory)]$Transaction)
    Set-SwitchTradeEngineStage 'wsl_stage'
    Set-SwitchTradeTransactionPhase -Path $Context.TransactionPath -Phase 'staging_wsl' | Out-Null
    $source = ConvertTo-SwitchTradeWslPath -Path (Join-Path $Context.PackageRoot 'payload\app')
    $provision = Join-Path $Context.PackageRoot 'installer\provision-wsl.sh'
    $result = Invoke-SwitchTradeWslProvision -Distro $Context.Distro -ScriptPath $provision -Mode stage -Arguments @('--source', $source, '--release-id', ([string]$Transaction.release_id)) -TimeoutSeconds 600
    if ($result.ExitCode -ne 0) { throw "WSL_STAGE_FAILED: $($result.Error)" }
    $candidate = Get-SwitchTradeWslRuntimeLocationProbe -Distro $Context.Distro -Location candidate
    Assert-SwitchTradePlanPrecondition ($candidate.Valid -and $candidate.ReleaseId -eq ([string]$Transaction.release_id)) 'WSL_STAGE_INTEGRITY_MISSING' 'staged runtime has no exact integrity manifest'
    Set-SwitchTradeTransactionPhase -Path $Context.TransactionPath -Phase 'wsl_staged' -Fields @{ wsl_staged = $true; wsl_integrity_sha256 = $candidate.IntegritySha256 } | Out-Null
    return $candidate.IntegritySha256
}

function Invoke-SwitchTradeProvisionValidate {
    param([Parameter(Mandatory)]$Context, [Parameter(Mandatory)]$Transaction)
    Set-SwitchTradeEngineStage 'wsl_validate'
    $provision = Join-Path $Context.PackageRoot 'installer\provision-wsl.sh'
    $result = Invoke-SwitchTradeWslProvision -Distro $Context.Distro -ScriptPath $provision -Mode validate -Arguments @('--release-id', ([string]$Transaction.release_id)) -TimeoutSeconds 600
    if ($result.ExitCode -ne 0) { throw "WSL_VALIDATE_FAILED: $($result.Error)" }
    Set-SwitchTradeTransactionPhase -Path $Context.TransactionPath -Phase 'software_validated' | Out-Null
}
function Test-SwitchTradeStagedControlReadiness {
    param([Parameter(Mandatory)]$Context, [Parameter(Mandatory)][string]$ExpectedReleaseId)
    Set-SwitchTradeEngineStage 'control_readiness'
    $port = 18787
    $arguments = @(
        '-d', $Context.Distro, '-u', 'root', '--cd', '/opt/switchtrade.candidate', '--exec',
        'env', "SWITCHTRADE_CONTROL_PORT=$port", 'SWITCHTRADE_CONTROL_INSTANCE=setup-candidate',
        'SWITCHTRADE_RELEASE_ROOT=/opt/switchtrade.candidate',
        '/opt/switchtrade.candidate/bridge/.venv/bin/python', '-m', 'switchtrade.control'
    )
    $wsl = Get-SwitchTradeWslClientPath
    $process = New-Object Diagnostics.Process
    $start = New-Object Diagnostics.ProcessStartInfo
    $start.FileName = $wsl
    $start.Arguments = (($arguments | ForEach-Object { ConvertTo-NativeCommandLineArgument ([string]$_) }) -join ' ')
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $process.StartInfo = $start
    $ready = $false
    try {
        if (-not $process.Start()) { throw "PROCESS_START_FAILED: $wsl" }
        for ($attempt = 0; $attempt -lt 30; $attempt++) {
            if ($process.HasExited) { break }
            try {
                $probe = Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/v1/app/readiness" -TimeoutSec 1
                if ($probe.contract_version -eq 'app-readiness.v1' -and $probe.compatible -and
                    [string]$probe.release_id -eq $ExpectedReleaseId) { $ready = $true; break }
            } catch { }
            Start-Sleep -Milliseconds 500
        }
    } finally {
        if (-not $process.HasExited) {
            try { $process.Kill() } catch { }
        }
        try { Invoke-SwitchTradeWsl -Arguments @('--terminate', $Context.Distro) -TimeoutSeconds 30 | Out-Null } catch { }
    }
    Assert-SwitchTradePlanPrecondition $ready 'STAGED_CONTROL_NOT_READY' 'staged control did not advertise the package release'
}
function Invoke-SwitchTradeApplyKernel {
    param([Parameter(Mandatory)]$Context, [Parameter(Mandatory)]$Transaction, [Parameter(Mandatory)]$State)
    Set-SwitchTradeEngineStage 'kernel_apply'
    $kernel = Join-Path $Context.PackageRoot 'payload\kernel\kernel'
    $kernelManifest = Join-Path $Context.PackageRoot 'payload\kernel\manifest.json'
    if (-not ((Test-Path -LiteralPath $kernel -PathType Leaf) -and (Test-Path -LiteralPath $kernelManifest -PathType Leaf))) {
        return
    }
    $priorReleaseId = [string]$Transaction.prior_release_id
    if ($priorReleaseId) {
        Initialize-SwitchTradeKernelReleaseIdentity -StateRoot $Context.StateRoot -CurrentReleaseId $priorReleaseId | Out-Null
    }
    $kernelArguments = @{
        Kernel = $kernel; Manifest = $kernelManifest; StateRoot = $Context.StateRoot
        KernelStorageRoot = (Join-Path $env:ProgramData 'SwitchTrade\kernel'); ReleaseId = ([string]$Transaction.release_id)
        UserProfileRoot = $Context.UserProfileRoot
        AcceptGlobalKernelChange = $Context.AcceptGlobalKernelChange
    }
    $modulesCandidates = @(
        (Join-Path $Context.PackageRoot 'payload\kernel\modules.vhdx'),
        (Join-Path $Context.PackageRoot 'payload\kernel\modules.vhd'),
        (Join-Path $Context.PackageRoot 'payload\kernel\modules.tar.gz')
    )
    $kernelModules = @($modulesCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1)
    if ($kernelModules) { $kernelArguments.KernelModules = $kernelModules }
    $kernelState = Install-SwitchTradeKernel @kernelArguments
    Set-SwitchTradeTransactionPhase -Path $Context.TransactionPath -Phase 'kernel_applied' -Fields @{ kernel_applied = $true } | Out-Null
    $kernelProbe = Invoke-SwitchTradeWslCommand -Distro $Context.Distro -Command @('uname', '-r') -TimeoutSeconds 30
    $kernelOutput = ($kernelProbe.Output + $kernelProbe.Error).Trim()
    if ($kernelProbe.ExitCode -ne 0 -or $kernelOutput -ne [string]$kernelState.kernel_release) {
        if ($kernelOutput -match '(?i)policy|blocked|access.+denied|administrator') {
            throw "CUSTOM_KERNEL_BLOCKED_BY_POLICY: this managed PC is unsupported by the private beta. $kernelOutput"
        }
        throw "CUSTOM_KERNEL_START_FAILED: expected $($kernelState.kernel_release), got $kernelOutput"
    }
    if ($kernelModules -and $kernelState.modules_format -eq 'archive') {
        Install-SwitchTradeKernelModulesArchive -Distro $Context.Distro -ModulesArchiveWindowsPath $kernelModules -KernelRelease ([string]$kernelState.kernel_release) | Out-Null
    }
    if ($kernelModules) {
        $kernelMetadata = Get-Content -Raw -LiteralPath $kernelManifest | ConvertFrom-Json
        $firmwareDigest = if ($kernelMetadata.PSObject.Properties.Name -contains 'firmware_sha256') {
            [string]$kernelMetadata.firmware_sha256
        } else { '' }
        $abiResult = Test-SwitchTradeKernelModuleAbi -Distro $Context.Distro -KernelRelease ([string]$kernelState.kernel_release) -FirmwareDigest $firmwareDigest
        if ($abiResult.ExitCode -ne 0) { throw "KERNEL_ABI_OR_FIRMWARE_MISMATCH: $($abiResult.Error)" }
    }
}

function Invoke-SwitchTradeProvisionCommit {
    param([Parameter(Mandatory)]$Context, [Parameter(Mandatory)]$Transaction)
    Set-SwitchTradeEngineStage 'commit'
    $provision = Join-Path $Context.PackageRoot 'installer\provision-wsl.sh'
    $integrity = [string]$Transaction.wsl_integrity_sha256
    $result = Invoke-SwitchTradeWslProvision -Distro $Context.Distro -ScriptPath $provision -Mode commit -Arguments @('--release-id', ([string]$Transaction.release_id), '--integrity-sha256', $integrity) -TimeoutSeconds 600
    if ($result.ExitCode -ne 0) { throw "WSL_COMMIT_FAILED: $($result.Error)" }
    Set-SwitchTradeTransactionPhase -Path $Context.TransactionPath -Phase 'wsl_committed' -Fields @{ wsl_committed = $true } | Out-Null
}

function Invoke-SwitchTradeCommitWindows {
    param([Parameter(Mandatory)]$Context, [Parameter(Mandatory)]$Transaction)
    Set-SwitchTradeEngineStage 'commit'
    $stage = [string]$Transaction.windows_stage
    $priorReleaseId = [string]$Transaction.prior_release_id
    $committedPrior = Commit-SwitchTradeWindowsRelease -Candidate $stage -Active $Context.InstallRoot -Previous $Context.PreviousInstall -ExpectedReleaseId ([string]$Transaction.release_id)
    if ($committedPrior -ne $priorReleaseId) { throw 'WINDOWS_PRIOR_RELEASE_CHANGED: setup state changed during commit' }
    Set-SwitchTradeTransactionPhase -Path $Context.TransactionPath -Phase 'completed' -Fields @{ windows_committed = $true } | Out-Null
}

function Invoke-SwitchTradeHardwarePrepare {
    param([Parameter(Mandatory)]$Context, [Parameter(Mandatory)]$State)
    if ($State.Host.VmwareUsbArbitrator -eq 'Running') {
        Set-SwitchTradeEngineStage 'hardware_ownership'
        if (-not $Context.AcceptVmwareRelease) {
            throw 'VMWARE_USB_OWNERSHIP_REQUIRED: run Setup Repair after accepting the temporary VMware USB release'
        }
        Stop-Service VMUSBArbService -Force
    }
    if ($Context.DeferHardwareSetup) { return }
    Set-SwitchTradeEngineStage 'hardware_readiness'
    $radioPreflight = Join-Path $Context.PackageRoot 'payload\app\scripts\windows\wsl-radio-preflight.ps1'
    $profileFile = Join-Path $Context.PackageRoot 'payload\app\config\wsl-radio-hardware.tsv'
    $preflightArguments = @{
        Distro = $Context.Distro; ProfileFile = $profileFile; Prepare = $true; AutoAttach = $true
        InstanceId = $Context.UsbInstanceId; WatcherStateRoot = $Context.StateRoot
        WatcherScript = (Join-Path $Context.InstallRoot 'installer\UsbAutoAttachWatcher.ps1')
        LifecycleScript = (Join-Path $Context.InstallRoot 'installer\SetupLifecycle.ps1')
    }
    if ($Context.BusId) { $preflightArguments.BusId = $Context.BusId }
    if ($Context.UsbId) { $preflightArguments.UsbId = @($Context.UsbId) }
    & $radioPreflight @preflightArguments
    if ($LASTEXITCODE -ne 0) { throw 'USB_OWNERSHIP_PREFLIGHT_FAILED: reconnect the selected adapter and run Setup Repair' }
    $watcherCommand = Get-SwitchTradeUsbWatcherCommand -ScriptPath $preflightArguments.WatcherScript -Distro $Context.Distro -InstanceId $Context.UsbInstanceId -StateFile (Join-Path $Context.StateRoot 'usb-watcher.json')
    $startupRegistryPath = "Registry::HKEY_USERS\$($Context.InvokingUserSid)\Software\Microsoft\Windows\CurrentVersion\Run"
    New-Item -Path $startupRegistryPath -Force | Out-Null
    Set-ItemProperty -Path $startupRegistryPath -Name 'SwitchTradeUsbWatcher' -Value $watcherCommand
    $wslHealthArguments = @(
        '-d', $Context.Distro, '-u', 'root', '--cd', '/opt/switchtrade', '--exec',
        './scripts/wsl-radio-prepare.sh', '--role', 'guest',
        '--health-channels', '1,6,11', '--target-channel', '6'
    )
    if ($Context.UsbId) { $wslHealthArguments += @('--usb-id', $Context.UsbId.ToLowerInvariant()) }
    $health = Invoke-SwitchTradeWsl -Arguments $wslHealthArguments -TimeoutSeconds 600
    if ($health.ExitCode -ne 0) { throw "RADIO_RX_HEALTH_FAILED: $($health.Error)" }
    if ($Context.UsbInstanceId -and $Context.UsbId -and $Context.BusId) {
        $windowsSelection = Write-SwitchTradeHardwareSelection -StateRoot $Context.StateRoot -UsbId $Context.UsbId -InstanceId $Context.UsbInstanceId -BusId $Context.BusId
        $selectionSource = ConvertTo-SwitchTradeWslPath -Path $windowsSelection
        $selectionRoot = '/root/.local/state/switchtrade/runtime'
        $selectionTarget = "$selectionRoot/hardware-selection.json"
        $selectionTemporary = "$selectionRoot/.hardware-selection.tmp"
        $mkdir = Invoke-SwitchTradeWslCommand -Distro $Context.Distro -Command @('install', '-d', '-m', '0700', $selectionRoot) -TimeoutSeconds 60
        if ($mkdir.ExitCode -ne 0) { throw "HARDWARE_SELECTION_IMPORT_FAILED: $($mkdir.Error)" }
        try {
            $copy = Invoke-SwitchTradeWslCommand -Distro $Context.Distro -Command @('install', '-m', '0600', $selectionSource, $selectionTemporary) -TimeoutSeconds 60
            if ($copy.ExitCode -ne 0) { throw "HARDWARE_SELECTION_IMPORT_FAILED: $($copy.Error)" }
            $move = Invoke-SwitchTradeWslCommand -Distro $Context.Distro -Command @('mv', '-f', $selectionTemporary, $selectionTarget) -TimeoutSeconds 60
            if ($move.ExitCode -ne 0) { throw "HARDWARE_SELECTION_IMPORT_FAILED: $($move.Error)" }
        } finally {
            $cleanup = Invoke-SwitchTradeWslCommand -Distro $Context.Distro -Command @('rm', '-f', $selectionTemporary) -TimeoutSeconds 60
        }
    }
}

function Invoke-SwitchTradeGateRecoveryAction {
    param([Parameter(Mandatory)]$Context, [Parameter(Mandatory)]$State)
    Set-SwitchTradeEngineStage 'transaction_recovery'
    $transaction = $State.Transaction.Transaction
    if ($Context.Action -ne 'Repair' -and $Context.Action -ne [string]$transaction.action) {
        throw "SETUP_TRANSACTION_INCOMPLETE: transaction $($transaction.transaction_id) stopped at $($transaction.phase); rerun the same action or choose Repair from the package that started it"
    }
}
function Invoke-SwitchTradeGateRecoveryPackage {
    param([Parameter(Mandatory)]$Context, [Parameter(Mandatory)]$State, [Parameter(Mandatory)]$Package)
    $transaction = $State.Transaction.Transaction
    if (-not (Test-SwitchTradeEarlyFreshInstallRecovery -Transaction $transaction)) {
        Assert-SwitchTradeTransactionPackage -Transaction $transaction -PackageRoot $Context.PackageRoot -ReleaseId $Package.ReleaseId
    }
}
function Invoke-SwitchTradeGateRecoveryPaths {
    param([Parameter(Mandatory)]$Context, [Parameter(Mandatory)]$State)
    $transaction = $State.Transaction.Transaction
    Assert-SwitchTradeRecordedPath -Recorded ([string]$transaction.install_root) -Expected $Context.InstallRoot -Code 'SETUP_TRANSACTION_INSTALL_PATH_MISMATCH' | Out-Null
    Assert-SwitchTradeRecordedPath -Recorded ([string]$transaction.previous_install) -Expected $Context.PreviousInstall -Code 'SETUP_TRANSACTION_PREVIOUS_PATH_MISMATCH' | Out-Null
    Assert-SwitchTradeRecordedPath -Recorded ([string]$transaction.distro_root) -Expected $Context.DistroRoot -Code 'SETUP_TRANSACTION_DISTRO_PATH_MISMATCH' | Out-Null
    Assert-SwitchTradeRecordedPath -Recorded ([string]$transaction.distro_base_path) -Expected $Context.DistroRoot -Code 'SETUP_TRANSACTION_DISTRO_BASE_PATH_MISMATCH' | Out-Null
    Assert-SwitchTradeRecordedPath -Recorded ([string]$transaction.kernel_state_path) -Expected $Context.KernelStatePath -Code 'SETUP_TRANSACTION_KERNEL_PATH_MISMATCH' | Out-Null
    if ([string]$transaction.distro_name -cne $Context.Distro) {
        throw 'SETUP_TRANSACTION_DISTRO_MISMATCH: recorded distribution name does not match Repair'
    }
    if ([string]$transaction.install_id -notmatch '^[0-9a-f]{32}$') {
        throw 'SETUP_TRANSACTION_INSTALL_ID_INVALID: recorded distribution identity is invalid'
    }
    $expectedWslPaths = @{
        wsl_active_path = '/opt/switchtrade'; wsl_candidate_path = '/opt/switchtrade.candidate'
        wsl_previous_path = '/opt/switchtrade.previous'
        wsl_commit_swap_path = '/opt/switchtrade.commit-swap'
        wsl_rollback_swap_path = '/opt/switchtrade.rollback-swap'
    }
    foreach ($property in $expectedWslPaths.Keys) {
        if ([string]$transaction.$property -cne $expectedWslPaths[$property]) {
            throw 'SETUP_TRANSACTION_WSL_PATH_MISMATCH: recorded runtime paths are not the fixed product paths'
        }
    }
    Assert-SwitchTradeRecordedStagePath -Recorded ([string]$transaction.windows_stage) -InstallRoot $Context.InstallRoot | Out-Null
}
function Invoke-SwitchTradeGateRecoveryIdentity {
    param([Parameter(Mandatory)]$Context, [Parameter(Mandatory)]$State)
    $identity = $State.Identity
    if (-not $identity.EnumerationKnown) {
        throw 'WSL_DISTRO_ENUMERATION_UNKNOWN: CLI and Lxss registration disagree'
    }
    if ($identity.DistroExists -and $identity.Classification -notin @('present_owned', 'present_generic')) {
        throw 'SETUP_TRANSACTION_DISTRO_OWNERSHIP_CHANGED: the named distribution is not installer-owned'
    }
}
function Invoke-SwitchTradeBootstrapMarker {
    param([Parameter(Mandatory)]$Context, [Parameter(Mandatory)]$State)
    $transaction = $State.Transaction.Transaction
    $identity = $State.Identity
    if ($identity.DistroExists -and (Test-SwitchTradeFreshImportMarkerBootstrap -Transaction $transaction -State $State)) {
        Set-SwitchTradeDistroMarker -Distro $Context.Distro -InstallId ([string]$transaction.install_id) | Out-Null
        Write-SwitchTradeEngineLog -Stage 'transaction_recovery' -Message 'bootstrapped the ownership marker for the markerless fresh import'
    }
}
function Test-SwitchTradeKernelConfigValid {
    param([Parameter(Mandatory)]$Context, [Parameter(Mandatory)]$State)
    $kernel = $State.Kernel.State
    if (-not $kernel) { return $false }
    if ($kernel.PSObject.Properties.Name -notcontains 'installed_config_sha256') { return $false }
    if ([string]$kernel.installed_config_sha256 -notmatch '^[0-9a-f]{64}$') { return $false }
    if (-not (Test-Path -LiteralPath $Context.WslConfigPath -PathType Leaf)) { return $false }
    return (Get-FileSha256 $Context.WslConfigPath) -eq [string]$kernel.installed_config_sha256
}

function Invoke-SwitchTradeRecoveryDecide {
    param([Parameter(Mandatory)]$Context, [Parameter(Mandatory)]$State)
    Set-SwitchTradeEngineStage 'transaction_recovery'
    $transaction = $State.Transaction.Transaction
    $decision = Resolve-SwitchTradeRecoveryDecision -Transaction $transaction -State $State
    if ($decision.Disposition -eq 'finalize') {
        $provision = Join-Path $Context.PackageRoot 'installer\provision-wsl.sh'
        $validate = Invoke-SwitchTradeWslProvision -Distro $Context.Distro -ScriptPath $provision -Mode validate-active -Arguments @('--release-id', ([string]$transaction.release_id), '--integrity-sha256', ([string]$transaction.wsl_integrity_sha256)) -TimeoutSeconds 600
        if ($validate.ExitCode -ne 0) { throw "WSL_RECOVERY_ACTIVE_INVALID: $($validate.Error)" }
        if ([string]$transaction.wsl_prior_release_id) {
            $retained = Invoke-SwitchTradeWslProvision -Distro $Context.Distro -ScriptPath $provision -Mode validate-retained -Arguments @('--release-id', ([string]$transaction.wsl_prior_release_id), '--integrity-sha256', ([string]$transaction.wsl_prior_integrity_sha256)) -TimeoutSeconds 600
            if ($retained.ExitCode -ne 0) { throw "WSL_RECOVERY_RETAINED_INVALID: $($retained.Error)" }
        }
        Set-SwitchTradeTransactionPhase -Path $Context.TransactionPath -Phase 'completed' -Fields @{ windows_committed = $true; wsl_committed = $true } | Out-Null
        Write-SwitchTradeEngineLog -Stage 'transaction_recovery' -Message "finalized coherent interrupted transaction $($transaction.transaction_id)"
        return 'finalize'
    }
    return 'compensate'
}
function Invoke-SwitchTradeCompensateKernel {
    param([Parameter(Mandatory)]$Context, [Parameter(Mandatory)]$State)
    Set-SwitchTradeEngineStage 'transaction_recovery'
    $transaction = $State.Transaction.Transaction
    $decision = Resolve-SwitchTradeRecoveryDecision -Transaction $transaction -State $State
    if ($decision.KernelAction -eq 'rollback') {
        $kernelState = $State.Kernel.State
        if ([string]$kernelState.rollback_kernel_path -ne [string]$transaction.kernel_prior_path -or
                [string]$kernelState.rollback_modules_path -ne [string]$transaction.kernel_prior_modules_path) {
            throw 'SETUP_TRANSACTION_KERNEL_ROLLBACK_MISMATCH: retained kernel paths differ from the recorded prior state'
        }
        Set-SwitchTradeTransactionPhase -Path $Context.TransactionPath -Phase 'compensating_kernel_rollback' | Out-Null
        Switch-SwitchTradeKernelRollback -StateRoot $Context.StateRoot -ExpectedReleaseId ([string]$transaction.kernel_prior_release_id) -UserProfileRoot $Context.UserProfileRoot | Out-Null
    } elseif ($decision.KernelAction -eq 'restore_original') {
        Set-SwitchTradeTransactionPhase -Path $Context.TransactionPath -Phase 'compensating_kernel_restore' | Out-Null
        Restore-SwitchTradeKernel -StateRoot $Context.StateRoot -UserProfileRoot $Context.UserProfileRoot | Out-Null
    }
}
function Invoke-SwitchTradeCompensateWindows {
    param([Parameter(Mandatory)]$Context, [Parameter(Mandatory)]$State)
    Set-SwitchTradeEngineStage 'transaction_recovery'
    $transaction = $State.Transaction.Transaction
    $decision = Resolve-SwitchTradeRecoveryDecision -Transaction $transaction -State $State
    switch ($decision.WindowsAction) {
        'rollback' {
            Set-SwitchTradeTransactionPhase -Path $Context.TransactionPath -Phase 'compensating_windows_rollback' | Out-Null
            Switch-SwitchTradeWindowsRollback -Active $Context.InstallRoot -Previous $Context.PreviousInstall -ExpectedReleaseId ([string]$transaction.prior_release_id) -ExpectedActiveReleaseId ([string]$transaction.release_id) | Out-Null
        }
        'restore_prior' {
            Set-SwitchTradeTransactionPhase -Path $Context.TransactionPath -Phase 'compensating_windows_restore' | Out-Null
            Test-WindowsReleaseTree -Root $Context.PreviousInstall -ExpectedReleaseId ([string]$transaction.prior_release_id) | Out-Null
            Move-Item -LiteralPath $Context.PreviousInstall -Destination $Context.InstallRoot
        }
        'remove_new' {
            Set-SwitchTradeTransactionPhase -Path $Context.TransactionPath -Phase 'compensating_windows_remove_new' | Out-Null
            Test-WindowsReleaseTree -Root $Context.InstallRoot -ExpectedReleaseId ([string]$transaction.release_id) | Out-Null
            Remove-SwitchTradeRecoveryTree -Path $Context.InstallRoot -ReparseCode 'SETUP_TRANSACTION_WINDOWS_REPARSE_POINT' | Out-Null
        }
    }
}
function Invoke-SwitchTradeRemoveStage {
    param([Parameter(Mandatory)]$Context, [Parameter(Mandatory)]$State)
    Set-SwitchTradeEngineStage 'transaction_recovery'
    $transaction = $State.Transaction.Transaction
    $decision = Resolve-SwitchTradeRecoveryDecision -Transaction $transaction -State $State
    if ($decision.RemoveStage) {
        $stage = Assert-SwitchTradeRecordedStagePath -Recorded ([string]$transaction.windows_stage) -InstallRoot $Context.InstallRoot
        Set-SwitchTradeTransactionPhase -Path $Context.TransactionPath -Phase 'compensating_stage_remove' | Out-Null
        Remove-SwitchTradeRecoveryTree -Path $stage -ReparseCode 'SETUP_TRANSACTION_STAGE_REPARSE_POINT' | Out-Null
    }
    if ($decision.Disposition -ne 'finalize') {
        Set-SwitchTradeTransactionPhase -Path $Context.TransactionPath -Phase 'compensated' | Out-Null
        Write-SwitchTradeEngineLog -Stage 'transaction_recovery' -Message "compensated interrupted transaction $($transaction.transaction_id)"
    }
}

function Invoke-SwitchTradeCompensateWsl {
    param([Parameter(Mandatory)]$Context, [Parameter(Mandatory)]$State)
    Set-SwitchTradeEngineStage 'transaction_recovery'
    $transaction = $State.Transaction.Transaction
    $decision = Resolve-SwitchTradeRecoveryDecision -Transaction $transaction -State $State
    $provision = Join-Path $Context.PackageRoot 'installer\provision-wsl.sh'
    $releaseId = [string]$transaction.release_id
    $wslPrior = [string]$transaction.wsl_prior_release_id
    switch ($decision.WslAction) {
        'abort_candidate' {
            if ([string]$transaction.phase -ne 'compensating_wsl_abort_candidate') {
                $validate = Invoke-SwitchTradeWslProvision -Distro $Context.Distro -ScriptPath $provision -Mode validate-candidate -Arguments @('--release-id', $releaseId, '--integrity-sha256', ([string]$transaction.wsl_integrity_sha256)) -TimeoutSeconds 600
                if ($validate.ExitCode -ne 0) { throw "WSL_RECOVERY_CANDIDATE_INVALID: $($validate.Error)" }
            }
            Set-SwitchTradeTransactionPhase -Path $Context.TransactionPath -Phase 'compensating_wsl_abort_candidate' | Out-Null
            $abort = Invoke-SwitchTradeWslProvision -Distro $Context.Distro -ScriptPath $provision -Mode abort -Arguments @('--release-id', $releaseId) -TimeoutSeconds 600
            if ($abort.ExitCode -ne 0) { throw "WSL_RECOVERY_ABORT_FAILED: $($abort.Error)" }
        }
        'compensate' {
            Set-SwitchTradeTransactionPhase -Path $Context.TransactionPath -Phase 'compensating_wsl_rollback' | Out-Null
            $comp = Invoke-SwitchTradeWslProvision -Distro $Context.Distro -ScriptPath $provision -Mode compensate -Arguments @('--release-id', $wslPrior, '--integrity-sha256', ([string]$transaction.wsl_prior_integrity_sha256), '--prior-release-id', $releaseId, '--prior-integrity-sha256', ([string]$transaction.wsl_integrity_sha256)) -TimeoutSeconds 600
            if ($comp.ExitCode -ne 0) { throw "WSL_RECOVERY_COMPENSATION_FAILED: $($comp.Error)" }
        }
        'recover_interrupted' {
            Set-SwitchTradeTransactionPhase -Path $Context.TransactionPath -Phase 'compensating_wsl_commit_swap' | Out-Null
            $recover = Invoke-SwitchTradeWslProvision -Distro $Context.Distro -ScriptPath $provision -Mode recover-interrupted -Arguments @('--release-id', $releaseId, '--prior-release-id', $wslPrior, '--integrity-sha256', ([string]$transaction.wsl_integrity_sha256), '--prior-integrity-sha256', ([string]$transaction.wsl_prior_integrity_sha256)) -TimeoutSeconds 600
            if ($recover.ExitCode -ne 0) { throw "WSL_RECOVERY_SWAP_FAILED: $($recover.Error)" }
        }
        'unregister_new' {
            Set-SwitchTradeTransactionPhase -Path $Context.TransactionPath -Phase 'compensating_wsl_unregister' | Out-Null
            $registration = Get-SwitchTradeDistroRegistrationState -Context $Context
            if (-not $registration.Exists -or
                    -not [string]::Equals($registration.BasePath,
                        [IO.Path]::GetFullPath([string]$transaction.distro_base_path).TrimEnd('\'),
                        [StringComparison]::OrdinalIgnoreCase)) {
                throw 'SETUP_TRANSACTION_DISTRO_IDENTITY_CHANGED: refusing to unregister changed BasePath'
            }
            $marker = Get-SwitchTradeDistroMarkerProbe -Distro $Context.Distro
            if (-not $marker.Valid -or $marker.InstallId -cne [string]$transaction.install_id) {
                throw 'SETUP_TRANSACTION_DISTRO_IDENTITY_CHANGED: refusing to unregister a distribution that is not installer-owned'
            }
            $unregister = Invoke-SwitchTradeWsl -Arguments @('--unregister', $Context.Distro) -TimeoutSeconds 120
            if ($unregister.ExitCode -ne 0) { throw 'DISTRO_RECOVERY_UNREGISTER_FAILED' }
        }
    }
}

function Invoke-SwitchTradeRecoverRollback {
    param([Parameter(Mandatory)]$Context, [Parameter(Mandatory)]$State)
    Set-SwitchTradeEngineStage 'rollback_recovery'
    $transaction = $State.Transaction.Transaction
    $journal = Assert-SwitchTradeRollbackJournal -Transaction $transaction
    $decision = Resolve-SwitchTradeRollbackRecoveryDecision -Journal $journal -State $State
    $direction = [string]$decision.Direction
    Set-SwitchTradeTransactionPhase -Path $Context.TransactionPath -Phase "rollback_recovering_$direction" | Out-Null
    $provision = Join-Path $Context.PackageRoot 'installer\provision-wsl.sh'
    if ($direction -eq 'source') {
        if ($decision.WindowsPosition -eq 'target_transition') {
            Switch-SwitchTradeWindowsRollback -Active $Context.InstallRoot -Previous $Context.PreviousInstall -ExpectedReleaseId ([string]$journal.target.release_id) -ExpectedActiveReleaseId ([string]$journal.source.release_id) | Out-Null
        }
        if ($decision.WindowsPosition -ne 'source') {
            Switch-SwitchTradeWindowsRollback -Active $Context.InstallRoot -Previous $Context.PreviousInstall -ExpectedReleaseId ([string]$journal.source.release_id) -ExpectedActiveReleaseId ([string]$journal.target.release_id) | Out-Null
        }
        if ($decision.KernelPosition -ne 'source') {
            Switch-SwitchTradeKernelRollback -StateRoot $Context.StateRoot -ExpectedReleaseId ([string]$journal.source.release_id) -UserProfileRoot $Context.UserProfileRoot | Out-Null
        } elseif (-not (Test-SwitchTradeKernelConfigValid -Context $Context -State $State)) {
            Repair-SwitchTradeKernelConfiguration -StateRoot $Context.StateRoot -UserProfileRoot $Context.UserProfileRoot | Out-Null
        }
        if ($decision.WslPosition -eq 'target_transition') {
            $roll = Invoke-SwitchTradeWslProvision -Distro $Context.Distro -ScriptPath $provision -Mode rollback -Arguments @('--release-id', ([string]$journal.target.release_id), '--integrity-sha256', ([string]$journal.target.wsl_integrity_sha256), '--prior-release-id', ([string]$journal.source.release_id), '--prior-integrity-sha256', ([string]$journal.source.wsl_integrity_sha256)) -TimeoutSeconds 600
            if ($roll.ExitCode -ne 0) { throw "ROLLBACK_WSL_RECOVERY_FAILED: $($roll.Error)" }
        }
        if ($decision.WslPosition -ne 'source') {
            Invoke-SwitchTradeWsl -Arguments @('--terminate', $Context.Distro) -TimeoutSeconds 30 | Out-Null
            $comp = Invoke-SwitchTradeWslProvision -Distro $Context.Distro -ScriptPath $provision -Mode compensate -Arguments @('--release-id', ([string]$journal.source.release_id), '--integrity-sha256', ([string]$journal.source.wsl_integrity_sha256), '--prior-release-id', ([string]$journal.target.release_id), '--prior-integrity-sha256', ([string]$journal.target.wsl_integrity_sha256)) -TimeoutSeconds 600
            if ($comp.ExitCode -ne 0) { throw "ROLLBACK_WSL_RECOVERY_FAILED: $($comp.Error)" }
        }
    } else {
        if (-not (Test-SwitchTradeKernelConfigValid -Context $Context -State $State)) {
            Repair-SwitchTradeKernelConfiguration -StateRoot $Context.StateRoot -UserProfileRoot $Context.UserProfileRoot | Out-Null
        }
        if ($decision.WslPosition -eq 'target_transition') {
            $roll = Invoke-SwitchTradeWslProvision -Distro $Context.Distro -ScriptPath $provision -Mode rollback -Arguments @('--release-id', ([string]$journal.target.release_id), '--integrity-sha256', ([string]$journal.target.wsl_integrity_sha256), '--prior-release-id', ([string]$journal.source.release_id), '--prior-integrity-sha256', ([string]$journal.source.wsl_integrity_sha256)) -TimeoutSeconds 600
            if ($roll.ExitCode -ne 0) { throw "ROLLBACK_WSL_RECOVERY_FAILED: $($roll.Error)" }
        }
        if ($decision.WindowsPosition -eq 'target_transition') {
            Switch-SwitchTradeWindowsRollback -Active $Context.InstallRoot -Previous $Context.PreviousInstall -ExpectedReleaseId ([string]$journal.target.release_id) -ExpectedActiveReleaseId ([string]$journal.source.release_id) | Out-Null
        }
    }
    $verifiedState = Get-SwitchTradeInstallState -Context $Context
    $verified = Resolve-SwitchTradeRollbackRecoveryDecision -Journal $journal -State $verifiedState
    if ($verified.WindowsPosition -ne $direction -or $verified.WslPosition -ne $direction -or
            $verified.KernelPosition -ne $direction -or
            -not (Test-SwitchTradeKernelConfigValid -Context $Context -State $verifiedState)) {
        throw 'ROLLBACK_RECOVERY_NOT_CONVERGED: release axes did not reach one journaled side'
    }
    $published = Get-SwitchTradeRollbackPublishedState -Transaction $transaction -Direction $direction
    Write-AtomicJson -Path $Context.TransactionPath -Value $published
    Write-SwitchTradeEngineLog -Stage 'rollback_recovery' -Message "recovered interrupted rollback to $direction"
}

function Invoke-SwitchTradeCreateShortcut {
    param([Parameter(Mandatory)]$Context)
    if ($Context.NoShortcut) { return }
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut((Join-Path $Context.DesktopRoot 'SwitchTrade.lnk'))
    $installedDesktop = Join-Path $Context.InstallRoot 'SwitchTrade.exe'
    $shortcut.TargetPath = if (Test-Path -LiteralPath $installedDesktop) { $installedDesktop } else { 'powershell.exe' }
    $shortcut.Arguments = if (Test-Path -LiteralPath $installedDesktop) { '' } else {
        "-NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $Context.InstallRoot 'installer\Launch-SwitchTrade.ps1')`""
    }
    $shortcut.WorkingDirectory = $Context.InstallRoot
    $shortcut.Save()
}
function Invoke-SwitchTradeRemoveShortcut {
    param([Parameter(Mandatory)]$Context)
    $shortcutPath = Join-Path $Context.DesktopRoot 'SwitchTrade.lnk'
    if (-not $Context.NoShortcut -and (Test-Path -LiteralPath $shortcutPath -PathType Leaf)) {
        Remove-Item -LiteralPath $shortcutPath -Force
    }
}
function Write-SwitchTradeHardwareSelection {
    param(
        [Parameter(Mandatory)][string]$StateRoot,
        [Parameter(Mandatory)][ValidatePattern('^[0-9a-fA-F]{4}:[0-9a-fA-F]{4}$')]
        [string]$UsbId,
        [Parameter(Mandatory)][ValidateLength(1, 512)][string]$InstanceId,
        [Parameter(Mandatory)][ValidatePattern('^\d+-\d+$')][string]$BusId
    )
    if ($InstanceId.ToCharArray() | Where-Object { [char]::IsControl($_) }) {
        throw 'USB_STABLE_ID_INVALID: the adapter instance identity contains invalid characters'
    }
    $path = Join-Path $StateRoot 'runtime\hardware-selection.json'
    Write-AtomicJson -Path $path -Value ([ordered]@{
        schema = 1
        usb_id = $UsbId.ToLowerInvariant()
        instance_id = $InstanceId
        bus_id = $BusId
    })
    return $path
}
function Get-SwitchTradeUsbWatcherCommand {
    param(
        [Parameter(Mandatory)][string]$ScriptPath,
        [Parameter(Mandatory)][string]$Distro,
        [Parameter(Mandatory)][string]$InstanceId,
        [Parameter(Mandatory)][string]$StateFile
    )
    $arguments = @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File',
        [IO.Path]::GetFullPath($ScriptPath), '-Distro', $Distro, '-InstanceId', $InstanceId,
        '-StateFile', [IO.Path]::GetFullPath($StateFile))
    return 'powershell.exe ' + (($arguments | ForEach-Object {
        ConvertTo-NativeCommandLineArgument ([string]$_)
    }) -join ' ')
}

function Invoke-SwitchTradeGateRollback {
    param([Parameter(Mandatory)]$Context, [Parameter(Mandatory)]$State)
    Set-SwitchTradeEngineStage 'rollback_validate'
    $transaction = $State.Transaction.Transaction
    if (-not $State.WindowsPrevious.Exists) {
        throw 'ROLLBACK_WINDOWS_MISSING: no retained SwitchTrade application version is available'
    }
    if (-not $State.Identity.DistroExists) { throw 'ROLLBACK_DISTRO_MISSING: the owned SwitchTrade distro is absent' }
    $rollbackRelease = $State.WindowsPrevious.ReleaseId
    $activeRelease = $State.WindowsActive.ReleaseId
    Test-WindowsReleaseTree -Root $Context.PreviousInstall -ExpectedReleaseId $rollbackRelease | Out-Null
    Test-WindowsReleaseTree -Root $Context.InstallRoot -ExpectedReleaseId $activeRelease | Out-Null
    if ($rollbackRelease -ne [string]$transaction.prior_release_id -or
            $activeRelease -ne [string]$transaction.release_id) {
        throw 'ROLLBACK_TRANSACTION_RELEASE_MISMATCH'
    }
    Test-SwitchTradeTreeIntegrity -Root $Context.PreviousInstall -ExpectedReleaseId $rollbackRelease -ExpectedIntegritySha256 ([string]$transaction.windows_prior_integrity_sha256) | Out-Null
    Test-SwitchTradeTreeIntegrity -Root $Context.InstallRoot -ExpectedReleaseId $activeRelease -ExpectedIntegritySha256 ([string]$transaction.windows_integrity_sha256) | Out-Null
    $provision = Join-Path $Context.PackageRoot 'installer\provision-wsl.sh'
    $retained = Invoke-SwitchTradeWslProvision -Distro $Context.Distro -ScriptPath $provision -Mode validate-retained -Arguments @('--release-id', $rollbackRelease, '--integrity-sha256', ([string]$transaction.wsl_prior_integrity_sha256)) -TimeoutSeconds 600
    if ($retained.ExitCode -ne 0) { throw "ROLLBACK_RUNTIME_INVALID: $($retained.Error)" }
    $kernelState = Test-SwitchTradeKernelRollback -StateRoot $Context.StateRoot -ExpectedReleaseId $rollbackRelease
    return $kernelState
}
function Invoke-SwitchTradeStartRollback {
    param([Parameter(Mandatory)]$Context, [Parameter(Mandatory)]$State, [Parameter(Mandatory)]$Package, [Parameter(Mandatory)]$KernelState)
    Set-SwitchTradeEngineStage 'rollback_validate'
    $transaction = $State.Transaction.Transaction
    $journal = [ordered]@{
        schema = 2
        source_action = [string]$transaction.action
        initiating_package = [ordered]@{
            root = [IO.Path]::GetFullPath($Context.PackageRoot).TrimEnd('\')
            release_id = $Package.ReleaseId
            manifest_sha256 = $Package.ManifestSha256
        }
        source = [ordered]@{
            release_id = [string]$transaction.release_id
            windows_integrity_sha256 = [string]$transaction.windows_integrity_sha256
            wsl_integrity_sha256 = [string]$transaction.wsl_integrity_sha256
            kernel_path = [string]$KernelState.kernel_path
            modules_path = [string]$KernelState.modules_path
            kernel_release = [string]$KernelState.kernel_release
            modules_format = [string]$KernelState.modules_format
            kernel_sha256 = [string]$KernelState.kernel_sha256
            modules_sha256 = [string]$KernelState.modules_sha256
        }
        target = [ordered]@{
            release_id = [string]$transaction.prior_release_id
            windows_integrity_sha256 = [string]$transaction.windows_prior_integrity_sha256
            wsl_integrity_sha256 = [string]$transaction.wsl_prior_integrity_sha256
            kernel_path = [string]$KernelState.rollback_kernel_path
            modules_path = [string]$KernelState.rollback_modules_path
            kernel_release = [string]$KernelState.rollback_kernel_release
            modules_format = [string]$KernelState.rollback_modules_format
            kernel_sha256 = [string]$KernelState.rollback_kernel_sha256
            modules_sha256 = [string]$KernelState.rollback_modules_sha256
        }
    }
    Set-SwitchTradeTransactionPhase -Path $Context.TransactionPath -Phase 'rollback_prepared' -Fields @{ rollback_journal = $journal } | Out-Null
}

function Invoke-SwitchTradeRollbackWsl {
    param([Parameter(Mandatory)]$Context, [Parameter(Mandatory)]$State)
    Set-SwitchTradeEngineStage 'rollback_commit'
    $transaction = $State.Transaction.Transaction
    $journal = Assert-SwitchTradeRollbackJournal -Transaction $transaction
    $provision = Join-Path $Context.PackageRoot 'installer\provision-wsl.sh'
    Invoke-SwitchTradeWsl -Arguments @('--terminate', $Context.Distro) -TimeoutSeconds 30 | Out-Null
    $roll = Invoke-SwitchTradeWslProvision -Distro $Context.Distro -ScriptPath $provision -Mode rollback -Arguments @('--release-id', ([string]$journal.target.release_id), '--integrity-sha256', ([string]$journal.target.wsl_integrity_sha256), '--prior-release-id', ([string]$journal.source.release_id), '--prior-integrity-sha256', ([string]$journal.source.wsl_integrity_sha256)) -TimeoutSeconds 600
    if ($roll.ExitCode -ne 0) { throw "ROLLBACK_RUNTIME_COMMIT_FAILED: $($roll.Error)" }
    Set-SwitchTradeTransactionPhase -Path $Context.TransactionPath -Phase 'rollback_wsl_committed' | Out-Null
}
function Invoke-SwitchTradeRollbackKernel {
    param([Parameter(Mandatory)]$Context, [Parameter(Mandatory)]$State)
    Set-SwitchTradeEngineStage 'rollback_commit'
    $transaction = $State.Transaction.Transaction
    Switch-SwitchTradeKernelRollback -StateRoot $Context.StateRoot -ExpectedReleaseId ([string]$transaction.prior_release_id) -UserProfileRoot $Context.UserProfileRoot | Out-Null
    Set-SwitchTradeTransactionPhase -Path $Context.TransactionPath -Phase 'rollback_kernel_committed' | Out-Null
}
function Invoke-SwitchTradeRollbackWindows {
    param([Parameter(Mandatory)]$Context, [Parameter(Mandatory)]$State)
    Set-SwitchTradeEngineStage 'rollback_commit'
    $transaction = $State.Transaction.Transaction
    Switch-SwitchTradeWindowsRollback -Active $Context.InstallRoot -Previous $Context.PreviousInstall -ExpectedReleaseId ([string]$transaction.prior_release_id) -ExpectedActiveReleaseId ([string]$transaction.release_id) | Out-Null
    Set-SwitchTradeTransactionPhase -Path $Context.TransactionPath -Phase 'rollback_windows_committed' | Out-Null
}
function Invoke-SwitchTradePublishRollback {
    param([Parameter(Mandatory)]$Context, [Parameter(Mandatory)]$State)
    Set-SwitchTradeEngineStage 'rollback_commit'
    $transaction = $State.Transaction.Transaction
    $published = Get-SwitchTradeRollbackPublishedState -Transaction $transaction -Direction 'target'
    Write-AtomicJson -Path $Context.TransactionPath -Value $published
}
function Invoke-SwitchTradeGateUninstall {
    param([Parameter(Mandatory)]$Context, [Parameter(Mandatory)]$State)
    Set-SwitchTradeEngineStage 'uninstall_validate'
    $identity = $State.Identity
    $transactionState = $State.Transaction
    if ($identity.DistroExists) {
        if ($transactionState.Classification -ne 'terminal' -or -not $transactionState.Transaction) {
            throw 'INSTALLED_DISTRO_IDENTITY_MISSING: destructive distro actions require a completed identity transaction'
        }
        Assert-SwitchTradeDistroMutationIdentity -Transaction $transactionState.Transaction -DistroName $Context.Distro -DistroRoot $Context.DistroRoot -Actual $identity | Out-Null
    }
}
function Invoke-SwitchTradeUnregisterDistro {
    param([Parameter(Mandatory)]$Context, [Parameter(Mandatory)]$State)
    Set-SwitchTradeEngineStage 'uninstall'
    if (-not $State.Identity.DistroExists) { return }
    $unregister = Invoke-SwitchTradeWsl -Arguments @('--unregister', $Context.Distro) -TimeoutSeconds 120
    if ($unregister.ExitCode -ne 0) { throw "DISTRO_UNREGISTER_FAILED: $($unregister.Error)" }
}
function Invoke-SwitchTradeWatcherTeardown {
    param([Parameter(Mandatory)]$Context)
    Set-SwitchTradeEngineStage 'uninstall'
    $startupRegistryPath = "Registry::HKEY_USERS\$($Context.InvokingUserSid)\Software\Microsoft\Windows\CurrentVersion\Run"
    Remove-ItemProperty -Path $startupRegistryPath -Name 'SwitchTradeUsbWatcher' -ErrorAction SilentlyContinue
    Stop-SwitchTradeUsbWatcher -StateRoot $Context.StateRoot | Out-Null
}
function Invoke-SwitchTradeKernelRestore {
    param([Parameter(Mandatory)]$Context)
    Set-SwitchTradeEngineStage 'uninstall'
    Restore-SwitchTradeKernel -StateRoot $Context.StateRoot -UserProfileRoot $Context.UserProfileRoot | Out-Null
}
function Invoke-SwitchTradeRemoveTree {
    param([Parameter(Mandatory)]$Context, [Parameter(Mandatory)][string]$Target)
    Set-SwitchTradeEngineStage 'uninstall'
    if (-not (Test-Path -LiteralPath $Target)) { return }
    $full = [IO.Path]::GetFullPath($Target).TrimEnd('\')
    if ($full -cne $Context.InstallRoot -and $full -cne $Context.PreviousInstall) {
        throw "DESTRUCTIVE_PATH_DENIED: $Target is not an installer-owned tree"
    }
    $item = Get-Item -LiteralPath $Target -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw 'DESTRUCTIVE_PATH_DENIED: refusing to remove a redirected path'
    }
    Remove-Item -LiteralPath $Target -Recurse -Force
}

function Invoke-SwitchTradePlan {
    param(
        [Parameter(Mandatory)]$Context,
        [Parameter(Mandatory)]$State,
        [Parameter(Mandatory)]$Package,
        [Parameter(Mandatory)]$Plan
    )
    $currentState = $State
    $kernelRollbackState = $null
    foreach ($step in $Plan.Steps) {
        Write-SwitchTradeEngineLog -Stage $step.Stage -Message "plan step $($step.Id)"
        switch ($step.Kind) {
            'require_prerequisites' { Invoke-SwitchTradeRequirePrerequisites -Context $Context -State $currentState -Package $Package }
            'ensure_wsl' {
                $outcome = Invoke-SwitchTradeEnsureWsl -Context $Context -State $currentState
                if ($outcome -eq 'reboot_required') { throw 'ENGINE_REBOOT_REQUIRED' }
            }
            'ensure_usbipd' {
                $outcome = Invoke-SwitchTradeEnsureUsbipd -Context $Context -State $currentState
                if ($outcome -eq 'reboot_required') { throw 'ENGINE_REBOOT_REQUIRED' }
            }
            'create_transaction' {
                $transaction = Invoke-SwitchTradeCreateTransaction -Context $Context -State $currentState -Package $Package
                $currentState = Get-SwitchTradeInstallState -Context $Context
            }
            'stage_windows' { Invoke-SwitchTradeStageWindows -Context $Context -Transaction (Get-Content -Raw -LiteralPath $Context.TransactionPath | ConvertFrom-Json) | Out-Null }
            'ensure_distro' {
                Invoke-SwitchTradeEnsureDistro -Context $Context -Transaction (Get-Content -Raw -LiteralPath $Context.TransactionPath | ConvertFrom-Json) -State $currentState
                $currentState = Get-SwitchTradeInstallState -Context $Context
            }
            'provision_stage' { Invoke-SwitchTradeProvisionStage -Context $Context -Transaction (Get-Content -Raw -LiteralPath $Context.TransactionPath | ConvertFrom-Json) | Out-Null }
            'provision_validate' { Invoke-SwitchTradeProvisionValidate -Context $Context -Transaction (Get-Content -Raw -LiteralPath $Context.TransactionPath | ConvertFrom-Json) | Out-Null }
            'control_readiness' {
                $transaction = Get-Content -Raw -LiteralPath $Context.TransactionPath | ConvertFrom-Json
                Test-SwitchTradeStagedControlReadiness -Context $Context -ExpectedReleaseId ([string]$transaction.release_id)
            }
            'apply_kernel' {
                Invoke-SwitchTradeApplyKernel -Context $Context -Transaction (Get-Content -Raw -LiteralPath $Context.TransactionPath | ConvertFrom-Json) -State $currentState
                $currentState = Get-SwitchTradeInstallState -Context $Context
            }
            'provision_commit' { Invoke-SwitchTradeProvisionCommit -Context $Context -Transaction (Get-Content -Raw -LiteralPath $Context.TransactionPath | ConvertFrom-Json) | Out-Null }
            'commit_windows' {
                Invoke-SwitchTradeCommitWindows -Context $Context -Transaction (Get-Content -Raw -LiteralPath $Context.TransactionPath | ConvertFrom-Json) | Out-Null
                $currentState = Get-SwitchTradeInstallState -Context $Context
            }
            'hardware_prepare' { Invoke-SwitchTradeHardwarePrepare -Context $Context -State $currentState }
            'shortcut' { Invoke-SwitchTradeCreateShortcut -Context $Context }
            'clear_resume' { Clear-SwitchTradeResume -Context $Context }
            'gate_recovery_action' { Invoke-SwitchTradeGateRecoveryAction -Context $Context -State $currentState }
            'gate_recovery_package' { Invoke-SwitchTradeGateRecoveryPackage -Context $Context -State $currentState -Package $Package }
            'gate_recovery_paths' { Invoke-SwitchTradeGateRecoveryPaths -Context $Context -State $currentState }
            'gate_recovery_identity' { Invoke-SwitchTradeGateRecoveryIdentity -Context $Context -State $currentState }
            'bootstrap_marker' {
                Invoke-SwitchTradeBootstrapMarker -Context $Context -State $currentState
                $currentState = Get-SwitchTradeInstallState -Context $Context
            }
            'recovery_decide' { $null = Invoke-SwitchTradeRecoveryDecide -Context $Context -State $currentState }
            'compensate_kernel' { Invoke-SwitchTradeCompensateKernel -Context $Context -State $currentState }
            'compensate_wsl' {
                Invoke-SwitchTradeCompensateWsl -Context $Context -State $currentState
                $currentState = Get-SwitchTradeInstallState -Context $Context
            }
            'compensate_windows' { Invoke-SwitchTradeCompensateWindows -Context $Context -State $currentState }
            'remove_stage' { Invoke-SwitchTradeRemoveStage -Context $Context -State $currentState }
            'recover_rollback' { Invoke-SwitchTradeRecoverRollback -Context $Context -State $currentState }
            'gate_rollback' { $kernelRollbackState = Invoke-SwitchTradeGateRollback -Context $Context -State $currentState }
            'start_rollback' { Invoke-SwitchTradeStartRollback -Context $Context -State $currentState -Package $Package -KernelState $kernelRollbackState }
            'rollback_wsl' { Invoke-SwitchTradeRollbackWsl -Context $Context -State $currentState }
            'rollback_kernel' { Invoke-SwitchTradeRollbackKernel -Context $Context -State $currentState }
            'rollback_windows' { Invoke-SwitchTradeRollbackWindows -Context $Context -State $currentState }
            'publish_rollback' { Invoke-SwitchTradePublishRollback -Context $Context -State $currentState }
            'gate_uninstall' { Invoke-SwitchTradeGateUninstall -Context $Context -State $currentState }
            'checkpoint' {
                $phase = if ($step.Id -eq 'uninstall.persist') { 'uninstalling' } elseif ($step.Id -eq 'uninstall.complete') { 'uninstalled' } else { '' }
                if ($phase) { Set-SwitchTradeTransactionPhase -Path $Context.TransactionPath -Phase $phase | Out-Null }
            }
            'unregister_distro' { Invoke-SwitchTradeUnregisterDistro -Context $Context -State $currentState }
            'watcher_teardown' { Invoke-SwitchTradeWatcherTeardown -Context $Context }
            'kernel_restore' { Invoke-SwitchTradeKernelRestore -Context $Context }
            'remove_tree' { Invoke-SwitchTradeRemoveTree -Context $Context -Target ([string]$step.Args['Target']) }
            'remove_shortcut' { Invoke-SwitchTradeRemoveShortcut -Context $Context }
            default { throw "PLAN_STEP_UNKNOWN: $($step.Kind)" }
        }
    }
    return $currentState
}

function New-SwitchTradeFailure {
    param(
        [Parameter(Mandatory)][string]$Code,
        [Parameter(Mandatory)][string]$Message,
        [Parameter(Mandatory)][string]$Stage,
        [bool]$Recoverable = $true,
        [string]$PrimaryAction = 'Run Setup Repair',
        [string]$LogPath = ''
    )
    $failure = [ordered]@{
        code = $Code
        message = Redact-SwitchTradeEngineText $Message
        stage = $Stage
        recoverable = $Recoverable
        primary_action = $PrimaryAction
        action = ''
        correlation_id = $script:SwitchTradeCorrelationId
        technical_detail_log_path = $LogPath
    }
    return $failure
}
function ConvertTo-SwitchTradeFailureCode {
    param([Parameter(Mandatory)][string]$Message)
    $candidateCode = ($Message -split ':', 2)[0]
    if ($candidateCode -match '^[A-Z][A-Z0-9_.-]+$') { return $candidateCode }
    return 'SETUP_FAILED'
}
