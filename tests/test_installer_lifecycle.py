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
        executor = (ROOT / "installer" / "engine" / "Executor.ps1").read_text(encoding="utf-8")
        platform = (ROOT / "installer" / "engine" / "PlatformOps.ps1").read_text(encoding="utf-8")
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
        self.assertIn("@('--unregister', $Context.Distro)", executor)
        self.assertNotIn("--unregister Ubuntu", executor)
        dialog = (ROOT / "installer" / "bootstrap" / "SetupDialog.cs").read_text(encoding="utf-8")
        progress = (ROOT / "installer" / "bootstrap" / "SetupProgressDialog.cs").read_text(encoding="utf-8")
        self.assertIn("DeferHardwareSetup", dialog)
        self.assertIn("global WSL 2 kernel selection", dialog)
        self.assertIn('new SetupActionChoice("Repair", "Repair interrupted setup")', dialog)
        self.assertIn('new SetupActionChoice("Repair", "Repair / reinstall")', dialog)
        self.assertIn('new SetupActionChoice("Uninstall", "Uninstall")', dialog)
        self.assertIn("DetectSetupState(localAppDataRoot)", dialog)
        self.assertIn("GetCommittedRelease", dialog)
        self.assertIn("previousRelease != installedRelease", dialog)
        self.assertIn("DecodeInvokingArgument", program)
        self.assertIn('phase is not ("completed" or "compensated" or "uninstalled")', dialog)
        self.assertIn("The isolated SwitchTrade WSL environment will also be removed", dialog)
        self.assertIn("ProgressBarStyle.Marquee", progress)
        self.assertIn("WaitForExitAsync", progress)
        self.assertIn('action == "resume"', program)
        self.assertIn('start.Environment["SWITCHTRADE_SETUP_PROGRESS"] = "1"', program)
        self.assertIn('"resume" => "Continuing SwitchTrade setup"', progress)
        self.assertIn("SWITCHTRADE_SETUP_PROGRESS: ", progress)
        self.assertIn("ReadLinesAsync(process.StandardOutput", progress)
        for stage in ("prerequisites_enable", "usbipd_install", "wsl_stage", "distro_identity",
                      "kernel_apply", "commit", "hardware_readiness", "rollback_recovery"):
            self.assertIn(f"Set-SwitchTradeEngineStage '{stage}'", executor)
        self.assertIn("Set-SwitchTradeTransactionPhase -Path $Context.TransactionPath -Phase 'importing_distro'", executor)
        self.assertIn("DISTRO_IMPORT_FAILED", executor)
        self.assertIn("Replace([string][char]0, '')", platform)
        self.assertIn("Invoke-SwitchTradeProcess", platform)
        self.assertIn("'Run Setup Install again'", setup)
        self.assertIn("You can now delete the extracted setup folder and ZIP", program)
        self.assertIn("$UsbId.ToLowerInvariant()", executor)
        self.assertIn("wslHealthArguments", executor)
        self.assertIn("Join-Path $env:ProgramData 'SwitchTrade\\kernel'", executor)
        self.assertIn("KernelStorageRoot =", executor)
        self.assertIn("'SwitchTradeUsbWatcher'", executor)
        self.assertIn("Set-ItemProperty -Path $startupRegistryPath -Name 'SwitchTradeUsbWatcher'", executor)
        self.assertIn("Remove-ItemProperty -Path $startupRegistryPath -Name 'SwitchTradeUsbWatcher'", executor)
        self.assertIn("HARDWARE_SELECTION_IMPORT_FAILED", executor)
        self.assertIn("'install', '-m', '0600'", executor)
        self.assertIn("SETUP_ELEVATION_FAILED", program)
        self.assertIn("--invoking-user-profile-b64=", program)
        self.assertIn("-InvokingUserSid", program)
        self.assertIn('requestedExecutionLevel level="asInvoker"', (ROOT / "installer" / "bootstrap" /
                                                                     "app.manifest").read_text(encoding="utf-8"))

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
        executor = (ROOT / "installer" / "engine" / "Executor.ps1").read_text(encoding="utf-8")
        platform = (ROOT / "installer" / "engine" / "PlatformOps.ps1").read_text(encoding="utf-8")
        rootfs = (ROOT / "installer" / "Build-Rootfs.sh").read_text(encoding="utf-8")
        provision = (ROOT / "installer" / "provision-wsl.sh").read_text(encoding="utf-8")
        self.assertIn("modules_format", lifecycle)
        self.assertIn("'archive'", lifecycle)
        self.assertIn("modules.tar.gz", executor)
        self.assertIn("tar -xzf", platform)
        self.assertIn("--include=ca-certificates,ethtool,iproute2,iw,kmod", rootfs)
        self.assertIn("command -v depmod", platform)
        self.assertIn("modinfo", provision)
        self.assertIn("KERNEL_ABI_OR_FIRMWARE_MISMATCH", executor)
        self.assertIn("CUSTOM_KERNEL_BLOCKED_BY_POLICY", executor)
        self.assertIn("builtInFirmwareVerified", platform)
        self.assertIn("firmware_sha256", executor)

    def test_package_requires_and_archives_runtime_ldn_keys(self):
        builder = (ROOT / "installer" / "Build-Package.ps1").read_text(encoding="utf-8")
        self.assertIn("config\\prod.keys", builder)
        self.assertIn("runtime LDN key input is missing", builder)
        self.assertIn("Join-Path $Stage 'README.md'", builder)
        self.assertTrue((ROOT / "config" / "prod.keys").is_file())

    def test_application_and_wsl_runtime_rollback_are_kept_together(self):
        provision = (ROOT / "installer" / "provision-wsl.sh").read_text(encoding="utf-8")
        executor = (ROOT / "installer" / "engine" / "Executor.ps1").read_text(encoding="utf-8")
        launcher = (ROOT / "installer" / "Launch-SwitchTrade.ps1").read_text(encoding="utf-8")
        self.assertIn("--rollback", provision)
        self.assertIn('${TARGET}.previous', provision)
        self.assertNotIn('${TARGET}.previous.$(date', provision)
        self.assertIn('cd "$CANDIDATE"', provision)
        self.assertLess(provision.index("--dry-run"), provision.index('commit)'))
        for mode in ("--stage", "--validate", "--commit", "--abort", "--compensate"):
            self.assertIn(mode, provision)
        for phase in ("rollback_wsl_committed", "rollback_kernel_committed",
                      "rollback_windows_committed"):
            self.assertIn(f"-Phase '{phase}'", executor)
        self.assertIn("Get-SwitchTradeRollbackPublishedState -Transaction $transaction -Direction 'target'", executor)
        self.assertIn("Test-InstalledConfiguration", launcher)
        self.assertIn("payload/release-config.json", launcher)
        self.assertIn("release_id", launcher)

    def test_destructive_recovery_blockers_fail_closed(self):
        planner = (ROOT / "installer" / "engine" / "Planner.ps1").read_text(encoding="utf-8")
        executor = (ROOT / "installer" / "engine" / "Executor.ps1").read_text(encoding="utf-8")
        self.assertIn("@('Install', 'Repair', 'Update', 'Rollback')",
                      (ROOT / "installer" / "SwitchTradeSetup.ps1").read_text(encoding="utf-8"))
        recovery_plan = planner[planner.index("function Resolve-SwitchTradeRecoveryPlan"):]
        self.assertLess(recovery_plan.index("gate_recovery_package"),
                        recovery_plan.index("recovery_decide"))
        self.assertLess(recovery_plan.index("recovery_decide"),
                        recovery_plan.index("compensate_kernel"))
        self.assertLess(recovery_plan.index("compensate_kernel"),
                        recovery_plan.index("compensate_wsl"))
        self.assertLess(recovery_plan.index("compensate_wsl"),
                        recovery_plan.index("compensate_windows"))
        uninstall_plan = planner[planner.index("function Resolve-SwitchTradeUninstallPlan"):
                                 planner.index("function Resolve-SwitchTradePlan {")]
        self.assertLess(uninstall_plan.index("gate_uninstall"),
                        uninstall_plan.index("unregister_distro"))
        self.assertLess(uninstall_plan.index("unregister_distro"),
                        uninstall_plan.index("remove_active"))
        self.assertIn("'uninstalled'", executor)
        self.assertIn("DESTRUCTIVE_PATH_DENIED", executor)
        self.assertIn("Assert-SwitchTradeDistroMutationIdentity", executor)

    def test_release_transaction_and_owned_identity_gates_are_present(self):
        setup = (ROOT / "installer" / "SwitchTradeSetup.ps1").read_text(encoding="utf-8")
        executor = (ROOT / "installer" / "engine" / "Executor.ps1").read_text(encoding="utf-8")
        planner = (ROOT / "installer" / "engine" / "Planner.ps1").read_text(encoding="utf-8")
        inspector = (ROOT / "installer" / "engine" / "StateInspector.ps1").read_text(encoding="utf-8")
        builder = (ROOT / "installer" / "Build-Package.ps1").read_text(encoding="utf-8")
        rootfs = (ROOT / "installer" / "Build-Rootfs.sh").read_text(encoding="utf-8")
        control = (ROOT / "switchtrade" / "control.py").read_text(encoding="utf-8")
        dialog = (ROOT / "installer" / "bootstrap" / "SetupDialog.cs").read_text(encoding="utf-8")
        for value in ("DISTRO_NAME_COLLISION", "Test-SwitchTradeStagedControlReadiness", "UsbInstanceId"):
            self.assertIn(value, executor)
        self.assertIn("SETUP_TRANSACTION_INCOMPLETE", executor)
        self.assertIn("package_manifest_sha256", executor)
        self.assertIn("Test-SwitchTradeEarlyFreshInstallRecovery", planner)
        self.assertIn("Test-SwitchTradeFreshImportMarkerBootstrap", planner)
        self.assertIn("-PackageManifestSha256 $Package.ManifestSha256", executor)
        self.assertIn("Global\\SwitchTrade.Setup", setup)
        self.assertLess(setup.index("Enter-SwitchTradeSetupMutex"),
                        setup.index("Resolve-SwitchTradePlan"))
        self.assertIn("switchtrade-distro.json", rootfs)
        self.assertIn("ROOTFS_IDENTITY_MARKER_MISSING", builder)
        self.assertIn('"release_id": runtime_release_id()', control)
        self.assertIn("InstanceId", dialog)
        self.assertIn("present_owned", inspector)
        self.assertIn("present_generic", inspector)
        self.assertLess(executor.index("Test-SwitchTradeKernelRollback"),
                        executor.index("function Invoke-SwitchTradeRollbackWsl"))

    def test_inline_wsl_shells_use_the_exec_argument_boundary(self):
        engine_files = [
            ROOT / "installer" / "engine" / "PlatformOps.ps1",
            ROOT / "installer" / "engine" / "Executor.ps1",
            ROOT / "installer" / "engine" / "StateInspector.ps1",
        ]
        platform = engine_files[0].read_text(encoding="utf-8")
        sh_boundary = platform[
            platform.index("function Invoke-SwitchTradeWslSh"):
            platform.index("function ConvertTo-SwitchTradeWslPath")
        ]
        self.assertIn("'--exec', 'sh', '-c'", sh_boundary)
        marker_writer = platform[
            platform.index("function Set-SwitchTradeDistroMarker"):
            platform.index("function Get-SwitchTradeWslRuntimeLocationProbe")
        ]
        self.assertIn("DISTRO_INSTALL_ID_WRITE_FAILED: $detail", marker_writer)
        for engine_file in engine_files:
            text = engine_file.read_text(encoding="utf-8")
            self.assertNotIn("'--', 'sh', '-c'", text)
            self.assertNotIn("'--', 'sh', '-lc'", text)

    @unittest.skipUnless(shutil.which("powershell"), "Windows PowerShell is required")
    def test_temp_rooted_setup_transaction_fails_closed_before_swap(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run([
                "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                str(ROOT / "installer" / "Test-SetupLifecycle.ps1"),
                "-TestRoot", temporary,
            ], cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Setup lifecycle simulation PASS", result.stdout)

    @unittest.skipUnless(shutil.which("powershell"), "Windows PowerShell is required")
    def test_engine_planner_parity_and_live_fixture_recovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run([
                "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                str(ROOT / "installer" / "Test-EnginePlanner.ps1"),
                "-TestRoot", temporary,
            ], cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Engine planner simulation PASS", result.stdout)

    @unittest.skipUnless(shutil.which("powershell"), "Windows PowerShell is required")
    def test_engine_subprocess_boundary_including_real_wsl_argv_round_trip(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run([
                "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                str(ROOT / "installer" / "Test-EngineBoundary.ps1"),
                "-TestRoot", temporary,
            ], cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Engine boundary simulation PASS", result.stdout)

    @unittest.skipUnless(shutil.which("powershell"), "Windows PowerShell is required")
    def test_rollback_process_death_repair_and_reverse_rollback(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run([
                "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                str(ROOT / "installer" / "Test-RollbackRecoveryLifecycle.ps1"),
                "-TestRoot", temporary,
            ], cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Rollback package-identity process-death simulation PASS", result.stdout)

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

    def test_setup_audit_does_not_launch_the_windows_wsl_install_stub(self):
        inspector = (ROOT / "installer" / "engine" / "StateInspector.ps1").read_text(encoding="utf-8")
        self.assertIn("function Test-SwitchTradeWslRuntimeLaunchSafe", inspector)
        identity_state = inspector[
            inspector.index("function Get-SwitchTradeDistroIdentityState"):
            inspector.index("function Get-SwitchTradeDistroRegistrationState")
        ]
        self.assertIn("Test-SwitchTradeWslRuntimeLaunchSafe", identity_state)
        self.assertLess(identity_state.index("Test-SwitchTradeWslRuntimeLaunchSafe"),
                        identity_state.index("Invoke-SwitchTradeWsl"))
        self.assertNotIn("Get-Command wsl.exe", identity_state)

    @unittest.skipUnless(shutil.which("powershell"), "Windows PowerShell is required")
    def test_setup_failure_has_a_stable_bootstrap_marker(self):
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary)
            shutil.copytree(ROOT / "installer", package / "installer")
            profile = package / "profile"
            local_app_data = profile / "AppData" / "Local"
            desktop = profile / "Desktop"
            local_app_data.mkdir(parents=True)
            desktop.mkdir(parents=True)
            result = subprocess.run([
                "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                str(package / "installer" / "SwitchTradeSetup.ps1"), "-Action", "Install",
                "-UserProfileRoot", str(profile),
                "-LocalAppDataRoot", str(local_app_data),
                "-DesktopRoot", str(desktop),
                "-InvokingUserSid", "S-1-5-21-1-2-3-1001",
            ], cwd=package, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SWITCHTRADE_SETUP_ERROR: PACKAGE_MANIFEST_MISSING", result.stderr)
        self.assertIn("SWITCHTRADE_SETUP_FAILURE:", result.stderr)
        self.assertIn("technical_detail_log_path", result.stderr)
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
        executor = (ROOT / "installer" / "engine" / "Executor.ps1").read_text(encoding="utf-8")
        entry = (ROOT / "installer" / "SwitchTradeSetup.ps1").read_text(encoding="utf-8")
        self.assertIn("Windows 10 22H2 x64 (build 19045)", executor)
        self.assertIn("$State.WslCapability.CapabilityReady", executor)
        self.assertIn("WslFeaturesEnabled", entry)
        self.assertIn("@('--update', '--web-download')", executor)
        self.assertNotIn("WindowsBuild -lt 26100", executor)

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
