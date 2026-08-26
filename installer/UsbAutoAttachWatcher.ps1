[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Distro,
    [Parameter(Mandatory)][ValidateLength(1, 512)][string]$InstanceId,
    [Parameter(Mandatory)][string]$StateFile
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'SetupLifecycle.ps1')
$StateFile = [IO.Path]::GetFullPath($StateFile)
$stateRoot = Split-Path -Parent $StateFile
New-Item -ItemType Directory -Force -Path $stateRoot | Out-Null
$algorithm = [Security.Cryptography.SHA256]::Create()
try { $identityBytes = $algorithm.ComputeHash([Text.Encoding]::UTF8.GetBytes($StateFile)) }
finally { $algorithm.Dispose() }
$identityHash = [BitConverter]::ToString($identityBytes).Replace('-', '').Substring(0, 16)
$created = $false
$mutex = New-Object Threading.Mutex($true, "Global\SwitchTrade.UsbWatcher.$identityHash", [ref]$created)
if (-not $created) { exit 0 }

try {
    $state = [ordered]@{
        schema = 1; pid = $PID; instance_id = $InstanceId; distro = $Distro
        current_bus_id = ''; last_error = ''; updated_utc = [DateTime]::UtcNow.ToString('o')
    }
    Write-AtomicJson -Path $StateFile -Value $state
    while (Test-Path -LiteralPath $StateFile -PathType Leaf) {
        try {
            $probe = Invoke-BoundedNativeProcess -FilePath 'usbipd.exe' -Arguments @('state') -TimeoutSeconds 15
            if ($probe.ExitCode -ne 0) { throw "usbipd state exit $($probe.ExitCode)" }
            $usbState = $probe.Output | ConvertFrom-Json
            $device = @($usbState.Devices | Where-Object { [string]$_.InstanceId -ceq $InstanceId }) |
                Select-Object -First 1
            if ($device) {
                $state.current_bus_id = [string]$device.BusId
                if (-not $device.ClientIPAddress) {
                    if (-not $device.PersistedGuid) { throw 'selected adapter is no longer bound' }
                    $attach = Invoke-BoundedNativeProcess -FilePath 'usbipd.exe' `
                        -Arguments @('attach', "--wsl=$Distro", '--busid', [string]$device.BusId) `
                        -TimeoutSeconds 30
                    if ($attach.ExitCode -ne 0) { throw "usbipd attach exit $($attach.ExitCode): $($attach.Error)" }
                }
                $state.last_error = ''
            } else {
                $state.current_bus_id = ''
                $state.last_error = 'USB_DEVICE_INSTANCE_NOT_FOUND'
            }
        } catch {
            $state.last_error = [string]$_.Exception.Message
        }
        $state.updated_utc = [DateTime]::UtcNow.ToString('o')
        Write-AtomicJson -Path $StateFile -Value $state
        Start-Sleep -Seconds 3
    }
} finally {
    try { $mutex.ReleaseMutex() } catch { }
    $mutex.Dispose()
}
