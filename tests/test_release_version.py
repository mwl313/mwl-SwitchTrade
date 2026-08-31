from pathlib import Path
import re
import subprocess

from switchtrade import __version__


ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / "switchtrade" / "VERSION").read_text(encoding="ascii").strip()
SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*)?$")


def product_version(value: str) -> tuple[int, int, int]:
    match = SEMVER.fullmatch(value)
    assert match, f"invalid SwitchTrade version: {value}"
    return tuple(map(int, match.groups()))


def test_checked_in_version_is_the_runtime_and_installer_source():
    assert __version__ == VERSION
    project = (ROOT / "apps" / "desktop" / "SwitchTrade.Desktop" /
               "SwitchTrade.Desktop.csproj").read_text(encoding="utf-8")
    builder = (ROOT / "installer" / "replacement" /
               "Build-ReplacementPackage.ps1").read_text(encoding="utf-8")
    qualification_builder = (ROOT / "installer" / "replacement" /
                             "Build-M7QualificationKit.ps1").read_text(encoding="utf-8")
    assert "switchtrade\\VERSION" in project
    assert "switchtrade\\VERSION" in builder
    assert "[string]$ProductVersion" not in builder
    assert "m7-qualification-kit.v1" in qualification_builder
    assert "qualification-manifest.json" in qualification_builder
    assert "3.12.14" in qualification_builder


def test_checked_in_installer_version_never_decreases_in_git_history():
    current = product_version(VERSION)
    history = subprocess.run(
        ["git", "log", "--format=%H", "--all", "--", "switchtrade/VERSION"],
        cwd=ROOT, check=True, capture_output=True, text=True,
    ).stdout.splitlines()
    prior = []
    for commit in history:
        result = subprocess.run(
            ["git", "show", f"{commit}:switchtrade/VERSION"], cwd=ROOT,
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            prior.append(product_version(result.stdout.strip()))
    assert not prior or current >= max(prior)
