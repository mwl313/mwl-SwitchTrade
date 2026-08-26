from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_wsl_runtime_requirements_are_exactly_pinned():
    requirements = ROOT / "bridge" / "requirements.txt"
    entries = [
        line.strip()
        for line in requirements.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert entries
    assert all("==" in entry for entry in entries)
