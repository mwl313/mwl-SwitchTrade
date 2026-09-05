Set-StrictMode -Version Latest

$script:RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$script:InstalledRoot = '/opt/switchtrade'
$script:OverlayRoot = '/opt/switchtrade-dev'
$script:PythonPath = '/opt/switchtrade/bridge/.venv/bin/python'

class DevOverlayException : System.Exception {
    [string]$Code

    DevOverlayException([string]$Code, [string]$Message) : base($Message) {
        $this.Code = $Code
    }
}

function Stop-DevOverlay {
    param([string]$Code, [string]$Message)
    throw [DevOverlayException]::new($Code, $Message)
}

function Invoke-DevCapturedProcess {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$ArgumentList,
        [string]$WorkingDirectory = $script:RepoRoot
    )

    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $FilePath
    $startInfo.WorkingDirectory = $WorkingDirectory
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    foreach ($argument in $ArgumentList) {
        [void]$startInfo.ArgumentList.Add($argument)
    }
    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    try {
        if (-not $process.Start()) {
            Stop-DevOverlay 'DEV_RUN_FAILED' "Could not start $FilePath."
        }
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        $process.WaitForExit()
        $stdout = $stdoutTask.GetAwaiter().GetResult()
        $stderr = $stderrTask.GetAwaiter().GetResult()
        return [pscustomobject]@{
            ExitCode = $process.ExitCode
            Stdout = $stdout
            Stderr = $stderr
        }
    } finally {
        $process.Dispose()
    }
}

function Invoke-DevInteractiveProcess {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$ArgumentList,
        [string]$WorkingDirectory = $script:RepoRoot
    )

    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $FilePath
    $startInfo.WorkingDirectory = $WorkingDirectory
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    foreach ($argument in $ArgumentList) {
        [void]$startInfo.ArgumentList.Add($argument)
    }
    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    try {
        if (-not $process.Start()) {
            Stop-DevOverlay 'DEV_RUN_FAILED' "Could not start $FilePath."
        }
        $stdoutTask = $process.StandardOutput.ReadLineAsync()
        $stderrTask = $process.StandardError.ReadLineAsync()
        while ($null -ne $stdoutTask -or $null -ne $stderrTask) {
            $pending = [System.Collections.Generic.List[System.Threading.Tasks.Task]]::new()
            if ($null -ne $stdoutTask) { [void]$pending.Add($stdoutTask) }
            if ($null -ne $stderrTask) { [void]$pending.Add($stderrTask) }
            $completed = [System.Threading.Tasks.Task]::WhenAny($pending.ToArray()).GetAwaiter().GetResult()
            if ($completed -eq $stdoutTask) {
                $line = $stdoutTask.GetAwaiter().GetResult()
                if ($null -eq $line) { $stdoutTask = $null } else {
                    Write-Output $line
                    $stdoutTask = $process.StandardOutput.ReadLineAsync()
                }
            } else {
                $line = $stderrTask.GetAwaiter().GetResult()
                if ($null -eq $line) { $stderrTask = $null } else {
                    Write-Error $line
                    $stderrTask = $process.StandardError.ReadLineAsync()
                }
            }
        }
        $process.WaitForExit()
        return $process.ExitCode
    } finally {
        $process.Dispose()
    }
}

function Invoke-DevWsl {
    param(
        [Parameter(Mandatory)][string]$Distro,
        [Parameter(Mandatory)][string]$Command,
        [string[]]$Arguments = @(),
        [string]$Cwd = '/opt/switchtrade'
    )
    $wslArguments = @('--distribution', $Distro, '--user', 'root', '--cd', $Cwd, '--', $Command) + $Arguments
    Invoke-DevCapturedProcess -FilePath 'wsl.exe' -ArgumentList $wslArguments
}

function Invoke-DevInteractiveWsl {
    param(
        [Parameter(Mandatory)][string]$Distro,
        [Parameter(Mandatory)][string]$Command,
        [string[]]$Arguments = @(),
        [string]$Cwd = '/opt/switchtrade'
    )
    $wslArguments = @('--distribution', $Distro, '--user', 'root', '--cd', $Cwd, '--', $Command) + $Arguments
    Invoke-DevInteractiveProcess -FilePath 'wsl.exe' -ArgumentList $wslArguments
}

function Get-ActiveRuntime {
    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        Stop-DevOverlay 'DEV_ACTIVE_RUNTIME_MISSING' 'LOCALAPPDATA is unavailable.'
    }
    $statePath = Join-Path $env:LOCALAPPDATA 'SwitchTrade\state\active-runtime.json'
    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
        Stop-DevOverlay 'DEV_ACTIVE_RUNTIME_MISSING' 'active-runtime.json is missing.'
    }
    try {
        $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    } catch {
        Stop-DevOverlay 'DEV_ACTIVE_RUNTIME_INVALID' 'active-runtime.json is not valid JSON.'
    }
    if ($state.schema -ne 1 -or $state.active_runtime -isnot [string] -or
        $state.active_runtime -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$') {
        Stop-DevOverlay 'DEV_ACTIVE_RUNTIME_INVALID' 'active runtime schema or name is invalid.'
    }
    return [pscustomobject]@{ Name = $state.active_runtime; StatePath = $statePath }
}

function ConvertTo-WslPath {
    param([Parameter(Mandatory)][string]$WindowsPath)
    $fullPath = [System.IO.Path]::GetFullPath($WindowsPath)
    if ($fullPath -notmatch '^(?<drive>[A-Za-z]):(?<rest>.*)$') {
        Stop-DevOverlay 'DEV_ARCHIVE_FAILED' 'The temporary archive path is not a Windows path.'
    }
    return "/mnt/$($Matches.drive.ToLowerInvariant())$($Matches.rest.Replace('\', '/'))"
}

function Get-FileDigest {
    param([Parameter(Mandatory)][string]$Path)
    (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Get-SourceFiles {
    $gitResult = Invoke-DevCapturedProcess -FilePath 'git' -ArgumentList @('ls-files', '--cached', '--others', '--exclude-standard')
    if ($gitResult.ExitCode -ne 0) {
        Stop-DevOverlay 'DEV_SOURCE_ALLOWLIST_EMPTY' 'Could not enumerate the source tree.'
    }
    $allPaths = @($gitResult.Stdout -split "`r?`n" | Where-Object { $_ })
    $denyPattern = '(^|/)(\.git|\.venv|__pycache__|artifacts|runs|captures|support-bundles?)(/|$)|\.(pcap|pcapng|zip)$|(^|/)config/prod\.keys$|(^|/)(token|credential)[^/]*$'
    if ($allPaths | Where-Object { $_ -match $denyPattern }) {
        Stop-DevOverlay 'DEV_SOURCE_FORBIDDEN' 'A forbidden source path is present in the checkout.'
    }
    $allowlistPath = Join-Path $PSScriptRoot 'dev-source-allowlist.txt'
    if (-not (Test-Path -LiteralPath $allowlistPath -PathType Leaf)) {
        Stop-DevOverlay 'DEV_SOURCE_ALLOWLIST_EMPTY' 'The source allowlist is missing.'
    }
    $allowPatterns = @(Get-Content -LiteralPath $allowlistPath | Where-Object { $_ -and $_ -notmatch '^\s*#' })
    $sourceFiles = @(
        foreach ($candidatePath in $allPaths) {
            $normalizedPath = $candidatePath -replace '\\', '/'
            $allowed = $false
            foreach ($allowPattern in $allowPatterns) {
                $allowRegex = '^' + [regex]::Escape($allowPattern.Trim()).Replace('\*\*/', '(?:.*/)?').Replace('\*', '[^/]*') + '$'
                if ($normalizedPath -match $allowRegex) { $allowed = $true; break }
            }
            if ($allowed) { $normalizedPath }
        }
    ) | Sort-Object -Unique
    if ($sourceFiles.Count -eq 0) {
        Stop-DevOverlay 'DEV_SOURCE_ALLOWLIST_EMPTY' 'The source allowlist produced no files.'
    }
    return $sourceFiles
}

function Get-SourceManifest {
    param([Parameter(Mandatory)][string[]]$RelativePaths)
    $fileMap = [ordered]@{}
    $identityLines = [System.Collections.Generic.List[string]]::new()
    foreach ($relativePath in $RelativePaths) {
        $absolutePath = Join-Path $script:RepoRoot ($relativePath -replace '/', '\')
        if (-not (Test-Path -LiteralPath $absolutePath -PathType Leaf)) {
            Stop-DevOverlay 'DEV_SOURCE_FORBIDDEN' "Allowlisted source is missing: $relativePath"
        }
        $digest = Get-FileDigest -Path $absolutePath
        $fileMap[$relativePath] = $digest
        [void]$identityLines.Add("$relativePath`0$digest`n")
    }
    $identityBytes = [System.Text.Encoding]::UTF8.GetBytes(($identityLines -join ''))
    $contentId = ([BitConverter]::ToString(([System.Security.Cryptography.SHA256]::Create().ComputeHash($identityBytes))).Replace('-', '')).ToLowerInvariant()
    $headResult = Invoke-DevCapturedProcess -FilePath 'git' -ArgumentList @('rev-parse', 'HEAD')
    if ($headResult.ExitCode -ne 0) {
        Stop-DevOverlay 'DEV_SOURCE_ALLOWLIST_EMPTY' 'Could not resolve the source commit.'
    }
    $dirty = (Invoke-DevCapturedProcess -FilePath 'git' -ArgumentList @('status', '--porcelain')).Stdout.Trim().Length -gt 0
    return [pscustomobject]@{
        Schema = 1
        GitHead = $headResult.Stdout.Trim()
        Dirty = $dirty
        ContentId = $contentId
        Files = $fileMap
    }
}

function Get-InstalledRequirementHashes {
    param([Parameter(Mandatory)][string]$Distro)
    $result = Invoke-DevWsl -Distro $Distro -Command '/usr/bin/sha256sum' -Arguments @(
        "$script:InstalledRoot/requirements.txt",
        "$script:InstalledRoot/bridge/requirements.txt"
    )
    if ($result.ExitCode -ne 0) {
        Stop-DevOverlay 'DEV_DEPENDENCY_MISMATCH' 'Installed dependency lock files could not be read.'
    }
    $hashes = @{}
    foreach ($line in ($result.Stdout -split "`r?`n" | Where-Object { $_ })) {
        if ($line -notmatch '^(?<hash>[0-9a-fA-F]{64})\s+\*?(?<path>/opt/switchtrade/.+)$') {
            Stop-DevOverlay 'DEV_DEPENDENCY_MISMATCH' 'Installed dependency hash output is invalid.'
        }
        $hashes[$Matches.path] = $Matches.hash.ToLowerInvariant()
    }
    return $hashes
}

function Assert-DependencyCompatibility {
    param([Parameter(Mandatory)][string]$Distro)
    $localRequirements = @{
        '/opt/switchtrade/requirements.txt' = Get-FileDigest (Join-Path $script:RepoRoot 'requirements.txt')
        '/opt/switchtrade/bridge/requirements.txt' = Get-FileDigest (Join-Path $script:RepoRoot 'bridge/requirements.txt')
    }
    $installedRequirements = Get-InstalledRequirementHashes -Distro $Distro
    foreach ($path in $localRequirements.Keys) {
        if (-not $installedRequirements.ContainsKey($path) -or $installedRequirements[$path] -ne $localRequirements[$path]) {
            Stop-DevOverlay 'DEV_DEPENDENCY_MISMATCH' 'The installed WSL runtime does not match this checkout.'
        }
    }
}

function Assert-RemoteManifest {
    param(
        [Parameter(Mandatory)][string]$Distro,
        [Parameter(Mandatory)]$Manifest,
        [Parameter(Mandatory)][string]$RemoteRoot
    )

    $verifyArguments = @($Manifest.Files.Keys | ForEach-Object { "$RemoteRoot/$_" })
    $verifyResult = Invoke-DevWsl -Distro $Distro -Command '/usr/bin/sha256sum' -Arguments $verifyArguments
    if ($verifyResult.ExitCode -ne 0) {
        Stop-DevOverlay 'DEV_MANIFEST_MISMATCH' 'The WSL overlay hash check failed.'
    }
    $prefix = "$RemoteRoot/"
    $actualFiles = @{}
    foreach ($line in ($verifyResult.Stdout -split "`r?`n" | Where-Object { $_ })) {
        if ($line -notmatch '^(?<hash>[0-9a-fA-F]{64})\s+\*?(?<path>.+)$' -or -not $Matches.path.StartsWith($prefix, [System.StringComparison]::Ordinal)) {
            Stop-DevOverlay 'DEV_MANIFEST_MISMATCH' 'The WSL overlay hash output is invalid.'
        }
        $relativePath = $Matches.path.Substring($prefix.Length)
        if ($actualFiles.ContainsKey($relativePath)) {
            Stop-DevOverlay 'DEV_MANIFEST_MISMATCH' 'The WSL overlay hash output has duplicate paths.'
        }
        $actualFiles[$relativePath] = $Matches.hash.ToLowerInvariant()
    }
    if ($actualFiles.Count -ne $Manifest.Files.Count) {
        Stop-DevOverlay 'DEV_MANIFEST_MISMATCH' 'The copied source does not match the local manifest.'
    }
    foreach ($relativePath in $Manifest.Files.Keys) {
        if (-not $actualFiles.ContainsKey($relativePath) -or $actualFiles[$relativePath] -ne $Manifest.Files[$relativePath]) {
            Stop-DevOverlay 'DEV_MANIFEST_MISMATCH' 'The copied source does not match the local manifest.'
        }
    }
}

function Set-DevCurrentRelease {
    param(
        [Parameter(Mandatory)][string]$Distro,
        [Parameter(Mandatory)][string]$ContentId,
        [Parameter(Mandatory)][string]$CurrentTemp
    )

    $linkResult = Invoke-DevWsl -Distro $Distro -Command '/bin/ln' -Arguments @('-s', "releases/$ContentId", $CurrentTemp)
    if ($linkResult.ExitCode -ne 0) { Stop-DevOverlay 'DEV_COMMIT_FAILED' 'Could not prepare the atomic current link.' }
    $switchResult = Invoke-DevWsl -Distro $Distro -Command '/bin/mv' -Arguments @('-Tf', $CurrentTemp, "$script:OverlayRoot/current")
    if ($switchResult.ExitCode -ne 0) { Stop-DevOverlay 'DEV_COMMIT_FAILED' 'Could not switch the current overlay atomically.' }
}

function Invoke-DevDoctor {
    $runtime = Get-ActiveRuntime
    $listResult = Invoke-DevCapturedProcess -FilePath 'wsl.exe' -ArgumentList @('--list', '--quiet')
    if ($listResult.ExitCode -ne 0 -or -not (@($listResult.Stdout -split "`r?`n" | ForEach-Object { $_.Trim() }) -contains $runtime.Name)) {
        Stop-DevOverlay 'DEV_WSL_RUNTIME_NOT_REGISTERED' 'The active WSL distro is not registered.'
    }
    $markerResult = Invoke-DevWsl -Distro $runtime.Name -Command '/bin/cat' -Arguments @('/etc/switchtrade-distro.json')
    if ($markerResult.ExitCode -ne 0) {
        Stop-DevOverlay 'DEV_RUNTIME_OWNERSHIP_INVALID' 'The SwitchTrade distro marker is unavailable.'
    }
    try { $marker = $markerResult.Stdout | ConvertFrom-Json } catch { Stop-DevOverlay 'DEV_RUNTIME_OWNERSHIP_INVALID' 'The distro marker is invalid JSON.' }
    if ($marker.owner -ne 'SwitchTrade') {
        Stop-DevOverlay 'DEV_RUNTIME_OWNERSHIP_INVALID' 'The active distro is not owned by SwitchTrade.'
    }
    $pythonProbe = Invoke-DevWsl -Distro $runtime.Name -Command '/usr/bin/test' -Arguments @('-x', $script:PythonPath)
    if ($pythonProbe.ExitCode -ne 0) {
        Stop-DevOverlay 'DEV_PYTHON_MISSING' 'The installed SwitchTrade Python executable is missing.'
    }
    $pythonVersion = Invoke-DevWsl -Distro $runtime.Name -Command $script:PythonPath -Arguments @('--version')
    if ($pythonVersion.ExitCode -ne 0) {
        Stop-DevOverlay 'DEV_PYTHON_MISSING' 'The installed SwitchTrade Python executable did not run.'
    }
    Assert-DependencyCompatibility -Distro $runtime.Name
    $result = [ordered]@{
        schema = 1
        active_runtime = $runtime.Name
        installed_root = $script:InstalledRoot
        overlay_root = $script:OverlayRoot
        python = $script:PythonPath
        python_version = ($pythonVersion.Stdout + $pythonVersion.Stderr).Trim()
        dependency_match = $true
    }
    $result | ConvertTo-Json -Compress
}

function Invoke-DevSync {
    $doctor = Invoke-DevDoctor | ConvertFrom-Json
    $sourceFiles = @(Get-SourceFiles)
    $manifest = Get-SourceManifest -RelativePaths $sourceFiles
    $nonce = [guid]::NewGuid().ToString('N')
    $tempTar = Join-Path ([System.IO.Path]::GetTempPath()) "SwitchTrade-dev-$($manifest.ContentId)-$nonce.tar"
    $lockPath = "$script:OverlayRoot/.lock"
    $stagingPath = "$script:OverlayRoot/.staging-$($manifest.ContentId)-$nonce"
    $releasePath = "$script:OverlayRoot/releases/$($manifest.ContentId)"
    $currentTemp = "$script:OverlayRoot/.current-$nonce"
    $lockAcquired = $false
    try {
        $rootResult = Invoke-DevWsl -Distro $doctor.active_runtime -Command '/bin/mkdir' -Arguments @('-p', "$script:OverlayRoot/releases")
        if ($rootResult.ExitCode -ne 0) { Stop-DevOverlay 'DEV_EXTRACT_FAILED' 'Could not prepare the overlay root.' }
        $lockResult = Invoke-DevWsl -Distro $doctor.active_runtime -Command '/bin/mkdir' -Arguments @($lockPath)
        if ($lockResult.ExitCode -ne 0) { Stop-DevOverlay 'DEV_DEPLOY_BUSY' 'Another overlay operation owns the lock.' }
        $lockAcquired = $true
        $releaseCheck = Invoke-DevWsl -Distro $doctor.active_runtime -Command '/usr/bin/test' -Arguments @('-e', $releasePath)
        if ($releaseCheck.ExitCode -eq 0) {
            Assert-RemoteManifest -Distro $doctor.active_runtime -Manifest $manifest -RemoteRoot $releasePath
            Set-DevCurrentRelease -Distro $doctor.active_runtime -ContentId $manifest.ContentId -CurrentTemp $currentTemp
            [ordered]@{ schema = 1; content_id = $manifest.ContentId; dirty = $manifest.Dirty; file_count = $sourceFiles.Count; reused = $true } | ConvertTo-Json -Compress
            return
        }
        if ($releaseCheck.ExitCode -ne 1) { Stop-DevOverlay 'DEV_COMMIT_FAILED' 'Could not check the immutable overlay release.' }
        $tarArguments = @('-cf', $tempTar, '-C', $script:RepoRoot, '--') + $sourceFiles
        $archive = Invoke-DevCapturedProcess -FilePath 'tar' -ArgumentList $tarArguments
        if ($archive.ExitCode -ne 0) { Stop-DevOverlay 'DEV_ARCHIVE_FAILED' 'Could not create the source archive.' }
        $stageResult = Invoke-DevWsl -Distro $doctor.active_runtime -Command '/bin/mkdir' -Arguments @('-p', $stagingPath)
        if ($stageResult.ExitCode -ne 0) { Stop-DevOverlay 'DEV_EXTRACT_FAILED' 'Could not create the staging directory.' }
        $extractResult = Invoke-DevWsl -Distro $doctor.active_runtime -Command '/usr/bin/tar' -Arguments @('-xf', (ConvertTo-WslPath $tempTar), '-C', $stagingPath)
        if ($extractResult.ExitCode -ne 0) { Stop-DevOverlay 'DEV_EXTRACT_FAILED' 'Could not extract the source archive in WSL.' }
        Assert-RemoteManifest -Distro $doctor.active_runtime -Manifest $manifest -RemoteRoot $stagingPath
        $commitResult = Invoke-DevWsl -Distro $doctor.active_runtime -Command '/bin/mv' -Arguments @($stagingPath, $releasePath)
        if ($commitResult.ExitCode -ne 0) { Stop-DevOverlay 'DEV_COMMIT_FAILED' 'Could not commit the immutable overlay release.' }
        Set-DevCurrentRelease -Distro $doctor.active_runtime -ContentId $manifest.ContentId -CurrentTemp $currentTemp
        [ordered]@{ schema = 1; content_id = $manifest.ContentId; dirty = $manifest.Dirty; file_count = $sourceFiles.Count; reused = $false } | ConvertTo-Json -Compress
    } finally {
        if ($lockAcquired) { [void](Invoke-DevWsl -Distro $doctor.active_runtime -Command '/bin/rm' -Arguments @('-rf', '--', $stagingPath)) }
        if ($lockAcquired) { [void](Invoke-DevWsl -Distro $doctor.active_runtime -Command '/bin/rmdir' -Arguments @($lockPath)) }
        if (Test-Path -LiteralPath $tempTar -PathType Leaf) { Remove-Item -LiteralPath $tempTar -Force }
    }
}

function Invoke-DevRun {
    param([string[]]$Arguments = @(), [switch]$Test, [switch]$CoreCli)
    $null = Invoke-DevSync
    $runtime = Get-ActiveRuntime
    $pythonArguments = if ($Test) { @('-m', 'pytest') + $Arguments } else { $Arguments }
    $commandArguments = if ($CoreCli) {
        $radioRole = if ($Arguments -contains 'host') { 'guest' } else { 'host' }
        $channel = '6'
        $usbId = $null
        for ($index = 2; $index -lt $Arguments.Count; $index += 1) {
            if ($Arguments[$index] -eq '--channel') { $index += 1; $channel = $Arguments[$index]; continue }
            if ($Arguments[$index] -eq '--usb-id') { $index += 1; $usbId = $Arguments[$index] }
        }
        $gateArguments = @('./scripts/wsl-radio-prepare.sh', '--role', $radioRole)
        if ($usbId) { $gateArguments += @('--usb-id', $usbId) }
        $gateArguments + @('--target-channel', $channel, '--', $script:PythonPath) + $pythonArguments
    } else {
        @($script:PythonPath) + $pythonArguments
    }
    $envArguments = @('/usr/bin/env', 'PYTHONNOUSERSITE=1', "PYTHONPATH=$script:OverlayRoot/current", "SWITCHTRADE_SOURCE_ROOT=$script:OverlayRoot/current", "SWITCHTRADE_INSTALLED_ROOT=$script:InstalledRoot") + $commandArguments
    $exitCode = Invoke-DevInteractiveWsl -Distro $runtime.Name -Cwd "$script:OverlayRoot/current" -Command $envArguments[0] -Arguments $envArguments[1..($envArguments.Count - 1)]
    if ($exitCode -ne 0) { Stop-DevOverlay 'DEV_RUN_FAILED' "The development process exited with code $exitCode." }
    return 0
}

function Invoke-DevClean {
    $runtime = Get-ActiveRuntime
    $result = Invoke-DevWsl -Distro $runtime.Name -Command '/bin/rm' -Arguments @('-rf', '--', $script:OverlayRoot)
    if ($result.ExitCode -ne 0) { Stop-DevOverlay 'DEV_CLEAN_REFUSED' 'Overlay cleanup failed.' }
    [void](Invoke-DevWsl -Distro $runtime.Name -Command '/bin/mkdir' -Arguments @('-p', "$script:OverlayRoot/releases"))
    [ordered]@{ schema = 1; cleaned = $script:OverlayRoot } | ConvertTo-Json -Compress
}

Export-ModuleMember -Function Invoke-DevDoctor, Invoke-DevSync, Invoke-DevRun, Invoke-DevClean
