import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "verify_kernel_artifact", ROOT / "scripts" / "verify-kernel-artifact.py"
)
VERIFIER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(VERIFIER)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifact(tmp_path: Path) -> Path:
    release = "6.18.35.2-test"
    kernel = tmp_path / "bzImage-wsl-st"
    firmware = tmp_path / "firmware-manifest.sha256"
    modules = tmp_path / f"modules-{release}.tar.gz"
    kernel.write_bytes(b"kernel")
    firmware.write_text("firmware hash list\n", encoding="utf-8")
    with tarfile.open(modules, "w:gz") as archive:
        for module in VERIFIER.REQUIRED_MODULES:
            info = tarfile.TarInfo(f"{release}/kernel/{module}")
            info.size = 1
            archive.addfile(info, io.BytesIO(b"x"))
    (tmp_path / "manifest.json").write_text(json.dumps({
        "schema": 1,
        "kernel_release": release,
        "kernel_sha256": _sha(kernel),
        "modules_sha256": _sha(modules),
        "firmware_sha256": _sha(firmware),
        "experimental_vendor_8188eu": False,
    }), encoding="utf-8")
    return tmp_path


def test_kernel_artifact_verifier_accepts_complete_matching_bundle(tmp_path):
    result = VERIFIER.verify(_artifact(tmp_path))

    assert result["kernel_release"] == "6.18.35.2-test"


def test_kernel_artifact_verifier_rejects_hash_mismatch(tmp_path):
    artifact = _artifact(tmp_path)
    (artifact / "bzImage-wsl-st").write_bytes(b"replaced")

    try:
        VERIFIER.verify(artifact)
    except ValueError as error:
        assert str(error) == "kernel_sha256 mismatch"
    else:
        raise AssertionError("mismatched artifact was accepted")
