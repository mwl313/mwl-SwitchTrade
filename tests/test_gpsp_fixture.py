"""Fixture provenance checks, not a substitute for real-process qualification."""
import hashlib
import json
from pathlib import Path


FIXTURE = Path(__file__).parent / "fixtures/rfu/gpsp-attach"


def test_gpsp_attach_fixture_provenance():
    provenance = json.loads((FIXTURE / "provenance.json").read_text(encoding="utf-8"))
    assert hashlib.sha256((FIXTURE / "attach.gba").read_bytes()).hexdigest() == provenance["binary_sha256"]
    for name, expected in provenance["source_sha256"].items():
        canonical = (FIXTURE / name).read_text(encoding="utf-8").replace("\r\n", "\n").encode()
        assert hashlib.sha256(canonical).hexdigest() == expected, name
    assert "MIT License" in (FIXTURE / "LICENSE.gba-link-connection.txt").read_text()


def test_test_process_launcher_is_not_in_the_product():
    root = Path(__file__).resolve().parents[1]
    for source in (root / "switchtrade").rglob("*.py"):
        text = source.read_text(encoding="utf-8")
        assert "gpsp_qualification" not in text, source
