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
            $runArguments = @(Remove-ArgumentMarker $Arguments)
            if ($runArguments.Count -gt 0 -and $runArguments[0] -in @('host', 'join')) {
                $mode = $runArguments[0]
                $runArguments = @(Resolve-DevCoreArguments -Arguments $runArguments)
                exit (Invoke-DevRun -Arguments $runArguments -CoreCli -CoreRole $mode)
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
} catch {
    # Import-Module does not export PowerShell class names into this script's
    # type scope. A typed catch would mask the original failure on this route.
    $errorCode = if ($_.Exception.GetType().Name -eq 'DevOverlayException') {
        $_.Exception.Code
    } else { 'DEV_RUN_FAILED' }
    [Console]::Error.WriteLine("${errorCode}: $($_.Exception.Message)")
    exit 1
}
