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

function Get-TextSha256([string]$Text) {
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.UTF8Encoding]::new($false).GetBytes($Text)
        return ([BitConverter]::ToString($algorithm.ComputeHash($bytes))).Replace('-', '').ToLowerInvariant()
    } finally { $algorithm.Dispose() }
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
                    if ($null -ne $Values[$key]) { $result.Add("$key=$($Values[$key])") }
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
        [string]$UserProfileRoot = $env:USERPROFILE,
        [Parameter(Mandatory)][ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$')]
        [string]$ReleaseId,
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
    if (Test-Path -LiteralPath $installedKernel -PathType Leaf) {
        if ((Get-FileSha256 $installedKernel) -ne (Get-FileSha256 $Kernel)) {
            throw 'stored custom kernel does not match its content-addressed identity'
        }
    } else {
        Copy-Item -LiteralPath $Kernel -Destination $installedKernel
    }
    $installedModules = ''
    $modulesFormat = 'none'
    if ($KernelModules) {
        $moduleIdentity = (Get-FileSha256 $KernelModules).Substring(0, 12)
        $moduleExtension = if ([IO.Path]::GetExtension($KernelModules).ToLowerInvariant() -in @('.vhd', '.vhdx')) {
            [IO.Path]::GetExtension($KernelModules).ToLowerInvariant()
        } else { '.tar.gz' }
        $installedModules = Join-Path $kernelRoot "modules-$safeRelease-$moduleIdentity$moduleExtension"
        if (Test-Path -LiteralPath $installedModules -PathType Leaf) {
            if ((Get-FileSha256 $installedModules) -ne (Get-FileSha256 $KernelModules)) {
                throw 'stored custom kernel modules do not match their content-addressed identity'
            }
        } else {
            Copy-Item -LiteralPath $KernelModules -Destination $installedModules
        }
        $modulesFormat = if ([IO.Path]::GetExtension($KernelModules).ToLowerInvariant() -in @('.vhd', '.vhdx')) {
            'vhd'
        } else { 'archive' }
    }

    $config = Join-Path $UserProfileRoot '.wslconfig'
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
    $samePackageRelease = $existingState -and $existingState.owns_kernel_change -and
        $existingState.PSObject.Properties.Name -contains 'package_release_id' -and
        [string]$existingState.package_release_id -eq $ReleaseId
    $state = @{
        schema = 3; owns_kernel_change = $true; prior_config_present = $priorPresentForRollback
        prior_config_backup = $backup; installed_config_sha256 = Get-TextSha256 $merged
        kernel_path = $installedKernel; modules_path = $installedModules
        modules_format = $modulesFormat
        kernel_release = [string]$metadata.kernel_release
        package_release_id = $ReleaseId
        kernel_sha256 = Get-FileSha256 $installedKernel
        modules_sha256 = if ($installedModules) { Get-FileSha256 $installedModules } else { '' }
        rollback_kernel_path = if ($existingState -and $existingState.owns_kernel_change) {
            if ($samePackageRelease) {
                [string]$existingState.rollback_kernel_path
            } else { [string]$existingState.kernel_path }
        } else { '' }
        rollback_modules_path = if ($existingState -and $existingState.owns_kernel_change) {
            if ($samePackageRelease) {
                [string]$existingState.rollback_modules_path
            } else { [string]$existingState.modules_path }
        } else { '' }
        rollback_modules_format = if ($existingState -and $existingState.owns_kernel_change -and
            $existingState.PSObject.Properties.Name -contains 'modules_format') {
            if ($samePackageRelease -and
                $existingState.PSObject.Properties.Name -contains 'rollback_modules_format') {
                [string]$existingState.rollback_modules_format
            } else { [string]$existingState.modules_format }
        } else { 'none' }
        rollback_kernel_release = if ($existingState -and $existingState.owns_kernel_change) {
            if ($samePackageRelease) {
                [string]$existingState.rollback_kernel_release
            } else { [string]$existingState.kernel_release }
        } else { '' }
        rollback_package_release_id = if ($existingState -and $existingState.owns_kernel_change) {
            if ($samePackageRelease -and
                $existingState.PSObject.Properties.Name -contains 'rollback_package_release_id') {
                [string]$existingState.rollback_package_release_id
            } elseif ($existingState.PSObject.Properties.Name -contains 'package_release_id') {
                [string]$existingState.package_release_id
            } else { '' }
        } else { '' }
        rollback_kernel_sha256 = if ($existingState -and $existingState.owns_kernel_change) {
            if ($samePackageRelease -and
                $existingState.PSObject.Properties.Name -contains 'rollback_kernel_sha256') {
                [string]$existingState.rollback_kernel_sha256
            } elseif ($existingState.PSObject.Properties.Name -contains 'kernel_sha256') {
                [string]$existingState.kernel_sha256
            } else { Get-FileSha256 ([string]$existingState.kernel_path) }
        } else { '' }
        rollback_modules_sha256 = if ($existingState -and $existingState.owns_kernel_change) {
            if ($samePackageRelease -and
                $existingState.PSObject.Properties.Name -contains 'rollback_modules_sha256') {
                [string]$existingState.rollback_modules_sha256
            } elseif ($existingState.PSObject.Properties.Name -contains 'modules_sha256') {
                [string]$existingState.modules_sha256
            } elseif ([string]$existingState.modules_path) {
                Get-FileSha256 ([string]$existingState.modules_path)
            } else { '' }
        } else { '' }
    }
    Write-KernelStateAtomic -Path $statePath -Value $state
    [IO.File]::WriteAllText($config, $merged, [Text.UTF8Encoding]::new($false))
    if ((Get-FileSha256 $config) -ne [string]$state.installed_config_sha256) {
        throw 'WSLCONFIG_COMMIT_HASH_MISMATCH'
    }
    Invoke-BoundedWslShutdown
    return $state
}

function Get-Wsl2Values {
    param([string]$Text, [string[]]$Keys)
    $values = @{}
    $section = ''
    foreach ($line in @($Text -split "`r?`n", 0)) {
        if ($line -match '^\s*\[([^]]+)\]\s*$') { $section = $Matches[1]; continue }
        if ($section -ieq 'wsl2' -and $line -match '^\s*([^#;=\s]+)\s*=\s*(.*?)\s*$') {
            $key = [string]$Matches[1]
            if ($Keys -icontains $key -and -not $values.ContainsKey($key)) { $values[$key] = [string]$Matches[2] }
        }
    }
    return $values
}

function Write-KernelStateAtomic([string]$Path, $Value) {
    $temporary = "$Path.tmp.$([guid]::NewGuid().ToString('N'))"
    try {
        $Value | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $temporary -Encoding UTF8
        Move-Item -LiteralPath $temporary -Destination $Path -Force
    } finally {
        if (Test-Path -LiteralPath $temporary -PathType Leaf) {
            Remove-Item -LiteralPath $temporary -Force
        }
    }
}

function Initialize-SwitchTradeKernelReleaseIdentity {
    param(
        [Parameter(Mandatory)][string]$StateRoot,
        [Parameter(Mandatory)][string]$CurrentReleaseId
    )
    $statePath = Join-Path $StateRoot 'kernel-state.json'
    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) { return $false }
    $state = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
    if (-not $state.owns_kernel_change) { throw 'KERNEL_STATE_NOT_OWNED' }
    if ($state.PSObject.Properties.Name -contains 'package_release_id') {
        if ([string]$state.package_release_id -ne $CurrentReleaseId) {
            throw 'KERNEL_RELEASE_ID_MISMATCH: installed Windows and kernel state disagree'
        }
        return $true
    }
    if (-not $state.kernel_path -or -not (Test-Path -LiteralPath $state.kernel_path -PathType Leaf)) {
        throw 'KERNEL_STATE_ACTIVE_MISSING'
    }
    $state.schema = 3
    $state | Add-Member -NotePropertyName package_release_id -NotePropertyValue $CurrentReleaseId
    $state | Add-Member -NotePropertyName kernel_sha256 -NotePropertyValue `
        (Get-FileSha256 ([string]$state.kernel_path))
    $modulesHash = if ([string]$state.modules_path) {
        if (-not (Test-Path -LiteralPath $state.modules_path -PathType Leaf)) {
            throw 'KERNEL_STATE_MODULES_MISSING'
        }
        Get-FileSha256 ([string]$state.modules_path)
    } else { '' }
    $state | Add-Member -NotePropertyName modules_sha256 -NotePropertyValue $modulesHash
    foreach ($property in @('rollback_package_release_id', 'rollback_kernel_sha256',
            'rollback_modules_sha256')) {
        $state | Add-Member -NotePropertyName $property -NotePropertyValue ''
    }
    Write-KernelStateAtomic -Path $statePath -Value $state
    return $true
}

function Test-SwitchTradeKernelRollback {
    param(
        [Parameter(Mandatory)][string]$StateRoot,
        [Parameter(Mandatory)][string]$ExpectedReleaseId
    )
    $statePath = Join-Path $StateRoot 'kernel-state.json'
    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
        throw 'ROLLBACK_KERNEL_STATE_MISSING'
    }
    $state = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
    if ([int]$state.schema -lt 3 -or [string]$state.rollback_package_release_id -ne $ExpectedReleaseId) {
        throw "ROLLBACK_KERNEL_RELEASE_MISMATCH: expected $ExpectedReleaseId"
    }
    if (-not $state.rollback_kernel_path -or
        -not (Test-Path -LiteralPath $state.rollback_kernel_path -PathType Leaf) -or
        (Get-FileSha256 ([string]$state.rollback_kernel_path)) -ne [string]$state.rollback_kernel_sha256) {
        throw 'ROLLBACK_KERNEL_HASH_MISMATCH'
    }
    if ($state.rollback_modules_path -and
        (-not (Test-Path -LiteralPath $state.rollback_modules_path -PathType Leaf) -or
         (Get-FileSha256 ([string]$state.rollback_modules_path)) -ne [string]$state.rollback_modules_sha256)) {
        throw 'ROLLBACK_KERNEL_MODULES_HASH_MISMATCH'
    }
    return $state
}

function Switch-SwitchTradeKernelRollback {
    param(
        [Parameter(Mandatory)][string]$StateRoot,
        [string]$ExpectedReleaseId = '',
        [string]$UserProfileRoot = $env:USERPROFILE
    )
    $statePath = Join-Path $StateRoot 'kernel-state.json'
    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) { return $false }
    $state = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
    if (-not $state.rollback_kernel_path) { return $false }
    if (-not $ExpectedReleaseId) { $ExpectedReleaseId = [string]$state.rollback_package_release_id }
    $state = Test-SwitchTradeKernelRollback -StateRoot $StateRoot -ExpectedReleaseId $ExpectedReleaseId
    $config = Join-Path $UserProfileRoot '.wslconfig'
    $text = if (Test-Path -LiteralPath $config) { Get-Content -Raw -LiteralPath $config } else { '' }
    $values = @{ kernel = ([string]$state.rollback_kernel_path).Replace('\', '\\') }
    if ($state.rollback_modules_path) {
        $rollbackFormat = if ($state.PSObject.Properties.Name -contains 'rollback_modules_format') {
            [string]$state.rollback_modules_format
        } else { 'vhd' }
        $values.kernelModules = if ($rollbackFormat -eq 'vhd') {
            ([string]$state.rollback_modules_path).Replace('\', '\\')
        } else { $null }
    } else {
        $values.kernelModules = $null
    }
    $rollbackText = Set-Wsl2Values -Text $text -Values $values
    $oldState = $state | ConvertTo-Json -Depth 6 | ConvertFrom-Json
    $currentKernel, $currentModules, $currentRelease = $state.kernel_path, $state.modules_path, $state.kernel_release
    $currentPackageRelease, $currentKernelHash, $currentModulesHash = `
        $state.package_release_id, $state.kernel_sha256, $state.modules_sha256
    $state.kernel_path, $state.modules_path, $state.kernel_release = `
        $state.rollback_kernel_path, $state.rollback_modules_path, $state.rollback_kernel_release
    $state.rollback_kernel_path, $state.rollback_modules_path, $state.rollback_kernel_release = `
        $currentKernel, $currentModules, $currentRelease
    $state.package_release_id, $state.kernel_sha256, $state.modules_sha256 = `
        $state.rollback_package_release_id, $state.rollback_kernel_sha256, $state.rollback_modules_sha256
    $state.rollback_package_release_id, $state.rollback_kernel_sha256, $state.rollback_modules_sha256 = `
        $currentPackageRelease, $currentKernelHash, $currentModulesHash
    if ($state.PSObject.Properties.Name -contains 'modules_format') {
        $currentFormat = $state.modules_format
        $state.modules_format = $state.rollback_modules_format
        $state.rollback_modules_format = $currentFormat
    }
    $state.installed_config_sha256 = Get-TextSha256 $rollbackText
    Write-KernelStateAtomic -Path $statePath -Value $state
    try {
        [IO.File]::WriteAllText($config, $rollbackText, [Text.UTF8Encoding]::new($false))
        if ((Get-FileSha256 $config) -ne [string]$state.installed_config_sha256) {
            throw 'WSLCONFIG_ROLLBACK_HASH_MISMATCH'
        }
        Invoke-BoundedWslShutdown
    } catch {
        Write-KernelStateAtomic -Path $statePath -Value $oldState
        [IO.File]::WriteAllText($config, $text, [Text.UTF8Encoding]::new($false))
        throw
    }
    return $true
}

function Restore-SwitchTradeKernel {
    param(
        [Parameter(Mandatory)][string]$StateRoot,
        [string]$UserProfileRoot = $env:USERPROFILE
    )
    $statePath = Join-Path $StateRoot 'kernel-state.json'
    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) { return $false }
    $state = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
    if (-not $state.owns_kernel_change) { return $false }
    $config = Join-Path $UserProfileRoot '.wslconfig'
    $currentChanged = $false
    $currentText = if (Test-Path -LiteralPath $config -PathType Leaf) {
        Get-Content -Raw -LiteralPath $config
    } else { '' }
    if (Test-Path -LiteralPath $config -PathType Leaf) {
        $currentHash = Get-FileSha256 $config
        if ($currentHash -ne [string]$state.installed_config_sha256) {
            $currentChanged = $true
            $conflict = Join-Path $StateRoot ("wslconfig-user-change-{0}.bak" -f (Get-Date -Format 'yyyyMMddTHHmmssfff'))
            Copy-Item -LiteralPath $config -Destination $conflict
        }
    }
    if ($currentChanged) {
        $priorText = if ($state.prior_config_present) {
            Get-Content -Raw -LiteralPath $state.prior_config_backup
        } else { '' }
        $priorValues = Get-Wsl2Values -Text $priorText -Keys @('kernel', 'kernelModules')
        $restoreValues = @{
            kernel = if ($priorValues.ContainsKey('kernel')) { $priorValues['kernel'] } else { $null }
            kernelModules = if ($priorValues.ContainsKey('kernelModules')) { $priorValues['kernelModules'] } else { $null }
        }
        [IO.File]::WriteAllText($config, (Set-Wsl2Values -Text $currentText -Values $restoreValues),
            [Text.UTF8Encoding]::new($false))
    } elseif ($state.prior_config_present) {
        Copy-Item -LiteralPath $state.prior_config_backup -Destination $config -Force
    } elseif (Test-Path -LiteralPath $config) {
        Remove-Item -LiteralPath $config -Force
    }
    $state.owns_kernel_change = $false
    Write-KernelStateAtomic -Path $statePath -Value $state
    Invoke-BoundedWslShutdown
    return $true
}
