import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from switchtrade.session_evidence import ApplicationEvidence


class ApplicationEvidenceTests(unittest.TestCase):
    def test_utf8_events_are_redacted_and_component_owned(self):
        with tempfile.TemporaryDirectory(prefix="스위치-세션-") as temporary:
            with patch.dict("os.environ", {
                "SWITCHTRADE_APP_SESSION_ID": "session-1",
                "SWITCHTRADE_SESSION_WSL_PATH": temporary,
            }):
                evidence = ApplicationEvidence.from_environment("connection-service")
                self.assertIsNotNone(evidence)
                evidence.event(
                    "failed", run_id="run-1", gate="P0b", code="RADIO_FAILED",
                    message="사용자 member_token=secret 00:11:22:33:44:55")
            path = Path(temporary) / "service-events.jsonl"
            record = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(record["app_session_id"], "session-1")
            self.assertEqual(record["gate"], "P0b")
            serialized = path.read_text(encoding="utf-8")
            self.assertNotIn("secret", serialized)
            self.assertNotIn("00:11:22:33:44:55", serialized)
            self.assertIn("사용자", serialized)

    def test_snapshot_failure_is_secondary_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            evidence = ApplicationEvidence("wrapper", "session-2", temporary)

            def timeout(*_args, **_kwargs):
                raise subprocess.TimeoutExpired("snapshot", 2)

            self.assertIsNone(evidence.capture_wsl_snapshot("p0b-before", runner=timeout))
            event = json.loads((Path(temporary) / "wrapper-events.jsonl").read_text())
            self.assertEqual(event["code"], "EVIDENCE_CAPTURE_FAILED")
            self.assertFalse((Path(temporary) / "failure-summary.v1.json").exists())

    def test_oversized_event_remains_valid_json_and_windows_user_is_redacted(self):
        with tempfile.TemporaryDirectory() as temporary:
            evidence = ApplicationEvidence("endpoint", "session-3", temporary)
            evidence.event(
                "bounded", run_id="run-3", optional=None,
                message="C:\\Users\\임민우\\Desktop\\secret " + ("가" * 40_000),
                trainer_name="Red")
            text = (Path(temporary) / "endpoint-events.jsonl").read_text(encoding="utf-8")
            record = json.loads(text)
            self.assertTrue(record["truncated"])
            self.assertNotIn("임민우", text)
            self.assertNotIn("Red", text)
            self.assertLessEqual(len(text), 16 * 1024)


if __name__ == "__main__":
    unittest.main()
