[CmdletBinding()]
param([Parameter(Mandatory)][string]$TestRoot)

$ErrorActionPreference = 'Stop'
$TestRoot = [IO.Path]::GetFullPath($TestRoot)
New-Item -ItemType Directory -Force -Path $TestRoot | Out-Null
. (Join-Path $PSScriptRoot 'KernelLifecycle.ps1')
. (Join-Path $PSScriptRoot 'SetupLifecycle.ps1')

function New-TestRelease([string]$Root, [string]$ReleaseId) {
    New-Item -ItemType Directory -Force -Path $Root | Out-Null
    $config = Join-Path $Root 'config.json'
    '{"relay_url":"https://relay.invalid"}' | Set-Content -LiteralPath $config -Encoding UTF8
    $hash = Get-FileSha256 $config
    [ordered]@{
        schema = 2; release_id = $ReleaseId
        artifact_hashes = [ordered]@{ 'payload/release-config.json' = $hash }
    } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $Root 'manifest.json') -Encoding UTF8
    Write-WindowsReleaseMarker -Root $Root -ReleaseId $ReleaseId
}

foreach ($fault in @('after_active_retained', 'after_candidate_activated')) {
    $faultRoot = Join-Path $TestRoot $fault
    $faultActive = Join-Path $faultRoot 'active'
    $faultPrevious = Join-Path $faultRoot 'previous'
    $faultCandidate = Join-Path $faultRoot 'candidate'
    New-TestRelease -Root $faultActive -ReleaseId release-a
    New-TestRelease -Root $faultCandidate -ReleaseId release-b
    try {
        Commit-SwitchTradeWindowsRelease -Candidate $faultCandidate -Active $faultActive `
            -Previous $faultPrevious -ExpectedReleaseId release-b -FaultAfter $fault | Out-Null
        throw "fault $fault was not injected"
    } catch {
        if ([string]$_.Exception.Message -notmatch '^INJECTED_') { throw }
    }
    if ((Get-InstalledWindowsReleaseId $faultActive) -ne 'release-a' -or
        (Get-InstalledWindowsReleaseId $faultCandidate) -ne 'release-b' -or
        (Test-Path -LiteralPath $faultPrevious)) {
        throw "fault $fault left a mixed Windows release"
    }
}

$active = Join-Path $TestRoot 'active'
$previous = Join-Path $TestRoot 'previous'
$candidate = Join-Path $TestRoot 'candidate'
$transaction = Join-Path $TestRoot 'transaction.json'
New-TestRelease -Root $active -ReleaseId release-a
New-TestRelease -Root $candidate -ReleaseId release-b
New-SwitchTradeTransaction -Path $transaction -Action Update -ReleaseId release-b `
    -PriorReleaseId release-a -WindowsStage $candidate | Out-Null
Set-SwitchTradeTransactionPhase -Path $transaction -Phase windows_staged | Out-Null
$prior = Commit-SwitchTradeWindowsRelease -Candidate $candidate -Active $active `
    -Previous $previous -ExpectedReleaseId release-b
if ($prior -ne 'release-a' -or (Get-InstalledWindowsReleaseId $active) -ne 'release-b' -or
    (Get-InstalledWindowsReleaseId $previous) -ne 'release-a') {
    throw 'A to B commit did not preserve a coherent rollback pair'
}
Switch-SwitchTradeWindowsRollback -Active $active -Previous $previous `
    -ExpectedReleaseId release-a | Out-Null
if ((Get-InstalledWindowsReleaseId $active) -ne 'release-a' -or
    (Get-InstalledWindowsReleaseId $previous) -ne 'release-b') {
    throw 'B to A compensation did not restore the coherent prior pair'
}

'tampered' | Set-Content -LiteralPath (Join-Path $previous 'config.json') -Encoding UTF8
$failedClosed = $false
try {
    Switch-SwitchTradeWindowsRollback -Active $active -Previous $previous `
        -ExpectedReleaseId release-b | Out-Null
} catch {
    $failedClosed = [string]$_.Exception.Message -match 'ROLLBACK_WINDOWS_HASH_MISMATCH'
}
if (-not $failedClosed -or (Get-InstalledWindowsReleaseId $active) -ne 'release-a' -or
    (Get-InstalledWindowsReleaseId $previous) -ne 'release-b') {
    throw 'corrupt rollback validation mutated the active/retained release pair'
}

$redacted = Redact-SwitchTradeSetupText 'Authorization: Bearer abc.def reconnect_token=secret'
if ($redacted -match 'abc\.def|=secret') { throw 'setup log redaction failed' }
$usbState = '{"Devices":[{"BusId":"9-4","InstanceId":"USB\\VID_0BDA&PID_818B\\RADIO-A"},{"BusId":"1-2","InstanceId":"USB\\VID_0BDA&PID_818B\\RADIO-B"}]}' | ConvertFrom-Json
$resolved = Resolve-SwitchTradeUsbDeviceFromState -State $usbState `
    -InstanceId 'USB\VID_0BDA&PID_818B\RADIO-A' -UsbId '0bda:818b'
if ([string]$resolved.BusId -ne '9-4') { throw 'stable USB identity did not survive a bus-ID change' }
$selection = Write-SwitchTradeHardwareSelection -StateRoot $TestRoot -UsbId '0bda:818b' `
    -InstanceId 'USB\VID_0BDA&PID_818B\RADIO-A' -BusId '9-4'
$savedSelection = Get-Content -Raw -LiteralPath $selection | ConvertFrom-Json
if ([string]$savedSelection.instance_id -ne 'USB\VID_0BDA&PID_818B\RADIO-A' -or
    [string]$savedSelection.bus_id -ne '9-4') { throw 'stable USB selection was not persisted' }
Write-Host 'Setup lifecycle simulation PASS'
