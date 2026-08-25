# SwitchTrade beta package

The bootstrap is deliberately split from the WSL kernel decision. It installs and provisions only the
named `SwitchTrade` distribution and never edits the user's global `.wslconfig`.

## Build

1. Install the pinned test/runtime dependencies under Python 3.12 or newer.
2. Run `apps/desktop/Publish.ps1 -Output artifacts/native/SwitchTrade` to build the self-contained native
   Windows executable.
3. Commit the exact source being packaged; the builder refuses a dirty worktree.
4. Run `installer/Build-Package.ps1 -Rootfs PATH -DesktopExe artifacts/native/SwitchTrade/SwitchTrade.exe`.
   Release builds also pass the signed external `-Kernel`, `-KernelManifest`, optional
   `-KernelModules`, pinned `-UsbipdMsi`, and production `-RelayUrl` inputs.

Pass `-Rootfs PATH` to include a versioned minimal WSL rootfs. Without it, the resulting archive is an
internal upgrade/repair package for a machine that already has the `SwitchTrade` distro; a clean
install intentionally fails with an exact missing-rootfs error.

`Build-Rootfs.sh OUTPUT.tar.gz` creates a minimal x86-64 Ubuntu rootfs with no kernel. The package
builder records a SHA-256 checksum and setup verifies it before import. The kernel remains a separate
release input because WSL distributions do not contain the WSL kernel.

The packaged `SwitchTrade.exe` is a native WPF application. It does not embed or launch Electron,
Chromium, WebView2, or the user's browser. On an installed copy it starts the adjacent WSL launcher
and communicates with the modular runtime through the localhost JSON control API.

The retired web/demo frontend is not bundled into the WSL runtime or required by the native beta.

## Setup safety

- `SwitchTradeSetup.ps1 -Action Audit` is read-only.
- `Install` and `Repair` provision the isolated distro and retain the previous `/opt/switchtrade`
  runtime for rollback.
- `Uninstall` removes application files only.
- The distro is unregistered only when `Uninstall -PurgeDistro` is explicitly requested.
- Setup changes global WSL kernel selection only when a verified kernel bundle is present and the user
  supplies `--accept-global-kernel-change`; it preserves the prior `.wslconfig` for exact rollback.
- Ordinary launch never self-elevates. Setup/Repair performs binding; daily attach uses that retained
  binding and fails with an exact repair action if administrator work is required.

The localhost relay default is for internal same-machine validation. A cross-network beta must supply
a reachable HTTPS relay URL in the installed `config.json`.
