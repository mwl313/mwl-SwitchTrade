from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class InstallerLifecycleTests(unittest.TestCase):
    def test_native_bootstrap_and_lifecycle_modes_are_present(self):
        program = (ROOT / "installer" / "bootstrap" / "Program.cs").read_text(encoding="utf-8")
        setup = (ROOT / "installer" / "SwitchTradeSetup.ps1").read_text(encoding="utf-8")
        self.assertIn("SwitchTradeSetup", program)
        for action in ("Audit", "Install", "Repair", "Update", "Rollback", "Uninstall"):
            self.assertIn(action, setup)
        self.assertIn("--unregister $Distro", setup)
        self.assertNotIn("--unregister Ubuntu", setup)

    def test_package_accepts_versioned_external_release_inputs(self):
        builder = (ROOT / "installer" / "Build-Package.ps1").read_text(encoding="utf-8")
        for value in ("Rootfs", "DesktopExe", "Kernel", "KernelModules", "KernelManifest",
                      "UsbipdMsi", "RelayUrl", "release_config_sha256"):
            self.assertIn(value, builder)

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
