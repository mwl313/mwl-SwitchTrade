[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$TestRoot,
    [ValidateSet('orchestrate', 'initialize', 'crash', 'repair', 'reverse')]
    [string]$Mode = 'orchestrate',
    [ValidateSet('', 'wsl_swap', 'kernel_swap', 'windows_swap', 'before_metadata_publish',
        'recovery_wsl_swap', 'recovery_kernel_config', 'recovery_windows_swap')]
    [string]$Fault = ''
)

$ErrorActionPreference = 'Stop'
$TestRoot = [IO.Path]::GetFullPath($TestRoot)
. (Join-Path $PSScriptRoot 'KernelLifecycle.ps1')
. (Join-Path $PSScriptRoot 'SetupLifecycle.ps1')

function Invoke-BoundedWslShutdown { return $true }

function New-Release([string]$Root, [string]$ReleaseId) {
    New-Item -ItemType Directory -Force -Path $Root | Out-Null
    '{"relay_url":"https://relay.invalid"}' | Set-Content -LiteralPath (Join-Path $Root 'config.json') -Encoding UTF8
    $configHash = Get-FileSha256 (Join-Path $Root 'config.json')
    [ordered]@{
        schema = 2; release_id = $ReleaseId
        artifact_hashes = [ordered]@{ 'payload/release-config.json' = $configHash }
    } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $Root 'manifest.json') -Encoding UTF8
    Write-WindowsReleaseMarker -Root $Root -ReleaseId $ReleaseId
    Write-SwitchTradeTreeIntegrity -Root $Root -ReleaseId $ReleaseId
}

function Get-Layout {
    return [pscustomobject]@{
        Transaction = Join-Path $TestRoot 'transaction.json'
        WindowsActive = Join-Path $TestRoot 'windows-active'
        WindowsPrevious = Join-Path $TestRoot 'windows-previous'
        WslActive = Join-Path $TestRoot 'wsl-active'
        WslPrevious = Join-Path $TestRoot 'wsl-previous'
        KernelState = Join-Path $TestRoot 'kernel-state.json'
        KernelSource = Join-Path $TestRoot 'kernel-b'
        KernelTarget = Join-Path $TestRoot 'kernel-a'
        UserProfile = Join-Path $TestRoot 'user-profile'
    }
}

function Get-TreeState([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) {
        return [pscustomobject]@{ Exists = $false; ReleaseId = ''; IntegritySha256 = '' }
    }
    return [pscustomobject]@{
        Exists = $true; ReleaseId = Get-InstalledWindowsReleaseId -Root $Path
        IntegritySha256 = Get-FileSha256 (Join-Path $Path '.switchtrade-integrity.json')
    }
}

function Get-PairActual([string]$Active, [string]$Previous) {
    $activeState = Get-TreeState $Active
    $previousState = Get-TreeState $Previous
    $swapState = Get-TreeState "$Active.rollback-swap"
    return [pscustomobject]@{
        ActiveExists = $activeState.Exists; ActiveRelease = $activeState.ReleaseId
        ActiveIntegrity = $activeState.IntegritySha256
        PreviousExists = $previousState.Exists; PreviousRelease = $previousState.ReleaseId
        PreviousIntegrity = $previousState.IntegritySha256
        SwapExists = $swapState.Exists; SwapRelease = $swapState.ReleaseId
        SwapIntegrity = $swapState.IntegritySha256
    }
}

function Switch-KernelStateOnly([string]$Path) {
    $state = Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json
    foreach ($pair in @(
            @('package_release_id', 'rollback_package_release_id'),
            @('kernel_path', 'rollback_kernel_path'),
            @('modules_path', 'rollback_modules_path'),
            @('kernel_release', 'rollback_kernel_release'),
            @('modules_format', 'rollback_modules_format'),
            @('kernel_sha256', 'rollback_kernel_sha256'),
            @('modules_sha256', 'rollback_modules_sha256'))) {
        $value = $state.($pair[0])
        $state.($pair[0]) = $state.($pair[1])
        $state.($pair[1]) = $value
    }
    Write-AtomicJson -Path $Path -Value $state
}

function Switch-Kernel($Layout) {
    $state = Get-Content -Raw -LiteralPath $Layout.KernelState | ConvertFrom-Json
    Switch-SwitchTradeKernelRollback -StateRoot $TestRoot `
        -ExpectedReleaseId ([string]$state.rollback_package_release_id) `
        -UserProfileRoot $Layout.UserProfile | Out-Null
}

function Get-Actual($Layout) {
    $kernel = Get-Content -Raw -LiteralPath $Layout.KernelState | ConvertFrom-Json
    $config = Join-Path $Layout.UserProfile '.wslconfig'
    $configValid = (Test-Path -LiteralPath $config -PathType Leaf) -and
        (Get-FileSha256 $config) -eq [string]$kernel.installed_config_sha256
    $kernel | Add-Member -NotePropertyName ConfigurationValid -NotePropertyValue $configValid -Force
    return [pscustomobject]@{
        Windows = Get-PairActual -Active $Layout.WindowsActive -Previous $Layout.WindowsPrevious
        Wsl = Get-PairActual -Active $Layout.WslActive -Previous $Layout.WslPrevious
        Kernel = $kernel
    }
}

function Switch-Pair($Layout, [string]$Axis, [string]$Target, [string]$Source) {
    $active = if ($Axis -eq 'Windows') { $Layout.WindowsActive } else { $Layout.WslActive }
    $previous = if ($Axis -eq 'Windows') { $Layout.WindowsPrevious } else { $Layout.WslPrevious }
    Switch-SwitchTradeWindowsRollback -Active $active -Previous $previous -ExpectedReleaseId $Target -ExpectedActiveReleaseId $Source | Out-Null
}

function Initialize-Fixture {
    $layout = Get-Layout
    New-Item -ItemType Directory -Force -Path $TestRoot | Out-Null
    New-Release $layout.WindowsActive release-b | Out-Null
    New-Release $layout.WindowsPrevious release-a | Out-Null
    New-Release $layout.WslActive release-b | Out-Null
    New-Release $layout.WslPrevious release-a | Out-Null
    'kernel-b' | Set-Content -LiteralPath $layout.KernelSource -Encoding UTF8
    'kernel-a' | Set-Content -LiteralPath $layout.KernelTarget -Encoding UTF8
    New-Item -ItemType Directory -Force -Path $layout.UserProfile | Out-Null
    $config = Join-Path $layout.UserProfile '.wslconfig'
    "[wsl2]`nkernel=$($layout.KernelSource.Replace('\', '\\'))`n" |
        Set-Content -LiteralPath $config -Encoding UTF8
    $kernel = [ordered]@{
        schema = 3
        package_release_id = 'release-b'; kernel_path = $layout.KernelSource
        modules_path = ''; kernel_release = 'kernel-b'; modules_format = 'none'
        kernel_sha256 = Get-FileSha256 $layout.KernelSource; modules_sha256 = ''
        rollback_package_release_id = 'release-a'; rollback_kernel_path = $layout.KernelTarget
        rollback_modules_path = ''; rollback_kernel_release = 'kernel-a'
        rollback_modules_format = 'none'; rollback_kernel_sha256 = Get-FileSha256 $layout.KernelTarget
        rollback_modules_sha256 = ''
        installed_config_sha256 = Get-FileSha256 $config
    }
    Write-AtomicJson -Path $layout.KernelState -Value $kernel
    $transaction = [pscustomobject]@{
        schema = 3; transaction_id = [guid]::NewGuid().ToString('N'); phase = 'completed'
        action = 'Update'; release_id = 'release-b'; prior_release_id = 'release-a'
        wsl_prior_release_id = 'release-a'; kernel_prior_release_id = 'release-a'
        kernel_prior_path = $layout.KernelTarget; kernel_prior_modules_path = ''
        windows_integrity_sha256 = Get-FileSha256 (Join-Path $layout.WindowsActive '.switchtrade-integrity.json')
        windows_prior_integrity_sha256 = Get-FileSha256 (Join-Path $layout.WindowsPrevious '.switchtrade-integrity.json')
        wsl_integrity_sha256 = Get-FileSha256 (Join-Path $layout.WslActive '.switchtrade-integrity.json')
        wsl_prior_integrity_sha256 = Get-FileSha256 (Join-Path $layout.WslPrevious '.switchtrade-integrity.json')
    }
    Write-AtomicJson -Path $layout.Transaction -Value $transaction
    Start-SwitchTradeRollbackTransaction -Path $layout.Transaction -Transaction $transaction -KernelState ([pscustomobject]$kernel) | Out-Null
}

function Crash-Rollback {
    $layout = Get-Layout
    Switch-Pair $layout Wsl release-a release-b
    if ($Fault -eq 'wsl_swap') { exit 197 }
    Set-SwitchTradeTransactionPhase -Path $layout.Transaction -Phase rollback_wsl_committed | Out-Null
    Switch-Kernel $layout
    if ($Fault -eq 'kernel_swap') { exit 197 }
    Set-SwitchTradeTransactionPhase -Path $layout.Transaction -Phase rollback_kernel_committed | Out-Null
    if ($Fault -eq 'recovery_kernel_config') {
        Switch-KernelStateOnly $layout.KernelState
        exit 197
    }
    if ($Fault -eq 'recovery_wsl_swap') {
        Switch-Kernel $layout
        Move-Item -LiteralPath $layout.WslActive -Destination "$($layout.WslActive).rollback-swap"
        exit 197
    }
    Switch-Pair $layout Windows release-a release-b
    if ($Fault -eq 'windows_swap') { exit 197 }
    Set-SwitchTradeTransactionPhase -Path $layout.Transaction -Phase rollback_windows_committed | Out-Null
    if ($Fault -eq 'recovery_windows_swap') {
        Move-Item -LiteralPath $layout.WindowsActive -Destination "$($layout.WindowsActive).rollback-swap"
        exit 197
    }
    exit 197
}

function Repair-Rollback {
    $layout = Get-Layout
    $transaction = Get-Content -Raw -LiteralPath $layout.Transaction | ConvertFrom-Json
    $plan = Resolve-SwitchTradeRollbackRecovery -Transaction $transaction -Actual (Get-Actual $layout)
    $transaction = Set-SwitchTradeTransactionPhase -Path $layout.Transaction -Phase "rollback_recovering_$($plan.Direction)"
    if ($plan.Direction -eq 'source') {
        if ($plan.WindowsPosition -eq 'target_transition') { Switch-Pair $layout Windows release-a release-b }
        if ($plan.WindowsPosition -ne 'source') { Switch-Pair $layout Windows release-b release-a }
        if ($plan.KernelPosition -ne 'source') {
            Switch-Kernel $layout
        } elseif (-not [bool](Get-Actual $layout).Kernel.ConfigurationValid) {
            Repair-SwitchTradeKernelConfiguration -StateRoot $TestRoot `
                -UserProfileRoot $layout.UserProfile | Out-Null
        }
        if ($plan.WslPosition -eq 'target_transition') { Switch-Pair $layout Wsl release-a release-b }
        if ($plan.WslPosition -ne 'source') { Switch-Pair $layout Wsl release-b release-a }
    } else {
        if (-not [bool](Get-Actual $layout).Kernel.ConfigurationValid) {
            Repair-SwitchTradeKernelConfiguration -StateRoot $TestRoot `
                -UserProfileRoot $layout.UserProfile | Out-Null
        }
        if ($plan.WslPosition -eq 'target_transition') { Switch-Pair $layout Wsl release-a release-b }
        if ($plan.WindowsPosition -eq 'target_transition') { Switch-Pair $layout Windows release-a release-b }
    }
    $verifiedActual = Get-Actual $layout
    $verified = Resolve-SwitchTradeRollbackRecovery -Transaction $transaction -Actual $verifiedActual
    if ($verified.WindowsPosition -ne $plan.Direction -or $verified.WslPosition -ne $plan.Direction -or
            $verified.KernelPosition -ne $plan.Direction -or
            -not [bool]$verifiedActual.Kernel.ConfigurationValid) {
        throw 'fresh Repair process did not converge all rollback axes'
    }
    Set-SwitchTradeRollbackPublishedState -Path $layout.Transaction -Transaction $transaction -Direction $plan.Direction | Out-Null
    Write-Output $plan.Direction
}

function Reverse-Rollback {
    $layout = Get-Layout
    $completed = Get-Content -Raw -LiteralPath $layout.Transaction | ConvertFrom-Json
    $kernel = Get-Content -Raw -LiteralPath $layout.KernelState | ConvertFrom-Json
    $transaction = Start-SwitchTradeRollbackTransaction -Path $layout.Transaction -Transaction $completed -KernelState $kernel
    Switch-Pair $layout Wsl $completed.prior_release_id $completed.release_id
    $transaction = Set-SwitchTradeTransactionPhase -Path $layout.Transaction -Phase rollback_wsl_committed
    Switch-Kernel $layout
    $transaction = Set-SwitchTradeTransactionPhase -Path $layout.Transaction -Phase rollback_kernel_committed
    Switch-Pair $layout Windows $completed.prior_release_id $completed.release_id
    $transaction = Set-SwitchTradeTransactionPhase -Path $layout.Transaction -Phase rollback_windows_committed
    Set-SwitchTradeRollbackPublishedState -Path $layout.Transaction -Transaction $transaction -Direction target | Out-Null
}

if ($Mode -eq 'initialize') { Initialize-Fixture; exit }
if ($Mode -eq 'crash') { Crash-Rollback }
if ($Mode -eq 'repair') { Repair-Rollback; exit }
if ($Mode -eq 'reverse') { Reverse-Rollback; exit }

$shell = (Get-Process -Id $PID).Path
foreach ($case in @(
        [pscustomobject]@{ Point = 'wsl_swap'; Direction = 'source' },
        [pscustomobject]@{ Point = 'kernel_swap'; Direction = 'source' },
        [pscustomobject]@{ Point = 'windows_swap'; Direction = 'target' },
        [pscustomobject]@{ Point = 'before_metadata_publish'; Direction = 'target' },
        [pscustomobject]@{ Point = 'recovery_wsl_swap'; Direction = 'source' },
        [pscustomobject]@{ Point = 'recovery_kernel_config'; Direction = 'source' },
        [pscustomobject]@{ Point = 'recovery_windows_swap'; Direction = 'source' })) {
    $caseRoot = Join-Path $TestRoot $case.Point
    & $shell -NoProfile -ExecutionPolicy Bypass -File $PSCommandPath -TestRoot $caseRoot -Mode initialize
    if ($LASTEXITCODE -ne 0) { throw "fixture initialization failed: $($case.Point)" }
    & $shell -NoProfile -ExecutionPolicy Bypass -File $PSCommandPath -TestRoot $caseRoot -Mode crash -Fault $case.Point
    if ($LASTEXITCODE -ne 197) { throw "crash process did not stop at $($case.Point): $LASTEXITCODE" }
    $interrupted = Get-Content -Raw -LiteralPath (Join-Path $caseRoot 'transaction.json') | ConvertFrom-Json
    if ([string]$interrupted.phase -notmatch '^rollback_' -or -not $interrupted.rollback_journal) {
        throw "crash at $($case.Point) did not leave an atomic nonterminal journal"
    }
    $repaired = & $shell -NoProfile -ExecutionPolicy Bypass -File $PSCommandPath -TestRoot $caseRoot -Mode repair
    if ($LASTEXITCODE -ne 0 -or [string]$repaired.Trim() -ne $case.Direction) {
        throw "fresh Repair process failed after $($case.Point)"
    }
    $completed = Get-Content -Raw -LiteralPath (Join-Path $caseRoot 'transaction.json') | ConvertFrom-Json
    if ($completed.phase -ne 'completed' -or $completed.rollback_journal) {
        throw "Repair did not publish a completed record after $($case.Point)"
    }
    $beforeReverse = [string]$completed.release_id
    & $shell -NoProfile -ExecutionPolicy Bypass -File $PSCommandPath -TestRoot $caseRoot -Mode reverse
    if ($LASTEXITCODE -ne 0) { throw "reverse Rollback failed after $($case.Point)" }
    $reversed = Get-Content -Raw -LiteralPath (Join-Path $caseRoot 'transaction.json') | ConvertFrom-Json
    if ($reversed.phase -ne 'completed' -or [string]$reversed.release_id -eq $beforeReverse) {
        throw "reverse Rollback did not rotate metadata after $($case.Point)"
    }
}
Write-Host 'Rollback process-death recovery simulation PASS'
