"""Explicit CI/test input preparation, NOT a product installer or launcher."""
import argparse
import hashlib
from pathlib import Path, PurePosixPath
import re
import subprocess
from urllib.request import urlopen

BASE = "https://buildbot.libretro.com/stable/1.22.2/windows/x86_64/"
ARCHIVES = {
    "RetroArch.7z": (202509078, "b2139b1d0f9d4526dc6b5ce23cbb3efdc766096fa6f2c3df016818b486ac6372"),
    "RetroArch_cores.7z": (229761684, "86b871e11b9b4772ac644b40a38f2c8e9449da1f355eae7da08aa061148547b0"),
}
BINARIES = {"retroarch.exe": "81c11b6f24932bf7918f05eee8928035bff3887335fd2a081507c75e9d94d06a",
    "cores/gpsp_libretro.dll": "c84f619c1077a7fbae84c385df752fbeb867d301880400add7cce6a380dbd516"}


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def selected_members(names, core=False):
    pattern = r"RetroArch-Win64/cores/gpsp_libretro\.dll" if core else r"RetroArch-Win64/(retroarch\.exe|[^/]+\.dll)"
    selected = [name for name in names if re.fullmatch(pattern, name)]
    if not selected or len(selected) != len(set(selected)):
        raise ValueError("STOCK_ARCHIVE_MEMBERS_INVALID")
    for name in selected:
        path = PurePosixPath(name)
        if path.is_absolute() or any(part in (".", "..") or ":" in part or "\\" in part for part in path.parts):
            raise ValueError("STOCK_ARCHIVE_PATH_INVALID")
    return selected


def prepare(output, archives=None):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    for name, (size, sha) in ARCHIVES.items():
        path = archives / name if archives else output / name
        if archives is None:
            with urlopen(BASE + name, timeout=60) as response, path.open("xb") as destination:
                received = 0
                while block := response.read(1024 * 1024):
                    received += len(block)
                    if received > size:
                        raise ValueError("STOCK_ARCHIVE_OVERSIZE")
                    destination.write(block)
        if path.stat().st_size != size or digest(path) != sha:
            raise ValueError("STOCK_ARCHIVE_IDENTITY_MISMATCH")
        names = subprocess.check_output(["tar", "-tf", str(path)], text=True).splitlines()
        members = selected_members(names, name == "RetroArch_cores.7z")
        subprocess.run(["tar", "-xf", str(path), "-C", str(output), *members], check=True)
    root = output / "RetroArch-Win64"
    for name, sha in BINARIES.items():
        if digest(root / name) != sha:
            raise ValueError("STOCK_BINARY_IDENTITY_MISMATCH")
    print("Pinned stock test runtime prepared; no process was launched.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--archives", type=Path)
    args = parser.parse_args()
    prepare(args.output, args.archives)
