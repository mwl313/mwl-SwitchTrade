from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import json


ROOT = Path(__file__).resolve().parents[1]


class InstallerLifecycleTests(unittest.TestCase):
    def test_native_bootstrap_and_lifecycle_modes_are_present(self):
        program = (ROOT / "installer" / "bootstrap" / "Program.cs").read_text(encoding="utf-8")
        setup = (ROOT / "installer" / "SwitchTradeSetup.ps1").read_text(encoding="utf-8")
        self.assertIn("SwitchTradeSetup", program)
        for action in ("Audit", "Install", "Repair", "Update", "Resume", "Rollback", "Uninstall"):
            self.assertIn(action, setup)
        self.assertIn("VerifyPackage", program)
        self.assertIn("SetupDialog.Show", program)
        self.assertIn("PACKAGE_SIGNATURE_MISSING", program)
        self.assertIn("RunOnce", setup)
        launcher = (ROOT / "installer" / "Launch-SwitchTrade.ps1").read_text(encoding="utf-8")
        self.assertIn("Choose a detected adapter in Settings", launcher)
        self.assertIn("--unregister $Distro", setup)
        self.assertNotIn("--unregister Ubuntu", setup)
        dialog = (ROOT / "installer" / "bootstrap" / "SetupDialog.cs").read_text(encoding="utf-8")
        self.assertIn("DeferHardwareSetup", dialog)
        self.assertIn("global WSL 2 kernel selection", dialog)
        self.assertIn("$UsbId.ToLowerInvariant()", setup)
        self.assertIn("wslHealthArguments", setup)

    def test_package_accepts_versioned_external_release_inputs(self):
        builder = (ROOT / "installer" / "Build-Package.ps1").read_text(encoding="utf-8")
        for value in ("Rootfs", "DesktopExe", "Kernel", "KernelModules", "KernelManifest",
                      "KernelManifestSignature", "UsbipdMsi", "RelayUrl", "Notices",
                      "SigningCertificateThumbprint", "signature-required"):
            self.assertIn(value, builder)

    def test_kernel_archive_is_not_mapped_as_a_wsl_modules_vhd(self):
        lifecycle = (ROOT / "installer" / "KernelLifecycle.ps1").read_text(encoding="utf-8")
        setup = (ROOT / "installer" / "SwitchTradeSetup.ps1").read_text(encoding="utf-8")
        self.assertIn("modules_format", lifecycle)
        self.assertIn("'archive'", lifecycle)
        self.assertIn("modules.tar.gz", setup)
        self.assertIn("tar -xzf", setup)
        self.assertIn("KERNEL_ABI_OR_FIRMWARE_MISMATCH", setup)
        self.assertIn("CUSTOM_KERNEL_BLOCKED_BY_POLICY", setup)

    def test_application_and_wsl_runtime_rollback_are_kept_together(self):
        provision = (ROOT / "installer" / "provision-wsl.sh").read_text(encoding="utf-8")
        setup = (ROOT / "installer" / "SwitchTradeSetup.ps1").read_text(encoding="utf-8")
        launcher = (ROOT / "installer" / "Launch-SwitchTrade.ps1").read_text(encoding="utf-8")
        self.assertIn("--rollback", provision)
        self.assertIn('${TARGET}.previous', provision)
        self.assertNotIn('${TARGET}.previous.$(date', provision)
        self.assertIn("application, WSL runtime, and retained kernel rollback completed", setup)
        self.assertIn("Test-InstalledConfiguration", launcher)
        self.assertIn("payload/release-config.json", launcher)

    @unittest.skipUnless(shutil.which("powershell"), "Windows PowerShell is required")
    def test_schema2_package_manifest_detects_tampering(self):
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary)
            (package / "payload").mkdir()
            artifact = package / "payload" / "artifact.txt"
            artifact.write_text("trusted", encoding="utf-8")
            manifest = package / "manifest.json"
            generated = subprocess.run([
                "python", str(ROOT / "scripts" / "write-release-manifest.py"),
                "--output", str(manifest), "--package-root", str(package),
                "--release-id", "test-release",
            ], cwd=ROOT, capture_output=True, text=True, timeout=30)
            self.assertEqual(generated.returncode, 0, generated.stderr)
            body = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(body["schema"], 2)
            self.assertIn("payload/artifact.txt", body["artifact_hashes"])
            integrity = ROOT / "installer" / "PackageIntegrity.ps1"
            command = (
                f". '{integrity}'; Test-SwitchTradePackage -PackageRoot '{package}' "
                "-AllowUnsignedPackage | Out-Null"
            )
            valid = subprocess.run(["powershell", "-NoProfile", "-Command", command],
                                   capture_output=True, text=True, timeout=30)
            self.assertEqual(valid.returncode, 0, valid.stderr)
            artifact.write_text("tampered", encoding="utf-8")
            invalid = subprocess.run(["powershell", "-NoProfile", "-Command", command],
                                     capture_output=True, text=True, timeout=30)
            self.assertNotEqual(invalid.returncode, 0)
            self.assertIn("PACKAGE_ARTIFACT_MISMATCH", invalid.stderr)

    @unittest.skipUnless(shutil.which("powershell"), "Windows PowerShell is required")
    def test_setup_audit_is_read_only_and_powershell5_compatible(self):
        result = subprocess.run([
            "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            str(ROOT / "installer" / "SwitchTradeSetup.ps1"), "-Action", "Audit",
        ], cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("WindowsBuild", result.stdout)
        self.assertIn("Distro", result.stdout)

    @unittest.skipUnless(shutil.which("powershell"), "Windows PowerShell is required")
    def test_kernel_update_release_rollback_and_exact_uninstall_restore(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run([
                "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                str(ROOT / "installer" / "Test-KernelLifecycle.ps1"),
                "-TestRoot", temporary,
            ], cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Kernel lifecycle simulation PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
