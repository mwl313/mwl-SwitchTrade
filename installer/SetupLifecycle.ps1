Set-StrictMode -Version Latest

$script:SwitchTradeReleaseMarker = '.switchtrade-release.json'
$script:SwitchTradeMinimumWslVersion = [version]'2.2.4.0'

function ConvertTo-NativeCommandLineArgument {
    param([AllowEmptyString()][string]$Value)
    if ($Value -and $Value -notmatch '[\s"]') { return $Value }
    $builder = New-Object Text.StringBuilder
    [void]$builder.Append('"')
    $slashes = 0
    foreach ($character in $Value.ToCharArray()) {
        if ($character -eq '\') { $slashes++; continue }
        if ($character -eq '"') {
            [void]$builder.Append(('\' * ($slashes * 2 + 1)))
            [void]$builder.Append('"')
        } else {
            if ($slashes) { [void]$builder.Append(('\' * $slashes)) }
            [void]$builder.Append($character)
        }
        $slashes = 0
    }
    if ($slashes) { [void]$builder.Append(('\' * ($slashes * 2))) }
    [void]$builder.Append('"')
    return $builder.ToString()
}

function Invoke-BoundedNativeProcess {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [string[]]$Arguments = @(),
        [ValidateRange(1, 3600)][int]$TimeoutSeconds = 30
    )
    $start = New-Object Diagnostics.ProcessStartInfo
    $start.FileName = $FilePath
    $start.Arguments = (($Arguments | ForEach-Object { ConvertTo-NativeCommandLineArgument ([string]$_) }) -join ' ')
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $process = New-Object Diagnostics.Process
    $process.StartInfo = $start
    try {
        if (-not $process.Start()) { throw "PROCESS_START_FAILED: $FilePath" }
        $outputTask = $process.StandardOutput.ReadToEndAsync()
        $errorTask = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
            try { $process.Kill() } catch { }
            throw "PROCESS_TIMEOUT: $FilePath exceeded $TimeoutSeconds seconds"
        }
        $outputTask.Wait()
        $errorTask.Wait()
        return [pscustomobject]@{
            ExitCode = $process.ExitCode
            Output = [string]$outputTask.Result
            Error = [string]$errorTask.Result
        }
    } finally { $process.Dispose() }
}

function ConvertTo-SwitchTradeVersion {
    param([Parameter(Mandatory)][string]$Text, [string]$FailureCode = 'VERSION_INVALID')
    $match = [regex]::Match($Text, '(?<!\d)(\d+\.\d+(?:\.\d+){0,2})(?!\d)')
    if (-not $match.Success) { throw "${FailureCode}: version output was not recognized" }
    try { return [version]$match.Groups[1].Value } catch { throw "${FailureCode}: version output was invalid" }
}

function Test-SwitchTradeWslCapabilities {
    param([string]$VersionText, [string]$HelpText)
    $version = ConvertTo-SwitchTradeVersion -Text $VersionText -FailureCode 'WSL_VERSION_INVALID'
    if ($version -lt $script:SwitchTradeMinimumWslVersion) {
        throw "WSL_VERSION_UNSUPPORTED: WSL $version is older than $($script:SwitchTradeMinimumWslVersion)"
    }
    foreach ($capability in @('--import', '--distribution', '--cd', '--version')) {
        if ($HelpText -notmatch [regex]::Escape($capability)) {
            throw "WSL_CAPABILITY_MISSING: $capability"
        }
    }
    return $version
}

function Test-SwitchTradeUsbipdCapabilities {
    param([string]$VersionText, [version]$MinimumVersion, [string]$HelpText, $State)
    $version = ConvertTo-SwitchTradeVersion -Text $VersionText -FailureCode 'USBIPD_VERSION_INVALID'
    if ($version -lt $MinimumVersion) {
        throw "USBIPD_VERSION_UNSUPPORTED: usbipd-win $version is older than $MinimumVersion"
    }
    foreach ($capability in @('attach', 'bind', 'state', '--wsl', '--busid')) {
        if ($HelpText -notmatch [regex]::Escape($capability)) {
            throw "USBIPD_CAPABILITY_MISSING: $capability"
        }
    }
    if (-not $State -or $State.PSObject.Properties.Name -notcontains 'Devices') {
        throw 'USBIPD_STATE_SCHEMA_UNSUPPORTED: Devices is missing'
    }
    return $version
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
        [bool]$KernelChangeExpected = $false
    )
    $state = [ordered]@{
        schema = 2
        transaction_id = [guid]::NewGuid().ToString('N')
        action = $Action
        release_id = $ReleaseId
        prior_release_id = $PriorReleaseId
        phase = 'created'
        windows_stage = $WindowsStage
        package_root = $PackageRoot
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
        kernel_prior_release_id = $KernelPriorReleaseId
        kernel_state_path = $KernelStatePath
        kernel_prior_path = $KernelPriorPath
        kernel_prior_modules_path = $KernelPriorModulesPath
        kernel_change_expected = $KernelChangeExpected
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

function Assert-SwitchTradeTransactionPackage {
    param(
        [Parameter(Mandatory)]$Transaction,
        [Parameter(Mandatory)][string]$PackageRoot,
        [Parameter(Mandatory)][string]$ReleaseId
    )
    if ([string]$Transaction.release_id -ne $ReleaseId -or
            -not [string]::Equals(
                [IO.Path]::GetFullPath([string]$Transaction.package_root).TrimEnd('\'),
                [IO.Path]::GetFullPath($PackageRoot).TrimEnd('\'),
                [StringComparison]::OrdinalIgnoreCase)) {
        throw 'SETUP_TRANSACTION_PACKAGE_MISMATCH: rerun Repair from the exact package that started the transaction'
    }
}

function Resolve-SwitchTradeTransactionRecovery {
    param(
        [Parameter(Mandatory)]$Transaction,
        [Parameter(Mandatory)]$Actual
    )
    if ([int]$Transaction.schema -ne 2) {
        throw 'SETUP_TRANSACTION_LEGACY_AMBIGUOUS: the interrupted transaction cannot prove pre-mutation ownership'
    }
    if ($Actual.DistroExists -and -not $Actual.DistroOwned) {
        throw 'SETUP_TRANSACTION_DISTRO_OWNERSHIP_CHANGED: the named distribution is not installer-owned'
    }
    if ([bool]$Transaction.distro_existed_before -and
            (-not [bool]$Transaction.distro_owned_before -or -not $Actual.DistroExists)) {
        throw 'SETUP_TRANSACTION_PRIOR_DISTRO_MISSING: the prior owned distribution cannot be proven'
    }

    $release = [string]$Transaction.release_id
    $windowsPrior = [string]$Transaction.prior_release_id
    $wslPrior = [string]$Transaction.wsl_prior_release_id
    $kernelPrior = [string]$Transaction.kernel_prior_release_id
    $kernelExpected = if ([bool]$Transaction.kernel_change_expected) { $release } else { $kernelPrior }
    $retainedReady = (-not $windowsPrior -or $Actual.WindowsPreviousRelease -eq $windowsPrior) -and
        (-not $wslPrior -or $Actual.WslPreviousRelease -eq $wslPrior)
    $coherentCommit = $Actual.WindowsActiveRelease -eq $release -and
        $Actual.WslActiveRelease -eq $release -and
        $Actual.KernelRelease -eq $kernelExpected -and $retainedReady -and
        -not $Actual.WindowsStageExists -and -not $Actual.WslCandidateExists -and
        -not $Actual.WslCommitSwapExists
    if ($coherentCommit) {
        return [pscustomobject]@{
            Disposition = 'finalize'; WindowsAction = 'none'; WslAction = 'none'
            KernelAction = 'none'; RemoveStage = $false
        }
    }

    $windowsAction = 'none'
    if ($Actual.WindowsActiveExists -and -not $Actual.WindowsActiveRelease) {
        throw 'SETUP_TRANSACTION_WINDOWS_ACTIVE_INVALID: the active Windows tree is not a proven release'
    }
    if ($Actual.WindowsPreviousExists -and -not $Actual.WindowsPreviousRelease) {
        throw 'SETUP_TRANSACTION_WINDOWS_RETAINED_INVALID: the retained Windows tree is not a proven release'
    }
    if ($windowsPrior) {
        if ($Actual.WindowsActiveRelease -eq $windowsPrior) { $windowsAction = 'none' }
        elseif ($Actual.WindowsActiveRelease -eq $release -and
                $Actual.WindowsPreviousRelease -eq $windowsPrior) { $windowsAction = 'rollback' }
        elseif (-not $Actual.WindowsActiveExists -and
                $Actual.WindowsPreviousRelease -eq $windowsPrior) { $windowsAction = 'restore_prior' }
        else { throw 'SETUP_TRANSACTION_WINDOWS_AMBIGUOUS: Windows release state cannot be compensated safely' }
    } elseif ($Actual.WindowsActiveRelease -eq $release) {
        $windowsAction = 'remove_new'
    } elseif ($Actual.WindowsActiveExists) {
        throw 'SETUP_TRANSACTION_WINDOWS_AMBIGUOUS: an unexpected Windows release is active'
    }

    $wslAction = 'none'
    if (-not [bool]$Transaction.distro_existed_before) {
        if ($Actual.DistroExists) { $wslAction = 'unregister_new' }
    } else {
        if (-not $wslPrior) {
            throw 'SETUP_TRANSACTION_WSL_PRIOR_UNKNOWN: the prior WSL release was not recorded'
        }
        if (($Actual.WslCandidateExists -and $Actual.WslCandidateRelease -ne $release) -or
                ($Actual.WslCommitSwapExists -and $Actual.WslCommitSwapRelease -ne $wslPrior)) {
            throw 'SETUP_TRANSACTION_WSL_LAYOUT_INVALID: an unproven WSL runtime occupies a transaction path'
        }
        if ($Actual.WslActiveRelease -eq $wslPrior -and -not $Actual.WslCommitSwapExists) {
            if ($Actual.WslCandidateExists) { $wslAction = 'abort_candidate' }
        } elseif ($Actual.WslActiveRelease -eq $release -and
                $Actual.WslPreviousRelease -eq $wslPrior -and
                -not $Actual.WslCommitSwapExists) {
            $wslAction = 'compensate'
        } elseif ($Actual.WslCommitSwapRelease -eq $wslPrior -and
                $Actual.WslActiveRelease -in @('', $release)) {
            $wslAction = 'recover_interrupted'
        } else {
            throw 'SETUP_TRANSACTION_WSL_AMBIGUOUS: WSL release state cannot be compensated safely'
        }
    }

    $kernelAction = 'none'
    if ($Actual.KernelRelease -eq $kernelPrior) { $kernelAction = 'none' }
    elseif ([bool]$Transaction.kernel_change_expected -and $Actual.KernelRelease -eq $release) {
        $kernelAction = if ($kernelPrior) { 'rollback' } else { 'restore_original' }
    } else {
        throw 'SETUP_TRANSACTION_KERNEL_AMBIGUOUS: kernel release state cannot be compensated safely'
    }
    return [pscustomobject]@{
        Disposition = 'compensate'; WindowsAction = $windowsAction; WslAction = $wslAction
        KernelAction = $kernelAction; RemoveStage = [bool]$Actual.WindowsStageExists
    }
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

function Register-SwitchTradeUsbWatcherStartup {
    param(
        [Parameter(Mandatory)][string]$RegistryPath,
        [Parameter(Mandatory)][string]$ScriptPath,
        [Parameter(Mandatory)][string]$Distro,
        [Parameter(Mandatory)][string]$InstanceId,
        [Parameter(Mandatory)][string]$StateFile
    )
    $command = Get-SwitchTradeUsbWatcherCommand -ScriptPath $ScriptPath -Distro $Distro `
        -InstanceId $InstanceId -StateFile $StateFile
    New-Item -Path $RegistryPath -Force | Out-Null
    Set-ItemProperty -Path $RegistryPath -Name 'SwitchTradeUsbWatcher' -Value $command
}

function Unregister-SwitchTradeUsbWatcherStartup {
    param([Parameter(Mandatory)][string]$RegistryPath)
    Remove-ItemProperty -Path $RegistryPath -Name 'SwitchTradeUsbWatcher' -ErrorAction SilentlyContinue
}
