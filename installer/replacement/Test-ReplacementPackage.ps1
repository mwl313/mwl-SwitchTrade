[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$PackageDirectory,
    [switch]$RunDisposableWslLifecycle
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath($PackageDirectory)
$resultPath = Join-Path $root 'build-result.json'
$setup = Join-Path $root 'SwitchTradeSetup.exe'
$manifestPath = Join-Path $root 'package\release-manifest.json'
foreach ($path in @($resultPath, $setup, $manifestPath)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing package artifact: $path" }
}
$result = Get-Content -Raw -LiteralPath $resultPath | ConvertFrom-Json
if ([long]$result.size -ne (Get-Item -LiteralPath $setup).Length -or
    [string]$result.sha256 -ne (Get-FileHash -LiteralPath $setup -Algorithm SHA256).Hash.ToLowerInvariant()) {
    throw 'Setup EXE does not match build-result.json.'
}
$manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
foreach ($payload in $manifest.payloads.PSObject.Properties) {
    $file = [IO.Path]::GetFullPath((Join-Path (Split-Path -Parent $manifestPath) ([string]$payload.Value.path)))
    if (-not $file.StartsWith((Split-Path -Parent $manifestPath).TrimEnd('\') + '\',
            [StringComparison]::OrdinalIgnoreCase) -or
        [long]$payload.Value.size -ne (Get-Item -LiteralPath $file).Length -or
        [string]$payload.Value.sha256 -ne
            (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()) {
        throw "Release payload verification failed: $($payload.Name)"
    }
}

foreach ($executable in @(
    (Join-Path $root 'publish\desktop\SwitchTrade.exe'),
    (Join-Path $root 'publish\prerequisite\SwitchTradePrerequisites.exe')
)) {
    $process = Start-Process -FilePath $executable -ArgumentList '--self-test' -Wait -PassThru -WindowStyle Hidden
    if ($process.ExitCode -ne 0) { throw "Self-test failed: $executable" }
}

$msi = Join-Path $root 'wix\SwitchTrade.Desktop.msi'
$installer = New-Object -ComObject WindowsInstaller.Installer
$database = $installer.GetType().InvokeMember(
    'OpenDatabase',
    [Reflection.BindingFlags]::InvokeMethod,
    $null,
    $installer,
    [object[]]@([string]$msi, [int]0)
)
function Get-MsiRowCount([ValidateSet('File', 'Shortcut', 'CustomAction')][string]$Table) {
    $column = if ($Table -eq 'CustomAction') { 'Action' } else { $Table }
    $sql = "SELECT ``$column`` FROM ``$Table``"
    $view = $database.GetType().InvokeMember(
        'OpenView', [Reflection.BindingFlags]::InvokeMethod, $null, $database, [object[]]@($sql))
    try {
        [void]$view.GetType().InvokeMember(
            'Execute', [Reflection.BindingFlags]::InvokeMethod, $null, $view, $null)
        $count = 0
        while ($null -ne $view.GetType().InvokeMember(
            'Fetch', [Reflection.BindingFlags]::InvokeMethod, $null, $view, $null)) {
            $count++
        }
        return $count
    } finally {
        [void]$view.GetType().InvokeMember(
            'Close', [Reflection.BindingFlags]::InvokeMethod, $null, $view, $null)
    }
}
if ((Get-MsiRowCount File) -ne 3) { throw 'Desktop MSI file table is unexpected.' }
if ((Get-MsiRowCount Shortcut) -ne 2) { throw 'Desktop MSI shortcuts are missing.' }
try {
    if ((Get-MsiRowCount CustomAction) -ne 0) {
        throw 'Desktop MSI must not contain WSL custom actions.'
    }
} catch [System.Runtime.InteropServices.COMException] {
    # An absent CustomAction table is the expected zero-custom-action representation.
}

$layout = Join-Path $root 'validation-layout'
New-Item -ItemType Directory -Force -Path $layout | Out-Null
$start = [Diagnostics.ProcessStartInfo]::new()
$start.FileName = $setup
$start.UseShellExecute = $false
foreach ($argument in @('/layout', $layout, '/quiet')) { [void]$start.ArgumentList.Add($argument) }
$process = [Diagnostics.Process]::Start($start)
$process.WaitForExit()
if ($process.ExitCode -ne 0) { throw "Burn layout verification failed: $($process.ExitCode)" }
$layoutBundle = @(Get-ChildItem -LiteralPath $layout -Filter '*.exe' -File)
if ($layoutBundle.Count -ne 1 -or
    (Get-FileHash -LiteralPath $layoutBundle[0].FullName -Algorithm SHA256).Hash -ne
        (Get-FileHash -LiteralPath $setup -Algorithm SHA256).Hash) {
    throw 'The compressed Burn bundle did not reproduce itself independently.'
}

if ($RunDisposableWslLifecycle) {
    $provisioner = Join-Path $root 'publish\provisioner\SwitchTradeProvisioner.exe'
    $data = Join-Path $root 'validation-lifecycle\data'
    $profile = Join-Path $root 'validation-lifecycle\사용자 profile'
    $before = @((@(& wsl.exe --list --quiet) -replace ([char]0), '') | Where-Object { $_ })
    function Invoke-Provisioner([string]$Action) {
        $arguments = @($Action, '--json', '--package-root', (Join-Path $root 'package'),
            '--data-root', $data, '--user-profile', $profile)
        $start = [Diagnostics.ProcessStartInfo]::new()
        $start.FileName = $provisioner
        $start.UseShellExecute = $false
        $start.Environment['SWITCHTRADE_PROVISIONER_TEST_ROOTS'] = '1'
        foreach ($argument in $arguments) { [void]$start.ArgumentList.Add($argument) }
        $process = [Diagnostics.Process]::Start($start)
        $process.WaitForExit()
        if ($process.ExitCode -ne 0) { throw "Provisioner $Action failed: $($process.ExitCode)" }
    }
    try {
        Invoke-Provisioner 'repair'
        Invoke-Provisioner 'verify-software'
        Invoke-Provisioner 'repair'
    } finally {
        Invoke-Provisioner 'uninstall'
    }
    $after = @((@(& wsl.exe --list --quiet) -replace ([char]0), '') | Where-Object { $_ })
    $distroDifference = $before.Count -ne $after.Count
    if (-not $distroDifference -and $before.Count -gt 0) {
        $distroDifference = @(Compare-Object -ReferenceObject $before -DifferenceObject $after).Count -ne 0
    }
    if ($distroDifference) {
        throw 'Disposable lifecycle changed unrelated WSL distributions.'
    }
    if (Test-Path -LiteralPath (Join-Path $profile '.wslconfig')) {
        throw 'Disposable lifecycle did not restore the absent .wslconfig state.'
    }
}

[pscustomobject]@{
    release_id = [string]$manifest.release_id
    setup_sha256 = (Get-FileHash -LiteralPath $setup -Algorithm SHA256).Hash.ToLowerInvariant()
    package_verified = $true
    disposable_wsl_lifecycle = [bool]$RunDisposableWslLifecycle
}
