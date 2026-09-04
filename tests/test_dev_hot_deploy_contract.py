from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "scripts/dev/DevOverlay.psm1"
DISPATCHER = ROOT / "dev.ps1"
ALLOWLIST = ROOT / "scripts/dev/dev-source-allowlist.txt"


class DevHotDeployContractTests(unittest.TestCase):
    def test_command_surface_is_documented(self) -> None:
        text = DISPATCHER.read_text(encoding="utf-8")
        for command in ("doctor", "sync", "run", "test", "clean"):
            self.assertIn(f"'{command}'", text)

    def test_allowlist_is_explicit_and_secret_free(self) -> None:
        entries = {
            line.strip()
            for line in ALLOWLIST.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        self.assertIn("switchtrade/**/*.py", entries)
        self.assertIn("bridge/**/*.py", entries)
        self.assertIn("tests/**/*.py", entries)
        self.assertNotIn("config/prod.keys", entries)
        self.assertNotIn("**/*.zip", entries)
        self.assertIn("dev-source-allowlist.txt", MODULE.read_text(encoding="utf-8"))

    def test_overlay_and_process_contract_are_explicit(self) -> None:
        text = MODULE.read_text(encoding="utf-8")
        for value in (
            "/opt/switchtrade/bridge/.venv/bin/python",
            "PYTHONNOUSERSITE=1",
            "PYTHONPATH=",
            "SWITCHTRADE_SOURCE_ROOT=",
            "SWITCHTRADE_INSTALLED_ROOT=",
            "--distribution",
            "--user",
            "--cd",
        ):
            self.assertIn(value, text)
        self.assertIn("$script:OverlayRoot/current", text)
        self.assertIn("$script:OverlayRoot/releases/", text)
        self.assertIn("(?:.*/)?", text)
        self.assertIn("DEV_DEPENDENCY_MISMATCH", text)
        self.assertIn("DEV_CLEAN_REFUSED", text)

    def test_production_root_is_not_a_mutation_target(self) -> None:
        text = MODULE.read_text(encoding="utf-8")
        self.assertNotRegex(text, r"(?:rm|mv|mkdir|ln)[^\n]*['\"]?/opt/switchtrade['\"]?(?:/|\s|$)")
        self.assertIn("InstalledRoot = '/opt/switchtrade'", text)
        self.assertIn("OverlayRoot = '/opt/switchtrade-dev'", text)

    def test_dispatcher_parses_without_live_wsl(self) -> None:
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if powershell is None:
            self.skipTest("PowerShell is unavailable")
        result = subprocess.run(
            [powershell, "-NoProfile", "-File", str(DISPATCHER), "help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
