# Beta distribution preflight checklist — 2026-08-25

> Status: approved architecture, execution intentionally paused.
> Start gate: the owner will add final GUI fixes and feature additions before this checklist begins.
> Distribution target: one `SwitchTradeSetup.exe`, one installed `SwitchTrade.exe`, one hidden isolated
> SwitchTrade WSL runtime, and one separately hosted relay service.

## Already-established foundations

- [x] Native browser-free WPF client builds as a self-contained Windows EXE.
- [x] Minimal SwitchTrade WSL rootfs builds and imports as an isolated named distribution.
- [x] Python control service, RFU endpoint, relay, hardware profiles, health gate, and diagnostics exist.
- [x] Source package includes SHA-256 verification for the rootfs and native EXE.
- [x] Throwaway-distro install, repair, retained rollback runtime, uninstall, and explicit purge passed.
- [x] Pinned WSL runtime suite passed 174 tests without Switch hardware.

## Gate 0 — freeze the beta experience

- [ ] Add the owner's final GUI fixes and feature additions to this checklist.
- [ ] Update `docs/54-native-ui-flow-and-runtime-structure-20260825.md` with the final screen flow.
- [ ] Mark functional, demonstration-only, experimental, and unavailable UI actions explicitly.
- [ ] Freeze the first beta version, supported Windows versions, and RTL8192EU hardware policy.
- [ ] Freeze the public-facing name, icons, license notices, privacy text, and support instructions.

Do not begin installer implementation until Gate 0 is approved.

## Gate 1 — build the one-piece Windows distribution

- [ ] Produce one signed `SwitchTradeSetup.exe` bootstrapper.
- [ ] Embed or checksummably bundle `SwitchTrade.exe`, the minimal rootfs, application runtime,
  hardware profiles, license notices, and release manifest.
- [ ] Install one isolated distro named `SwitchTrade`; never reuse, reset, or delete another distro.
- [ ] Install the daily application under the user's Windows application directory and create one
  normal SwitchTrade shortcut.
- [ ] Hide PowerShell, WSL consoles, and implementation details during ordinary use.
- [ ] Support detect, install, repair, update, rollback, and uninstall modes.
- [ ] Persist installer state and resume safely after a required Windows reboot.
- [ ] Refuse partial or mismatched artifacts using signatures and SHA-256 manifests.

## Gate 2 — prerequisites and first-run setup

- [ ] Detect Windows build, architecture, virtualization, free space, pending reboot, and WSL version.
- [ ] Enable or update WSL 2 and Virtual Machine Platform only after explaining the change.
- [ ] Detect and install a pinned `usbipd-win` version when absent.
- [ ] Detect VMware USB ownership and request consent before changing it.
- [ ] Detect the profiled adapter and distinguish duplicate USB IDs by bus ID.
- [ ] Perform administrator-only USB binding during setup; avoid a daily UAC prompt when normal attach
  can be performed without elevation.
- [ ] Run the same fail-closed USB, driver, module, RX, channel, and role health gate used by sessions.
- [ ] Offer exact repair guidance when automatic recovery is unsafe.

## Gate 3 — SwitchTrade custom WSL kernel

Decision: the beta uses the project-maintained custom WSL kernel because it is the qualified runtime.

- [ ] Consume a signed, versioned kernel and modules artifact from the separate kernel repository.
- [ ] Warn before installation that WSL custom-kernel selection is global to all WSL 2 distributions.
- [ ] Back up the user's complete existing `.wslconfig` before making any change.
- [ ] Merge only the required `kernel` and `kernelModules` values; preserve unrelated settings.
- [ ] Store the previous configuration and kernel-selection metadata for one-action rollback.
- [ ] Use a bounded `wsl --shutdown` when applying or removing the kernel; never unregister unrelated
  distributions.
- [ ] Verify the running kernel, module ABI, firmware, RTL8192EU driver binding, and actual packet RX.
- [ ] Restore the prior configuration during rollback/uninstall when SwitchTrade owns the change.
- [ ] Treat corporate policy that blocks custom WSL kernels as an explicit unsupported condition.

## Gate 4 — make the EXE and WSL behave as one app

- [ ] Add single-instance protection for the Windows client and local runtime.
- [ ] Start the isolated WSL distro and control service automatically and without a terminal window.
- [ ] Replace the ambiguous `BACKEND` label with separate control, relay, radio, and session states.
- [ ] Add bounded startup timeouts, cancellation, retry, repair routing, and actionable errors.
- [ ] Prevent duplicate control, endpoint, or development-relay processes.
- [ ] Decide and document whether closing the window stops everything or leaves an explicit background
  service running.
- [ ] On full shutdown, stop the endpoint and control service cleanly, release the adapter, and allow
  WSL to become idle.
- [ ] Recover safely after an EXE crash, WSL crash, USB removal, or interrupted previous session.
- [ ] Keep radio, driver, and protocol implementation outside the WPF process and behind the local API.

## Gate 5 — production relay

- [ ] Deploy a reachable TLS-protected relay; the localhost relay remains internal-test-only.
- [ ] Configure the relay URL through signed installation configuration rather than hardcoded UI state.
- [ ] Add session expiration, participant limits, heartbeat handling, size limits, and rate controls.
- [ ] Add operational health checks, structured server logs, metrics, retention, and incident procedures.
- [ ] Verify two endpoints behind different NATs and ordinary consumer firewalls.
- [ ] Confirm that the relay forwards opaque envelopes and does not require Pokémon payload decoding.

## Gate 6 — install and lifecycle qualification

- [ ] Test a clean supported Windows machine with neither WSL nor `usbipd-win` installed.
- [ ] Test a machine with existing WSL distributions and a pre-existing `.wslconfig`.
- [ ] Test installation with and without a reboot, including resume after sign-in.
- [ ] Test install, first launch, repeated launch, repair, upgrade, rollback, uninstall, and reinstall.
- [ ] Confirm uninstall removes only SwitchTrade files and optionally only the named SwitchTrade distro.
- [ ] Confirm kernel rollback restores the exact prior WSL configuration.
- [ ] Confirm application logs and support bundles contain no keys, captures, passcodes, or private data
  outside the documented privacy manifest.
- [ ] Verify Windows Defender/SmartScreen behavior and signed artifact trust.

## Gate 7 — hardware and product qualification

- [ ] Qualify both physical RTL8192EU adapters through cold attach, detach/reattach, reboot, RX/TX soak,
  teardown, and immediate reuse.
- [ ] Run two-PC, two-WSL, two-Switch room discovery and entry.
- [ ] Complete movement, chair interaction, trade, animation, save, menu return, graceful exit, and a
  second immediate session.
- [ ] Run LAN and WAN loss, delay, duplicate, reordering, endpoint restart, relay restart, and recovery
  tests with run IDs and support bundles.
- [ ] Confirm the production path does not depend on the PC-to-Switch emulator peer.
- [ ] Keep RTL8188EU quarantined unless it separately passes the full qualification matrix.

## Gate 8 — release approval

- [ ] Sign the bootstrapper, native EXE, kernel, modules, rootfs, manifest, and update metadata.
- [ ] Publish supported hardware, Windows/WSL versions, limitations, privacy behavior, and recovery guide.
- [ ] Preserve one tested previous release for atomic rollback.
- [ ] Archive reproducible build inputs and checksums outside the user package.
- [ ] Approve a private beta only after Gates 0–7 pass or each accepted exception is written here.

## Release result

The beta user experience is considered complete only when a user can download one setup executable,
install with guided consent, launch one native application, connect a supported adapter, and complete
a two-Switch session without opening a browser, WSL terminal, PowerShell, or developer tool.
