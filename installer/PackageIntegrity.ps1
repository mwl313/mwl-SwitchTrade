Set-StrictMode -Version Latest

function Get-PackageFileSha256([string]$Path) {
    $stream = [IO.File]::OpenRead([IO.Path]::GetFullPath($Path))
    try {
        $algorithm = [Security.Cryptography.SHA256]::Create()
        try { return ([BitConverter]::ToString($algorithm.ComputeHash($stream))).Replace('-', '').ToLowerInvariant() }
        finally { $algorithm.Dispose() }
    } finally { $stream.Dispose() }
}

function Test-DetachedCmsSignature {
    param(
        [Parameter(Mandatory)][string]$ContentPath,
        [Parameter(Mandatory)][string]$SignaturePath
    )
    Add-Type -AssemblyName System.Security
    $content = [Security.Cryptography.Pkcs.ContentInfo]::new([IO.File]::ReadAllBytes($ContentPath))
    $signed = [Security.Cryptography.Pkcs.SignedCms]::new($content, $true)
    $signed.Decode([IO.File]::ReadAllBytes($SignaturePath))
    $signed.CheckSignature($false)
    if ($signed.SignerInfos.Count -lt 1) { throw 'the detached signature has no signer' }
    foreach ($signer in $signed.SignerInfos) {
        $certificate = $signer.Certificate
        if (-not $certificate) { throw 'the detached signature does not include its signing certificate' }
        $codeSigning = $false
        foreach ($extension in $certificate.Extensions) {
            if ($extension -is [Security.Cryptography.X509Certificates.X509EnhancedKeyUsageExtension]) {
                foreach ($usage in $extension.EnhancedKeyUsages) {
                    if ($usage.Value -eq '1.3.6.1.5.5.7.3.3') { $codeSigning = $true }
                }
            }
        }
        if (-not $codeSigning) { throw 'the detached signature certificate is not valid for code signing' }
    }
    return $true
}

function Test-SwitchTradePackage {
    param(
        [Parameter(Mandatory)][string]$PackageRoot,
        [switch]$AllowUnsignedPackage
    )
    $root = [IO.Path]::GetFullPath($PackageRoot).TrimEnd('\')
    $manifestPath = Join-Path $root 'manifest.json'
    $signaturePath = Join-Path $root 'manifest.json.p7s'
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        throw 'PACKAGE_MANIFEST_MISSING: the SwitchTrade package is incomplete'
    }
    $manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
    if ([int]$manifest.schema -ne 2 -or -not $manifest.artifact_hashes) {
        throw 'PACKAGE_MANIFEST_UNSUPPORTED: this setup requires a schema 2 package manifest'
    }
    $signatureRequired = [bool]$manifest.signature_required
    if (Test-Path -LiteralPath $signaturePath -PathType Leaf) {
        try { Test-DetachedCmsSignature -ContentPath $manifestPath -SignaturePath $signaturePath | Out-Null }
        catch { throw "PACKAGE_SIGNATURE_INVALID: $($_.Exception.Message)" }
    } elseif ($signatureRequired -or -not $AllowUnsignedPackage) {
        throw 'PACKAGE_SIGNATURE_MISSING: use a signed release package; unsigned packages are internal-test only'
    }

    $expected = @{}
    foreach ($property in $manifest.artifact_hashes.PSObject.Properties) {
        $relative = ([string]$property.Name).Replace('/', '\')
        if ([IO.Path]::IsPathRooted($relative) -or $relative -match '(^|\\)\.\.(\\|$)') {
            throw "PACKAGE_PATH_INVALID: $relative"
        }
        $candidate = [IO.Path]::GetFullPath((Join-Path $root $relative))
        if (-not $candidate.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) {
            throw "PACKAGE_PATH_INVALID: $relative"
        }
        $expected[$relative.ToLowerInvariant()] = ([string]$property.Value).ToLowerInvariant()
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            throw "PACKAGE_ARTIFACT_MISSING: $relative"
        }
        if ((Get-PackageFileSha256 $candidate) -ne $expected[$relative.ToLowerInvariant()]) {
            throw "PACKAGE_ARTIFACT_MISMATCH: $relative"
        }
    }
    $actual = @(Get-ChildItem -LiteralPath $root -File -Recurse | ForEach-Object {
        $_.FullName.Substring($root.Length + 1).ToLowerInvariant()
    } | Where-Object { $_ -notin @('manifest.json', 'manifest.json.p7s') })
    foreach ($relative in $actual) {
        if (-not $expected.ContainsKey($relative)) { throw "PACKAGE_UNEXPECTED_ARTIFACT: $relative" }
    }
    if ($actual.Count -ne $expected.Count) { throw 'PACKAGE_ARTIFACT_SET_MISMATCH' }
    return $manifest
}
