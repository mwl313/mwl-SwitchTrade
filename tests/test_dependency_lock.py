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


def test_relay_dependency_graph_and_base_image_are_digest_locked():
    requirements = (ROOT / "relay" / "requirements.txt").read_text(encoding="utf-8")
    dependencies = [
        line for line in requirements.splitlines()
        if line and not line.startswith((" ", "#"))
    ]
    assert dependencies
    assert all("==" in line and line.endswith("\\") for line in dependencies)
    assert requirements.count("--hash=sha256:") >= len(dependencies)
    dockerfile = (ROOT / "relay" / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM python:3.12.11-slim@sha256:" in dockerfile
    assert "--require-hashes" in dockerfile
