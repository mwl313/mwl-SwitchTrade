# SwitchTrade 0.2.0-beta.0 internal build — 2026-08-25

## Outcome

The first production-shaped private/passcode beta is implemented and internally testable without a
Switch. It is not yet hardware-certified or ready for public distribution.

The runtime path is now:

```text
native WPF Windows UI (optional HTML/CSS debug UI)
  -> local control API
  -> profile/role selection
  -> Windows USB ownership preflight
  -> isolated SwitchTrade WSL distro
  -> driver selector + actual-RX health gate
  -> local LDN/Pia/Reliable endpoint
  -> versioned opaque RFU WebSocket tunnel
  -> relay private session
  -> remote endpoint and mirrored Switch room
```

## What was built

### Feature-neutral two-endpoint runtime

- `switchtrade/endpoint.py` maps online group roles to the correct local radio roles. The online host
  joins the leader Switch room; the online guest creates the mirrored room for the joining Switch.
- The leader's actual LDN `application_data` is carried as a tunnel advertisement and reused by the
  remote host transport. A late remote endpoint receives the relay's retained advertisement.
- `bridge/frlgsim/tunnel.py` terminates Pia/Reliable locally and forwards all Reliable AppData as
  opaque bytes. It does not instantiate `TradeEngine` or decode trade/movement/battle opcodes.
- RFU envelopes record protocol version, session, direction, reconnect epoch, sequence, monotonic
  time, player mapping, Reliable flags, and exact payload.
- Queues are bounded; sending while disconnected fails closed; dead-link queued frames are discarded;
  duplicate/out-of-order and retired-epoch frames are rejected; reconnects use new random epochs.

This boundary preserves future feature expansion. FireRed/LeafGreen Union Room movement, trading, and
battles may require activity-specific validation or session setup, but they do not require a new
internet tunnel format merely because their RFU payloads differ.

### Hardware and driver expansion

- `config/wsl-radio-hardware.tsv` remains the single policy registry used by Python, the WSL selector,
  Windows preflight, endpoint role checks, and GUI display.
- RTL8192EU remains the sole automatic beta candidate. RTL8188EU remains quarantined and cannot be
  selected for host/guest sessions.
- Adding a card remains a qualification/profile operation. A new driver module may be supplied by a
  profile artifact without modifying the RFU tunnel, relay, control API, or frontend.
- `scripts/run-beta-endpoint.sh` puts the existing real-RX health gate in front of every product
  endpoint run and applies a bounded watchdog.

### Product control and UI

- Relay-created six-character private groups now work across two independent control API instances.
- The API launches/stops the real WSL endpoint, reports atomic endpoint state, exposes profiles, logs
  every run, and creates privacy-manifest support bundles.
- The supplied Emerald-style UI now drives the real private create/join/start/stop API flow and shows
  backend/hardware state. Public groups remain intentionally demonstrative; the real public directory
  is backlog.
- `apps/desktop/SwitchTrade.Desktop` provides the distributable native WPF client. Its self-contained
  `SwitchTrade.exe` uses native Windows controls and has no Electron, Chromium, WebView2, or browser
  dependency. It starts the installed WSL launcher and uses the same localhost JSON API, so radio,
  driver, and future feature expansion remain behind the modular backend boundary.
- A separate Vite desktop build produces static `index.html`/CSS/JavaScript and is served directly by
  FastAPI for debug/alternate-client use. Node is a build dependency, not a beta runtime dependency.
  Its former blank-screen failure was fixed by guarding Node-only `process.env` access in the browser.

### Bootstrap/package foundation

- `installer/SwitchTradeSetup.ps1` supports audit/install/repair/uninstall and unregisters the WSL
  distro only with the explicit `-PurgeDistro` switch.
- `installer/provision-wsl.sh` atomically stages `/opt/switchtrade`, pins Python dependencies, retains
  the previous runtime, and requires Python 3.12+ because the pinned LDN package uses that syntax.
- `installer/Launch-SwitchTrade.ps1` performs Windows USB ownership/attachment preflight before
  starting the local services.
- `installer/Build-Package.ps1` packages tracked source, the static debug frontend, and an optional
  checksummed native EXE, and refuses a dirty worktree. It can consume a separately built rootfs
  artifact.
- `installer/Build-Rootfs.sh` produced a 44,521,402-byte Ubuntu 26.04 (`resolute`) minimal rootfs. The
  final package embeds it with SHA-256 verification; it does not copy the user's existing Ubuntu
  distribution.
- These scripts do not write `.wslconfig`, select a custom kernel, reset WSL, or modify another distro.
  The future kernel artifact can therefore be added as a versioned installer input without coupling it
  to application features or hardware profiles.

## Internal verification

No Switch or radio was used for this build, as requested.

- Linux/WSL pinned runtime: **174 tests passed**.
- New RFU/control integration subset: **14 tests passed**, including exact bidirectional payloads and
  flags, late advertisement delivery, endpoint restart, separate control API instances, opaque local
  forwarding, mirrored advertisement reuse, fail-closed sends, and quarantined-card rejection.
- Python compilation passed for `switchtrade`, `relay`, and `bridge/frlgsim`.
- PowerShell parser validation passed for all installer scripts; Bash syntax validation passed for the
  provisioning and endpoint launch scripts.
- Native WPF build and self-contained single-file EXE self-test passed. The optional web UI production
  build, TypeScript checking, ESLint, and FastAPI static-serving smoke test also passed.
- A uniquely named throwaway WSL distro passed package checksum verification, clean import,
  provisioning, runtime/profile/UI smoke checks, repair with previous-runtime retention, and explicit
  isolated uninstall/purge. The unrelated `Ubuntu` distro remained installed.

The root pytest configuration now ignores archived/reference repositories. Windows-only execution is
not authoritative for Linux sysfs/LDN tests; the full suite was run inside WSL with the pinned runtime.

## What is still required before calling it a working production beta

1. Qualify both physical RTL8192EU adapters, including the newly purchased matching adapter.
2. Run the first real two-PC/two-WSL/two-Switch passcode session through room entry, movement, trade,
   save, return, exit, and immediate reuse.
3. Run LAN/WAN loss, delay, reconnect, radio recovery, and repeated-session soak tests with captured
   run IDs and support bundles.
4. Test reboot/resume and the same setup/repair/uninstall path on a genuinely clean external Windows
   machine. The kernel choice is intentionally deferred; the current bootstrap does not alter it.
5. Sign the installer and artifacts and add atomic update/rollback release policy.
6. Configure a reachable relay URL for cross-network use. The package's localhost relay default is for
   single-machine/internal validation only.

Until those gates pass, `0.2.0-beta.0` means an internally built beta candidate, not a certified user
release.
