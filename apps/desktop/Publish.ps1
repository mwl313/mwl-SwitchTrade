[CmdletBinding()]
param([string]$Output = '')

$ErrorActionPreference = 'Stop'
$Repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
if (-not $Output) { $Output = Join-Path $Repo 'artifacts\native\SwitchTrade' }
$Project = Join-Path $PSScriptRoot 'SwitchTrade.Desktop\SwitchTrade.Desktop.csproj'

dotnet publish $Project -c Release -r win-x64 --self-contained true `
    -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true `
    -p:EnableCompressionInSingleFile=true -p:DebugType=None -p:DebugSymbols=false `
    -o $Output
if ($LASTEXITCODE -ne 0) { throw 'native desktop publish failed' }

$files = @(Get-ChildItem -LiteralPath $Output -File)
if ($files.Count -ne 1 -or $files[0].Name -ne 'SwitchTrade.exe') {
    throw "expected one self-contained SwitchTrade.exe in $Output"
}
& $files[0].FullName --self-test
if ($LASTEXITCODE -ne 0) { throw 'native desktop self-test failed' }
Write-Host $files[0].FullName
