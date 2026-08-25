[CmdletBinding()]
param(
    [string]$Distro = "Ubuntu",
    [string[]]$UsbId = @(),
    [string]$BusId = "",
    [switch]$Prepare,
    [switch]$AllowVmwareStop,
    [switch]$AutoAttach,
    [string]$ProfileFile = (Join-Path $PSScriptRoot "..\..\config\wsl-radio-hardware.tsv")
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    throw "WSL radio preflight: $Message"
}

function Invoke-Usbipd([string[]]$Arguments) {
    & usbipd @Arguments
    if ($LASTEXITCODE -ne 0) {
        Fail "usbipd $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
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
$principal = New-Object Security.Principal.WindowsPrincipal(
    [Security.Principal.WindowsIdentity]::GetCurrent()
)
$isAdministrator = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

$profiles = @(
    Get-Content -LiteralPath $ProfileFile | ForEach-Object {
        if ($_ -and -not $_.StartsWith('#')) {
            $columns = @($_ -split "`t", 8)
            if ($columns.Count -ne 8) { Fail "invalid hardware profile row: $_" }
            [pscustomobject]@{
                UsbId = $columns[0].ToLowerInvariant()
                Status = $columns[5]
                AutoSelect = $columns[6] -eq 'yes'
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
& wsl.exe -d $Distro -- true
if ($LASTEXITCODE -ne 0) { Fail "WSL distro '$Distro' did not start" }

$state = usbipd state | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { Fail "usbipd state failed" }
$profiledDevices = @()
foreach ($device in $state.Devices) {
    $id = UsbId-OfDevice $device
    $profile = @($profiles | Where-Object UsbId -eq $id)
    if ($id -and $profile.Count -eq 1) {
        $profiledDevices += [pscustomobject]@{
            UsbId = $id
            AutoSelect = $profile[0].AutoSelect
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
        $existing = @(Get-CimInstance Win32_Process -Filter "Name = 'usbipd.exe'" |
            Where-Object { $_.CommandLine -match '--auto-attach' -and
                           $_.CommandLine -match ("--busid\s+" + [regex]::Escape($busId)) })
        if ($existing.Count -eq 0) {
            $proc = Start-Process -FilePath (Get-Command usbipd).Source -WindowStyle Hidden -PassThru `
                -ArgumentList @('attach', "--wsl=$Distro", '--busid', $busId, '--auto-attach')
            Start-Sleep -Milliseconds 500
            if ($proc.HasExited) { Fail "usbipd auto-attach exited early for $id ($busId)" }
            Write-Host "[windows] auto-attach watcher pid=$($proc.Id) usb=$id busid=$busId"
        } else {
            Write-Host "[windows] auto-attach watcher already running usb=$id busid=$busId"
        }
    }
}

$kernel = (& wsl.exe -d $Distro -- uname -r).Trim()
if ($LASTEXITCODE -ne 0 -or $kernel -notmatch 'microsoft') {
    Fail "'$Distro' is not running a WSL kernel"
}
Write-Host "[wsl] kernel=$kernel"

foreach ($id in @($matched | ForEach-Object UsbId | Select-Object -Unique)) {
    $seen = & wsl.exe -d $Distro -- sh -c "lsusb -d '$id' 2>/dev/null"
    if ($LASTEXITCODE -ne 0 -or -not $seen) {
        Fail "$id is attached in usbipd but absent from lsusb inside '$Distro'"
    }
    Write-Host "[wsl] PASS usb=$id $seen"
}

if ($vmware) {
    $current = Get-Service -Name VMUSBArbService
    Write-Host "[windows] VMUSBArbService=$($current.Status) startType=$($current.StartType)"
}
Write-Host "WSL radio ownership preflight PASS"
