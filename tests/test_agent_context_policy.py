from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from build_incident_index import render_index  # noqa: E402


ARCHIVE = ROOT / "docs/incidents/archive/MISTAKES_TO_AVOID-legacy-20260901.md"
CURRENT = ROOT / "docs/incidents/current/INCIDENTS.md"
INDEX = ROOT / "docs/incidents/INDEX.md"
MANIFEST = ROOT / "docs/incidents/ARCHIVE_MANIFEST.json"
AGENTS = ROOT / "AGENTS.md"
STUB = ROOT / "docs/MISTAKES_TO_AVOID.md"


class AgentContextPolicyTests(unittest.TestCase):
    def test_archive_matches_manifest(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        archive_path = ARCHIVE.relative_to(ROOT).as_posix()
        archive_bytes = subprocess.run(
            ["git", "show", f"HEAD:{archive_path}"],
            cwd=ROOT,
            capture_output=True,
            check=True,
        ).stdout
        self.assertEqual(manifest["byte_size"], len(archive_bytes))
        self.assertEqual(
            manifest["sha256"], hashlib.sha256(archive_bytes).hexdigest()
        )

    def test_generated_index_is_current(self) -> None:
        self.assertEqual(render_index(ARCHIVE, CURRENT), INDEX.read_text(encoding="utf-8"))
        relative_archive = Path(
            "docs/incidents/archive/MISTAKES_TO_AVOID-legacy-20260901.md"
        )
        relative_current = Path("docs/incidents/current/INCIDENTS.md")
        self.assertEqual(
            render_index(relative_archive, relative_current), render_index(ARCHIVE, CURRENT)
        )

    def test_current_incidents_share_the_primary_index(self) -> None:
        self.assertTrue(CURRENT.is_file())
        self.assertFalse((ROOT / "docs/mistakes/INCIDENTS.md").exists())
        self.assertFalse((ROOT / "docs/mistakes/INCIDENT_INDEX.md").exists())

    def test_root_agents_is_bounded(self) -> None:
        agents_text = AGENTS.read_text(encoding="utf-8")
        self.assertLessEqual(len(agents_text.splitlines()), 120)
        self.assertLessEqual(len(AGENTS.read_bytes()), 8 * 1024)

    def test_active_policy_does_not_require_full_archive_read(self) -> None:
        active_text = f"{AGENTS.read_text(encoding='utf-8')}\n{STUB.read_text(encoding='utf-8')}".lower()
        self.assertNotRegex(active_text, re.compile(r"read .*?(complete|full).*?archive"))
        self.assertIn("not mandatory default context", active_text)
        self.assertIn("docs/incidents/index.md", active_text)


if __name__ == "__main__":
    unittest.main()
