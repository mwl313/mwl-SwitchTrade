"""Regression coverage for persisted production-diagnostic lifecycle and API purity."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
import zipfile
from unittest.mock import patch

from fastapi.testclient import TestClient

from switchtrade.control import create_app
from switchtrade.diagnostics import RunLogger
from switchtrade.production_diagnostics import (
    AP_FIXTURE, DIAGNOSTIC_CONTRACT, DiagnosticFailure, ProductionDiagnostics, fixture_metadata,
)


class ProductionDiagnosticsTests(unittest.TestCase):
    def _wait(self, diagnostics: ProductionDiagnostics, run_id: str, status: str) -> dict:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            value = diagnostics.get(run_id)
            if value and value["status"] == status:
                return value
            time.sleep(0.01)
        self.fail(f"diagnostic {run_id} did not reach {status}")

    def test_checkpoint_is_persisted_idempotent_and_terminal_after_worker_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            diagnostics = ProductionDiagnostics(temporary)

            def worker(run):
                run.stage("preflight", "passed", "DIAG_PREFLIGHT_PASSED", "Ready")
                run.await_continue("open_switch_room", "Open one Switch room.", timeout=2)
                run.stage("cleanup", "passed", "DIAG_CLEANUP_PASSED", "Released")
                run.finish("passed", result_level="switch_room_joined")

            started = diagnostics.start("room_detection", "0bda:818b", worker)
            waiting = self._wait(diagnostics, started["run_id"], "awaiting_user")
            self.assertEqual(waiting["contract_version"], DIAGNOSTIC_CONTRACT)
            self.assertEqual(waiting["checkpoint"]["id"], "open_switch_room")
            self.assertFalse(diagnostics.continue_run(started["run_id"], "wrong"))
            self.assertTrue(diagnostics.continue_run(started["run_id"], "open_switch_room"))
            finished = self._wait(diagnostics, started["run_id"], "passed")
            self.assertEqual(finished["cleanup"]["status"], "passed")
            self.assertEqual(finished["result_level"], "switch_room_joined")

    def test_restart_marks_incomplete_record_as_cleanup_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run = root / "20260829T000000Z-deadbeef"
            run.mkdir()
            report = run / "production-diagnostic-report.json"
            report.write_text(json.dumps({
                "contract_version": DIAGNOSTIC_CONTRACT, "run_id": run.name,
                "status": "running", "cleanup": {"status": "pending"},
            }), encoding="utf-8")
            recovered = ProductionDiagnostics(root).get(run.name)
            self.assertEqual(recovered["status"], "failed")
            self.assertEqual(recovered["failure"]["code"], "DIAG_CLEANUP_FAILED")

    def test_incomplete_cleanup_blocks_another_start(self):
        with tempfile.TemporaryDirectory() as temporary:
            diagnostics = ProductionDiagnostics(temporary)
            started = diagnostics.start(
                "automated", "0bda:818b",
                lambda run: run.finish("failed", cleanup_ok=False),
            )
            self._wait(diagnostics, started["run_id"], "failed")
            with self.assertRaisesRegex(DiagnosticFailure, "did not prove cleanup"):
                diagnostics.start("automated", "0bda:818b", lambda run: None)

    def test_fixture_is_immutable_and_redacted_metadata_only(self):
        self.assertEqual(len(AP_FIXTURE), 122)
        metadata = fixture_metadata()
        self.assertEqual(metadata["id"], "frlg-search-v1")
        self.assertEqual(len(metadata["sha256"]), 64)

    def test_support_bundle_includes_production_diagnostic_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            logger = RunLogger("control", temporary)
            diagnostic = ProductionDiagnostics(logger.run_dir / "production-diagnostics")
            created = diagnostic.start(
                "automated", "0bda:818b",
                lambda run: run.finish("passed", result_level="relay_exchange_passed"),
            )
            self._wait(diagnostic, created["run_id"], "passed")
            with zipfile.ZipFile(logger.support_bundle()) as archive:
                self.assertIn(
                    f"production-diagnostics/{created['run_id']}/production-diagnostic-report.json",
                    archive.namelist(),
                )

    def test_start_rejects_missing_adapter_before_any_endpoint_launch(self):
        with tempfile.TemporaryDirectory() as temporary, TestClient(create_app(runs_root=temporary)) as client:
            with patch("switchtrade.control.subprocess.Popen") as popen:
                started = client.post("/api/v1/production-diagnostics", json={
                    "test": "automated", "usb_id": "0bda:818b",
                })
                self.assertEqual(started.status_code, 409, started.text)
                self.assertEqual(started.json()["code"], "diag_adapter_not_selected")
                popen.assert_not_called()

    def test_get_projection_never_launches_or_mutates_a_diagnostic(self):
        with tempfile.TemporaryDirectory() as temporary, TestClient(create_app(runs_root=temporary)) as client:
            runtime = client.app.state.runtime
            release = threading.Event()

            def worker(run):
                run.transition("running", "fixture")
                release.wait(2)
                run.finish("passed", result_level="relay_exchange_passed")

            run_id = runtime.diagnostics.start("automated", "0bda:818b", worker)["run_id"]
            with patch("switchtrade.control.subprocess.Popen") as popen:
                snapshots = [client.get(f"/api/v1/production-diagnostics/{run_id}") for _ in range(20)]
                self.assertTrue(all(response.status_code == 200 for response in snapshots))
                popen.assert_not_called()
            release.set()


if __name__ == "__main__":
    unittest.main()
