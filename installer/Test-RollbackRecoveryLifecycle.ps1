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
. (Join-Path $PSScriptRoot 'PackageIntegrity.ps1')
. (Join-Path $PSScriptRoot 'SetupLifecycle.ps1')
. (Join-Path $PSScriptRoot 'engine\PlatformOps.ps1')
. (Join-Path $PSScriptRoot 'engine\StateInspector.ps1')
. (Join-Path $PSScriptRoot 'engine\Planner.ps1')
. (Join-Path $PSScriptRoot 'engine\Executor.ps1')
# The engine loads after SetupLifecycle so the engine marker-bootstrap gate and the
# executor's ports win; legacy-only helpers (Start-SwitchTradeRollbackTransaction) remain.

# --- Simulated platform boundary (never touches a real distribution) ---
function Invoke-BoundedWslShutdown { return $true }
function Invoke-BoundedNativeProcess {
    param([string]$FilePath, [string[]]$Arguments, [int]$TimeoutSeconds)
    return [pscustomobject]@{ ExitCode = 0; Output = ''; Error = '' }
}
function Convert-ToWslPath([string]$Path) { return $Path }
function Write-SwitchTradeSetupLog {
    param([string]$Path, [string]$Stage, [string]$Message, [string]$Level)
}
function Invoke-SwitchTradeWsl {
    param(
        [Parameter(Mandatory)][string[]]$Arguments,
        [ValidateRange(1, 3600)][int]$TimeoutSeconds = 30,
        [string]$FilePath = '',
        [scriptblock]$CancellationCheck = $null
    )
    $output = if ($Arguments[0] -eq '--list') { 'SwitchTrade' } else { '' }
    return [pscustomobject]@{
        ExitCode = 0; Output = $output; Error = ''
        TimedOut = $false; Cancelled = $false; CommandLine = ''; DurationMs = 0
    }
}
function Get-SwitchTradeDistroRegistrationState {
    param([Parameter(Mandatory)]$Context)
    return [pscustomobject]@{ Exists = $true; BasePath = (Get-Layout).DistroRoot; Known = $true }
}
function Get-SwitchTradeDistroMarkerProbe {
    param([Parameter(Mandatory)][string]$Distro, [string]$FilePath = '', [int]$TimeoutSeconds = 20)
    return [pscustomobject]@{ Missing = $false; Valid = $true; InstallId = '0123456789abcdef0123456789abcdef'; ExitCode = 0 }
}
function Get-SwitchTradeWslRuntimeLocationProbe {
    param(
        [Parameter(Mandatory)][string]$Distro,
        [Parameter(Mandatory)][ValidateSet('active', 'candidate', 'previous', 'commit_swap', 'rollback_swap')]
        [string]$Location,
        [string]$FilePath = '',
        [int]$TimeoutSeconds = 30
    )
    $layout = Get-Layout
    $root = switch ($Location) {
        'active' { $layout.WslActive }
        'previous' { $layout.WslPrevious }
        'candidate' { Join-Path $TestRoot 'wsl-candidate' }
        'commit_swap' { $layout.WslActive + '.commit-swap' }
        'rollback_swap' { $layout.WslActive + '.rollback-swap' }
    }
    if (-not (Test-Path -LiteralPath $root -PathType Container)) {
        return [pscustomobject]@{ Exists = $false; Valid = $true; ReleaseId = ''; IntegritySha256 = '' }
    }
    $release = (Get-Content -Raw -LiteralPath (Join-Path $root '.switchtrade-release.json') |
        ConvertFrom-Json).release_id
    return [pscustomobject]@{
        Exists = $true; Valid = $true; ReleaseId = [string]$release
        IntegritySha256 = (Get-FileSha256 (Join-Path $root '.switchtrade-integrity.json'))
    }
}
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
    return Invoke-SwitchTradeWsl -Arguments $Command -TimeoutSeconds $TimeoutSeconds
}
function Invoke-SwitchTradeWslProvision {
    param(
        [Parameter(Mandatory)][string]$Distro,
        [Parameter(Mandatory)][string]$ScriptPath,
        [Parameter(Mandatory)][string]$Mode,
        [AllowEmptyString()][string[]]$Arguments = @(),
        [ValidateRange(1, 3600)][int]$TimeoutSeconds = 600,
        [string]$FilePath = '',
        [scriptblock]$CancellationCheck = $null
    )
    if ($Mode -notin @('rollback', 'compensate')) {
        return [pscustomobject]@{ ExitCode = 0; Output = ''; Error = '' }
    }
    $releaseIndex = [Array]::IndexOf($Arguments, '--release-id')
    $priorIndex = [Array]::IndexOf($Arguments, '--prior-release-id')
    if ($releaseIndex -lt 0 -or $priorIndex -lt 0) {
        throw "unexpected simulated provision arguments: $($Arguments -join ' ')"
    }
    Switch-Pair (Get-Layout) Wsl $Arguments[$releaseIndex + 1] $Arguments[$priorIndex + 1]
    return [pscustomobject]@{ ExitCode = 0; Output = ''; Error = '' }
}

function New-Release([string]$Root, [string]$ReleaseId) {
    New-Item -ItemType Directory -Force -Path $Root | Out-Null
    '{"relay_url":"https://relay.invalid"}' |
        Set-Content -LiteralPath (Join-Path $Root 'config.json') -Encoding UTF8
    $configHash = Get-FileSha256 (Join-Path $Root 'config.json')
    [ordered]@{
        schema = 2; release_id = $ReleaseId
        artifact_hashes = [ordered]@{ 'payload/release-config.json' = $configHash }
    } | ConvertTo-Json -Depth 4 |
        Set-Content -LiteralPath (Join-Path $Root 'manifest.json') -Encoding UTF8
    Write-WindowsReleaseMarker -Root $Root -ReleaseId $ReleaseId
    Write-SwitchTradeTreeIntegrity -Root $Root -ReleaseId $ReleaseId
}

function New-Package([string]$Root, [string]$ReleaseId) {
    New-Item -ItemType Directory -Force -Path $Root | Out-Null
    $payload = Join-Path $Root 'payload.txt'
    "package-$ReleaseId" | Set-Content -LiteralPath $payload -Encoding UTF8
    [ordered]@{
        schema = 2; release_id = $ReleaseId; signature_required = $false
        artifact_hashes = [ordered]@{ 'payload.txt' = Get-PackageFileSha256 $payload }
    } | ConvertTo-Json -Depth 4 |
        Set-Content -LiteralPath (Join-Path $Root 'manifest.json') -Encoding UTF8
    Test-SwitchTradePackage -PackageRoot $Root -AllowUnsignedPackage | Out-Null
}

function Get-Layout {
    param([string]$Root = $TestRoot)
    $stateRoot = Join-Path $Root 'appdata-local\SwitchTrade'
    return [pscustomobject]@{
        Transaction = Join-Path $stateRoot 'setup-transaction.json'
        StateRoot = $stateRoot
        WindowsActive = Join-Path $Root 'windows-active'
        WindowsPrevious = (Join-Path $Root 'windows-active') + '.previous'
        WslActive = Join-Path $Root 'wsl-active'
        WslPrevious = Join-Path $Root 'wsl-previous'
        KernelState = Join-Path $stateRoot 'kernel-state.json'
        KernelSource = Join-Path $TestRoot 'kernel-b'
        KernelTarget = Join-Path $TestRoot 'kernel-a'
        UserProfile = Join-Path $TestRoot 'user-profile'
        PackageA = Join-Path $TestRoot 'package-a'
        PackageB = Join-Path $TestRoot 'package-b'
        DistroRoot = Join-Path $TestRoot 'distro'
        WindowsStage = Join-Path $TestRoot 'SwitchTrade.stage.0123456789abcdef0123456789abcdef'
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
    Switch-SwitchTradeKernelRollback -StateRoot $Layout.StateRoot `
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
    Switch-SwitchTradeWindowsRollback -Active $active -Previous $previous `
        -ExpectedReleaseId $Target -ExpectedActiveReleaseId $Source | Out-Null
}

function Start-TestRollback($Layout, [string]$PackageRoot) {
    Test-SwitchTradePackage -PackageRoot $PackageRoot -AllowUnsignedPackage | Out-Null
    $transaction = Get-Content -Raw -LiteralPath $Layout.Transaction | ConvertFrom-Json
    $kernel = Get-Content -Raw -LiteralPath $Layout.KernelState | ConvertFrom-Json
    return Start-SwitchTradeRollbackTransaction -Path $Layout.Transaction `
        -Transaction $transaction -KernelState $kernel -PackageRoot $PackageRoot `
        -PackageReleaseId ([string]$transaction.release_id) `
        -PackageManifestSha256 (Get-FileSha256 (Join-Path $PackageRoot 'manifest.json'))
}

function Complete-TestRollback($Layout, $Transaction) {
    $journal = $Transaction.rollback_journal
    Switch-Pair $Layout Wsl $journal.target.release_id $journal.source.release_id
    $Transaction = Set-SwitchTradeTransactionPhase -Path $Layout.Transaction -Phase rollback_wsl_committed
    Switch-Kernel $Layout
    $Transaction = Set-SwitchTradeTransactionPhase -Path $Layout.Transaction -Phase rollback_kernel_committed
    Switch-Pair $Layout Windows $journal.target.release_id $journal.source.release_id
    $Transaction = Set-SwitchTradeTransactionPhase -Path $Layout.Transaction -Phase rollback_windows_committed
    Set-SwitchTradeRollbackPublishedState -Path $Layout.Transaction `
        -Transaction $Transaction -Direction target | Out-Null
}

function Initialize-Fixture {
    $layout = Get-Layout
    New-Item -ItemType Directory -Force -Path $TestRoot, $layout.DistroRoot | Out-Null
    New-Package $layout.PackageA release-a
    New-Package $layout.PackageB release-b
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
        rollback_modules_sha256 = ''; installed_config_sha256 = Get-FileSha256 $config
    }
    Write-AtomicJson -Path $layout.KernelState -Value $kernel
    $transaction = New-SwitchTradeTransaction -Path $layout.Transaction -Action Update `
        -ReleaseId release-b -PriorReleaseId release-a -WindowsStage $layout.WindowsStage `
        -PackageRoot $layout.PackageB -InstallRoot $layout.WindowsActive `
        -PreviousInstall $layout.WindowsPrevious -DistroName SwitchTrade `
        -DistroRoot $layout.DistroRoot -DistroExistedBefore $true -DistroOwnedBefore $true `
        -WslPriorReleaseId release-a -KernelPriorReleaseId release-a `
        -KernelStatePath $layout.KernelState -KernelPriorPath $layout.KernelTarget `
        -InstallId 0123456789abcdef0123456789abcdef -DistroBasePath $layout.DistroRoot `
        -WindowsPriorIntegritySha256 (Get-FileSha256 (Join-Path $layout.WindowsPrevious '.switchtrade-integrity.json')) `
        -WslPriorIntegritySha256 (Get-FileSha256 (Join-Path $layout.WslPrevious '.switchtrade-integrity.json'))
    $transaction.phase = 'completed'
    $transaction.windows_integrity_sha256 =
        Get-FileSha256 (Join-Path $layout.WindowsActive '.switchtrade-integrity.json')
    $transaction.wsl_integrity_sha256 =
        Get-FileSha256 (Join-Path $layout.WslActive '.switchtrade-integrity.json')
    Write-AtomicJson -Path $layout.Transaction -Value $transaction

    Complete-TestRollback $layout (Start-TestRollback $layout $layout.PackageB)
    $completed = Get-Content -Raw -LiteralPath $layout.Transaction | ConvertFrom-Json
    if ($completed.release_id -ne 'release-a' -or
            [string]$completed.package_root -ne [string]$layout.PackageB) {
        throw 'initial package-B rollback to release A did not preserve the stale package-B root'
    }
    $reverse = Start-TestRollback $layout $layout.PackageA
    if ([string]$reverse.rollback_journal.initiating_package.root -ne [string]$layout.PackageA) {
        throw 'reverse rollback did not journal independently verified package A'
    }
}

function Crash-Rollback {
    $layout = Get-Layout
    $transaction = Get-Content -Raw -LiteralPath $layout.Transaction | ConvertFrom-Json
    $source = [string]$transaction.rollback_journal.source.release_id
    $target = [string]$transaction.rollback_journal.target.release_id
    Switch-Pair $layout Wsl $target $source
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
    Switch-Pair $layout Windows $target $source
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
    $localAppData = Join-Path $TestRoot 'appdata-local'
    $context = New-SwitchTradeSetupContext -Action Repair -Distro 'SwitchTrade' -UserProfileRoot $layout.UserProfile -LocalAppDataRoot $localAppData -DesktopRoot (Join-Path $layout.UserProfile 'Desktop') -InstallRoot $layout.WindowsActive -DistroRoot $layout.DistroRoot -PackageRoot $layout.PackageA
    $script:TransactionPath = $context.TransactionPath
    Test-SwitchTradePackage -PackageRoot $context.PackageRoot -AllowUnsignedPackage | Out-Null
    $releaseId = Get-SwitchTradeReleaseId -ManifestPath (Join-Path $context.PackageRoot 'manifest.json')
    $package = New-SwitchTradePackageIdentity -ReleaseId $releaseId -ManifestSha256 (Get-FileSha256 (Join-Path $context.PackageRoot 'manifest.json'))
    $transaction = Get-Content -Raw -LiteralPath $context.TransactionPath | ConvertFrom-Json
    $source = [string]$transaction.rollback_journal.source.release_id
    $state = Get-SwitchTradeInstallState -Context $context
    $plan = Resolve-SwitchTradePlan -Context $context -State $state -Package $package
    if ($plan.Outcome -ne 'plan') { throw "actual interrupted transaction Repair blocked: $($plan.Code)" }
    $null = Invoke-SwitchTradePlan -Context $context -State $state -Package $package -Plan $plan
    $completed = Get-Content -Raw -LiteralPath $context.TransactionPath | ConvertFrom-Json
    if ($completed.phase -ne 'completed') { throw 'actual interrupted transaction Repair did not finalize' }
    if ($completed.release_id -eq $source) { return 'source' }
    if ($completed.release_id -eq [string]$transaction.rollback_journal.target.release_id) { return 'target' }
    throw 'actual interrupted transaction Repair published an unexpected release'
}

function Reverse-Rollback {
    $layout = Get-Layout
    $completed = Get-Content -Raw -LiteralPath $layout.Transaction | ConvertFrom-Json
    $package = if ($completed.release_id -eq 'release-a') { $layout.PackageA } else { $layout.PackageB }
    Complete-TestRollback $layout (Start-TestRollback $layout $package)
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
    & $shell -NoProfile -ExecutionPolicy Bypass -File $PSCommandPath `
        -TestRoot $caseRoot -Mode initialize
    if ($LASTEXITCODE -ne 0) { throw "fixture initialization failed: $($case.Point)" }
    & $shell -NoProfile -ExecutionPolicy Bypass -File $PSCommandPath `
        -TestRoot $caseRoot -Mode crash -Fault $case.Point
    if ($LASTEXITCODE -ne 197) {
        throw "crash process did not stop at $($case.Point): $LASTEXITCODE"
    }
    $interrupted = Get-Content -Raw -LiteralPath (Get-Layout -Root $caseRoot).Transaction |
        ConvertFrom-Json
    if ([string]$interrupted.phase -notmatch '^rollback_' -or
            [string]$interrupted.rollback_journal.initiating_package.release_id -ne 'release-a' -or
            [string]$interrupted.rollback_journal.initiating_package.root -ne
                [string](Join-Path $caseRoot 'package-a')) {
        throw "crash at $($case.Point) did not retain package-A rollback identity"
    }
    if ($case.Point -eq 'wsl_swap') {
        $packageA = Join-Path $caseRoot 'package-a'
        $manifestPath = Join-Path $packageA 'manifest.json'
        $payloadPath = Join-Path $packageA 'payload.txt'
        $manifestBackup = Join-Path $caseRoot 'package-a-manifest.original'
        $payloadBackup = Join-Path $caseRoot 'package-a-payload.original'
        Copy-Item -LiteralPath $manifestPath -Destination $manifestBackup
        Copy-Item -LiteralPath $payloadPath -Destination $payloadBackup
        'valid replacement package with the same release id' |
            Set-Content -LiteralPath $payloadPath -Encoding UTF8
        $replacement = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
        $replacement.artifact_hashes.'payload.txt' = Get-PackageFileSha256 $payloadPath
        $replacement | ConvertTo-Json -Depth 4 |
            Set-Content -LiteralPath $manifestPath -Encoding UTF8
        $transactionHash = Get-FileSha256 (Get-Layout -Root $caseRoot).Transaction
        $savedErrorAction = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        & $shell -NoProfile -ExecutionPolicy Bypass -File $PSCommandPath `
            -TestRoot $caseRoot -Mode repair 2>$null | Out-Null
        $replacementExit = $LASTEXITCODE
        $ErrorActionPreference = $savedErrorAction
        if ($replacementExit -eq 0 -or
                (Get-FileSha256 (Get-Layout -Root $caseRoot).Transaction) -ne $transactionHash) {
            throw 'same-release replacement package bypassed rollback package identity without mutation'
        }
        Copy-Item -LiteralPath $manifestBackup -Destination $manifestPath -Force
        Copy-Item -LiteralPath $payloadBackup -Destination $payloadPath -Force
    }
    $repaired = & $shell -NoProfile -ExecutionPolicy Bypass -File $PSCommandPath `
        -TestRoot $caseRoot -Mode repair
    if ($LASTEXITCODE -ne 0 -or [string]$repaired.Trim() -ne $case.Direction) {
        throw "actual Repair package gate failed after $($case.Point)"
    }
    $completed = Get-Content -Raw -LiteralPath (Get-Layout -Root $caseRoot).Transaction |
        ConvertFrom-Json
    if ($completed.phase -ne 'completed' -or $completed.rollback_journal) {
        throw "Repair did not publish a completed record after $($case.Point)"
    }
    $beforeReverse = [string]$completed.release_id
    & $shell -NoProfile -ExecutionPolicy Bypass -File $PSCommandPath `
        -TestRoot $caseRoot -Mode reverse
    if ($LASTEXITCODE -ne 0) { throw "reverse Rollback failed after $($case.Point)" }
    $reversed = Get-Content -Raw -LiteralPath (Get-Layout -Root $caseRoot).Transaction |
        ConvertFrom-Json
    if ($reversed.phase -ne 'completed' -or [string]$reversed.release_id -eq $beforeReverse) {
        throw "reverse Rollback did not rotate metadata after $($case.Point)"
    }
}
Write-Host 'Rollback package-identity process-death simulation PASS'
