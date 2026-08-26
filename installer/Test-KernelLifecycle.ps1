[CmdletBinding()]
param([Parameter(Mandatory)][string]$TestRoot)

$ErrorActionPreference = 'Stop'
$TestRoot = [IO.Path]::GetFullPath($TestRoot)
New-Item -ItemType Directory -Force -Path $TestRoot | Out-Null
$originalProfile = $env:USERPROFILE
try {
    $env:USERPROFILE = Join-Path $TestRoot 'profile'
    New-Item -ItemType Directory -Force -Path $env:USERPROFILE | Out-Null
    $original = "[general]`r`ninstanceIdleTimeout=-1`r`n`r`n[wsl2]`r`nvmIdleTimeout=-1`r`n"
    [IO.File]::WriteAllText((Join-Path $env:USERPROFILE '.wslconfig'), $original,
        [Text.UTF8Encoding]::new($false))

    . (Join-Path $PSScriptRoot 'KernelLifecycle.ps1')
    function Invoke-BoundedWslShutdown { }

    $stateRoot = Join-Path $TestRoot 'state'
    $kernelStorageRoot = Join-Path $TestRoot 'kernel-storage'
    $releaseOne = Join-Path $TestRoot 'release-one'
    $releaseTwo = Join-Path $TestRoot 'release-two'
    New-Item -ItemType Directory -Force -Path $releaseOne, $releaseTwo | Out-Null
    $kernelOne = Join-Path $releaseOne 'kernel'
    $kernelTwo = Join-Path $releaseTwo 'kernel'
    $modulesOne = Join-Path $TestRoot 'modules-one.tar.gz'
    [IO.File]::WriteAllText($kernelOne, 'kernel one')
    [IO.File]::WriteAllText($kernelTwo, 'kernel two')
    [IO.File]::WriteAllText($modulesOne, 'test module archive')
    $manifestOne = Join-Path $TestRoot 'manifest-one.json'
    $manifestTwo = Join-Path $TestRoot 'manifest-two.json'
    @{ kernel_release = 'test-one'; kernel_sha256 = Get-FileSha256 $kernelOne
       modules_sha256 = Get-FileSha256 $modulesOne } |
        ConvertTo-Json | Set-Content -LiteralPath $manifestOne -Encoding UTF8
    @{ kernel_release = 'test-two'; kernel_sha256 = Get-FileSha256 $kernelTwo } |
        ConvertTo-Json | Set-Content -LiteralPath $manifestTwo -Encoding UTF8

    Install-SwitchTradeKernel -Kernel $kernelOne -KernelModules $modulesOne `
        -Manifest $manifestOne -StateRoot $stateRoot -KernelStorageRoot $kernelStorageRoot `
        -ReleaseId release-a `
        -AcceptGlobalKernelChange | Out-Null
    $merged = Get-Content -Raw -LiteralPath (Join-Path $env:USERPROFILE '.wslconfig')
    if ($merged -notmatch 'instanceIdleTimeout=-1' -or $merged -notmatch 'vmIdleTimeout=-1') {
        throw 'unrelated WSL settings were not preserved'
    }
    if ($merged -match '(?m)^kernelModules=') {
        throw 'a modules tar archive was incorrectly configured as a WSL modules VHD'
    }
    $installedState = Get-Content -Raw -LiteralPath (Join-Path $stateRoot 'kernel-state.json') | ConvertFrom-Json
    if (-not ([string]$installedState.kernel_path).StartsWith(
            [IO.Path]::GetFullPath($kernelStorageRoot), [StringComparison]::OrdinalIgnoreCase)) {
        throw 'kernel was not copied to the dedicated WSL-safe storage root'
    }
    Install-SwitchTradeKernel -Kernel $kernelOne -KernelModules $modulesOne `
        -Manifest $manifestOne -StateRoot $stateRoot -KernelStorageRoot $kernelStorageRoot `
        -ReleaseId release-a `
        -AcceptGlobalKernelChange | Out-Null
    $sameRelease = Get-Content -Raw -LiteralPath (Join-Path $stateRoot 'kernel-state.json') | ConvertFrom-Json
    if ($sameRelease.rollback_kernel_path -or $sameRelease.kernel_path -ne $installedState.kernel_path) {
        throw 'same-release repair replaced the active kernel or invented a rollback release'
    }
    Install-SwitchTradeKernel -Kernel $kernelTwo -Manifest $manifestTwo -StateRoot $stateRoot `
        -KernelStorageRoot $kernelStorageRoot `
        -ReleaseId release-b `
        -AcceptGlobalKernelChange | Out-Null
    $beforeRollback = Get-Content -Raw -LiteralPath (Join-Path $stateRoot 'kernel-state.json') | ConvertFrom-Json
    if ($beforeRollback.kernel_path -eq $beforeRollback.rollback_kernel_path -or
        -not (Test-Path -LiteralPath $beforeRollback.rollback_kernel_path -PathType Leaf)) {
        throw 'versioned kernel update overwrote the retained rollback artifact'
    }
    Test-SwitchTradeKernelRollback -StateRoot $stateRoot -ExpectedReleaseId release-a | Out-Null
    if (-not (Switch-SwitchTradeKernelRollback -StateRoot $stateRoot -ExpectedReleaseId release-a)) {
        throw 'release kernel rollback was not available'
    }
    $state = Get-Content -Raw -LiteralPath (Join-Path $stateRoot 'kernel-state.json') | ConvertFrom-Json
    if ($state.kernel_release -ne 'test-one') { throw 'release kernel rollback selected the wrong version' }
    if ($state.package_release_id -ne 'release-a') { throw 'package release rollback selected the wrong version' }
    if (-not (Restore-SwitchTradeKernel -StateRoot $stateRoot)) {
        throw 'original WSL configuration rollback was not available'
    }
    $restored = Get-Content -Raw -LiteralPath (Join-Path $env:USERPROFILE '.wslconfig')
    if ($restored -cne $original) { throw 'original WSL configuration was not restored exactly' }

    Install-SwitchTradeKernel -Kernel $kernelOne -KernelModules $modulesOne `
        -Manifest $manifestOne -StateRoot $stateRoot -KernelStorageRoot $kernelStorageRoot `
        -ReleaseId release-c -AcceptGlobalKernelChange | Out-Null
    $userEdited = (Get-Content -Raw -LiteralPath (Join-Path $env:USERPROFILE '.wslconfig')).Replace(
        "vmIdleTimeout=-1", "vmIdleTimeout=-1`r`nmemory=4GB")
    [IO.File]::WriteAllText((Join-Path $env:USERPROFILE '.wslconfig'), $userEdited,
        [Text.UTF8Encoding]::new($false))
    Restore-SwitchTradeKernel -StateRoot $stateRoot | Out-Null
    $conflictRestored = Get-Content -Raw -LiteralPath (Join-Path $env:USERPROFILE '.wslconfig')
    if ($conflictRestored -notmatch '(?m)^memory=4GB\r?$' -or $conflictRestored -match '(?m)^kernel(?:Modules)?=') {
        throw 'conflict-aware uninstall did not preserve user settings while removing owned kernel keys'
    }
    Write-Host 'Kernel lifecycle simulation PASS'
} finally {
    $env:USERPROFILE = $originalProfile
}
