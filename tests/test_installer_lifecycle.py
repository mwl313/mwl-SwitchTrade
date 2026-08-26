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
        self.assertNotIn("wsl-radio-preflight.ps1", launcher)
        self.assertNotIn("preflightArguments", launcher)
        self.assertIn("switchtrade.control", launcher)
        self.assertIn("RedirectStandardError", launcher)
        desktop_services = (ROOT / "apps" / "desktop" / "SwitchTrade.Desktop" /
                            "Services" / "DesktopServices.cs").read_text(encoding="utf-8")
        main_view_model = (ROOT / "apps" / "desktop" / "SwitchTrade.Desktop" /
                           "ViewModels" / "MainViewModel.cs").read_text(encoding="utf-8")
        self.assertIn("Task<BackendLaunchResult> StartAsync", desktop_services)
        self.assertIn("await _launcher.StartAsync", main_view_model)
        self.assertIn("if (_refreshing || _starting)", main_view_model)
        self.assertIn("--unregister $Distro", setup)
        self.assertNotIn("--unregister Ubuntu", setup)
        dialog = (ROOT / "installer" / "bootstrap" / "SetupDialog.cs").read_text(encoding="utf-8")
        progress = (ROOT / "installer" / "bootstrap" / "SetupProgressDialog.cs").read_text(encoding="utf-8")
        self.assertIn("DeferHardwareSetup", dialog)
        self.assertIn("global WSL 2 kernel selection", dialog)
        self.assertIn('action.Items.Add("Repair")', dialog)
        self.assertIn('action.Items.Add("Uninstall")', dialog)
        self.assertNotIn('if (installed) action.Items.Add("Repair")', dialog)
        self.assertNotIn('if (installed) action.Items.Add("Uninstall")', dialog)
        self.assertIn("ProgressBarStyle.Marquee", progress)
        self.assertIn("WaitForExitAsync", progress)
        self.assertIn("You can now delete the extracted setup folder and ZIP", program)
        self.assertIn("$UsbId.ToLowerInvariant()", setup)
        self.assertIn("wslHealthArguments", setup)
        self.assertIn("$KernelStorageRoot = Join-Path $env:ProgramData 'SwitchTrade\\kernel'", setup)
        self.assertIn("KernelStorageRoot = $KernelStorageRoot", setup)

    def test_package_accepts_versioned_external_release_inputs(self):
        builder = (ROOT / "installer" / "Build-Package.ps1").read_text(encoding="utf-8")
        for value in ("Rootfs", "DesktopExe", "Kernel", "KernelModules", "KernelManifest",
                      "KernelManifestSignature", "UsbipdMsi", "RelayUrl", "Notices",
                      "SigningCertificateThumbprint", "signature-required", "UnsignedPrivateBeta"):
            self.assertIn(value, builder)
        self.assertIn("payload\\release-config.json", builder)
        self.assertIn("legal\\THIRD-PARTY-NOTICES.txt", builder)
        self.assertIn('"$archive.sha256"', builder)
        release_config = json.loads((ROOT / "payload" / "release-config.json").read_text())
        self.assertEqual(release_config["relay_url"], "https://relay.pangyostonefist.org")

    def test_kernel_archive_is_not_mapped_as_a_wsl_modules_vhd(self):
        lifecycle = (ROOT / "installer" / "KernelLifecycle.ps1").read_text(encoding="utf-8")
        setup = (ROOT / "installer" / "SwitchTradeSetup.ps1").read_text(encoding="utf-8")
        rootfs = (ROOT / "installer" / "Build-Rootfs.sh").read_text(encoding="utf-8")
        provision = (ROOT / "installer" / "provision-wsl.sh").read_text(encoding="utf-8")
        self.assertIn("modules_format", lifecycle)
        self.assertIn("'archive'", lifecycle)
        self.assertIn("modules.tar.gz", setup)
        self.assertIn("tar -xzf", setup)
        self.assertIn("--include=ca-certificates,kmod", rootfs)
        self.assertIn("command -v depmod", setup)
        self.assertIn(" kmod ", provision)
        self.assertIn("KERNEL_ABI_OR_FIRMWARE_MISMATCH", setup)
        self.assertIn("CUSTOM_KERNEL_BLOCKED_BY_POLICY", setup)

    def test_package_requires_and_archives_runtime_ldn_keys(self):
        builder = (ROOT / "installer" / "Build-Package.ps1").read_text(encoding="utf-8")
        self.assertIn("config\\prod.keys", builder)
        self.assertIn("runtime LDN key input is missing", builder)
        self.assertIn("Join-Path $Stage 'README.md'", builder)
        self.assertTrue((ROOT / "config" / "prod.keys").is_file())

    def test_application_and_wsl_runtime_rollback_are_kept_together(self):
        provision = (ROOT / "installer" / "provision-wsl.sh").read_text(encoding="utf-8")
        setup = (ROOT / "installer" / "SwitchTradeSetup.ps1").read_text(encoding="utf-8")
        launcher = (ROOT / "installer" / "Launch-SwitchTrade.ps1").read_text(encoding="utf-8")
        self.assertIn("--rollback", provision)
        self.assertIn('${TARGET}.previous', provision)
        self.assertNotIn('${TARGET}.previous.$(date', provision)
        self.assertIn('cd "$stage"', provision)
        self.assertLess(provision.index("--dry-run"), provision.index('backup=""'))
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
                "--unsigned-private-beta",
            ], cwd=ROOT, capture_output=True, text=True, timeout=30)
            self.assertEqual(generated.returncode, 0, generated.stderr)
            body = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(body["schema"], 2)
            self.assertIn("payload/artifact.txt", body["artifact_hashes"])
            self.assertTrue(body["unsigned_private_beta"])
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
    def test_setup_failure_has_a_stable_bootstrap_marker(self):
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary)
            shutil.copytree(ROOT / "installer", package / "installer")
            result = subprocess.run([
                "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                str(package / "installer" / "SwitchTradeSetup.ps1"), "-Action", "Install",
            ], cwd=package, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SWITCHTRADE_SETUP_ERROR: PACKAGE_MANIFEST_MISSING", result.stderr)
        program = (ROOT / "installer" / "bootstrap" / "Program.cs").read_text(encoding="utf-8")
        self.assertIn('error.Replace("\\0", "")', program)

    @unittest.skipUnless(shutil.which("powershell"), "Windows PowerShell is required")
    def test_windows_host_support_matrix(self):
        compatibility = ROOT / "installer" / "HostCompatibility.ps1"
        cases = (
            (19044, 1, "X64", False),
            (19045, 1, "X64", True),
            (22000, 1, "X64", True),
            (26100, 1, "X64", True),
            (19045, 1, "Arm64", False),
            (20348, 3, "X64", False),
        )
        checks = "; ".join(
            f"if ((Test-SwitchTradeWindowsHost -Build {build} -ProductType {product_type} "
            f"-Architecture '{architecture}') -ne ${str(expected).lower()}) {{ exit 1 }}"
            for build, product_type, architecture, expected in cases
        )
        result = subprocess.run([
            "powershell", "-NoProfile", "-Command", f". '{compatibility}'; {checks}",
        ], cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        setup = (ROOT / "installer" / "SwitchTradeSetup.ps1").read_text(encoding="utf-8")
        self.assertIn("Windows 10 22H2 x64 (build 19045)", setup)
        self.assertIn("$audit.WslModern", setup)
        self.assertIn("WslFeaturesEnabled", setup)
        self.assertIn("wsl.exe --update --web-download", setup)
        self.assertNotIn("WindowsBuild -lt 26100", setup)

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
