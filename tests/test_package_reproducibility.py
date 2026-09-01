from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_release_manifest_and_zip_are_reproducible():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        package = root / "SwitchTrade-test"
        package.mkdir()
        (package / "payload.txt").write_text("same input\n", encoding="utf-8")
        manifests = []
        archives = []
        for suffix in ("a", "b"):
            manifest = package / "manifest.json"
            subprocess.run([
                sys.executable, str(ROOT / "scripts" / "write-release-manifest.py"),
                "--output", str(manifest), "--package-root", str(package),
                "--release-id", "release-test", "--source-date-epoch", "1700000000",
            ], cwd=ROOT, check=True)
            manifests.append(manifest.read_bytes())
            archive = root / f"{suffix}.zip"
            subprocess.run([
                sys.executable, str(ROOT / "scripts" / "create-deterministic-zip.py"),
                str(package), str(archive), "--epoch", "1700000000",
            ], cwd=ROOT, check=True)
            archives.append(_sha(archive))
        assert manifests[0] == manifests[1]
        assert archives[0] == archives[1]
        body = json.loads(manifests[0])
        assert body["source_date_epoch"] == 1700000000
        assert "branch" not in body
        with zipfile.ZipFile(root / "a.zip") as archive:
            assert archive.namelist() == sorted(archive.namelist())


def test_packaging_and_provisioning_fail_closed_to_verified_offline_inputs():
    builder = (ROOT / "installer" / "Build-Package.ps1").read_text(encoding="utf-8")
    setup_project = (ROOT / "installer" / "bootstrap" / "SwitchTrade.Setup.csproj").read_text(
        encoding="utf-8"
    )
    provision = (ROOT / "installer" / "provision-wsl.sh").read_text(encoding="utf-8")
    rootfs = (ROOT / "installer" / "Build-Rootfs.sh").read_text(encoding="utf-8")
    assert "Wheelhouse = $Wheelhouse" in builder
    assert "wheelhouse-manifest.json" in builder
    assert "create-deterministic-zip.py" in builder
    assert "ContinuousIntegrationBuild=true" in builder
    assert "--no-restore" in builder
    assert "<RuntimeIdentifier>win-x64</RuntimeIdentifier>" in setup_project
    assert "--no-index" in provision
    assert "OFFLINE_WHEELHOUSE_MISSING" in provision
    assert "apt-get update" not in provision
    assert "apt-get update" not in (ROOT / "installer" / "SwitchTradeSetup.ps1").read_text(encoding="utf-8")
    assert "SOURCE_DATE_EPOCH is required" in rootfs
    assert "--sort=name" in rootfs


def test_production_source_payload_excludes_test_and_internal_documentation():
    builder = (ROOT / "installer" / "Build-Package.ps1").read_text(encoding="utf-8")
    runtime_block = builder.split("$runtimePaths = @(", 1)[1].split(")\n& git", 1)[0]
    for required in ("'bridge'", "'config'", "'switchtrade'", "'requirements.txt'",
                     "'scripts/run-beta-endpoint.sh'", "'scripts/windows/wsl-radio-preflight.ps1'"):
        assert required in runtime_block
    for forbidden in ("'tests'", "'pytest.ini'", "'test-requirements.txt'", "'README.md'"):
        assert forbidden not in runtime_block
    for forbidden_path in ("bridge\\tests", "bridge\\README.md", "relay\\DEPLOYMENT.md"):
        assert forbidden_path in builder
    assert "Remove-Item -LiteralPath $path -Recurse -Force" in builder
    installer_block = builder.split("$installerRuntimePaths = @(", 1)[1].split(")\n& git", 1)[0]
    for required in ("installer/engine", "SwitchTradeSetup.ps1", "SetupLifecycle.ps1", "PackageIntegrity.ps1",
                     "UsbAutoAttachWatcher.ps1", "provision-wsl.sh"):
        assert required in installer_block
    for forbidden in ("Test-", "Build-Package.ps1", "Build-Rootfs.sh", "bootstrap", "README.md"):
        assert forbidden not in installer_block


def test_replacement_package_requires_the_complete_dynamic_hardware_contract():
    replacement = (
        ROOT / "installer" / "replacement" / "Build-ReplacementPackage.ps1"
    ).read_text(encoding="utf-8")
    immutable = (
        ROOT / "installer" / "replacement" / "Build-ImmutableWsl.ps1"
    ).read_text(encoding="utf-8")
    validator = (
        ROOT / "installer" / "replacement" / "Test-ReplacementPackage.ps1"
    ).read_text(encoding="utf-8")

    assert "[string]$KernelArtifact" in replacement
    assert "verify-kernel-artifact.py" in replacement
    assert "config\\wsl-radio-hardware.tsv" in replacement
    assert "driver_profiles = $driverProfiles" in replacement
    assert "driver_modules = $driverModules" in replacement
    assert "Get-NormalizedFirmwareManifest" in replacement
    assert "Compare-Object" in replacement
    assert "final-package-27d17b1" not in replacement
    assert "artifacts\\kernel-production" in immutable
    assert "final-package-27d17b1" not in immutable
    assert "The packaged hardware contract does not match the source matrix." in validator
    assert "The packaged kernel is missing a matrix driver" in validator
