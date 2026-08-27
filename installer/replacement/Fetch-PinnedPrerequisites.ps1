[CmdletBinding()]
param([string]$Destination = '')

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
if (-not $Destination) { $Destination = Join-Path $repo 'artifacts\replacement\prerequisites' }
$destinationPath = [IO.Path]::GetFullPath($Destination)
$definition = Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot 'prerequisites.json') | ConvertFrom-Json
if ([int]$definition.schema -ne 1) { throw 'Unsupported prerequisite manifest.' }

foreach ($property in $definition.packages.PSObject.Properties) {
    $package = $property.Value
    $target = [IO.Path]::GetFullPath((Join-Path $destinationPath ([string]$package.file)))
    if (-not $target.StartsWith($destinationPath.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Unsafe prerequisite path: $target"
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
    $valid = (Test-Path -LiteralPath $target -PathType Leaf) -and
        (Get-Item -LiteralPath $target).Length -eq [long]$package.size -and
        (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant() -eq [string]$package.sha256
    if (-not $valid) { Invoke-WebRequest -UseBasicParsing -Uri ([string]$package.url) -OutFile $target }
    if ((Get-Item -LiteralPath $target).Length -ne [long]$package.size -or
        (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant() -ne [string]$package.sha256) {
        throw "Pinned prerequisite verification failed: $($property.Name)"
    }
}

Write-Output $destinationPath
