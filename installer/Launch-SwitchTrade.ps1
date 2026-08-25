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

function Test-Administrator {
    $principal = New-Object Security.Principal.WindowsPrincipal(
        [Security.Principal.WindowsIdentity]::GetCurrent()
    )
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Quote-Argument([string]$Value) {
    return '"' + $Value.Replace('"', '\"') + '"'
}

if (-not (Test-Administrator)) {
    $arguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Quote-Argument $PSCommandPath),
        '-Distro', (Quote-Argument $Distro))
    if ($RelayUrl) { $arguments += @('-RelayUrl', (Quote-Argument $RelayUrl)) }
    if ($BusId) { $arguments += @('-BusId', (Quote-Argument $BusId)) }
    if ($UsbId) { $arguments += @('-UsbId', (Quote-Argument $UsbId)) }
    if ($NoBrowser) { $arguments += '-NoBrowser' }
    Start-Process powershell.exe -Verb RunAs -WindowStyle Hidden -ArgumentList $arguments
    exit
}

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
    $processes += Start-Process wsl.exe -WindowStyle Hidden -PassThru -ArgumentList @(
        '-d', $Distro, '-u', 'root', '--cd', '/opt/switchtrade', '--',
        $python, '-m', 'uvicorn', 'relay.server:app', '--host', '127.0.0.1', '--port', '8788'
    )
}
$processes += Start-Process wsl.exe -WindowStyle Hidden -PassThru -ArgumentList @(
    '-d', $Distro, '-u', 'root', '--cd', '/opt/switchtrade', '--',
    'env', "SWITCHTRADE_RELAY_URL=$RelayUrl", $python, '-m', 'switchtrade.control'
)

$ready = $false
for ($attempt = 0; $attempt -lt 40; $attempt++) {
    try {
        $response = Invoke-RestMethod -Uri "http://127.0.0.1:8787/api/status" -TimeoutSec 2
        if ($response.status) { $ready = $true; break }
    } catch {
        Start-Sleep -Milliseconds 500
    }
}
if (-not $ready) {
    $processes | Where-Object { -not $_.HasExited } | Stop-Process -Force
    throw "SwitchTrade control service did not become ready."
}

if (-not $NoBrowser) { Start-Process "http://127.0.0.1:8787/" }
Write-Host "SwitchTrade is ready at http://127.0.0.1:8787/"
