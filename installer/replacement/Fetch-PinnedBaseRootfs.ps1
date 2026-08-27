[CmdletBinding()]
param([string]$Destination = '')

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$definition = Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot 'runtime\base-rootfs.json') |
    ConvertFrom-Json
if ([int]$definition.schema -ne 1) { throw 'Unsupported base-rootfs manifest.' }
if (-not $Destination) {
    $Destination = Join-Path $repo ('artifacts\replacement\inputs\' + [string]$definition.file)
}
$target = [IO.Path]::GetFullPath($Destination)
$inputs = [IO.Path]::GetFullPath((Join-Path $repo 'artifacts\replacement\inputs')).TrimEnd('\') + '\'
if (-not $target.StartsWith($inputs, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Base rootfs output must be inside replacement inputs: $target"
}
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
$valid = (Test-Path -LiteralPath $target -PathType Leaf) -and
    (Get-Item -LiteralPath $target).Length -eq [long]$definition.size -and
    (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant() -eq
        [string]$definition.sha256
if (-not $valid) {
    Invoke-WebRequest -UseBasicParsing -Uri ([string]$definition.url) -OutFile $target
}
if ((Get-Item -LiteralPath $target).Length -ne [long]$definition.size -or
    (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant() -ne
        [string]$definition.sha256) {
    throw 'Pinned Ubuntu base rootfs verification failed.'
}
Write-Output $target
