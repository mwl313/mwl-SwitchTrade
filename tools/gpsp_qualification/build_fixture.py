"""Build only the licensed attach qualification homebrew; no runtime install."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
DEPENDENCY = "c61bf351f68ad2d6e1c9d72d70e21bec19adfc0b"


def build(toolchain: Path, dependency: Path, output: Path, source_name: str = "main.cpp"):
    dependency = dependency.resolve(strict=True)
    git = ["git", "-c", f"safe.directory={dependency.as_posix()}", "-C", str(dependency)]
    if subprocess.check_output(git + ["rev-parse", "HEAD"], text=True).strip() != DEPENDENCY:
        raise RuntimeError("FIXTURE_DEPENDENCY_IDENTITY_MISMATCH")
    if subprocess.check_output(git + ["status", "--porcelain"], text=True).strip():
        raise RuntimeError("FIXTURE_DEPENDENCY_DIRTY")
    compiler = toolchain / "bin/arm-none-eabi-g++.exe"
    version = subprocess.check_output([str(compiler), "--version"], text=True).splitlines()[0]
    if "14.2.Rel1" not in version or "14.2.1 20241119" not in version:
        raise RuntimeError("FIXTURE_COMPILER_IDENTITY_MISMATCH")
    output.mkdir(parents=True, exist_ok=False)
    source = ROOT / "tests/fixtures/rfu/gpsp-attach"
    flags = ["-mcpu=arm7tdmi", "-marm", "-ffreestanding"]
    def run(args):
        subprocess.run([str(a) for a in args], check=True)
    run([toolchain / "bin/arm-none-eabi-gcc.exe", "-c", source / "crt0.s", "-o", output / "crt0.o", *flags])
    run([compiler, "-c", source / source_name, "-o", output / "main.o", "-I", dependency / "lib", *flags,
         "-std=gnu++17", "-O2", "-fno-builtin", "-fno-exceptions", "-fno-rtti", "-fno-use-cxa-atexit",
         "-fno-unwind-tables", "-fno-asynchronous-unwind-tables", "-ffunction-sections", "-fdata-sections",
         "-frandom-seed=gpsp-attach", "-DLINK_DEVELOPMENT"])
    run([compiler, output / "crt0.o", output / "main.o", "-o", output / "attach.elf", "-nostdlib",
         *flags, "-T", source / "linker.ld", "-Wl,--gc-sections", "-Wl,--build-id=none"])
    run([toolchain / "bin/arm-none-eabi-objcopy.exe", "-O", "binary", output / "attach.elf", output / "attach.gba"])
    undefined = subprocess.check_output([str(toolchain / "bin/arm-none-eabi-nm.exe"), "-u", str(output / "attach.elf")], text=True)
    if undefined.strip():
        raise RuntimeError("FIXTURE_UNDEFINED_SYMBOLS")
    result = {"dependency": DEPENDENCY, "compiler": version,
              "sha256": hashlib.sha256((output / "attach.gba").read_bytes()).hexdigest()}
    print(json.dumps(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("toolchain", "dependency", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--source-name", choices=("main.cpp", "host_probe.cpp", "qualification.cpp"), default="main.cpp")
    build(**vars(parser.parse_args()))
