[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [switch]$Apply,
    [string]$ArtifactsRoot = (Join-Path (Split-Path -Parent $PSScriptRoot) 'artifacts'),
    [string]$ReviewedPreview = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-TreeInfo {
    param([Parameter(Mandatory)][string]$Path)

    if (Test-Path -LiteralPath $Path -PathType Leaf) {
        $item = Get-Item -LiteralPath $Path -Force
        return [ordered]@{
            size_bytes = [long]$item.Length
            sha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    }

    $files = @(Get-ChildItem -LiteralPath $Path -File -Recurse -Force | Sort-Object FullName)
    $lines = foreach ($file in $files) {
        $relative = [IO.Path]::GetRelativePath($Path, $file.FullName).Replace('\', '/')
        $hash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        "$relative`t$hash`t$($file.Length)"
    }
    $payload = [Text.Encoding]::UTF8.GetBytes(($lines -join "`n"))
    $digest = [Security.Cryptography.SHA256]::HashData($payload)
    [long]$treeBytes = 0
    foreach ($file in $files) { $treeBytes += $file.Length }
    return [ordered]@{
        size_bytes = $treeBytes
        sha256 = [Convert]::ToHexString($digest).ToLowerInvariant()
    }
}

function Assert-ArtifactPath {
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][string]$Path
    )

    $resolvedRoot = [IO.Path]::GetFullPath($Root).TrimEnd('\')
    $resolved = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    if (-not $resolved.StartsWith("$resolvedRoot\", [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing path outside artifacts: $resolved"
    }
    $item = Get-Item -LiteralPath $resolved -Force
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Refusing reparse point: $resolved"
    }
    if ($item.PSIsContainer) {
        $pending = [Collections.Generic.Stack[string]]::new()
        $pending.Push($resolved)
        while ($pending.Count -gt 0) {
            foreach ($entry in Get-ChildItem -LiteralPath $pending.Pop() -Force) {
                if (($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                    throw "Refusing tree containing a reparse point: $($entry.FullName)"
                }
                if ($entry.PSIsContainer) { $pending.Push($entry.FullName) }
            }
        }
    }
    return $resolved
}

$root = [IO.Path]::GetFullPath($ArtifactsRoot).TrimEnd('\')
if (-not (Test-Path -LiteralPath $root -PathType Container)) {
    throw "Artifacts directory does not exist: $root"
}

$retained = [ordered]@{
    'final-package-27d17b1' = 'Authoritative legacy rootfs, kernel, modules, and usbipd source bundle'
    'audit-wheelhouse-linux-cp312' = 'Locked Linux wheel source for immutable runtime construction'
    'SwitchTrade-unsigned-private-beta-91f5a3e.zip' = 'Latest legacy installer migration fixture'
    'SwitchTrade-capture-evidence-20260827' = 'Validated capture evidence'
    'SwitchTrade-capture-evidence-20260827.zip' = 'Portable capture evidence bundle'
    'SwitchTrade-capture-evidence-20260827.zip.sha256' = 'Capture evidence integrity record'
    'audit-local-relay.sqlite3' = 'Project database; never delete during build cleanup'
}

$retainedRows = foreach ($entry in $retained.GetEnumerator()) {
    $path = Join-Path $root $entry.Key
    if (-not (Test-Path -LiteralPath $path)) { continue }
    $safe = Assert-ArtifactPath -Root $root -Path $path
    $info = Get-TreeInfo -Path $safe
    [pscustomobject][ordered]@{
        name = $entry.Key
        size_bytes = $info.size_bytes
        sha256 = $info.sha256
        reason = $entry.Value
        owner = 'SwitchTrade replacement installer'
    }
}

$exactNames = @(
    'release-candidates', 'native', 'native-beta', 'win10support',
    'installer-overhaul-dafb92a-a', 'installer-overhaul-dafb92a-b',
    'installer-overhaul-dafb92a-verified',
    'installer-commandfix-836100b-a', 'installer-commandfix-836100b-b',
    'installer-commandfix-836100b-verified',
    'installer-commandfix-921a839-a', 'installer-commandfix-921a839-b',
    'installer-commandfix-921a839-verified',
    'final-package-extract-47a69d2-v1', 'qa-expanded-91f5a3e',
    'SwitchTrade-unsigned-private-beta-91f5a3e',
    'preflight-final', 'preflight-commit', 'native-beta',
    'desktop-startup-smoke', 'setup-progress-smoke', 'rootfs-marker-fixed',
    'stitch-ui-reference-20260826', 'qa'
)
$prefixes = @(
    'final-package-', 'final-native-', 'validation-', 'transaction-call-probe-',
    'repair-entry-probe-', 'test-kernel-lifecycle', 'audit-kernel-', 'audit-setup-',
    'final-kernel-', 'final-ps5-', 'final-ps7-', 'final-rollback-', 'final-setup-',
    'final2-', 'setup-lifecycle-', 'lifecycle-final-', 'marker-final-',
    'marker-recovery-', 'launcher-smoke', 'kernel-start-probe'
)

$candidates = foreach ($item in Get-ChildItem -LiteralPath $root -Force) {
    if ($retained.Contains($item.Name)) { continue }
    $selected = $exactNames -contains $item.Name
    if (-not $selected) {
        $selected = @($prefixes | Where-Object { $item.Name.StartsWith($_, [StringComparison]::OrdinalIgnoreCase) }).Count -gt 0
    }
    if (-not $selected) { continue }
    $safe = Assert-ArtifactPath -Root $root -Path $item.FullName
    $bytes = if ($item.PSIsContainer) {
        [long]$directoryBytes = 0
        foreach ($file in Get-ChildItem -LiteralPath $safe -File -Recurse -Force) {
            $directoryBytes += $file.Length
        }
        $directoryBytes
    } else { [long]$item.Length }
    [pscustomobject][ordered]@{ name = $item.Name; path = $safe; size_bytes = $bytes }
}
$replacementRoot = Join-Path $root 'replacement'
$replacementGenerated = @(
    'build-script-test', 'package-chain-validation', 'latest-desktop-selftest',
    'latest-provisioner', 'latest-lifecycle', 'layout-validation', 'sources', 'prototype'
)
$replacementCandidates = if (Test-Path -LiteralPath $replacementRoot -PathType Container) {
    foreach ($name in $replacementGenerated) {
        $path = Join-Path $replacementRoot $name
        if (-not (Test-Path -LiteralPath $path)) { continue }
        $safe = Assert-ArtifactPath -Root $root -Path $path
        [long]$bytes = 0
        foreach ($file in Get-ChildItem -LiteralPath $safe -File -Recurse -Force) {
            $bytes += $file.Length
        }
        [pscustomobject][ordered]@{
            name = "replacement/$name"; path = $safe; size_bytes = $bytes
        }
    }
}
$candidates = @(@($candidates) + @($replacementCandidates) | Sort-Object name)

$targetText = ($candidates | ForEach-Object { "$($_.name)`t$($_.size_bytes)" }) -join "`n"
$targetHash = [Convert]::ToHexString(
    [Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($targetText))
).ToLowerInvariant()
[long]$totalBytes = 0
foreach ($candidate in $candidates) { $totalBytes += $candidate.size_bytes }
$preview = [ordered]@{
    schema = 1
    created_utc = [DateTimeOffset]::UtcNow.ToString('O')
    artifacts_root = $root
    targets_sha256 = $targetHash
    total_bytes = $totalBytes
    targets = $candidates
}
$retainedPath = Join-Path $root 'retained-inputs-manifest.json'
$previewPath = Join-Path $root 'cleanup-preview.json'

if (-not $Apply) {
    $retainedRows | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $retainedPath -Encoding utf8
    $preview | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $previewPath -Encoding utf8
    Write-Host "Preview only. Review: $previewPath"
    Write-Host ("Would remove {0} targets ({1:N2} GiB)." -f $candidates.Count, ($preview.total_bytes / 1GB))
    $candidates | Select-Object name, @{n='GiB';e={[math]::Round($_.size_bytes / 1GB, 3)}} | Format-Table -AutoSize
    return
}

if (-not $ReviewedPreview) {
    throw 'Apply requires -ReviewedPreview pointing to the previously reviewed cleanup-preview.json.'
}
$reviewPath = [IO.Path]::GetFullPath($ReviewedPreview)
$review = Get-Content -Raw -LiteralPath $reviewPath | ConvertFrom-Json
if ([string]$review.artifacts_root -cne $root -or [string]$review.targets_sha256 -cne $targetHash) {
    throw 'Cleanup targets changed after preview. Run preview again and review the new manifest.'
}

foreach ($candidate in $candidates) {
    $safe = Assert-ArtifactPath -Root $root -Path $candidate.path
    if ($PSCmdlet.ShouldProcess($safe, 'Remove generated build artifact')) {
        Remove-Item -LiteralPath $safe -Recurse -Force
    }
}
Write-Host ("Removed {0} reviewed targets ({1:N2} GiB)." -f $candidates.Count, ($preview.total_bytes / 1GB))
