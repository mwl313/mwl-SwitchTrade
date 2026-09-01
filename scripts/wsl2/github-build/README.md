# SwitchTrade WSL2 kernel build

This directory is the SwitchTrade-side source of truth for the reproducible custom-kernel build. Make
and validate changes here, then mirror the same tracked files to the separate kernel build repository.
The two copies must match before a kernel release is considered synchronized.

The GitHub Actions workflow checks out Microsoft's WSL2 Linux kernel, enables every driver in the
production hardware matrix, embeds the pinned firmware contract, and produces the kernel image,
module archive, checksums, manifest, and installation notes. The qualified default tag is
`linux-msft-wsl-6.18.35.2`.

To add an already-upstream driver, append space-separated `CONFIG_DRIVER=m` entries through
`extra_kernel_config`. If it needs firmware, add `vendor/file.bin=https://...` entries through
`extra_firmware`. The build validates symbols, values, relative paths, and fails when `olddefconfig`
changes a requested setting.

The executable matrix currently requires `rtl8xxxu`, `mt76x0u`, `mt76x2u`, `rt2800usb`, and
`rtw88_8821cu`. The workflow fails if any required kernel symbol, module, pinned firmware file, or
artifact hash is absent. Maturity notes and excluded-card research stay in the main repository's
engineering documentation and are not part of the user-facing runtime contract.
