from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts" / "wsl2" / "github-build"


def test_kernel_workflow_preserves_qualified_runtime_and_expansion_hooks():
    workflow = (SOURCE / ".github" / "workflows" / "build-kernel.yml").read_text(
        encoding="utf-8"
    )

    assert workflow.count("linux-msft-wsl-6.18.35.2") == 2
    assert "include_vendor_8188eu" in workflow
    assert "extra_kernel_config" in workflow
    assert "extra_firmware" in workflow
    for symbol in (
        "CONFIG_RTL8XXXU",
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


def test_experimental_8188eu_patch_is_versioned_with_the_workflow():
    patch = SOURCE / "patches" / "rtl8188eus-linux-6.18-netdev.patch"

    assert patch.is_file()
    assert "eth_hw_addr_set" in patch.read_text(encoding="utf-8")
