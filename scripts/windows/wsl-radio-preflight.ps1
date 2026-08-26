[CmdletBinding()]
param(
    [string]$Distro = "Ubuntu",
    [string[]]$UsbId = @(),
    [string]$BusId = "",
    [string]$InstanceId = "",
    [switch]$Prepare,
    [switch]$AllowVmwareStop,
    [switch]$AutoAttach,
    [switch]$AllowExperimentalHardware,
    [string]$WatcherScript = "",
    [string]$WatcherStateRoot = "",
    [string]$LifecycleScript = "",
    [string]$ProfileFile = (Join-Path $PSScriptRoot "..\..\config\wsl-radio-hardware.tsv")
)

$ErrorActionPreference = "Stop"
if (-not $LifecycleScript -or -not (Test-Path -LiteralPath $LifecycleScript -PathType Leaf)) {
    throw 'WSL radio preflight: bounded process lifecycle helper is missing'
}
. $LifecycleScript

function Fail([string]$Message) {
    throw "WSL radio preflight: $Message"
}

function Invoke-Usbipd([string[]]$Arguments) {
    $result = Invoke-BoundedNativeProcess -FilePath (Get-Command usbipd.exe).Source `
        -Arguments $Arguments -TimeoutSeconds 30
    if ($result.ExitCode -ne 0) {
        Fail "usbipd $($Arguments -join ' ') failed with exit code $($result.ExitCode): $($result.Error)"
    }
    return $result.Output
}

function UsbId-OfDevice($Device) {
    if ($Device.InstanceId -match 'VID_([0-9A-F]{4})&PID_([0-9A-F]{4})') {
        return ("{0}:{1}" -f $Matches[1], $Matches[2]).ToLowerInvariant()
    }
    return $null
}

if (-not (Test-Path -LiteralPath $ProfileFile -PathType Leaf)) {
    Fail "profile table not found: $ProfileFile"
}
if (-not (Get-Command usbipd -ErrorAction SilentlyContinue)) {
    Fail "usbipd-win is not installed or is not on PATH"
}
if ($AutoAttach -and -not $Prepare) {
    Fail "-AutoAttach requires -Prepare"
}
if ($AutoAttach -and (-not $InstanceId -or -not $WatcherScript -or -not $WatcherStateRoot)) {
    Fail "stable InstanceId and owned watcher paths are required for auto-attach"
}
$principal = New-Object Security.Principal.WindowsPrincipal(
    [Security.Principal.WindowsIdentity]::GetCurrent()
)
$isAdministrator = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

$profiles = @(
    Get-Content -LiteralPath $ProfileFile | ForEach-Object {
        if ($_ -and -not $_.StartsWith('#')) {
            $columns = @($_ -split "`t")
            if ($columns.Count -notin @(8, 12)) { Fail "invalid hardware profile row: $_" }
            [pscustomobject]@{
                UsbId = $columns[0].ToLowerInvariant()
                Status = $columns[5]
                AutoSelect = $columns[6] -eq 'yes'
                HostEngine = if ($columns.Count -eq 12) { $columns[10] } else { 'ldn' }
            }
        }
    }
)
$profileIds = @($profiles | ForEach-Object UsbId)
$wanted = @()
if ($UsbId.Count -gt 0) {
    $wanted = @($UsbId | ForEach-Object { $_.ToLowerInvariant() })
    foreach ($id in $wanted) {
        if ($profileIds -notcontains $id) { Fail "USB ID $id has no hardware profile" }
        $profile = @($profiles | Where-Object UsbId -eq $id)[0]
        if ($profile.Status -eq 'quarantined') { Fail "HARDWARE_QUARANTINED: $id cannot be used" }
        if ($profile.HostEngine -ne 'ldn') {
            Fail "HOST_ENGINE_IN_DEVELOPMENT: $($profile.HostEngine) cannot be selected"
        }
    }
}

$vmware = Get-Service -Name VMUSBArbService -ErrorAction SilentlyContinue
if ($vmware -and $vmware.Status -eq 'Running') {
    if (-not $Prepare -or -not $AllowVmwareStop) {
        Fail "VMware USB Arbitrator can reclaim this adapter. Close VMware and stop VMUSBArbService, or run Repair and approve releasing it."
    }
    if (-not $isAdministrator) { Fail "stopping VMware USB ownership requires administrator repair" }
    Stop-Service -Name VMUSBArbService -Force
    Write-Host "[windows] stopped VMware USB Arbitrator for this Windows session"
}

# Starting the distro before attachment avoids attaching to a stale WSL VM address.
$wslStart = Invoke-BoundedNativeProcess -FilePath 'wsl.exe' -Arguments @('-d', $Distro, '--', 'true') `
    -TimeoutSeconds 30
if ($wslStart.ExitCode -ne 0) { Fail "WSL distro '$Distro' did not start: $($wslStart.Error)" }

$stateResult = Invoke-BoundedNativeProcess -FilePath (Get-Command usbipd.exe).Source `
    -Arguments @('state') -TimeoutSeconds 15
if ($stateResult.ExitCode -ne 0) { Fail "usbipd state failed: $($stateResult.Error)" }
$state = $stateResult.Output | ConvertFrom-Json
$profiledDevices = @()
foreach ($device in $state.Devices) {
    $id = UsbId-OfDevice $device
    $profile = @($profiles | Where-Object UsbId -eq $id)
    if ($id -and $profile.Count -eq 1) {
        $profiledDevices += [pscustomobject]@{
            UsbId = $id
            AutoSelect = $profile[0].AutoSelect
            Status = $profile[0].Status
            HostEngine = $profile[0].HostEngine
            Device = $device
        }
    }
}

if ($BusId) {
    $matched = @($profiledDevices | Where-Object { $_.Device.BusId -eq $BusId })
    if ($matched.Count -eq 0) { Fail "BUSID $BusId is not a physically enumerated profiled radio" }
    if ($wanted.Count -gt 0 -and $wanted -notcontains $matched[0].UsbId) {
        Fail "BUSID $BusId is $($matched[0].UsbId), not one of the requested USB IDs"
    }
    if ($InstanceId -and [string]$matched[0].Device.InstanceId -cne $InstanceId) {
        Fail "BUSID $BusId no longer belongs to the selected stable device identity"
    }
} elseif ($wanted.Count -gt 0) {
    $matched = @($profiledDevices | Where-Object { $wanted -contains $_.UsbId })
    foreach ($id in $wanted) {
        $count = @($matched | Where-Object UsbId -eq $id).Count
        if ($count -eq 0) { Fail "$id is profiled but not physically enumerated by Windows" }
        if ($count -gt 1) { Fail "multiple devices use $id; rerun with -BusId from 'usbipd list'" }
    }
} else {
    $matched = @($profiledDevices | Where-Object AutoSelect)
    if ($matched.Count -eq 0) { Fail "no auto-selectable profiled radio is physically enumerated" }
    if ($matched.Count -gt 1) { Fail "multiple auto-selectable radios are present; rerun with -BusId" }
}

foreach ($entry in $matched) {
    $id = $entry.UsbId
    $device = $entry.Device
    if ($entry.Status -eq 'quarantined') {
        Fail "HARDWARE_QUARANTINED: $id cannot be prepared for a trading attempt"
    }
    if ($entry.HostEngine -ne 'ldn') {
        Fail "HOST_ENGINE_IN_DEVELOPMENT: $($entry.HostEngine) cannot be selected"
    }
    if (-not $device.BusId) { Fail "$id has no BUSID; unplug/replug it, then rerun" }
    if (-not $device.ClientIPAddress) {
        if (-not $Prepare) {
            Fail "$id ($($device.BusId)) is not attached to WSL; rerun elevated with -Prepare"
        }
        if (-not $device.PersistedGuid) {
            if (-not $isAdministrator) {
                Fail "$id ($($device.BusId)) is not bound. Run SwitchTrade Setup Repair once as administrator."
            }
            Invoke-Usbipd @('bind', '--busid', [string]$device.BusId)
        }
        Invoke-Usbipd @('attach', '--wsl', '--busid', [string]$device.BusId)
    }
    if ($AutoAttach) {
        $busId = [string]$device.BusId
        $watcherState = Join-Path $WatcherStateRoot 'usb-watcher.json'
        $watcherReady = $false
        if (Test-Path -LiteralPath $watcherState -PathType Leaf) {
            try {
                $saved = Get-Content -Raw -LiteralPath $watcherState | ConvertFrom-Json
                $savedProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $([int]$saved.pid)" `
                    -ErrorAction SilentlyContinue
                $watcherReady = $savedProcess -and [string]$saved.instance_id -ceq $InstanceId -and
                    [string]$savedProcess.CommandLine -match [regex]::Escape([IO.Path]::GetFullPath($WatcherScript)) -and
                    [string]$savedProcess.CommandLine -match [regex]::Escape([IO.Path]::GetFullPath($watcherState))
            } catch { }
            if (-not $watcherReady) { Stop-SwitchTradeUsbWatcher -StateRoot $WatcherStateRoot | Out-Null }
        }
        if (-not $watcherReady) {
            $start = New-Object Diagnostics.ProcessStartInfo
            $start.FileName = 'powershell.exe'
            $start.Arguments = ((@('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File',
                $WatcherScript, '-Distro', $Distro, '-InstanceId', $InstanceId, '-StateFile', $watcherState) |
                ForEach-Object { ConvertTo-NativeCommandLineArgument ([string]$_) }) -join ' ')
            $start.UseShellExecute = $false
            $start.CreateNoWindow = $true
            $proc = [Diagnostics.Process]::Start($start)
            for ($attempt = 0; $attempt -lt 20 -and -not (Test-Path -LiteralPath $watcherState); $attempt++) {
                if ($proc.HasExited) { break }
                Start-Sleep -Milliseconds 100
            }
            if ($proc.HasExited -or -not (Test-Path -LiteralPath $watcherState)) {
                Fail "stable auto-attach watcher did not start for $id"
            }
            Write-Host "[windows] stable auto-attach watcher pid=$($proc.Id) usb=$id instance=$InstanceId busid=$busId"
        } else {
            Write-Host "[windows] stable auto-attach watcher already running usb=$id instance=$InstanceId"
        }
    }
}

$kernelResult = Invoke-BoundedNativeProcess -FilePath 'wsl.exe' `
    -Arguments @('-d', $Distro, '--', 'uname', '-r') -TimeoutSeconds 30
$kernel = $kernelResult.Output.Trim()
if ($kernelResult.ExitCode -ne 0 -or $kernel -notmatch 'microsoft') {
    Fail "'$Distro' is not running a WSL kernel"
}
Write-Host "[wsl] kernel=$kernel"

foreach ($id in @($matched | ForEach-Object UsbId | Select-Object -Unique)) {
    $seenResult = Invoke-BoundedNativeProcess -FilePath 'wsl.exe' `
        -Arguments @('-d', $Distro, '--', 'lsusb', '-d', $id) -TimeoutSeconds 30
    $seen = $seenResult.Output.Trim()
    if ($seenResult.ExitCode -ne 0 -or -not $seen) {
        Fail "$id is attached in usbipd but absent from lsusb inside '$Distro'"
    }
    Write-Host "[wsl] PASS usb=$id $seen"
}

if ($vmware) {
    $current = Get-Service -Name VMUSBArbService
    Write-Host "[windows] VMUSBArbService=$($current.Status) startType=$($current.StartType)"
}
Write-Host "WSL radio ownership preflight PASS"
