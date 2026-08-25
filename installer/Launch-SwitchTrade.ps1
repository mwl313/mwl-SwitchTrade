[CmdletBinding()]
param(
    [string]$Distro = "SwitchTrade",
    [string]$RelayUrl = "",
    [string]$BusId = "",
    [string]$UsbId = "",
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$InstallRoot = Split-Path -Parent $PSScriptRoot
$AppRoot = Join-Path $InstallRoot "app"
$ProfileFile = Join-Path $AppRoot "config\wsl-radio-hardware.tsv"
$Preflight = Join-Path $AppRoot "scripts\windows\wsl-radio-preflight.ps1"
$ConfigFile = Join-Path $InstallRoot "config.json"
$ExpectedReadinessContract = "app-readiness.v1"

function Get-ControlReadiness {
    try {
        return Invoke-RestMethod -Uri "http://127.0.0.1:8787/api/v1/app/readiness" -TimeoutSec 1
    } catch {
        return $null
    }
}

$existing = Get-ControlReadiness
if ($existing -and $existing.contract_version -eq $ExpectedReadinessContract) {
    if (-not $NoBrowser) { Start-Process "http://127.0.0.1:8787/" }
    exit 0
}

$created = $false
$launchMutex = New-Object System.Threading.Mutex($true, "Local\SwitchTrade.RuntimeLauncher", [ref]$created)
if (-not $created) {
    if (-not $launchMutex.WaitOne(15000)) {
        throw "Another SwitchTrade startup is still running. Try again."
    }
}

try {

if (-not (Test-Path -LiteralPath $Preflight -PathType Leaf)) {
    throw "SwitchTrade installation is incomplete: $Preflight"
}

if (-not $RelayUrl -and (Test-Path -LiteralPath $ConfigFile -PathType Leaf)) {
    $configuration = Get-Content -Raw -LiteralPath $ConfigFile | ConvertFrom-Json
    $RelayUrl = [string]$configuration.relay_url
}
if (-not $RelayUrl) { $RelayUrl = "http://127.0.0.1:8788" }

$preflightArguments = @('-Distro', $Distro, '-ProfileFile', $ProfileFile, '-Prepare', '-AutoAttach')
if ($BusId) { $preflightArguments += @('-BusId', $BusId) }
if ($UsbId) { $preflightArguments += @('-UsbId', $UsbId) }
& $Preflight @preflightArguments

$python = "/opt/switchtrade/bridge/.venv/bin/python"
$processes = @()
if ($RelayUrl -match '^http://(127\.0\.0\.1|localhost):8788/?$') {
    $relayReady = $false
    try {
        $relay = Invoke-RestMethod -Uri "http://127.0.0.1:8788/health" -TimeoutSec 1
        $relayReady = $relay.status -eq "ready"
    } catch { }
    if (-not $relayReady) {
        $processes += Start-Process wsl.exe -WindowStyle Hidden -PassThru -ArgumentList @(
            '-d', $Distro, '-u', 'root', '--cd', '/opt/switchtrade', '--',
            'env', 'SWITCHTRADE_ALLOW_PROCESS_SHUTDOWN=1', $python, '-m', 'relay.server'
        )
    }
}
$existing = Get-ControlReadiness
if (-not $existing) {
    $processes += Start-Process wsl.exe -WindowStyle Hidden -PassThru -ArgumentList @(
        '-d', $Distro, '-u', 'root', '--cd', '/opt/switchtrade', '--',
        'env', "SWITCHTRADE_RELAY_URL=$RelayUrl", 'SWITCHTRADE_ALLOW_PROCESS_SHUTDOWN=1',
        $python, '-m', 'switchtrade.control'
    )
}

$ready = $false
for ($attempt = 0; $attempt -lt 40; $attempt++) {
    $response = Get-ControlReadiness
    if ($response -and $response.contract_version -eq $ExpectedReadinessContract -and $response.compatible) {
        $ready = $true
        break
    }
    Start-Sleep -Milliseconds 500
}
if (-not $ready) {
    $processes | Where-Object { -not $_.HasExited } | Stop-Process -Force
    throw "SwitchTrade control service did not become ready."
}

if (-not $NoBrowser) { Start-Process "http://127.0.0.1:8787/" }
Write-Host "SwitchTrade is ready at http://127.0.0.1:8787/"
} finally {
    try { $launchMutex.ReleaseMutex() } catch { }
    $launchMutex.Dispose()
}
