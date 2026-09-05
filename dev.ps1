[CmdletBinding()]
param(
    [Parameter(Position = 0)][string]$Command = 'help',
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments
)

$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'scripts/dev/DevOverlay.psm1') -Force

function Remove-ArgumentMarker {
    param([string[]]$Values)
    if ($Values.Count -gt 0 -and $Values[0] -eq '--') { return @($Values | Select-Object -Skip 1) }
    return @($Values)
}

try {
    switch ($Command.ToLowerInvariant()) {
        'doctor' { Invoke-DevDoctor; exit 0 }
        'sync' { Invoke-DevSync; exit 0 }
        'run' {
            $runArguments = Remove-ArgumentMarker $Arguments
            if ($runArguments.Count -gt 0 -and $runArguments[0] -in @('host', 'join')) {
                $runArguments = @('-m', 'switchtrade.core_cli') + $runArguments
            }
            exit (Invoke-DevRun -Arguments $runArguments)
        }
        'test' { exit (Invoke-DevRun -Arguments (Remove-ArgumentMarker $Arguments) -Test) }
        'clean' { Invoke-DevClean; exit 0 }
        default {
            Write-Output '.\dev.ps1 doctor | sync | run -- <arguments> | test -- <pytest arguments> | clean'
            exit 0
        }
    }
} catch [DevOverlayException] {
    [Console]::Error.WriteLine("$($_.Exception.Code): $($_.Exception.Message)")
    exit 1
} catch {
    [Console]::Error.WriteLine("DEV_RUN_FAILED: $($_.Exception.Message)")
    exit 1
}
