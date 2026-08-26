Set-StrictMode -Version Latest

function Invoke-BoundedWslShutdown {
    param([int]$TimeoutSeconds = 20)
    $process = Start-Process -FilePath wsl.exe -ArgumentList '--shutdown' -WindowStyle Hidden -PassThru
    if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
        $process.Kill()
        throw "WSL did not shut down within $TimeoutSeconds seconds. No distributions were removed."
    }
    if ($process.ExitCode -ne 0) { throw "wsl --shutdown failed with exit code $($process.ExitCode)" }
}

function Get-FileSha256([string]$Path) {
    $stream = [IO.File]::OpenRead([IO.Path]::GetFullPath($Path))
    try {
        $algorithm = [Security.Cryptography.SHA256]::Create()
        try { return ([BitConverter]::ToString($algorithm.ComputeHash($stream))).Replace('-', '').ToLowerInvariant() }
        finally { $algorithm.Dispose() }
    } finally { $stream.Dispose() }
}

function Set-Wsl2Values {
    param([string]$Text, [hashtable]$Values)
    $newline = if ($Text.Contains("`r`n")) { "`r`n" } else { "`n" }
    $lines = @($Text -split "`r?`n", 0)
    $result = [Collections.Generic.List[string]]::new()
    $section = ''
    $seen = @{}
    $inserted = $false
    foreach ($line in $lines) {
        if ($line -match '^\s*\[([^]]+)\]\s*$') {
            if ($section -ieq 'wsl2' -and -not $inserted) {
                foreach ($key in $Values.Keys) {
                    if (-not $seen.ContainsKey($key) -and $null -ne $Values[$key]) {
                        $result.Add("$key=$($Values[$key])")
                    }
                }
                $inserted = $true
            }
            $section = $Matches[1]
            $result.Add($line)
            continue
        }
        if ($section -ieq 'wsl2' -and $line -match '^\s*([^#;=\s]+)\s*=') {
            $key = [string]$Matches[1]
            if ($Values.ContainsKey($key)) {
                if (-not $seen.ContainsKey($key)) {
                    $result.Add("$key=$($Values[$key])")
                    $seen[$key] = $true
                }
                continue
            }
        }
        $result.Add($line)
    }
    if ($section -ieq 'wsl2' -and -not $inserted) {
        foreach ($key in $Values.Keys) {
            if (-not $seen.ContainsKey($key) -and $null -ne $Values[$key]) {
                $result.Add("$key=$($Values[$key])")
            }
        }
        $inserted = $true
    }
    if (-not $inserted) {
        if ($result.Count -gt 0 -and $result[$result.Count - 1]) { $result.Add('') }
        $result.Add('[wsl2]')
        foreach ($key in $Values.Keys) {
            if ($null -ne $Values[$key]) { $result.Add("$key=$($Values[$key])") }
        }
    }
    return ($result -join $newline).TrimEnd("`r", "`n") + $newline
}

function Install-SwitchTradeKernel {
    param(
        [Parameter(Mandatory)][string]$Kernel,
        [string]$KernelModules = '',
        [Parameter(Mandatory)][string]$Manifest,
        [Parameter(Mandatory)][string]$StateRoot,
        [Parameter(Mandatory)][string]$KernelStorageRoot,
        [switch]$AcceptGlobalKernelChange
    )
    if (-not $AcceptGlobalKernelChange) {
        throw 'The custom WSL kernel applies to every WSL 2 distro. Rerun after accepting the global kernel warning.'
    }
    $metadata = Get-Content -Raw -LiteralPath $Manifest | ConvertFrom-Json
    if (-not $metadata.kernel_release -or -not $metadata.kernel_sha256) {
        throw 'kernel manifest is missing kernel_release or kernel_sha256'
    }
    if ((Get-FileSha256 $Kernel) -ne ([string]$metadata.kernel_sha256).ToLowerInvariant()) {
        throw 'custom kernel checksum verification failed'
    }
    if ($KernelModules) {
        if (-not $metadata.modules_sha256 -or
            (Get-FileSha256 $KernelModules) -ne ([string]$metadata.modules_sha256).ToLowerInvariant()) {
            throw 'custom kernel modules checksum verification failed'
        }
    }

    $kernelRoot = [IO.Path]::GetFullPath($KernelStorageRoot)
    $backupRoot = Join-Path $StateRoot 'backups'
    New-Item -ItemType Directory -Force -Path $kernelRoot, $backupRoot | Out-Null
    $safeRelease = ([string]$metadata.kernel_release) -replace '[^A-Za-z0-9._-]', '_'
    $kernelIdentity = (Get-FileSha256 $Kernel).Substring(0, 12)
    $installedKernel = Join-Path $kernelRoot "kernel-$safeRelease-$kernelIdentity"
    Copy-Item -LiteralPath $Kernel -Destination $installedKernel -Force
    $installedModules = ''
    $modulesFormat = 'none'
    if ($KernelModules) {
        $moduleIdentity = (Get-FileSha256 $KernelModules).Substring(0, 12)
        $moduleExtension = if ([IO.Path]::GetExtension($KernelModules).ToLowerInvariant() -in @('.vhd', '.vhdx')) {
            [IO.Path]::GetExtension($KernelModules).ToLowerInvariant()
        } else { '.tar.gz' }
        $installedModules = Join-Path $kernelRoot "modules-$safeRelease-$moduleIdentity$moduleExtension"
        Copy-Item -LiteralPath $KernelModules -Destination $installedModules -Force
        $modulesFormat = if ([IO.Path]::GetExtension($KernelModules).ToLowerInvariant() -in @('.vhd', '.vhdx')) {
            'vhd'
        } else { 'archive' }
    }

    $config = Join-Path $env:USERPROFILE '.wslconfig'
    $priorPresent = Test-Path -LiteralPath $config -PathType Leaf
    $priorText = if ($priorPresent) { Get-Content -Raw -LiteralPath $config } else { '' }
    $statePath = Join-Path $StateRoot 'kernel-state.json'
    $existingState = if (Test-Path -LiteralPath $statePath -PathType Leaf) {
        Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
    } else { $null }
    if ($existingState -and $existingState.owns_kernel_change) {
        $backup = [string]$existingState.prior_config_backup
        $priorPresentForRollback = [bool]$existingState.prior_config_present
    } else {
        $backup = Join-Path $backupRoot ("wslconfig-{0}.bak" -f (Get-Date -Format 'yyyyMMddTHHmmssfff'))
        [IO.File]::WriteAllText($backup, $priorText, [Text.UTF8Encoding]::new($false))
        $priorPresentForRollback = $priorPresent
    }

    $values = @{
        kernel = $installedKernel.Replace('\', '\\')
        kernelModules = if ($modulesFormat -eq 'vhd') { $installedModules.Replace('\', '\\') } else { $null }
    }
    $merged = Set-Wsl2Values -Text $priorText -Values $values
    [IO.File]::WriteAllText($config, $merged, [Text.UTF8Encoding]::new($false))
    $state = @{
        schema = 2; owns_kernel_change = $true; prior_config_present = $priorPresentForRollback
        prior_config_backup = $backup; installed_config_sha256 = Get-FileSha256 $config
        kernel_path = $installedKernel; modules_path = $installedModules
        modules_format = $modulesFormat
        kernel_release = [string]$metadata.kernel_release
        rollback_kernel_path = if ($existingState -and $existingState.owns_kernel_change) {
            [string]$existingState.kernel_path
        } else { '' }
        rollback_modules_path = if ($existingState -and $existingState.owns_kernel_change) {
            [string]$existingState.modules_path
        } else { '' }
        rollback_modules_format = if ($existingState -and $existingState.owns_kernel_change -and
            $existingState.PSObject.Properties.Name -contains 'modules_format') {
            [string]$existingState.modules_format
        } else { 'none' }
        rollback_kernel_release = if ($existingState -and $existingState.owns_kernel_change) {
            [string]$existingState.kernel_release
        } else { '' }
    }
    $state | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
    Invoke-BoundedWslShutdown
    return $state
}

function Switch-SwitchTradeKernelRollback {
    param([Parameter(Mandatory)][string]$StateRoot)
    $statePath = Join-Path $StateRoot 'kernel-state.json'
    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) { return $false }
    $state = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
    if (-not $state.rollback_kernel_path) { return $false }
    if (-not (Test-Path -LiteralPath $state.rollback_kernel_path -PathType Leaf)) {
        throw 'the retained rollback kernel is missing'
    }
    $config = Join-Path $env:USERPROFILE '.wslconfig'
    $text = if (Test-Path -LiteralPath $config) { Get-Content -Raw -LiteralPath $config } else { '' }
    $values = @{ kernel = ([string]$state.rollback_kernel_path).Replace('\', '\\') }
    if ($state.rollback_modules_path) {
        if (-not (Test-Path -LiteralPath $state.rollback_modules_path -PathType Leaf)) {
            throw 'the retained rollback kernel modules are missing'
        }
        $rollbackFormat = if ($state.PSObject.Properties.Name -contains 'rollback_modules_format') {
            [string]$state.rollback_modules_format
        } else { 'vhd' }
        $values.kernelModules = if ($rollbackFormat -eq 'vhd') {
            ([string]$state.rollback_modules_path).Replace('\', '\\')
        } else { $null }
    } else {
        $values.kernelModules = $null
    }
    [IO.File]::WriteAllText($config, (Set-Wsl2Values -Text $text -Values $values),
        [Text.UTF8Encoding]::new($false))
    $currentKernel, $currentModules, $currentRelease = $state.kernel_path, $state.modules_path, $state.kernel_release
    $state.kernel_path, $state.modules_path, $state.kernel_release = `
        $state.rollback_kernel_path, $state.rollback_modules_path, $state.rollback_kernel_release
    $state.rollback_kernel_path, $state.rollback_modules_path, $state.rollback_kernel_release = `
        $currentKernel, $currentModules, $currentRelease
    if ($state.PSObject.Properties.Name -contains 'modules_format') {
        $currentFormat = $state.modules_format
        $state.modules_format = $state.rollback_modules_format
        $state.rollback_modules_format = $currentFormat
    }
    $state.installed_config_sha256 = Get-FileSha256 $config
    $state | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
    Invoke-BoundedWslShutdown
    return $true
}

function Restore-SwitchTradeKernel {
    param([Parameter(Mandatory)][string]$StateRoot)
    $statePath = Join-Path $StateRoot 'kernel-state.json'
    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) { return $false }
    $state = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
    if (-not $state.owns_kernel_change) { return $false }
    $config = Join-Path $env:USERPROFILE '.wslconfig'
    if (Test-Path -LiteralPath $config -PathType Leaf) {
        $currentHash = Get-FileSha256 $config
        if ($currentHash -ne [string]$state.installed_config_sha256) {
            $conflict = Join-Path $StateRoot ("wslconfig-user-change-{0}.bak" -f (Get-Date -Format 'yyyyMMddTHHmmssfff'))
            Copy-Item -LiteralPath $config -Destination $conflict
        }
    }
    if ($state.prior_config_present) {
        Copy-Item -LiteralPath $state.prior_config_backup -Destination $config -Force
    } elseif (Test-Path -LiteralPath $config) {
        Remove-Item -LiteralPath $config -Force
    }
    $state.owns_kernel_change = $false
    $state | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
    Invoke-BoundedWslShutdown
    return $true
}
