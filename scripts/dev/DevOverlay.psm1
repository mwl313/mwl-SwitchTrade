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

function Invoke-DevProcess {
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
        $stdout = $process.StandardOutput.ReadToEnd()
        $stderr = $process.StandardError.ReadToEnd()
        $process.WaitForExit()
        return [pscustomobject]@{
            ExitCode = $process.ExitCode
            Stdout = $stdout
            Stderr = $stderr
        }
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
    Invoke-DevProcess -FilePath 'wsl.exe' -ArgumentList $wslArguments
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
    $gitResult = Invoke-DevProcess -FilePath 'git' -ArgumentList @('ls-files', '--cached', '--others', '--exclude-standard')
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
    $headResult = Invoke-DevProcess -FilePath 'git' -ArgumentList @('rev-parse', 'HEAD')
    if ($headResult.ExitCode -ne 0) {
        Stop-DevOverlay 'DEV_SOURCE_ALLOWLIST_EMPTY' 'Could not resolve the source commit.'
    }
    $dirty = (Invoke-DevProcess -FilePath 'git' -ArgumentList @('status', '--porcelain')).Stdout.Trim().Length -gt 0
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

function Invoke-DevDoctor {
    $runtime = Get-ActiveRuntime
    $listResult = Invoke-DevProcess -FilePath 'wsl.exe' -ArgumentList @('--list', '--quiet')
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
    $runtime = Get-ActiveRuntime
    $doctor = Invoke-DevDoctor | ConvertFrom-Json
    $sourceFiles = Get-SourceFiles
    $manifest = Get-SourceManifest -RelativePaths $sourceFiles
    $nonce = [guid]::NewGuid().ToString('N')
    $tempTar = Join-Path ([System.IO.Path]::GetTempPath()) "SwitchTrade-dev-$($manifest.ContentId)-$nonce.tar"
    $lockPath = "$script:OverlayRoot/.lock"
    $stagingPath = "$script:OverlayRoot/.staging-$($manifest.ContentId)-$nonce"
    $releasePath = "$script:OverlayRoot/releases/$($manifest.ContentId)"
    $currentTemp = "$script:OverlayRoot/.current-$nonce"
    $lockAcquired = $false
    try {
        $tarArguments = @('-cf', $tempTar, '-C', $script:RepoRoot, '--') + $sourceFiles
        $archive = Invoke-DevProcess -FilePath 'tar' -ArgumentList $tarArguments
        if ($archive.ExitCode -ne 0) {
            Stop-DevOverlay 'DEV_ARCHIVE_FAILED' 'Could not create the source archive.'
        }
        $rootResult = Invoke-DevWsl -Distro $doctor.active_runtime -Command '/bin/mkdir' -Arguments @('-p', $script:OverlayRoot)
        if ($rootResult.ExitCode -ne 0) { Stop-DevOverlay 'DEV_EXTRACT_FAILED' 'Could not prepare the overlay root.' }
        $lockResult = Invoke-DevWsl -Distro $doctor.active_runtime -Command '/bin/mkdir' -Arguments @($lockPath)
        if ($lockResult.ExitCode -ne 0) { Stop-DevOverlay 'DEV_DEPLOY_BUSY' 'Another overlay operation owns the lock.' }
        $lockAcquired = $true
        $stageResult = Invoke-DevWsl -Distro $doctor.active_runtime -Command '/bin/mkdir' -Arguments @('-p', $stagingPath)
        if ($stageResult.ExitCode -ne 0) { Stop-DevOverlay 'DEV_EXTRACT_FAILED' 'Could not create the staging directory.' }
        $extractResult = Invoke-DevWsl -Distro $doctor.active_runtime -Command '/usr/bin/tar' -Arguments @('-xf', (ConvertTo-WslPath $tempTar), '-C', $stagingPath)
        if ($extractResult.ExitCode -ne 0) { Stop-DevOverlay 'DEV_EXTRACT_FAILED' 'Could not extract the source archive in WSL.' }
        $verifyArguments = @()
        foreach ($sourceFile in $sourceFiles) { $verifyArguments += "$stagingPath/$sourceFile" }
        $verifyResult = Invoke-DevWsl -Distro $doctor.active_runtime -Command '/usr/bin/sha256sum' -Arguments $verifyArguments
        if ($verifyResult.ExitCode -ne 0) { Stop-DevOverlay 'DEV_MANIFEST_MISMATCH' 'The WSL overlay hash check failed.' }
        $expectedHashes = @($manifest.Files.Values)
        $actualHashes = @($verifyResult.Stdout -split "`r?`n" | Where-Object { $_ } | ForEach-Object { ($_ -split '\s+')[0].ToLowerInvariant() })
        if ($actualHashes.Count -ne $expectedHashes.Count -or (@(Compare-Object $expectedHashes $actualHashes)).Count -ne 0) {
            Stop-DevOverlay 'DEV_MANIFEST_MISMATCH' 'The copied source does not match the local manifest.'
        }
        $releaseCheck = Invoke-DevWsl -Distro $doctor.active_runtime -Command '/usr/bin/test' -Arguments @('!', '-e', $releasePath)
        if ($releaseCheck.ExitCode -ne 0) { Stop-DevOverlay 'DEV_COMMIT_FAILED' 'The content release already exists or cannot be checked.' }
        $commitResult = Invoke-DevWsl -Distro $doctor.active_runtime -Command '/bin/mv' -Arguments @($stagingPath, $releasePath)
        if ($commitResult.ExitCode -ne 0) { Stop-DevOverlay 'DEV_COMMIT_FAILED' 'Could not commit the immutable overlay release.' }
        $linkResult = Invoke-DevWsl -Distro $doctor.active_runtime -Command '/bin/ln' -Arguments @('-s', "releases/$($manifest.ContentId)", $currentTemp)
        if ($linkResult.ExitCode -ne 0) { Stop-DevOverlay 'DEV_COMMIT_FAILED' 'Could not prepare the atomic current link.' }
        $switchResult = Invoke-DevWsl -Distro $doctor.active_runtime -Command '/bin/mv' -Arguments @('-Tf', $currentTemp, "$script:OverlayRoot/current")
        if ($switchResult.ExitCode -ne 0) { Stop-DevOverlay 'DEV_COMMIT_FAILED' 'Could not switch the current overlay atomically.' }
        [ordered]@{ schema = 1; content_id = $manifest.ContentId; dirty = $manifest.Dirty; file_count = $sourceFiles.Count } | ConvertTo-Json -Compress
    } finally {
        if ($lockAcquired) { [void](Invoke-DevWsl -Distro $doctor.active_runtime -Command '/bin/rmdir' -Arguments @($lockPath)) }
        if (Test-Path -LiteralPath $tempTar -PathType Leaf) { Remove-Item -LiteralPath $tempTar -Force }
    }
}

function Invoke-DevRun {
    param([string[]]$Arguments = @(), [switch]$Test)
    $null = Invoke-DevSync
    $runtime = Get-ActiveRuntime
    $pythonArguments = if ($Test) { @('-m', 'pytest') + $Arguments } else { $Arguments }
    $envArguments = @('/usr/bin/env', 'PYTHONNOUSERSITE=1', "PYTHONPATH=$script:OverlayRoot/current", "SWITCHTRADE_SOURCE_ROOT=$script:OverlayRoot/current", "SWITCHTRADE_INSTALLED_ROOT=$script:InstalledRoot", $script:PythonPath) + $pythonArguments
    $result = Invoke-DevWsl -Distro $runtime.Name -Cwd "$script:OverlayRoot/current" -Command $envArguments[0] -Arguments $envArguments[1..($envArguments.Count - 1)]
    if ($result.Stdout) { [Console]::Out.Write($result.Stdout) }
    if ($result.Stderr) { [Console]::Error.Write($result.Stderr) }
    return $result.ExitCode
}

function Invoke-DevClean {
    $runtime = Get-ActiveRuntime
    $result = Invoke-DevWsl -Distro $runtime.Name -Command '/bin/rm' -Arguments @('-rf', '--', $script:OverlayRoot)
    if ($result.ExitCode -ne 0) { Stop-DevOverlay 'DEV_CLEAN_REFUSED' 'Overlay cleanup failed.' }
    [void](Invoke-DevWsl -Distro $runtime.Name -Command '/bin/mkdir' -Arguments @('-p', "$script:OverlayRoot/releases"))
    [ordered]@{ schema = 1; cleaned = $script:OverlayRoot } | ConvertTo-Json -Compress
}

Export-ModuleMember -Function Invoke-DevDoctor, Invoke-DevSync, Invoke-DevRun, Invoke-DevClean
