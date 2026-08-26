# SwitchTrade beta package

The bootstrap installs and provisions only the named `SwitchTrade` distribution. When a verified
custom-kernel bundle is supplied and the user accepts the global warning, it merges only SwitchTrade's
kernel settings into the user's global `.wslconfig` and retains the complete prior file for rollback.

## Build

1. Install the pinned test/runtime dependencies under Python 3.12 or newer.
2. Run `apps/desktop/Publish.ps1 -Output artifacts/native/SwitchTrade` to build the self-contained native
   Windows executable.
3. Commit the exact source being packaged; the builder refuses a dirty worktree.
4. Internal QA may run `installer/Build-Package.ps1 -Rootfs PATH -DesktopExe
   artifacts/native/SwitchTrade/SwitchTrade.exe`. Its bootstrap only runs when explicitly passed
   `--allow-unsigned-package`.
5. A release build passes `-Release` plus the rootfs, desktop EXE, kernel, modules, signed kernel
   manifest, pinned `usbipd-win` MSI, approved notice file, non-loopback HTTPS relay, code-signing
   certificate thumbprint, and timestamp URL. Missing inputs fail the build before publication.

The schema-2 package manifest hashes every shipped file. A release manifest has a detached CMS
signature chained to a trusted code-signing certificate; the bootstrap verifies that signature, every
SHA-256 digest, missing files, and unexpected files before PowerShell can run. The desktop and setup
executables are also Authenticode-signed before their final hashes are recorded.

Pass `-Rootfs PATH` to include a versioned minimal WSL rootfs. Without it, the resulting archive is an
internal upgrade/repair package for a machine that already has the `SwitchTrade` distro; a clean
install intentionally fails with an exact missing-rootfs error.

`Build-Rootfs.sh OUTPUT.tar.gz` creates a minimal x86-64 Ubuntu rootfs with no kernel. The package
builder records a SHA-256 checksum and setup verifies it before import. The kernel remains a separate
release input because WSL distributions do not contain the WSL kernel.

Kernel module `.vhd`/`.vhdx` inputs are the only artifacts written to WSL's `kernelModules` setting.
The kernel repository currently produces `modules-<release>.tar.gz`; setup installs that archive under
`/lib/modules` in the isolated distro, runs `depmod`, and verifies the running release, `rtl8xxxu`
vermagic, required firmware, profiled USB binding, and actual packet RX. Treating a tar archive as a
modules VHD is a release-blocking error.

The packaged `SwitchTrade.exe` is a native WPF application. It does not embed or launch Electron,
Chromium, WebView2, or the user's browser. On an installed copy it starts the adjacent WSL launcher
and communicates with the modular runtime through the localhost JSON control API.

Double-clicking `SwitchTradeSetup.exe` opens a native guided setup window. It exposes only the safe
Install/Update/Repair/Rollback/Uninstall actions available for the current state, requires explicit
prerequisite/global-kernel consent, lists profiled USB radios by bus ID, labels experimental choices,
and permits adapter setup to be deferred. Command-line actions remain available for automated QA.

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
- If enabling WSL or installing `usbipd-win` requires a restart, setup persists only non-secret setup
  options and registers a per-user RunOnce continuation. The same package is re-verified when setup
  resumes after sign-in.
- A managed-PC policy denial while starting the custom kernel restores the previous `.wslconfig` and
  reports `CUSTOM_KERNEL_BLOCKED_BY_POLICY`; such systems are unsupported by the private beta.

The localhost relay default is for internal same-machine validation. A cross-network beta must supply
a reachable HTTPS relay URL through `Build-Package.ps1 -Release`; the installed `config.json` is
verified against the signed package manifest on every launch. Relay hosting is documented in
`relay/DEPLOYMENT.md`, and user-safe recovery is documented in `docs/70`.
