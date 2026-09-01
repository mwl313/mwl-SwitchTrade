[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$PackageDirectory,
    [switch]$RunDisposableWslLifecycle
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath($PackageDirectory)
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$resultPath = Join-Path $root 'build-result.json'
$setup = Join-Path $root 'SwitchTradeSetup.exe'
$manifestPath = Join-Path $root 'package\release-manifest.json'
foreach ($path in @($resultPath, $setup, $manifestPath)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing package artifact: $path" }
}
$result = Get-Content -Raw -LiteralPath $resultPath | ConvertFrom-Json
$applicationVersion = (Get-Content -Raw -LiteralPath (
    Join-Path $repo 'switchtrade\VERSION')).Trim()
$versionMatch = [regex]::Match(
    $applicationVersion, '^(\d+)\.(\d+)\.(\d+)(?:-[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*)?$')
if (-not $versionMatch.Success) { throw 'switchtrade/VERSION is invalid.' }
$productVersion = "$($versionMatch.Groups[1].Value).$($versionMatch.Groups[2].Value).$($versionMatch.Groups[3].Value)"
if ([long]$result.size -ne (Get-Item -LiteralPath $setup).Length -or
    [string]$result.sha256 -ne (Get-FileHash -LiteralPath $setup -Algorithm SHA256).Hash.ToLowerInvariant()) {
    throw 'Setup EXE does not match build-result.json.'
}
if ($result.PSObject.Properties.Name -notcontains 'qualification' -or
    [string]$result.qualification.contract_version -ne 'm7-qualification-kit-build.v1' -or
    [string]$result.qualification.release_id -ne [string]$result.release_id -or
    [string]$result.qualification.source_sha -notmatch '^[0-9a-f]{40}$' -or
    [string]$result.qualification.release_id -ne
        "beta-$(([string]$result.qualification.source_sha).Substring(0, 12))") {
    throw 'Qualification build identity is missing or invalid.'
}
$qualificationArchive = [IO.Path]::GetFullPath((Join-Path $root ([string]$result.qualification.archive)))
if (-not $qualificationArchive.StartsWith($root.TrimEnd('\') + '\',
        [StringComparison]::OrdinalIgnoreCase) -or
    -not (Test-Path -LiteralPath $qualificationArchive -PathType Leaf) -or
    [long]$result.qualification.size -ne (Get-Item -LiteralPath $qualificationArchive).Length -or
    [string]$result.qualification.sha256 -ne
        (Get-FileHash -LiteralPath $qualificationArchive -Algorithm SHA256).Hash.ToLowerInvariant()) {
    throw 'Qualification archive does not match build-result.json.'
}
$manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
if ([string]$result.version -ne $applicationVersion -or
    [string]$result.product_version -ne $productVersion -or
    [string]$result.release_tag -ne "v$applicationVersion" -or
    [string]$manifest.version -ne $applicationVersion) {
    throw 'Release, installer, and application versions do not share switchtrade/VERSION.'
}
$expectedProfiles = @()
$expectedModules = @()
foreach ($line in Get-Content -LiteralPath (Join-Path $repo 'config\wsl-radio-hardware.tsv')) {
    if (-not $line -or $line.StartsWith('#')) { continue }
    $columns = @($line -split "`t")
    if ($columns.Count -ne 13 -or $columns[6] -ne 'yes') {
        throw 'The source hardware matrix is malformed or not fully auto-eligible.'
    }
    $expectedProfiles += $columns[0]
    $expectedModules += @($columns[3] -split ',')
}
$expectedProfiles = @($expectedProfiles | Sort-Object -Unique)
$expectedModules = @($expectedModules | Sort-Object -Unique)
$packagedProfiles = @($manifest.kernel.driver_profiles | Sort-Object -Unique)
$packagedModules = @($manifest.kernel.driver_modules | Sort-Object -Unique)
if ($packagedProfiles.Count -ne $expectedProfiles.Count -or
    (Compare-Object $expectedProfiles $packagedProfiles) -or
    $packagedModules.Count -ne $expectedModules.Count -or
    (Compare-Object $expectedModules $packagedModules)) {
    throw 'The packaged hardware contract does not match the source matrix.'
}
foreach ($payload in $manifest.payloads.PSObject.Properties) {
    $file = [IO.Path]::GetFullPath((Join-Path (Split-Path -Parent $manifestPath) ([string]$payload.Value.path)))
    if (-not $file.StartsWith((Split-Path -Parent $manifestPath).TrimEnd('\') + '\',
            [StringComparison]::OrdinalIgnoreCase) -or
        [long]$payload.Value.size -ne (Get-Item -LiteralPath $file).Length -or
        [string]$payload.Value.sha256 -ne
            (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()) {
        throw "Release payload verification failed: $($payload.Name)"
    }
}
$packagedModuleArchive = [IO.Path]::GetFullPath((Join-Path (
    Split-Path -Parent $manifestPath) ([string]$manifest.payloads.kernel_modules.path)))
$moduleEntries = @(& tar -tzf $packagedModuleArchive)
if ($LASTEXITCODE -ne 0) { throw 'The packaged kernel module archive cannot be inspected.' }
foreach ($driver in $expectedModules) {
    $modulePattern = [regex]::Escape($driver.Replace('-', '_') + '.ko') +
        '(?:\.(?:xz|zst|gz))?$'
    if (-not @($moduleEntries | Where-Object { $_ -match $modulePattern })) {
        throw "The packaged kernel is missing a matrix driver: $driver"
    }
}

foreach ($executable in @(
    (Join-Path $root 'publish\desktop\SwitchTrade.exe'),
    (Join-Path $root 'publish\prerequisite\SwitchTradePrerequisites.exe')
)) {
    $process = Start-Process -FilePath $executable -ArgumentList '--self-test' -Wait -PassThru -WindowStyle Hidden
    if ($process.ExitCode -ne 0) { throw "Self-test failed: $executable" }
}
$desktopVersion = [Diagnostics.FileVersionInfo]::GetVersionInfo(
    (Join-Path $root 'publish\desktop\SwitchTrade.exe')).ProductVersion
if ($desktopVersion -ne $applicationVersion) {
    throw "Desktop product version does not match switchtrade/VERSION: $desktopVersion"
}

$msi = Join-Path $root 'wix\SwitchTrade.Desktop.msi'
$installer = New-Object -ComObject WindowsInstaller.Installer
$database = $installer.GetType().InvokeMember(
    'OpenDatabase',
    [Reflection.BindingFlags]::InvokeMethod,
    $null,
    $installer,
    [object[]]@([string]$msi, [int]0)
)
function Get-MsiRowCount([ValidateSet('File', 'Shortcut', 'CustomAction')][string]$Table) {
    $column = if ($Table -eq 'CustomAction') { 'Action' } else { $Table }
    $sql = "SELECT ``$column`` FROM ``$Table``"
    $view = $database.GetType().InvokeMember(
        'OpenView', [Reflection.BindingFlags]::InvokeMethod, $null, $database, [object[]]@($sql))
    try {
        [void]$view.GetType().InvokeMember(
            'Execute', [Reflection.BindingFlags]::InvokeMethod, $null, $view, $null)
        $count = 0
        while ($null -ne $view.GetType().InvokeMember(
            'Fetch', [Reflection.BindingFlags]::InvokeMethod, $null, $view, $null)) {
            $count++
        }
        return $count
    } finally {
        [void]$view.GetType().InvokeMember(
            'Close', [Reflection.BindingFlags]::InvokeMethod, $null, $view, $null)
    }
}
function Get-MsiProperty([string]$Name) {
    $sql = "SELECT ``Value`` FROM ``Property`` WHERE ``Property``='$Name'"
    $view = $database.GetType().InvokeMember(
        'OpenView', [Reflection.BindingFlags]::InvokeMethod, $null, $database, [object[]]@($sql))
    try {
        [void]$view.GetType().InvokeMember(
            'Execute', [Reflection.BindingFlags]::InvokeMethod, $null, $view, $null)
        $record = $view.GetType().InvokeMember(
            'Fetch', [Reflection.BindingFlags]::InvokeMethod, $null, $view, $null)
        if ($null -eq $record) { return $null }
        return $record.GetType().InvokeMember(
            'StringData', [Reflection.BindingFlags]::GetProperty,
            $null, $record, [object[]]@(1))
    } finally {
        [void]$view.GetType().InvokeMember(
            'Close', [Reflection.BindingFlags]::InvokeMethod, $null, $view, $null)
    }
}
if ((Get-MsiRowCount File) -ne 3) { throw 'Desktop MSI file table is unexpected.' }
if ((Get-MsiRowCount Shortcut) -ne 2) { throw 'Desktop MSI shortcuts are missing.' }
if ((Get-MsiProperty 'ProductVersion') -ne $productVersion) {
    throw 'Desktop MSI ProductVersion does not match switchtrade/VERSION.'
}
try {
    if ((Get-MsiRowCount CustomAction) -ne 0) {
        throw 'Desktop MSI must not contain WSL custom actions.'
    }
} catch [System.Runtime.InteropServices.COMException] {
    # An absent CustomAction table is the expected zero-custom-action representation.
}

$tempPrefix = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
$validationRoot = [IO.Path]::GetFullPath((Join-Path $tempPrefix (
    'SwitchTrade-package-validation-' + [Guid]::NewGuid().ToString('N'))))
if (-not $validationRoot.StartsWith($tempPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Validation directory escaped the system temporary directory.'
}
New-Item -ItemType Directory -Force -Path $validationRoot | Out-Null
try {
    $qualificationRoot = Join-Path $validationRoot 'qualification'
    [IO.Compression.ZipFile]::ExtractToDirectory($qualificationArchive, $qualificationRoot)
    $qualificationManifest = Join-Path $qualificationRoot 'qualification-manifest.json'
    if (-not (Test-Path -LiteralPath $qualificationManifest -PathType Leaf) -or
        [string]$result.qualification.manifest_sha256 -ne
            (Get-FileHash -LiteralPath $qualificationManifest -Algorithm SHA256).Hash.ToLowerInvariant()) {
        throw 'Extracted qualification manifest does not match build-result.json.'
    }
    $launcher = Join-Path $qualificationRoot 'Invoke-M7DistributedHarness.ps1'
    $generatedBytecode = @(Get-ChildItem -LiteralPath $qualificationRoot -Recurse -Force | Where-Object {
        $_.Name -eq '__pycache__' -or (-not $_.PSIsContainer -and $_.Extension -eq '.pyc')
    })
    if ($generatedBytecode.Count -ne 0) {
        throw 'Qualification archive contains mutable Python bytecode.'
    }
    $verifications = @()
    foreach ($iteration in 1..2) {
        $verificationText = @(& pwsh -NoProfile -File $launcher verify 2>&1) -join "`n"
        if ($LASTEXITCODE -ne 0) {
            throw "Qualification launcher verification $iteration failed: $verificationText"
        }
        try { $verifications += ,($verificationText | ConvertFrom-Json) } catch {
            throw "Qualification launcher returned invalid verification output on iteration $iteration."
        }
    }
    $verification = $verifications[1]
    if ([string]$verification.status -ne 'verified' -or
        [string]$verification.mode -ne 'packaged' -or
        [string]$verification.source_sha -ne [string]$result.qualification.source_sha -or
        [string]$verification.release -ne [string]$result.release_id -or
        [string]$verification.qualification_manifest -ne
            [string]$result.qualification.manifest_sha256) {
        throw 'Qualification launcher identity does not match the release.'
    }
    $generatedBytecode = @(Get-ChildItem -LiteralPath $qualificationRoot -Recurse -Force | Where-Object {
        $_.Name -eq '__pycache__' -or (-not $_.PSIsContainer -and $_.Extension -eq '.pyc')
    })
    if ($generatedBytecode.Count -ne 0) {
        throw 'Qualification verification mutated its immutable kit.'
    }

    $layout = Join-Path $validationRoot 'layout'
    New-Item -ItemType Directory -Force -Path $layout | Out-Null
    $start = [Diagnostics.ProcessStartInfo]::new()
    $start.FileName = $setup
    $start.UseShellExecute = $false
    foreach ($argument in @('/layout', $layout, '/quiet')) { [void]$start.ArgumentList.Add($argument) }
    $process = [Diagnostics.Process]::Start($start)
    $process.WaitForExit()
    if ($process.ExitCode -ne 0) { throw "Burn layout verification failed: $($process.ExitCode)" }
    $layoutBundle = @(Get-ChildItem -LiteralPath $layout -Filter '*.exe' -File)
    if ($layoutBundle.Count -ne 1 -or
        (Get-FileHash -LiteralPath $layoutBundle[0].FullName -Algorithm SHA256).Hash -ne
            (Get-FileHash -LiteralPath $setup -Algorithm SHA256).Hash) {
        throw 'The compressed Burn bundle did not reproduce itself independently.'
    }

    $wixProject = Join-Path $repo 'installer\replacement\wix\Bundle\SwitchTrade.Bundle.wixproj'
    $sdkMatch = [regex]::Match((Get-Content -Raw -LiteralPath $wixProject),
        'Sdk="WixToolset\.Sdk/([^"]+)"')
    if (-not $sdkMatch.Success) { throw 'Could not resolve the pinned WiX SDK version.' }
    $wix = Join-Path $env:USERPROFILE (
        ".nuget\packages\wixtoolset.sdk\$($sdkMatch.Groups[1].Value)\tools\net6.0\wix.dll")
    if (-not (Test-Path -LiteralPath $wix -PathType Leaf)) { throw "Pinned WiX CLI is missing: $wix" }
    $attachedRoot = Join-Path $validationRoot 'attached'
    $baRoot = Join-Path $validationRoot 'ba'
    $start = [Diagnostics.ProcessStartInfo]::new()
    $start.FileName = (Get-Command dotnet -ErrorAction Stop).Source
    $start.UseShellExecute = $false
    foreach ($argument in @($wix, 'burn', 'extract', '-o', $attachedRoot, '-oba', $baRoot, $setup)) {
        [void]$start.ArgumentList.Add($argument)
    }
    $process = [Diagnostics.Process]::Start($start)
    $process.WaitForExit()
    if ($process.ExitCode -ne 0) { throw "Burn extraction failed: $($process.ExitCode)" }

    $cache = Join-Path $attachedRoot 'WixAttachedContainer'
    $embeddedManifestPath = Join-Path $cache 'release-manifest.json'
    if ((Get-FileHash -LiteralPath $embeddedManifestPath -Algorithm SHA256).Hash -ne
        (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash) {
        throw 'The Setup EXE contains a stale or altered release manifest.'
    }
    $embeddedManifest = Get-Content -Raw -LiteralPath $embeddedManifestPath | ConvertFrom-Json
    if ([string]$embeddedManifest.release_id -ne [string]$manifest.release_id -or
        [string]$embeddedManifest.release_id -ne [string]$result.release_id) {
        throw 'The Setup EXE release identity does not match its build result.'
    }
    foreach ($payload in $embeddedManifest.payloads.PSObject.Properties) {
        $embeddedFile = Join-Path $cache ([string]$payload.Value.path)
        if ([long]$payload.Value.size -ne (Get-Item -LiteralPath $embeddedFile).Length -or
            [string]$payload.Value.sha256 -ne
                (Get-FileHash -LiteralPath $embeddedFile -Algorithm SHA256).Hash.ToLowerInvariant()) {
            throw "Embedded release payload verification failed: $($payload.Name)"
        }
    }
    $embeddedProvisioner = Join-Path $cache 'SwitchTradeProvisioner.exe'
    if ((Get-FileHash -LiteralPath $embeddedProvisioner -Algorithm SHA256).Hash -ne
        (Get-FileHash -LiteralPath (Join-Path $root 'publish\provisioner\SwitchTradeProvisioner.exe') -Algorithm SHA256).Hash) {
        throw 'The Setup EXE contains a stale provisioner.'
    }

    [xml]$burnManifest = Get-Content -Raw -LiteralPath (Join-Path $baRoot 'manifest.xml')
    $namespace = [Xml.XmlNamespaceManager]::new($burnManifest.NameTable)
    $namespace.AddNamespace('burn', 'http://wixtoolset.org/schemas/v4/2008/Burn')
    $registration = $burnManifest.SelectSingleNode('//burn:Registration', $namespace)
    if ($null -eq $registration -or
        ([version]$registration.Version).ToString(3) -ne $productVersion) {
        throw 'Burn bundle version does not match switchtrade/VERSION.'
    }
    $runtimePackage = $burnManifest.SelectSingleNode(
        '//burn:ExePackage[@Id="SwitchTradeRuntime"]', $namespace)
    $expectedDetect = 'InstalledRelease = "' + [string]$manifest.release_id + '"'
    if ($null -eq $runtimePackage -or $runtimePackage.DetectCondition -ne $expectedDetect -or
        $runtimePackage.InstallArguments -notmatch '--burn' -or
        $runtimePackage.InstallArguments -notmatch 'WixBundleLog_SwitchTradeRuntime' -or
        $runtimePackage.InstallArguments -match '--package-root') {
        throw 'The Setup EXE contains stale or unsafe runtime package arguments.'
    }
    $msiPackages = @($burnManifest.SelectNodes('//burn:MsiPackage', $namespace))
    if ($msiPackages.Count -ne 3 -or @($msiPackages | Where-Object {
            $_.HasAttribute('LogPathVariable') -or $_.HasAttribute('RollbackLogPathVariable')
        }).Count -ne 0) {
        throw 'The Setup EXE can pass a locale-sensitive automatic log path to a chained MSI.'
    }

    if ($RunDisposableWslLifecycle) {
        $provisioner = $embeddedProvisioner
        $data = Join-Path $validationRoot 'lifecycle\data'
        $profile = [Environment]::GetFolderPath([Environment+SpecialFolder]::UserProfile)
        $kernelValidationParent = Join-Path ([Environment]::GetFolderPath(
            [Environment+SpecialFolder]::CommonApplicationData)) (
            'SwitchTradeValidation\' + [Guid]::NewGuid().ToString('N'))
        $kernelRoot = Join-Path $kernelValidationParent 'kernel'
        if ($kernelRoot.ToCharArray() | Where-Object { [int]$_ -gt 127 }) {
            throw 'The WSL lifecycle gate requires an ASCII common application-data path.'
        }
        $runtimeLog = Join-Path $validationRoot 'lifecycle\SwitchTradeRuntime.log'
        $wslConfig = Join-Path $profile '.wslconfig'
        $originalWslConfigExists = Test-Path -LiteralPath $wslConfig -PathType Leaf
        $originalWslConfigHash = if ($originalWslConfigExists) {
            (Get-FileHash -LiteralPath $wslConfig -Algorithm SHA256).Hash
        } else { $null }
        $before = @((@(& wsl.exe --list --quiet) -replace ([char]0), '') | Where-Object { $_ })
        function Invoke-Provisioner([string]$Action) {
            $arguments = @($Action, '--json', '--burn', '--log', $runtimeLog,
                '--data-root', $data, '--user-profile', $profile, '--kernel-root', $kernelRoot)
            $start = [Diagnostics.ProcessStartInfo]::new()
            $start.FileName = $provisioner
            $start.UseShellExecute = $false
            $start.Environment['SWITCHTRADE_PROVISIONER_TEST_ROOTS'] = '1'
            foreach ($argument in $arguments) { [void]$start.ArgumentList.Add($argument) }
            $process = [Diagnostics.Process]::Start($start)
            $process.WaitForExit()
            if ($process.ExitCode -ne 0) { throw "Provisioner $Action failed: $($process.ExitCode)" }
        }
        try {
            Invoke-Provisioner 'repair'
            Invoke-Provisioner 'verify-software'
            $validationSelection = Join-Path $validationRoot 'lifecycle\hardware-selection.json'
            [ordered]@{
                schema = 1
                usb_id = '0bda:818b'
                instance_id = 'USB\VID_0BDA&PID_818B\QUALIFICATION'
                bus_id = 'validation'
            } | ConvertTo-Json -Compress | Set-Content -LiteralPath $validationSelection -Encoding utf8
            $preflightText = @(& pwsh -NoProfile -File $launcher preflight `
                -SelectionFile $validationSelection 2>&1) -join "`n"
            if ($LASTEXITCODE -ne 0) {
                throw "Qualification launcher preflight failed: $preflightText"
            }
            try { $preflight = $preflightText | ConvertFrom-Json } catch {
                throw 'Qualification launcher returned invalid preflight output.'
            }
            if ([string]$preflight.status -ne 'ready' -or
                [string]$preflight.source_sha -ne [string]$result.qualification.source_sha -or
                [string]$preflight.release -ne [string]$result.release_id -or
                [string]::IsNullOrWhiteSpace([string]$preflight.distro) -or
                [string]$preflight.qualification_manifest -ne
                    [string]$result.qualification.manifest_sha256) {
                throw 'Qualification launcher preflight identity does not match the release.'
            }
            $generatedBytecode = @(Get-ChildItem -LiteralPath $qualificationRoot -Recurse -Force |
                Where-Object {
                    $_.Name -eq '__pycache__' -or
                    (-not $_.PSIsContainer -and $_.Extension -eq '.pyc')
                })
            if ($generatedBytecode.Count -ne 0) {
                throw 'Qualification preflight mutated its immutable kit.'
            }
            Invoke-Provisioner 'repair'
        } finally {
            Invoke-Provisioner 'uninstall'
            if (Test-Path -LiteralPath $kernelValidationParent) {
                $resolvedKernelValidationParent = [IO.Path]::GetFullPath($kernelValidationParent)
                $commonApplicationData = [Environment]::GetFolderPath(
                    [Environment+SpecialFolder]::CommonApplicationData)
                $expectedKernelPrefix = [IO.Path]::GetFullPath(
                    (Join-Path $commonApplicationData 'SwitchTradeValidation')).TrimEnd('\') + '\'
                if (-not $resolvedKernelValidationParent.StartsWith(
                        $expectedKernelPrefix, [StringComparison]::OrdinalIgnoreCase)) {
                    throw 'Kernel validation cleanup escaped its dedicated root.'
                }
                Remove-Item -LiteralPath $resolvedKernelValidationParent -Recurse -Force
            }
        }
        $after = @((@(& wsl.exe --list --quiet) -replace ([char]0), '') | Where-Object { $_ })
        $distroDifference = $before.Count -ne $after.Count
        if (-not $distroDifference -and $before.Count -gt 0) {
            $distroDifference = @(Compare-Object -ReferenceObject $before -DifferenceObject $after).Count -ne 0
        }
        if ($distroDifference) { throw 'Disposable lifecycle changed unrelated WSL distributions.' }
        if ($originalWslConfigExists) {
            if (-not (Test-Path -LiteralPath $wslConfig -PathType Leaf) -or
                (Get-FileHash -LiteralPath $wslConfig -Algorithm SHA256).Hash -ne $originalWslConfigHash) {
                throw 'Disposable lifecycle did not restore the original .wslconfig bytes.'
            }
        } elseif (Test-Path -LiteralPath $wslConfig) {
            throw 'Disposable lifecycle did not restore the absent .wslconfig state.'
        }
    }
} finally {
    if (Test-Path -LiteralPath $validationRoot) {
        Remove-Item -LiteralPath $validationRoot -Recurse -Force
    }
}

[pscustomobject]@{
    release_id = [string]$manifest.release_id
    setup_sha256 = (Get-FileHash -LiteralPath $setup -Algorithm SHA256).Hash.ToLowerInvariant()
    package_verified = $true
    embedded_bundle_verified = $true
    disposable_wsl_lifecycle = [bool]$RunDisposableWslLifecycle
}
