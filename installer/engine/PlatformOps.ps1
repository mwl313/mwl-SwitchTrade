# SwitchTrade installer engine: platform operations (single audited native/WSL boundary)
#
# Handoff: HANDOFF-20260827-installer-engine-overhaul.md section 8.4. Every native process
# launch and every wsl.exe call in the installer routes through this file. Policy:
#   - Exact argv: data is passed as positional parameters or argument arrays, never composed
#     into shell strings. WSL Linux commands use --exec; when a shell is genuinely
#     required (probes), the script text is a CONSTANT and data travels as $1..$n.
#   - Bounded subprocesses: timeout, cancellation check, captured stdout/stderr.
#   - Output normalization: Store WSL emits UTF-16; NUL stripping is centralized here.
# Compatible with Windows PowerShell 5.1 and PowerShell 7.
Set-StrictMode -Version Latest

# Escape exactly one argument for the Windows native command line (CRT parsing rules).
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

# Normalize WSL/Store runtime output: strip UTF-16 NULs and surrounding blanks.
function ConvertFrom-SwitchTradeProcessOutput {
    param([AllowEmptyString()][string]$Text)
    if ($null -eq $Text) { return '' }
    return ([string]$Text).Replace([string][char]0, '').Trim()
}

# The one bounded native subprocess runner.
# Returns ExitCode, Output, Error, TimedOut, Cancelled, CommandLine, DurationMs.
# Throws PROCESS_START_FAILED / PROCESS_TIMEOUT / PROCESS_CANCELLED.
function Invoke-SwitchTradeProcess {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [string[]]$Arguments = @(),
        [ValidateRange(1, 3600)][int]$TimeoutSeconds = 30,
        [string]$WorkingDirectory = '',
        [hashtable]$Environment = @{},
        [scriptblock]$CancellationCheck = $null
    )
    $start = New-Object Diagnostics.ProcessStartInfo
    $start.FileName = $FilePath
    $start.Arguments = (($Arguments | ForEach-Object { ConvertTo-NativeCommandLineArgument ([string]$_) }) -join ' ')
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    if ($WorkingDirectory) { $start.WorkingDirectory = $WorkingDirectory }
    foreach ($key in $Environment.Keys) {
        $start.EnvironmentVariables[[string]$key] = [string]$Environment[$key]
    }
    $process = New-Object Diagnostics.Process
    $process.StartInfo = $start
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    $timedOut = $false
    $cancelled = $false
    try {
        if (-not $process.Start()) { throw "PROCESS_START_FAILED: $FilePath" }
        $outputTask = $process.StandardOutput.ReadToEndAsync()
        $errorTask = $process.StandardError.ReadToEndAsync()
        while (-not $process.WaitForExit(200)) {
            if ($CancellationCheck -and (& $CancellationCheck)) {
                $cancelled = $true
                break
            }
            if ([DateTime]::UtcNow -ge $deadline) { $timedOut = $true; break }
        }
        if ($timedOut -or $cancelled) {
            try { $process.Kill() } catch { }
            if ($timedOut) {
                throw "PROCESS_TIMEOUT: $FilePath exceeded $TimeoutSeconds seconds"
            }
            throw 'PROCESS_CANCELLED'
        }
        $outputTask.Wait()
        $errorTask.Wait()
        return [pscustomobject]@{
            ExitCode = $process.ExitCode
            Output = [string]$outputTask.Result
            Error = [string]$errorTask.Result
            TimedOut = $false
            Cancelled = $false
            CommandLine = $start.FileName + ' ' + $start.Arguments
            DurationMs = [int]([DateTime]::UtcNow - $deadline.AddSeconds(-$TimeoutSeconds)).TotalMilliseconds
        }
    } finally { $process.Dispose() }
}

# Resolve the wsl.exe client the installer will use (System32 shim forwards to Store WSL).
function Get-SwitchTradeWslClientPath {
    $command = Get-Command wsl.exe -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    return (Join-Path $env:SystemRoot 'System32\wsl.exe')
}

# One audited wsl.exe invocation. Output is normalized (NULs stripped).
function Invoke-SwitchTradeWsl {
    param(
        [Parameter(Mandatory)][AllowEmptyString()][string[]]$Arguments,
        [ValidateRange(1, 3600)][int]$TimeoutSeconds = 30,
        [string]$FilePath = '',
        [scriptblock]$CancellationCheck = $null
    )
    $wsl = if ($FilePath) { $FilePath } else { Get-SwitchTradeWslClientPath }
    $result = Invoke-SwitchTradeProcess -FilePath $wsl -Arguments $Arguments -TimeoutSeconds $TimeoutSeconds -CancellationCheck $CancellationCheck
    return [pscustomobject]@{
        ExitCode = $result.ExitCode
        Output = ConvertFrom-SwitchTradeProcessOutput $result.Output
        Error = ConvertFrom-SwitchTradeProcessOutput $result.Error
        TimedOut = $result.TimedOut
        Cancelled = $result.Cancelled
        CommandLine = $result.CommandLine
        DurationMs = $result.DurationMs
    }
}

# Execute a Linux command as exact argv inside a distribution (wsl --exec, no shell).
# Example: Invoke-SwitchTradeWslCommand -Distro SwitchTrade -Command @('cat', '/etc/hostname')
function Invoke-SwitchTradeWslCommand {
    param(
        [Parameter(Mandatory)][string]$Distro,
        [Parameter(Mandatory)][AllowEmptyString()][string[]]$Command,
        [string]$User = 'root',
        [string]$WorkingDirectory = '',
        [ValidateRange(1, 3600)][int]$TimeoutSeconds = 30,
        [string]$FilePath = '',
        [scriptblock]$CancellationCheck = $null
    )
    if (-not $Command.Count) { throw 'WSL_COMMAND_EMPTY: an empty Linux command was requested' }
    $wslArgs = @('-d', $Distro, '-u', $User)
    if ($WorkingDirectory) { $wslArgs += @('--cd', $WorkingDirectory) }
    $wslArgs += @('--exec') + $Command
    return Invoke-SwitchTradeWsl -Arguments $wslArgs -TimeoutSeconds $TimeoutSeconds -FilePath $FilePath -CancellationCheck $CancellationCheck
}

# Execute a CONSTANT shell script inside a distribution with data as positional parameters.
# $ScriptText must never be built from data; pass data via -Arguments ($1..$n).
function Invoke-SwitchTradeWslSh {
    param(
        [Parameter(Mandatory)][string]$Distro,
        [Parameter(Mandatory)][string]$ScriptText,
        [string[]]$Arguments = @(),
        [string]$User = 'root',
        [ValidateRange(1, 3600)][int]$TimeoutSeconds = 30,
        [string]$FilePath = '',
        [scriptblock]$CancellationCheck = $null
    )
    $wslArgs = @('-d', $Distro, '-u', $User, '--exec', 'sh', '-c', $ScriptText, 'switchtrade-sh') + @($Arguments)
    return Invoke-SwitchTradeWsl -Arguments $wslArgs -TimeoutSeconds $TimeoutSeconds -FilePath $FilePath -CancellationCheck $CancellationCheck
}

# Map a Windows path into the WSL /mnt/<drive>/... form. Requires the path to exist.
function ConvertTo-SwitchTradeWslPath {
    param([Parameter(Mandatory)][string]$Path)
    $resolved = (Resolve-Path -LiteralPath $Path).Path
    if ($resolved -notmatch '^([A-Za-z]):\\(.*)$') {
        throw "cannot map path into WSL: $resolved"
    }
    return "/mnt/$($Matches[1].ToLowerInvariant())/$($Matches[2].Replace('\', '/'))"
}

# Invoke installer/provision-wsl.sh inside a distribution. argv only; no shell strings.
function Invoke-SwitchTradeWslProvision {
    param(
        [Parameter(Mandatory)][string]$Distro,
        [Parameter(Mandatory)][string]$ScriptPath,
        [Parameter(Mandatory)][ValidateSet(
            'stage', 'validate', 'validate-candidate', 'validate-active', 'validate-location',
            'validate-retained', 'commit', 'abort', 'rollback', 'compensate',
            'recover-interrupted', 'cleanup-staging')][string]$Mode,
        [string[]]$Arguments = @(),
        [ValidateRange(1, 3600)][int]$TimeoutSeconds = 600,
        [string]$FilePath = '',
        [scriptblock]$CancellationCheck = $null
    )
    $script = ConvertTo-SwitchTradeWslPath -Path $ScriptPath
    $command = @('bash', $script, ('--' + $Mode)) + @($Arguments)
    return Invoke-SwitchTradeWslCommand -Distro $Distro -Command $command -User 'root' -TimeoutSeconds $TimeoutSeconds -FilePath $FilePath -CancellationCheck $CancellationCheck
}

# Read the SwitchTrade distro ownership marker. Distinguishes absent (44) / invalid / valid.
function Get-SwitchTradeDistroMarkerProbe {
    param(
        [Parameter(Mandatory)][string]$Distro,
        [string]$FilePath = '',
        [ValidateRange(1, 3600)][int]$TimeoutSeconds = 20
    )
    # Constant script; the marker path is fixed product content.
    $script = 'if [ ! -e /etc/switchtrade-distro.json ]; then exit 44; fi; exec cat /etc/switchtrade-distro.json'
    $result = Invoke-SwitchTradeWslSh -Distro $Distro -ScriptText $script -TimeoutSeconds $TimeoutSeconds -FilePath $FilePath
    if ($result.ExitCode -eq 44) {
        return [pscustomobject]@{ Missing = $true; Valid = $false; InstallId = ''; ExitCode = 44 }
    }
    $raw = $result.Output.Trim()
    if ($result.ExitCode -ne 0 -or -not $raw) {
        return [pscustomobject]@{ Missing = $false; Valid = $false; InstallId = ''; ExitCode = $result.ExitCode }
    }
    try {
        $marker = $raw | ConvertFrom-Json
        $props = @($marker.PSObject.Properties.Name)
        $hasInstallId = $props -contains 'install_id'
        $installId = if ($hasInstallId) { [string]$marker.install_id } else { '' }
        $schema = if ($props -contains 'schema') { [int]$marker.schema } else { 0 }
        $owner = if ($props -contains 'owner') { [string]$marker.owner } else { '' }
        $product = if ($props -contains 'product') { [string]$marker.product } else { '' }
        $valid = $schema -in @(1, 2) -and
            $owner -ceq 'switchtrade-installer' -and
            $product -ceq 'SwitchTrade' -and
            (-not $installId -or $installId -match '^[0-9a-f]{32}$')
        return [pscustomobject]@{
            Missing = $false; Valid = $valid
            InstallId = $(if ($valid) { $installId } else { '' }); ExitCode = 0
        }
    } catch {
        return [pscustomobject]@{ Missing = $false; Valid = $false; InstallId = ''; ExitCode = 0 }
    }
}

# Write the distro install-id marker atomically. Data travels as positional parameters.
function Set-SwitchTradeDistroMarker {
    param(
        [Parameter(Mandatory)][string]$Distro,
        [Parameter(Mandatory)][string]$InstallId,
        [string]$FilePath = '',
        [ValidateRange(1, 3600)][int]$TimeoutSeconds = 20
    )
    if ($InstallId -notmatch '^[0-9a-f]{32}$') { throw 'DISTRO_INSTALL_ID_INVALID' }
    $document = '{"schema":2,"owner":"switchtrade-installer","product":"SwitchTrade","install_id":"' +
        $InstallId + '"}'
    $script = 'set -eu; p=/etc/switchtrade-distro.json.tmp; printf ''%s\n'' "$1" >"$p"; chmod 0644 "$p"; mv -f -- "$p" /etc/switchtrade-distro.json'
    $result = Invoke-SwitchTradeWslSh -Distro $Distro -ScriptText $script -Arguments @($document) -TimeoutSeconds $TimeoutSeconds -FilePath $FilePath
    if ($result.ExitCode -ne 0) {
        $detail = (($result.Error + [Environment]::NewLine + $result.Output).Trim())
        if ($detail) { throw "DISTRO_INSTALL_ID_WRITE_FAILED: $detail" }
        throw 'DISTRO_INSTALL_ID_WRITE_FAILED'
    }
    return $result
}

# Probe one fixed /opt runtime location. Location comes from a closed enum, never data.
function Get-SwitchTradeWslRuntimeLocationProbe {
    param(
        [Parameter(Mandatory)][string]$Distro,
        [Parameter(Mandatory)][ValidateSet('active', 'candidate', 'previous', 'commit_swap', 'rollback_swap')]
        [string]$Location,
        [string]$FilePath = '',
        [ValidateRange(1, 3600)][int]$TimeoutSeconds = 30
    )
    $path = @{
        active = '/opt/switchtrade'; candidate = '/opt/switchtrade.candidate'
        previous = '/opt/switchtrade.previous'; commit_swap = '/opt/switchtrade.commit-swap'
        rollback_swap = '/opt/switchtrade.rollback-swap'
    }[$Location]
    # Constant script; the location path arrives as $1 from the closed enum map above.
    $script = 'set -eu; p="$1"; if [ ! -e "$p" ]; then printf ''absent''; elif [ ! -d "$p" ] || [ ! -f "$p/.switchtrade-release.json" ] || [ ! -f "$p/.switchtrade-integrity.json" ]; then printf ''invalid''; else cat "$p/.switchtrade-release.json"; printf ''\n''; sha256sum "$p/.switchtrade-integrity.json" | cut -d'' '' -f1; fi'
    $result = Invoke-SwitchTradeWslSh -Distro $Distro -ScriptText $script -Arguments @($path) -TimeoutSeconds $TimeoutSeconds -FilePath $FilePath
    $raw = $result.Output.Trim()
    if ($result.ExitCode -ne 0 -or $raw -eq 'invalid') {
        return [pscustomobject]@{ Exists = $true; Valid = $false; ReleaseId = ''; IntegritySha256 = '' }
    }
    if ($raw -eq 'absent') {
        return [pscustomobject]@{ Exists = $false; Valid = $true; ReleaseId = ''; IntegritySha256 = '' }
    }
    try {
        $parts = @($raw -split "\r?\n" | Where-Object { $_ })
        $marker = $parts[0] | ConvertFrom-Json
        $props = @($marker.PSObject.Properties.Name)
        $release = if ($props -contains 'release_id') { [string]$marker.release_id } else { '' }
        $integrity = [string]$parts[-1]
        $schema = if ($props -contains 'schema') { [int]$marker.schema } else { 0 }
        $valid = $schema -eq 1 -and
            $release -match '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$' -and
            $integrity -match '^[0-9a-f]{64}$'
        return [pscustomobject]@{
            Exists = $true; Valid = $valid
            ReleaseId = $(if ($valid) { $release } else { '' })
            IntegritySha256 = $(if ($valid) { $integrity } else { '' })
        }
    } catch {
        return [pscustomobject]@{ Exists = $true; Valid = $false; ReleaseId = ''; IntegritySha256 = '' }
    }
}

# Extract a kernel modules archive and run depmod. Data travels as positional parameters.
function Install-SwitchTradeKernelModulesArchive {
    param(
        [Parameter(Mandatory)][string]$Distro,
        [Parameter(Mandatory)][string]$ModulesArchiveWindowsPath,
        [Parameter(Mandatory)][string]$KernelRelease,
        [string]$FilePath = '',
        [ValidateRange(1, 3600)][int]$TimeoutSeconds = 600,
        [scriptblock]$CancellationCheck = $null
    )
    $modulesWsl = ConvertTo-SwitchTradeWslPath -Path $ModulesArchiveWindowsPath
    $script = 'set -eu; p="$1"; rel="$2"; command -v depmod >/dev/null 2>&1 && command -v modinfo >/dev/null 2>&1 || { echo "RUNTIME_OS_DEPENDENCY_MISSING: kmod" >&2; exit 1; }; mkdir -p /lib/modules; tar -xzf "$p" -C /lib/modules; depmod -a "$rel"'
    return Invoke-SwitchTradeWslSh -Distro $Distro -ScriptText $script -Arguments @($modulesWsl, $KernelRelease) -TimeoutSeconds $TimeoutSeconds -FilePath $FilePath -CancellationCheck $CancellationCheck
}

# Verify the running kernel ABI/vermagic/firmware. Data travels as positional parameters.
function Test-SwitchTradeKernelModuleAbi {
    param(
        [Parameter(Mandatory)][string]$Distro,
        [Parameter(Mandatory)][string]$KernelRelease,
        [string]$FirmwareDigest = '',
        [string]$FilePath = '',
        [ValidateRange(1, 3600)][int]$TimeoutSeconds = 60,
        [scriptblock]$CancellationCheck = $null
    )
    $builtInFirmwareVerified = $FirmwareDigest -match '^[0-9a-fA-F]{64}$'
    $script = if ($builtInFirmwareVerified) {
        'set -eu; rel="$1"; test "$(uname -r)" = "$rel"; test "$(modinfo -F vermagic rtl8xxxu | awk ''{print $1}'')" = "$rel"'
    } else {
        'set -eu; rel="$1"; test "$(uname -r)" = "$rel"; test "$(modinfo -F vermagic rtl8xxxu | awk ''{print $1}'')" = "$rel"; modinfo -F firmware rtl8xxxu | while IFS= read -r fw; do test -z "$fw" || test -f "/lib/firmware/$fw"; done'
    }
    return Invoke-SwitchTradeWslSh -Distro $Distro -ScriptText $script -Arguments @($KernelRelease) -TimeoutSeconds $TimeoutSeconds -FilePath $FilePath -CancellationCheck $CancellationCheck
}