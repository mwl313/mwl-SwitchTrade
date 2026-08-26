Set-StrictMode -Version Latest

function Test-SwitchTradeWindowsHost {
    param(
        [Parameter(Mandatory)][int]$Build,
        [Parameter(Mandatory)][int]$ProductType,
        [Parameter(Mandatory)][string]$Architecture
    )
    return $ProductType -eq 1 -and $Architecture -eq 'X64' -and $Build -ge 19045
}
