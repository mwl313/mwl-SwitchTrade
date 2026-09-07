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

function Resolve-DevCoreArguments {
    param([string[]]$Arguments, [switch]$Native)
    $mode = $Arguments[0]
    if ($Native -and $mode -notin @('join', 'doctor')) {
        Stop-DevOverlay 'DEV_CORE_ARGUMENT_INVALID' 'gpSP currently supports join and doctor only.'
    }
    $code = $null
    $start = 1
    if ($mode -eq 'join') {
        if ($Arguments.Count -lt 2 -or $Arguments[1] -cnotmatch '^[0-9]{6}$') {
            Stop-DevOverlay 'DEV_CORE_ARGUMENT_INVALID' 'join requires a six-digit Pair code.'
        }
        $code = $Arguments[1]
        $start = 2
    }
    $options = @($Arguments | Select-Object -Skip $start)
    $allowed = if ($Native) { @('--relay', '--log-dir', '--emulator', '--emulator-port', '--emulator-pid') } else {
        @('--relay', '--usb-id', '--channel', '--log-dir')
    }
    $selectedEmulator = $false
    if ($env:SWITCHTRADE_CORE_RELAY -and -not ($options | Where-Object { $_ -eq '--relay' -or $_ -like '--relay=*' })) {
        # Windows environment variables are not automatically inherited by WSL.
        $options = @('--relay', $env:SWITCHTRADE_CORE_RELAY) + $options
    }
    for ($index = 0; $index -lt $options.Count; $index++) {
        $option = $options[$index]
        if ($option -eq '--verbose') { continue }
        $parts = $option -split '=', 2
        $name = $parts[0]
        if ($name -notin $allowed) {
            Stop-DevOverlay 'DEV_CORE_ARGUMENT_INVALID' 'Unknown Core CLI option.'
        }
        if ($parts.Count -eq 2) { $value = $parts[1] } else {
            $index++
            if ($index -ge $options.Count) { Stop-DevOverlay 'DEV_CORE_ARGUMENT_INVALID' 'Core CLI option value is missing.' }
            $value = $options[$index]
        }
        if ([string]::IsNullOrWhiteSpace($value) -or $value.StartsWith('--')) {
            Stop-DevOverlay 'DEV_CORE_ARGUMENT_INVALID' 'Core CLI option value is missing.'
        }
        if ($name -eq '--channel' -and $value -notin @('1', '6', '11')) {
            Stop-DevOverlay 'DEV_CORE_ARGUMENT_INVALID' 'channel must be 1, 6 or 11.'
        }
        if ($name -eq '--usb-id' -and $value -notmatch '^[0-9a-fA-F]{4}:[0-9a-fA-F]{4}$') {
            Stop-DevOverlay 'DEV_CORE_ARGUMENT_INVALID' 'usb-id must be VID:PID.'
        }
        if ($name -eq '--emulator') {
            if ($value -cne 'gpsp' -or $selectedEmulator) {
                Stop-DevOverlay 'DEV_CORE_ARGUMENT_INVALID' 'Select exactly one supported emulator: gpsp.'
            }
            $selectedEmulator = $true
        }
        if ($name -in @('--emulator-port', '--emulator-pid')) {
            [uint32]$number = 0
            if (-not [uint32]::TryParse($value, [ref]$number) -or $number -eq 0 -or
                ($name -eq '--emulator-port' -and $number -gt 65535)) {
                Stop-DevOverlay 'DEV_CORE_ARGUMENT_INVALID' 'Invalid emulator port or PID.'
            }
        }
        if ($name -eq '--relay') {
            $uri = $null
            if (-not [Uri]::TryCreate($value, [UriKind]::Absolute, [ref]$uri) -or
                $uri.Scheme -notin @('http', 'https', 'ws', 'wss') -or -not $uri.Host -or
                $uri.UserInfo -or $uri.Query -or $uri.Fragment) {
                Stop-DevOverlay 'DEV_CORE_ARGUMENT_INVALID' 'relay must be an HTTP(S)/WS(S) base URL without credentials or query.'
            }
        }
    }
    if ($Native -and -not $selectedEmulator) {
        Stop-DevOverlay 'DEV_CORE_ARGUMENT_INVALID' 'Native execution requires --emulator gpsp.'
    }
    return @('-m', 'switchtrade.core_cli') + $options + @($mode) + $(if ($code) { @($code) } else { @() })
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
        [string]$WorkingDirectory = $script:RepoRoot,
        [switch]$ParentLifetime,
        [hashtable]$Environment = @{}
    )

    if ($ParentLifetime -and -not ('DevChildLifetime' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Diagnostics;
using System.Threading;
public sealed class DevChildLifetime : IDisposable {
    private readonly Process child;
    private int closed;
    public Exception Failure;
    public DevChildLifetime(Process process) {
        child = process;
        Console.CancelKeyPress += Cancel;
    }
    private void Cancel(object sender, ConsoleCancelEventArgs e) {
        e.Cancel = true;
        CloseInput();
    }
    public void CloseInput() {
        if (Interlocked.Exchange(ref closed, 1) == 0) {
            try { child.StandardInput.Close(); }
            catch (Exception error) { Failure = error; }
        }
    }
    public void Dispose() { Console.CancelKeyPress -= Cancel; CloseInput(); }
}
'@
    }
    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $FilePath
    $startInfo.WorkingDirectory = $WorkingDirectory
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.RedirectStandardInput = [bool]$ParentLifetime
    foreach ($name in $Environment.Keys) { $startInfo.Environment[$name] = $Environment[$name] }
    foreach ($argument in $ArgumentList) {
        [void]$startInfo.ArgumentList.Add($argument)
    }
    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    $lifetime = $null
    $started = $false
    try {
        $started = $process.Start()
        if (-not $started) {
            Stop-DevOverlay 'DEV_RUN_FAILED' "Could not start $FilePath."
        }
        if ($ParentLifetime) { $lifetime = [DevChildLifetime]::new($process) }
        $stdoutTask = $process.StandardOutput.ReadLineAsync()
        $stderrTask = $process.StandardError.ReadLineAsync()
        while ($null -ne $stdoutTask -or $null -ne $stderrTask) {
            $pending = [System.Collections.Generic.List[System.Threading.Tasks.Task]]::new()
            if ($null -ne $stdoutTask) { [void]$pending.Add($stdoutTask) }
            if ($null -ne $stderrTask) { [void]$pending.Add($stderrTask) }
            $index = [System.Threading.Tasks.Task]::WaitAny($pending.ToArray(), 100)
            if ($index -lt 0) { continue }
            $completed = $pending[$index]
            if ($completed -eq $stdoutTask) {
                $line = $stdoutTask.GetAwaiter().GetResult()
                if ($null -eq $line) { $stdoutTask = $null } else {
                    [Console]::Out.WriteLine($line)
                    $stdoutTask = $process.StandardOutput.ReadLineAsync()
                }
            } else {
                $line = $stderrTask.GetAwaiter().GetResult()
                if ($null -eq $line) { $stderrTask = $null } else {
                    [Console]::Error.WriteLine($line)
                    $stderrTask = $process.StandardError.ReadLineAsync()
                }
            }
        }
        $process.WaitForExit()
        return $process.ExitCode
    } finally {
        if ($ParentLifetime -and $started) {
            # EOF is the owned parent's cancellation signal across wsl.exe.
            # Wait for CLI cleanup, never mistake disposing Windows handles
            # for release of Linux AP/TAP/PHY resources.
            if ($null -ne $lifetime) { $lifetime.Dispose() } else { $process.StandardInput.Close() }
            if (-not $process.WaitForExit(30000)) {
                $process.Dispose()
                Stop-DevOverlay 'DEV_CHILD_CLEANUP_UNVERIFIED' 'CLI did not finish cleanup after parent cancellation. Do not retry.'
            }
            if ($null -ne $lifetime -and $null -ne $lifetime.Failure) {
                $process.Dispose()
                Stop-DevOverlay 'DEV_PARENT_CONTROL_FAILED' 'Owned child cancellation pipe could not be closed.'
            }
        }
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
        [string]$Cwd = '/opt/switchtrade',
        [switch]$ParentLifetime
    )
    $wslArguments = @('--distribution', $Distro, '--user', 'root', '--cd', $Cwd, '--', $Command) + $Arguments
    Invoke-DevInteractiveProcess -FilePath 'wsl.exe' -ArgumentList $wslArguments -ParentLifetime:$ParentLifetime
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
    $allowlistPath = Join-Path $PSScriptRoot 'dev-source-allowlist.txt'
    if (-not (Test-Path -LiteralPath $allowlistPath -PathType Leaf)) {
        Stop-DevOverlay 'DEV_SOURCE_ALLOWLIST_EMPTY' 'The source allowlist is missing.'
    }
    $allowPatterns = @(Get-Content -LiteralPath $allowlistPath | Where-Object { $_ -and $_ -notmatch '^\s*#' })
    $sourceFiles = @(@(
        foreach ($candidatePath in $allPaths) {
            $normalizedPath = $candidatePath -replace '\\', '/'
            $allowed = $false
            foreach ($allowPattern in $allowPatterns) {
                $allowRegex = '^' + [regex]::Escape($allowPattern.Trim()).Replace('\*\*/', '(?:.*/)?').Replace('\*', '[^/]*') + '$'
                if ($normalizedPath -match $allowRegex) { $allowed = $true; break }
            }
            if ($allowed) { $normalizedPath }
        }
    ) | Sort-Object -Unique)
    if ($sourceFiles.Count -eq 0) {
        Stop-DevOverlay 'DEV_SOURCE_ALLOWLIST_EMPTY' 'The source allowlist produced no files.'
    }
    if ($sourceFiles | Where-Object { $_ -match $denyPattern }) {
        Stop-DevOverlay 'DEV_SOURCE_FORBIDDEN' 'A forbidden path was selected for the overlay.'
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
            [ordered]@{ schema = 1; git_head = $manifest.GitHead; content_id = $manifest.ContentId; dirty = $manifest.Dirty; file_count = $sourceFiles.Count; reused = $true } | ConvertTo-Json -Compress
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
        [ordered]@{ schema = 1; git_head = $manifest.GitHead; content_id = $manifest.ContentId; dirty = $manifest.Dirty; file_count = $sourceFiles.Count; reused = $false } | ConvertTo-Json -Compress
    } finally {
        if ($lockAcquired) { [void](Invoke-DevWsl -Distro $doctor.active_runtime -Command '/bin/rm' -Arguments @('-rf', '--', $stagingPath)) }
        if ($lockAcquired) { [void](Invoke-DevWsl -Distro $doctor.active_runtime -Command '/bin/rmdir' -Arguments @($lockPath)) }
        if (Test-Path -LiteralPath $tempTar -PathType Leaf) { Remove-Item -LiteralPath $tempTar -Force }
    }
}

function Invoke-DevRun {
    param(
        [string[]]$Arguments = @(),
        [switch]$Test,
        [switch]$CoreCli,
        [ValidateSet('host', 'join')][string]$CoreRole
    )
    $synced = Invoke-DevSync | ConvertFrom-Json
    $runtime = Get-ActiveRuntime
    $pythonArguments = if ($Test) { @('-m', 'pytest') + $Arguments } elseif ($CoreCli) { @('-u') + $Arguments } else { $Arguments }
    $commandArguments = if ($CoreCli) {
        if (-not $CoreRole) { Stop-DevOverlay 'DEV_CORE_ROUTE_INVALID' 'The Core CLI role is missing.' }
        $radioRole = if ($CoreRole -eq 'host') { 'guest' } else { 'host' }
        $channel = '6'
        $usbId = $null
        for ($index = 0; $index -lt $Arguments.Count; $index += 1) {
            if ($Arguments[$index] -eq '--channel' -and $index + 1 -lt $Arguments.Count) { $index += 1; $channel = $Arguments[$index]; continue }
            if ($Arguments[$index] -like '--channel=*') { $channel = $Arguments[$index].Substring(10); continue }
            if ($Arguments[$index] -eq '--usb-id' -and $index + 1 -lt $Arguments.Count) { $index += 1; $usbId = $Arguments[$index]; continue }
            if ($Arguments[$index] -like '--usb-id=*') { $usbId = $Arguments[$index].Substring(9) }
        }
        $gateArguments = @('./scripts/wsl-radio-prepare.sh', '--role', $radioRole)
        if ($usbId) { $gateArguments += @('--usb-id', $usbId) }
        @($script:PythonPath, '-u', '-m', 'switchtrade.parent_lifetime', '--') + $gateArguments + @('--target-channel', $channel, '--', $script:PythonPath) + $pythonArguments
    } else {
        @($script:PythonPath) + $pythonArguments
    }
    $parentEnvironment = if ($CoreCli) {
        @('SWITCHTRADE_PARENT_STDIN=1', "SWITCHTRADE_CORE_RELEASE=$($synced.git_head):$($synced.content_id)")
    } else { @() }
    $envArguments = @('/usr/bin/env', 'PYTHONNOUSERSITE=1', 'PYTHONUNBUFFERED=1', "PYTHONPATH=$script:OverlayRoot/current", "SWITCHTRADE_SOURCE_ROOT=$script:OverlayRoot/current", "SWITCHTRADE_INSTALLED_ROOT=$script:InstalledRoot") + $parentEnvironment + $commandArguments
    $interactiveOptions = @{}
    if ($CoreCli) { $interactiveOptions.ParentLifetime = $true }
    $exitCode = Invoke-DevInteractiveWsl -Distro $runtime.Name -Cwd "$script:OverlayRoot/current" -Command $envArguments[0] -Arguments $envArguments[1..($envArguments.Count - 1)] @interactiveOptions
    return [int]$exitCode
}

function Invoke-DevNative {
    param([Parameter(Mandatory)][string[]]$Arguments)
    if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
        Stop-DevOverlay 'GPSP_NATIVE_WINDOWS_REQUIRED' 'Run the gpSP endpoint in native Windows.'
    }
    $nativePython = if ($env:SWITCHTRADE_NATIVE_PYTHON) { $env:SWITCHTRADE_NATIVE_PYTHON } else {
        Join-Path $script:RepoRoot '.gpsp-venv\Scripts\python.exe'
    }
    if (-not (Test-Path -LiteralPath $nativePython -PathType Leaf)) {
        Stop-DevOverlay 'GPSP_ENVIRONMENT_MISSING' 'Prepare .gpsp-venv with Python 3.12 and requirements-gpsp.lock; no automatic installation is performed.'
    }
    $nativePython = (Resolve-Path -LiteralPath $nativePython).Path
    $probeCode = 'import sys,importlib.metadata; assert sys.platform=="win32" and sys.version_info[:2]==(3,12) and sys.maxsize>2**32; assert importlib.metadata.version("websockets")=="17.0.1"'
    $probe = Invoke-DevCapturedProcess -FilePath $nativePython -ArgumentList @('-I', '-c', $probeCode)
    if ($probe.ExitCode -ne 0) {
        Stop-DevOverlay 'GPSP_ENVIRONMENT_INVALID' 'Use native 64-bit Python 3.12 and install requirements-gpsp.lock in the selected environment.'
    }
    $nativeEnvironment = @{
        PYTHONNOUSERSITE='1'; PYTHONUTF8='1'; PYTHONPATH=''; SWITCHTRADE_PARENT_STDIN='1'
    }
    return [int](Invoke-DevInteractiveProcess -FilePath $nativePython -ArgumentList (@('-s', '-u') + $Arguments) -ParentLifetime -Environment $nativeEnvironment)
}

function Invoke-DevClean {
    $runtime = Get-ActiveRuntime
    $result = Invoke-DevWsl -Distro $runtime.Name -Command '/bin/rm' -Arguments @('-rf', '--', $script:OverlayRoot)
    if ($result.ExitCode -ne 0) { Stop-DevOverlay 'DEV_CLEAN_REFUSED' 'Overlay cleanup failed.' }
    [void](Invoke-DevWsl -Distro $runtime.Name -Command '/bin/mkdir' -Arguments @('-p', "$script:OverlayRoot/releases"))
    [ordered]@{ schema = 1; cleaned = $script:OverlayRoot } | ConvertTo-Json -Compress
}

Export-ModuleMember -Function Invoke-DevDoctor, Invoke-DevSync, Invoke-DevRun, Invoke-DevClean, Resolve-DevCoreArguments, Invoke-DevNative
