[CmdletBinding()]
param(
    [string]$Distro = "Ubuntu",
    [string[]]$UsbId = @(),
    [switch]$Prepare,
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

$profileIds = @(
    Get-Content -LiteralPath $ProfileFile | ForEach-Object {
        if ($_ -and -not $_.StartsWith('#')) { ($_ -split "`t", 2)[0].ToLowerInvariant() }
    }
)
if ($UsbId.Count -gt 0) {
    $wanted = @($UsbId | ForEach-Object { $_.ToLowerInvariant() })
    foreach ($id in $wanted) {
        if ($profileIds -notcontains $id) { Fail "USB ID $id has no hardware profile" }
    }
} else {
    $wanted = $profileIds
}

$vmware = Get-Service -Name VMUSBArbService -ErrorAction SilentlyContinue
if ($vmware -and $vmware.Status -eq 'Running') {
    if (-not $Prepare) {
        Fail "VMware USB Arbitrator is running and can reclaim a dongle; rerun elevated with -Prepare"
    }
    $principal = New-Object Security.Principal.WindowsPrincipal(
        [Security.Principal.WindowsIdentity]::GetCurrent()
    )
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Fail "-Prepare must run in an elevated PowerShell"
    }
    Stop-Service -Name VMUSBArbService -Force
    Write-Host "[windows] stopped VMware USB Arbitrator for this Windows session"
}

# Starting the distro before attachment avoids attaching to a stale WSL VM address.
& wsl.exe -d $Distro -- true
if ($LASTEXITCODE -ne 0) { Fail "WSL distro '$Distro' did not start" }

$state = usbipd state | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { Fail "usbipd state failed" }
$matched = @()
foreach ($device in $state.Devices) {
    $id = UsbId-OfDevice $device
    if ($id -and $wanted -contains $id) {
        $matched += [pscustomobject]@{ UsbId = $id; Device = $device }
    }
}

foreach ($id in $wanted) {
    $entry = @($matched | Where-Object UsbId -eq $id)
    if ($entry.Count -eq 0) {
        Fail "$id is profiled but not physically enumerated by Windows"
    }
    if ($entry.Count -gt 1) {
        Fail "multiple devices use $id; select by BUSID manually before production use"
    }
    $device = $entry[0].Device
    if (-not $device.BusId) { Fail "$id has no BUSID; unplug/replug it, then rerun" }
    if (-not $device.ClientIPAddress) {
        if (-not $Prepare) {
            Fail "$id ($($device.BusId)) is not attached to WSL; rerun elevated with -Prepare"
        }
        if (-not $device.PersistedGuid) {
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

foreach ($id in $wanted) {
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
