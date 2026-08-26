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
        -Manifest $manifestOne -StateRoot $stateRoot `
        -AcceptGlobalKernelChange | Out-Null
    $merged = Get-Content -Raw -LiteralPath (Join-Path $env:USERPROFILE '.wslconfig')
    if ($merged -notmatch 'instanceIdleTimeout=-1' -or $merged -notmatch 'vmIdleTimeout=-1') {
        throw 'unrelated WSL settings were not preserved'
    }
    if ($merged -match '(?m)^kernelModules=') {
        throw 'a modules tar archive was incorrectly configured as a WSL modules VHD'
    }
    Install-SwitchTradeKernel -Kernel $kernelTwo -Manifest $manifestTwo -StateRoot $stateRoot `
        -AcceptGlobalKernelChange | Out-Null
    $beforeRollback = Get-Content -Raw -LiteralPath (Join-Path $stateRoot 'kernel-state.json') | ConvertFrom-Json
    if ($beforeRollback.kernel_path -eq $beforeRollback.rollback_kernel_path -or
        -not (Test-Path -LiteralPath $beforeRollback.rollback_kernel_path -PathType Leaf)) {
        throw 'versioned kernel update overwrote the retained rollback artifact'
    }
    if (-not (Switch-SwitchTradeKernelRollback -StateRoot $stateRoot)) {
        throw 'release kernel rollback was not available'
    }
    $state = Get-Content -Raw -LiteralPath (Join-Path $stateRoot 'kernel-state.json') | ConvertFrom-Json
    if ($state.kernel_release -ne 'test-one') { throw 'release kernel rollback selected the wrong version' }
    if (-not (Restore-SwitchTradeKernel -StateRoot $stateRoot)) {
        throw 'original WSL configuration rollback was not available'
    }
    $restored = Get-Content -Raw -LiteralPath (Join-Path $env:USERPROFILE '.wslconfig')
    if ($restored -cne $original) { throw 'original WSL configuration was not restored exactly' }
    Write-Host 'Kernel lifecycle simulation PASS'
} finally {
    $env:USERPROFILE = $originalProfile
}
