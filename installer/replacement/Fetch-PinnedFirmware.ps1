[CmdletBinding()]
param(
    [string]$Destination = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
if (-not $Destination) {
    $Destination = Join-Path $repo 'artifacts\replacement\firmware'
}
$destinationPath = [IO.Path]::GetFullPath($Destination)
$manifestPath = Join-Path $PSScriptRoot 'runtime\firmware-manifest.sha256'

$linuxFirmwareCommit = '01205307636157a12c29e6a774bf83b218732050'
$regulatoryCommit = '74cb99ff3853e0092d909a8b8afeadea88dfd16b'
$items = @(
    @{ Relative = 'regulatory.db'; Url = "https://kernel.googlesource.com/pub/scm/linux/kernel/git/wens/wireless-regdb/+/$regulatoryCommit/regulatory.db?format=TEXT" },
    @{ Relative = 'regulatory.db.p7s'; Url = "https://kernel.googlesource.com/pub/scm/linux/kernel/git/wens/wireless-regdb/+/$regulatoryCommit/regulatory.db.p7s?format=TEXT" },
    @{ Relative = 'rtlwifi/rtl8188eufw.bin'; Url = "https://kernel.googlesource.com/pub/scm/linux/kernel/git/firmware/linux-firmware/+/$linuxFirmwareCommit/rtlwifi/rtl8188eufw.bin?format=TEXT" },
    @{ Relative = 'rtlwifi/rtl8192eu_nic.bin'; Url = "https://kernel.googlesource.com/pub/scm/linux/kernel/git/firmware/linux-firmware/+/$linuxFirmwareCommit/rtlwifi/rtl8192eu_nic.bin?format=TEXT" }
)
$expected = @{}
foreach ($line in Get-Content -LiteralPath $manifestPath) {
    if ($line -match '^([0-9a-f]{64})\s+firmware/(.+)$') { $expected[$Matches[2]] = $Matches[1] }
}
if ($expected.Count -ne $items.Count) { throw 'Pinned firmware manifest is incomplete.' }

foreach ($item in $items) {
    $relative = [string]$item.Relative
    $target = [IO.Path]::GetFullPath((Join-Path $destinationPath $relative))
    if (-not $target.StartsWith($destinationPath.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Unsafe firmware target: $target"
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
    $encoded = (Invoke-WebRequest -UseBasicParsing -Uri ([string]$item.Url)).Content.Trim()
    [IO.File]::WriteAllBytes($target, [Convert]::FromBase64String($encoded))
    $actual = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $expected[$relative]) { throw "Pinned firmware hash mismatch: $relative" }
}

Write-Output $destinationPath
