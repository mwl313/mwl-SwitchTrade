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
    $VersionText = $VersionText.Replace([string][char]0, '')
    $HelpText = $HelpText.Replace([string][char]0, '')
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
    $VersionText = $VersionText.Replace([string][char]0, '')
    $HelpText = $HelpText.Replace([string][char]0, '')
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
        [bool]$KernelChangeExpected = $false,
        [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{32}$')][string]$InstallId,
        [Parameter(Mandatory)][string]$DistroBasePath,
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
        $rollbackPackage = (Assert-SwitchTradeRollbackJournal -Transaction $Transaction).initiating_package
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

function Resolve-SwitchTradeTransactionRecovery {
    param(
        [Parameter(Mandatory)]$Transaction,
        [Parameter(Mandatory)]$Actual
    )
    if ([int]$Transaction.schema -ne 3) {
        throw 'SETUP_TRANSACTION_LEGACY_AMBIGUOUS: the interrupted transaction cannot prove pre-mutation ownership'
    }
    if (-not [bool]$Actual.EnumerationKnown) {
        throw 'SETUP_TRANSACTION_DISTRO_ENUMERATION_UNKNOWN: WSL distribution state could not be determined'
    }
    if ($Actual.DistroExists -and -not $Actual.DistroOwned) {
        throw 'SETUP_TRANSACTION_DISTRO_OWNERSHIP_CHANGED: the named distribution is not installer-owned'
    }
    if ($Actual.DistroExists -and
            ([string]$Actual.DistroInstallId -cne [string]$Transaction.install_id -or
             -not [string]::Equals([IO.Path]::GetFullPath([string]$Actual.DistroBasePath).TrimEnd('\'),
                 [IO.Path]::GetFullPath([string]$Transaction.distro_base_path).TrimEnd('\'),
                 [StringComparison]::OrdinalIgnoreCase))) {
        throw 'SETUP_TRANSACTION_DISTRO_IDENTITY_CHANGED: distribution install identity or BasePath changed'
    }
    if ([bool]$Transaction.distro_existed_before -and
            (-not [bool]$Transaction.distro_owned_before -or -not $Actual.DistroExists)) {
        throw 'SETUP_TRANSACTION_PRIOR_DISTRO_MISSING: the prior owned distribution cannot be proven'
    }

    $release = [string]$Transaction.release_id
    $windowsPrior = [string]$Transaction.prior_release_id
    $wslPrior = [string]$Transaction.wsl_prior_release_id
    $kernelPrior = [string]$Transaction.kernel_prior_release_id
    $windowsIntegrity = [string]$Transaction.windows_integrity_sha256
    $wslIntegrity = [string]$Transaction.wsl_integrity_sha256
    $kernelExpected = if ([bool]$Transaction.kernel_change_expected) { $release } else { $kernelPrior }
    $retainedReady = (-not $windowsPrior -or $Actual.WindowsPreviousRelease -eq $windowsPrior) -and
        (-not $wslPrior -or $Actual.WslPreviousRelease -eq $wslPrior)
    $coherentCommit = $windowsIntegrity -and $wslIntegrity -and
        $Actual.WindowsActiveRelease -eq $release -and
        $Actual.WindowsActiveIntegrity -eq $windowsIntegrity -and
        $Actual.WslActiveRelease -eq $release -and $Actual.WslActiveIntegrity -eq $wslIntegrity -and
        $Actual.KernelRelease -eq $kernelExpected -and $retainedReady -and
        -not $Actual.WindowsStageExists -and -not $Actual.WslCandidateExists -and
        -not $Actual.WslCommitSwapExists -and -not $Actual.WslRollbackSwapExists
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
    if ($Actual.WindowsSwapExists) {
        if (-not $windowsPrior -or $Actual.WindowsSwapRelease -ne $release -or
                -not (($Actual.WindowsActiveRelease -eq '' -and
                        $Actual.WindowsPreviousRelease -eq $windowsPrior) -or
                       ($Actual.WindowsActiveRelease -eq $windowsPrior -and
                        -not $Actual.WindowsPreviousExists))) {
            throw 'SETUP_TRANSACTION_WINDOWS_SWAP_INVALID: interrupted rollback state is not proven'
        }
        $windowsAction = 'rollback'
    } elseif ($windowsPrior) {
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
                ($Actual.WslCommitSwapExists -and $Actual.WslCommitSwapRelease -ne $wslPrior) -or
                ($Actual.WslRollbackSwapExists -and $Actual.WslRollbackSwapRelease -ne $release)) {
            throw 'SETUP_TRANSACTION_WSL_LAYOUT_INVALID: an unproven WSL runtime occupies a transaction path'
        }
        if ($Actual.WslRollbackSwapExists -and
                (($Actual.WslActiveRelease -eq '' -and $Actual.WslPreviousRelease -eq $wslPrior) -or
                 ($Actual.WslActiveRelease -eq $wslPrior -and $Actual.WslPreviousRelease -eq ''))) {
            $wslAction = 'compensate'
        } elseif ($Actual.WslActiveRelease -eq $wslPrior -and
                -not $Actual.WslCommitSwapExists) {
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

function Assert-SwitchTradeInterruptedTransactionAction {
    param(
        [Parameter(Mandatory)][string]$RequestedAction,
        [Parameter(Mandatory)]$Transaction
    )
    if ($RequestedAction -eq 'Repair' -or
            $RequestedAction -eq [string]$Transaction.action) {
        return $true
    }
    throw "SETUP_TRANSACTION_INCOMPLETE: transaction $($Transaction.transaction_id) stopped at $($Transaction.phase); rerun the same action or choose Repair from the package that started it"
}

function Test-SwitchTradeEarlyFreshInstallRecovery {
    param([Parameter(Mandatory)]$Transaction)
    return [int]$Transaction.schema -eq 3 -and
        -not [string]$Transaction.prior_release_id -and
        -not [bool]$Transaction.distro_existed_before -and
        [string]$Transaction.phase -in @('created', 'windows_staged', 'importing_distro',
            'distro_imported')
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

function Get-SwitchTradeCompletedRollbackState {
    param(
        [Parameter(Mandatory)]$Transaction,
        [Parameter(Mandatory)]$KernelState
    )
    if ([int]$Transaction.schema -ne 3 -or [string]$Transaction.phase -ne 'completed') {
        throw 'ROLLBACK_TRANSACTION_NOT_COMPLETED: only a completed release transaction can rotate'
    }
    $activeRelease = [string]$Transaction.release_id
    $rollbackRelease = [string]$Transaction.prior_release_id
    if (-not $activeRelease -or -not $rollbackRelease -or
            [string]$Transaction.wsl_prior_release_id -ne $rollbackRelease) {
        throw 'ROLLBACK_TRANSACTION_RELEASE_MISMATCH: active and retained identities are incomplete'
    }
    foreach ($anchor in @([string]$Transaction.windows_integrity_sha256,
            [string]$Transaction.windows_prior_integrity_sha256,
            [string]$Transaction.wsl_integrity_sha256,
            [string]$Transaction.wsl_prior_integrity_sha256)) {
        if ($anchor -notmatch '^[0-9a-f]{64}$') {
            throw 'ROLLBACK_TRANSACTION_INTEGRITY_ANCHOR_INVALID'
        }
    }
    if ([string]$KernelState.package_release_id -ne $rollbackRelease -or
            [string]$KernelState.rollback_package_release_id -ne $activeRelease -or
            -not [string]$KernelState.rollback_kernel_path) {
        throw 'ROLLBACK_KERNEL_IDENTITY_MISMATCH: rolled-back kernel state is not reversible'
    }
    $state = $Transaction | ConvertTo-Json -Depth 8 | ConvertFrom-Json
    $state.action = 'Rollback'
    $state.release_id = $rollbackRelease
    $state.prior_release_id = $activeRelease
    $state.wsl_prior_release_id = $activeRelease
    $state.kernel_prior_release_id = $activeRelease
    $state.kernel_prior_path = [string]$KernelState.rollback_kernel_path
    $state.kernel_prior_modules_path = [string]$KernelState.rollback_modules_path
    $state.windows_integrity_sha256 = [string]$Transaction.windows_prior_integrity_sha256
    $state.windows_prior_integrity_sha256 = [string]$Transaction.windows_integrity_sha256
    $state.wsl_integrity_sha256 = [string]$Transaction.wsl_prior_integrity_sha256
    $state.wsl_prior_integrity_sha256 = [string]$Transaction.wsl_integrity_sha256
    $state.phase = 'completed'
    return $state
}

function Set-SwitchTradeCompletedRollbackState {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)]$Transaction,
        [Parameter(Mandatory)]$KernelState
    )
    $state = Get-SwitchTradeCompletedRollbackState -Transaction $Transaction -KernelState $KernelState
    Write-AtomicJson -Path $Path -Value $state
    return $state
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

function Start-SwitchTradeRollbackTransaction {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)]$Transaction,
        [Parameter(Mandatory)]$KernelState,
        [Parameter(Mandatory)][string]$PackageRoot,
        [Parameter(Mandatory)][string]$PackageReleaseId,
        [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{64}$')]
        [string]$PackageManifestSha256
    )
    $journal = New-SwitchTradeRollbackJournal -Transaction $Transaction -KernelState $KernelState `
        -PackageRoot $PackageRoot -PackageReleaseId $PackageReleaseId `
        -PackageManifestSha256 $PackageManifestSha256
    return Set-SwitchTradeTransactionPhase -Path $Path -Phase 'rollback_prepared' -Fields @{
        rollback_journal = $journal
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

function Set-SwitchTradeRollbackPublishedState {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)]$Transaction,
        [Parameter(Mandatory)][ValidateSet('source', 'target')][string]$Direction
    )
    $state = Get-SwitchTradeRollbackPublishedState -Transaction $Transaction -Direction $Direction
    Write-AtomicJson -Path $Path -Value $state
    return $state
}

function Get-SwitchTradeRollbackPairPosition {
    param(
        [Parameter(Mandatory)]$Source,
        [Parameter(Mandatory)]$Target,
        [Parameter(Mandatory)]$Actual,
        [Parameter(Mandatory)][string]$Axis
    )
    $sourceActive = $Actual.ActiveExists -and
        [string]$Actual.ActiveRelease -eq [string]$Source.release_id -and
        [string]$Actual.ActiveIntegrity -eq [string]$Source.integrity_sha256
    $targetActive = $Actual.ActiveExists -and
        [string]$Actual.ActiveRelease -eq [string]$Target.release_id -and
        [string]$Actual.ActiveIntegrity -eq [string]$Target.integrity_sha256
    $sourcePrevious = $Actual.PreviousExists -and
        [string]$Actual.PreviousRelease -eq [string]$Source.release_id -and
        [string]$Actual.PreviousIntegrity -eq [string]$Source.integrity_sha256
    $targetPrevious = $Actual.PreviousExists -and
        [string]$Actual.PreviousRelease -eq [string]$Target.release_id -and
        [string]$Actual.PreviousIntegrity -eq [string]$Target.integrity_sha256
    $sourceSwap = $Actual.SwapExists -and
        [string]$Actual.SwapRelease -eq [string]$Source.release_id -and
        [string]$Actual.SwapIntegrity -eq [string]$Source.integrity_sha256
    $targetSwap = $Actual.SwapExists -and
        [string]$Actual.SwapRelease -eq [string]$Target.release_id -and
        [string]$Actual.SwapIntegrity -eq [string]$Target.integrity_sha256
    if (-not $Actual.SwapExists -and $sourceActive -and $targetPrevious) { return 'source' }
    if (-not $Actual.SwapExists -and $targetActive -and $sourcePrevious) { return 'target' }
    if ($sourceSwap -and
            ((-not $Actual.ActiveExists -and $targetPrevious) -or
             ($targetActive -and -not $Actual.PreviousExists))) {
        return 'target_transition'
    }
    if ($targetSwap -and
            ((-not $Actual.ActiveExists -and $sourcePrevious) -or
             ($sourceActive -and -not $Actual.PreviousExists))) {
        return 'source_transition'
    }
    throw ('ROLLBACK_{0}_STATE_AMBIGUOUS: release pair or integrity anchor changed' -f $Axis)
}

function Resolve-SwitchTradeRollbackRecovery {
    param(
        [Parameter(Mandatory)]$Transaction,
        [Parameter(Mandatory)]$Actual
    )
    $journal = Assert-SwitchTradeRollbackJournal -Transaction $Transaction
    $windowsSource = [pscustomobject]@{
        release_id = [string]$journal.source.release_id
        integrity_sha256 = [string]$journal.source.windows_integrity_sha256
    }
    $windowsTarget = [pscustomobject]@{
        release_id = [string]$journal.target.release_id
        integrity_sha256 = [string]$journal.target.windows_integrity_sha256
    }
    $wslSource = [pscustomobject]@{
        release_id = [string]$journal.source.release_id
        integrity_sha256 = [string]$journal.source.wsl_integrity_sha256
    }
    $wslTarget = [pscustomobject]@{
        release_id = [string]$journal.target.release_id
        integrity_sha256 = [string]$journal.target.wsl_integrity_sha256
    }
    $windows = Get-SwitchTradeRollbackPairPosition -Source $windowsSource -Target $windowsTarget -Actual $Actual.Windows -Axis 'WINDOWS'
    $wsl = Get-SwitchTradeRollbackPairPosition -Source $wslSource -Target $wslTarget -Actual $Actual.Wsl -Axis 'WSL'
    $kernel = ''
    foreach ($direction in @('source', 'target')) {
        $axis = $journal.$direction
        $pathsMatch = [string]::Equals([string]$Actual.Kernel.kernel_path,
            [string]$axis.kernel_path, [StringComparison]::OrdinalIgnoreCase) -and
            [string]::Equals([string]$Actual.Kernel.modules_path,
                [string]$axis.modules_path, [StringComparison]::OrdinalIgnoreCase)
        if ([string]$Actual.Kernel.package_release_id -eq [string]$axis.release_id -and
                $pathsMatch -and [string]$Actual.Kernel.kernel_release -eq [string]$axis.kernel_release -and
                [string]$Actual.Kernel.modules_format -eq [string]$axis.modules_format -and
                [string]$Actual.Kernel.kernel_sha256 -eq [string]$axis.kernel_sha256 -and
                [string]$Actual.Kernel.modules_sha256 -eq [string]$axis.modules_sha256) {
            $kernel = $direction
        }
    }
    if (-not $kernel) { throw 'ROLLBACK_KERNEL_STATE_AMBIGUOUS: kernel identity or anchor changed' }
    $desired = if ($windows -notin @('source', 'source_transition') -and
            $wsl -notin @('source', 'source_transition') -and $kernel -ne 'source') {
        'target'
    } else { 'source' }
    return [pscustomobject]@{
        Direction = $desired; WindowsPosition = $windows; WslPosition = $wsl
        KernelPosition = $kernel
    }
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
