from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts" / "wsl2" / "github-build"


def test_kernel_workflow_preserves_qualified_runtime_and_expansion_hooks():
    workflow = (SOURCE / ".github" / "workflows" / "build-kernel.yml").read_text(
        encoding="utf-8"
    )

    assert workflow.count("linux-msft-wsl-6.18.35.2") == 2
    assert "include_vendor_8188eu" not in workflow
    assert "extra_kernel_config" in workflow
    assert "extra_firmware" in workflow
    for symbol in (
        "CONFIG_RTL8XXXU",
        "CONFIG_MT76x0U",
        "CONFIG_MT76x2U",
        "CONFIG_RT2800USB",
        "CONFIG_RT2800USB_RT35XX",
        "CONFIG_RTW88_8821CU",
        "CONFIG_TUN",
        "CONFIG_TAP",
        "CONFIG_CRYPTO_CCM",
        "CONFIG_CRYPTO_CMAC",
        "CONFIG_USBIP_VHCI_HCD",
    ):
        assert symbol in workflow

    assert '"kernel_release"' in workflow
    assert '"kernel_sha256"' in workflow
    assert '"modules_sha256"' in workflow
    assert '"firmware_sha256"' in workflow


def test_kernel_workflow_uses_the_release_firmware_contract():
    workflow_manifest = (SOURCE / "firmware-manifest.sha256").read_text(
        encoding="utf-8"
    ).splitlines()
    release_manifest = (
        ROOT / "installer" / "replacement" / "runtime" / "firmware-manifest.sha256"
    ).read_text(encoding="utf-8").splitlines()

    assert workflow_manifest == release_manifest
    assert len(workflow_manifest) == 9
    assert all(line.startswith(tuple("0123456789abcdef")) for line in workflow_manifest)
