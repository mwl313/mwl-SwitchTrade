#!/usr/bin/env python3
"""Fail closed when a SwitchTrade kernel artifact is incomplete or mismatched."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tarfile


REQUIRED_MODULES = (
    "rtl8xxxu.ko",
    "vhci-hcd.ko",
    "tun.ko",
    "tap.ko",
    "ccm.ko",
    "cmac.ko",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(root: Path) -> dict:
    root = root.resolve()
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != 1:
        raise ValueError("unsupported kernel manifest schema")

    kernel = root / "bzImage-wsl-st"
    module_archives = list(root.glob("modules-*.tar.gz"))
    firmware_manifest = root / "firmware-manifest.sha256"
    if not kernel.is_file() or len(module_archives) != 1 or not firmware_manifest.is_file():
        raise ValueError("kernel artifact is missing the kernel, one module archive, or firmware manifest")
    modules = module_archives[0]

    expected = {
        "kernel_sha256": sha256(kernel),
        "modules_sha256": sha256(modules),
        "firmware_sha256": sha256(firmware_manifest),
    }
    for field, actual in expected.items():
        if manifest.get(field) != actual:
            raise ValueError(f"{field} mismatch")

    release = manifest.get("kernel_release")
    if not isinstance(release, str) or not release:
        raise ValueError("kernel_release is missing")
    with tarfile.open(modules, "r:gz") as archive:
        names = [name.removeprefix("./") for name in archive.getnames()]
    if not any(name == release or name.startswith(f"{release}/") for name in names):
        raise ValueError("module archive does not contain the declared kernel release")
    missing = [module for module in REQUIRED_MODULES if not any(module in name for name in names)]
    if missing:
        raise ValueError(f"required kernel modules are missing: {', '.join(missing)}")

    if manifest.get("experimental_vendor_8188eu") is False and (root / "8188eu-vendor.ko").exists():
        raise ValueError("artifact contains an undeclared experimental RTL8188EU module")
    return {
        "kernel_release": release,
        "kernel_sha256": expected["kernel_sha256"],
        "modules_sha256": expected["modules_sha256"],
        "firmware_sha256": expected["firmware_sha256"],
        "required_modules": list(REQUIRED_MODULES),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.artifact), sort_keys=True))


if __name__ == "__main__":
    main()
