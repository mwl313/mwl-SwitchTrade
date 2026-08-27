# SwitchTrade beta package

The installer accepts Windows 10 22H2 x64 build 19045 and Windows 11 x64. It rejects older Windows,
Windows Server, and ARM64 because the packaged application and rootfs are x64. A successful
`wsl --version` probe is required; with prerequisite consent, Setup updates legacy inbox WSL through
the native `wsl --update` path before importing the isolated distribution.

The bootstrap installs and provisions only the named `SwitchTrade` distribution. When a verified
custom-kernel bundle is supplied and the user accepts the global warning, it merges only SwitchTrade's
kernel settings into the user's global `.wslconfig` and retains the complete prior file for rollback.
WSL-facing kernel and module files are stored under `%ProgramData%\SwitchTrade\kernel`, whose physical
path is independent of the Windows account name. Per-user state, logs, backups, distro data, and the
daily application remain in their existing `%LOCALAPPDATA%` locations.

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

The builder reads the default relay URL from the tracked `payload/release-config.json`. Pass
`-RelayUrl` only to override it for an explicit local or staged test.
The tracked `legal/THIRD-PARTY-NOTICES.txt` is the default notice inventory; pass `-Notices` only when
building against a separately reviewed replacement.

The owner-approved unsigned private beta uses `-UnsignedPrivateBeta` instead of `-Release`. It still
requires the complete rootfs, desktop, kernel/modules, USB/IP, notice, and public HTTPS relay inputs,
but produces an explicitly named package that can be opened normally after an unavoidable publisher
warning. The signed `-Release` path remains available for a future public release.

The schema-2 package manifest hashes every shipped file. A release manifest has a detached CMS
signature chained to a trusted code-signing certificate; the bootstrap verifies that signature, every
SHA-256 digest, missing files, and unexpected files before PowerShell can run. The desktop and setup
executables are also Authenticode-signed before their final hashes are recorded.

Pass `-Rootfs PATH` to include a versioned minimal WSL rootfs. Without it, the resulting archive is an
internal upgrade/repair package for a machine that already has the `SwitchTrade` distro; a clean
install intentionally fails with an exact missing-rootfs error.

`Build-Rootfs.sh OUTPUT.tar.gz` creates a minimal x86-64 Ubuntu rootfs with no kernel. The package
builder records a SHA-256 checksum and setup verifies it before import. The kernel remains a separate
release input because WSL distributions do not contain the WSL kernel. New rootfs builds include the
small `kmod` bootstrap required to run `depmod` and `modinfo`; Setup installs it on demand when repairing
an older qualified rootfs that predates that inclusion.

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
and permits adapter setup to be deferred. Mutating actions show a native indeterminate progress window
instead of freezing or displaying command output, and successful completion uses a short summary.
Command-line actions remain available for automated QA.

`SwitchTradeSetup.exe` is the launcher for a versioned payload, not the entire 200+ MB package by
itself. Keep the extracted package together only while Setup is running. After a successful install,
the Windows app and WSL runtime are self-contained in their installed locations, so the downloaded ZIP
and extracted package may be deleted. A complete current package must be re-downloaded or retained only
for Update, Repair, Rollback, or Uninstall; daily SwitchTrade use does not read it.

The retired web/demo frontend is not bundled into the WSL runtime or required by the native beta.

## Installer engine

SwitchTradeSetup.ps1 is a thin dispatcher over the layered engine in installer/engine/:

- PlatformOps.ps1 - the single audited native/WSL subprocess boundary. Exact argv (no data in shell strings), bounded processes with cancellation, UTF-16 NUL normalization, distro marker probes/writes, runtime-location probes, kernel module archive/ABI operations.
- StateInspector.ps1 - one read-only normalized snapshot (host, WSL runtime/capabilities, distro identity classification, transaction, Windows/WSL/kernel releases, resume, usbipd). Never repairs while inspecting; unknown enumeration never means absent.
- Planner.ps1 - deterministic pure planner: action + verified package identity + snapshot -> an explicit step plan or a structured blocker (stage, code, recovery action, evidence). Recovery and rollback decisions are parity-tested against the legacy resolvers.
- Executor.ps1 - applies validated plans. Every mutating step persists its checkpoint before mutation and completion after success; compensation is explicit persisted recovery work; identity gates precede every destructive operation; the failure contract carries code/message/stage/recoverable/primary_action/correlation_id/technical_detail_log_path.

The schema-3 transaction, phase vocabulary, distro marker, rollback journal, and RunOnce continuation are unchanged on disk, so interrupted installations from previous versions remain recoverable.

## Setup safety

- `SwitchTradeSetup.ps1 -Action Audit` is read-only.
- `Install` and `Repair` provision the isolated distro and retain the previous `/opt/switchtrade`
  runtime for rollback.
- WSL provisioning builds and self-checks a complete staged runtime from its own application root
  before replacing `/opt/switchtrade`; Setup's Windows or WSL working directory is irrelevant.
- `Uninstall` removes the application files and unregisters only the UUID/BasePath-verified isolated
  `SwitchTrade` distro; unrelated WSL distributions are never selected by name alone.
- Setup changes global WSL kernel selection only when a verified kernel bundle is present and the user
  supplies `--accept-global-kernel-change`; it preserves the prior `.wslconfig` for exact rollback.
- Ordinary launch never self-elevates. Setup/Repair performs binding; daily attach uses that retained
  binding and fails with an exact repair action if administrator work is required.
- If enabling WSL or installing `usbipd-win` requires a restart, setup persists only non-secret setup
  options and registers a per-user RunOnce continuation. The same package is re-verified when setup
  resumes after sign-in. Resume reopens the native progress window and reports the current prerequisite,
  WSL, runtime, kernel, commit, or hardware stage until setup succeeds or shows a targeted failure.
- Reopening the same action or choosing Repair resumes one interrupted transaction through the
  recovery planner. New transactions bind the package manifest SHA-256, so a byte-identical
  re-extraction is accepted while a modified package is rejected. Early fresh-install state
  (including the markerless fresh-import state) is recognized, marker-bootstrapped, and safely
  continued or compensated by a verified package before any runtime data was staged.
- Windows 10 compatibility is qualified against build 19045 with current Microsoft Store WSL. Merely
  having an old `wsl.exe` stub is not treated as a complete WSL installation.
- A managed-PC policy denial while starting the custom kernel restores the previous `.wslconfig` and
  reports `CUSTOM_KERNEL_BLOCKED_BY_POLICY`; such systems are unsupported by the private beta.

The repository default is the public HTTPS relay in `payload/release-config.json`; local development may
override it explicitly. The installed `config.json` is verified against the package's complete hashed
manifest on every launch. A future signed release also authenticates that manifest. Relay hosting is
documented in `relay/DEPLOYMENT.md`, and user-safe recovery is documented in
`docs/TECHNICAL_GUIDE.md#troubleshooting-and-recovery`.
