# SwitchTrade WSL2 kernel build

This directory is the SwitchTrade-side source of truth for the reproducible custom-kernel build. Make
and validate changes here, then mirror the same tracked files to the separate kernel build repository.
The two copies must match before a kernel release is considered synchronized.

The GitHub Actions workflow checks out Microsoft's WSL2 Linux kernel, enables the required Wi-Fi
drivers, embeds selected RTL8188EU/RTL8192EU firmware, and produces the kernel image, module archive,
checksums, manifest, and installation notes. The qualified default tag is
`linux-msft-wsl-6.18.35.2`.

To add an already-upstream driver, append space-separated `CONFIG_DRIVER=m` entries through
`extra_kernel_config`. If it needs firmware, add `vendor/file.bin=https://...` entries through
`extra_firmware`. The build validates symbols, values, relative paths, and fails when `olddefconfig`
changes a requested setting.

`include_vendor_8188eu=true` is an opt-in experiment for diagnosing RTL8188EU firmware-start behavior
over WSL USB/IP. It builds `SimplyCEO/rtl8188eus` commit
`b5f02e742fad6ae27d893ffae62d05e27374c0ed`, applies the pinned Linux 6.18 netdev bookkeeping patch,
and adds `8188eu-vendor.ko`. The default remains false. Do not make it a distribution default until it
passes the same observe, join, host, full-trade, and soak gates as the beta adapter.
