# SwitchTrade replacement installer execution plan

**Status:** authoritative implementation plan  
**Date:** 2026-08-27  
**Scope:** Windows installer, immutable WSL runtime, mandatory custom kernel, lifecycle, migration, and post-install hardware onboarding

This plan supersedes the current PowerShell installer-engine design for all new implementation work. The existing engine remains available only as legacy behavior, migration evidence, and an uninstall reference until the replacement passes qualification.

## 1. Locked product decisions

1. The product exposes exactly three lifecycle actions: **Install**, **Repair**, and **Uninstall**.
2. The action remains named **Repair**. Repair does not diagnose or patch individual components; it replaces SwitchTrade-owned software with a verified fresh installation.
3. The SwitchTrade custom WSL kernel is mandatory. Installing SwitchTrade is consent to activate that kernel globally for WSL 2.
4. The installer must preserve unrelated `.wslconfig` settings and must be able to restore the pre-SwitchTrade kernel configuration.
5. A Wi-Fi adapter is not required during installation or Repair.
6. Adapter selection, USB attachment, driver loading, and RX validation happen after installation in the application's Hardware Setup flow.
7. Microsoft WSL and unrelated WSL distributions are shared host resources and are never removed by SwitchTrade Uninstall.
8. `usbipd-win` is installed as a prerequisite but retained by default on Uninstall because it may be shared by other applications.
9. The relay server, room availability, Switch availability, and physical radio health are runtime concerns and cannot determine installer success.
10. No live Python package download or Linux application assembly is allowed on a user machine.

## 2. Target package architecture

```text
SwitchTradeSetup.exe                 WiX Burn bundle and standard setup UI
├── SwitchTrade.Desktop.msi         native WPF client, provisioner, configuration, shortcuts
├── usbipd-win.msi                  pinned prerequisite, conditionally installed
├── SwitchTradeProvisioner.exe      native, idempotent WSL/kernel lifecycle helper
├── SwitchTrade-<release>.wsl       immutable, fully provisioned Linux appliance
├── kernel/
│   ├── kernel                      mandatory custom WSL kernel
│   ├── modules payload             matching modules in the validated WSL format
│   └── manifest.json               release, ABI, hashes, drivers, and firmware identity
└── release-manifest.json           hashes and compatibility contract for every payload
```

WiX Burn owns standard Windows packaging, elevation, prerequisite chaining, package caching, reboot continuation, MSI repair, and uninstall registration. `SwitchTradeProvisioner.exe` owns only SwitchTrade-specific WSL distribution and kernel operations.

## 3. Stable runtime boundaries

The replacement must preserve these application contracts until a separately tested migration changes them:

- Local control API: `http://127.0.0.1:8787`
- Remote relay URL from the installed release configuration
- Native desktop application remains self-contained
- WSL backend starts from `/opt/switchtrade`
- Provisioner status is exposed as versioned JSON, not English text
- Persistent local state is outside replaceable WSL distributions

The launcher will stop hardcoding one WSL distribution name. It will read an atomic active-runtime record:

```json
{
  "schema": 1,
  "active_runtime": "SwitchTrade-beta-<release>",
  "previous_runtime": "SwitchTrade-beta-<prior-release>",
  "kernel_release": "<kernel-release>"
}
```

## 4. Lifecycle semantics

### 4.1 Install

Install is available only when no SwitchTrade installation is active.

1. Verify the complete package and free-space requirement.
2. Record the invoking user and the untouched pre-SwitchTrade kernel configuration.
3. Enable/install the supported modern WSL prerequisite when necessary; resume after reboot through Burn.
4. Install or upgrade the pinned `usbipd-win` prerequisite.
5. Install the versioned kernel and matching modules.
6. Merge the mandatory SwitchTrade kernel values into `.wslconfig` without changing unrelated settings.
7. Install the immutable versioned `.wsl` distribution.
8. Start it and run software-only health checks.
9. Install the desktop MSI and write the active-runtime record.
10. Finish successfully even when no USB Wi-Fi adapter exists.

If an active, partial, or legacy SwitchTrade installation is found, Install performs no mutation and offers Repair.

### 4.2 Repair

Repair is a fresh replacement, not diagnostic patching.

1. Verify the replacement package before modifying the current installation.
2. Verify ownership of every SwitchTrade distribution or path that may later be removed.
3. Install a fresh versioned WSL runtime beside the current runtime.
4. Reinstall the mandatory kernel/modules and reassert the owned `.wslconfig` values.
5. Reinstall the desktop MSI payload.
6. Start and health-check the fresh runtime.
7. Atomically switch the active-runtime record.
8. Remove the prior SwitchTrade-owned runtime and obsolete SwitchTrade application files.
9. Clear obsolete legacy installer transactions and staging paths.
10. Finish successfully without a connected Wi-Fi card.

If Repair is interrupted, rerunning Repair discards only uncommitted SwitchTrade-owned staging resources and repeats the clean replacement. It does not infer dozens of legacy mutation phases.

### 4.3 Uninstall

Uninstall performs a complete removal of SwitchTrade-owned software:

- Stop the desktop application and local backend.
- Remove every recorded, ownership-verified SwitchTrade WSL runtime.
- Remove SwitchTrade desktop files, shortcuts, provisioner, watcher, state, cache, and non-exported local application data.
- Restore the recorded pre-SwitchTrade `kernel` and `kernelModules` configuration while preserving unrelated `.wslconfig` settings added later.
- Delete SwitchTrade-owned kernel/module files after configuration restoration is proven.
- Run `wsl --shutdown` so the restored configuration takes effect.

Uninstall does **not**:

- Disable or uninstall Microsoft WSL.
- Remove Ubuntu or any unrelated distribution.
- Remove `usbipd-win` by default.
- Remove user-exported files outside SwitchTrade-owned directories.
- Delete server-side account or relay data.

If the current `.wslconfig` kernel values no longer match the recorded SwitchTrade-owned values, Uninstall preserves the file, writes a recovery backup, and reports one precise manual-resolution action instead of overwriting newer user changes.

## 5. Software and hardware readiness are separate

```text
software_ready
  desktop + WSL + immutable runtime + mandatory kernel + local control health

hardware_unconfigured
  valid installed state; no adapter has been selected

hardware_ready
  selected adapter + usbipd share/attach + driver/PHY/RX health

trade_ready
  software_ready + hardware_ready + compatible relay
```

The installer validates only `software_ready`. The application owns `hardware_unconfigured` and later transitions through Hardware Setup.

## 6. Execution phases

### Phase 0 — Recover disk space before new builds

Create `scripts/cleanup-build-artifacts.ps1` with mandatory `-WhatIf` preview and an explicit allowlist. It must resolve every target under the repository's `artifacts` directory before deletion and refuse reparse points or paths outside that directory.

Preserve until the replacement artifacts are independently reproducible:

- `artifacts/final-package-27d17b1` as the retained rootfs/kernel/modules/usbipd source bundle
- `artifacts/audit-wheelhouse-linux-cp312`
- all golden capture and capture-evidence material
- all `.sqlite3`, `.db`, and project data
- one latest legacy installer ZIP for migration fixtures, clearly labeled unsupported
- any unique kernel artifact whose hash is not already present in the retained source bundle

Delete after the preview manifest is reviewed:

- `artifacts/installer-overhaul-dafb92a-*`
- `artifacts/installer-commandfix-836100b-*`
- duplicate `artifacts/installer-commandfix-921a839-b`
- old `final-package-*` directories except the retained input bundle
- old native publish directories after retaining the current source inputs
- obsolete release-candidate copies already represented by Git/release hashes
- setup probes, smoke outputs, extracted QA copies, and empty validation directories
- duplicate capture bundles only after byte hashes and manifests prove equivalence

Write `artifacts/retained-inputs-manifest.json` before deletion with absolute source name, size, SHA-256, reason retained, and replacement owner. Expected recovery is approximately 10–14 GiB from the current 17.75 GiB artifact tree.

**Exit gate:** retained inputs and evidence have manifests; cleanup dry-run lists only generated outputs; actual cleanup leaves the repository, databases, captures, and retained inputs intact.

### Phase 1 — Freeze the legacy installer

- Tag the final legacy source commit for migration reference.
- Mark the existing PowerShell engine unsupported for new packages.
- Prevent release packaging from accidentally selecting the legacy entry point.
- Keep legacy tests available until migration qualification is complete.

**Exit gate:** no production build path can silently produce the legacy installer.

### Phase 2 — Freeze replacement contracts

- Define the release manifest schema.
- Define the provisioner JSON request, status, progress, and error contracts.
- Define owned Windows paths, WSL names, markers, kernel paths, and data paths.
- Define the active-runtime record and compatibility versions.
- Define the exact pre-SwitchTrade `.wslconfig` backup and compare-and-restore rules.

**Exit gate:** desktop, provisioner, bundle, and tests consume one contract source of truth.

### Phase 3 — Build the immutable `.wsl` appliance

- Add `/etc/wsl-distribution.conf` and deterministic distribution identity.
- Preinstall `/opt/switchtrade`, the virtual environment, all locked Python wheels, firmware, scripts, and release markers.
- Eliminate runtime `pip`, `apt`, and application directory staging.
- Build reproducibly and verify the output on both supported Windows versions using disposable distribution names.

**Exit gate:** the `.wsl` file installs, boots, serves the local health endpoint, and unregisters without the desktop installer or a Wi-Fi adapter.

### Phase 4 — Normalize the mandatory kernel bundle

- Produce a kernel/module payload in the format supported by the minimum accepted Store WSL version.
- Bind kernel, modules, firmware, supported driver profiles, ABI, and hashes in one manifest.
- Validate boot, module loading, and restoration to the prior kernel configuration.

**Exit gate:** kernel activation and restoration pass with absent, existing, comment-heavy, Unicode-path, and user-modified `.wslconfig` fixtures.

### Phase 5 — Implement the native provisioner

Implement a self-contained C# executable with these verbs:

```text
inspect
install
repair
uninstall
verify-software
status --json
```

Requirements:

- Query before mutation and converge on the requested end state.
- Typed process arguments; no constructed shell command lines.
- Bounded timeouts and cancellation.
- Stable stage/error/correlation identifiers.
- Atomic state and active-runtime writes.
- Strict ownership checks before every deletion or unregister operation.
- Minimal operation journal containing requested outcome and committed active runtime, not a detailed diagnostic state machine.
- Repeatable after process termination or reboot.

**Exit gate:** Install, Repair, and Uninstall pass fault injection after every mutating operation without touching unrelated WSL resources.

### Phase 6 — Build the WiX Burn bundle

- Create the per-user desktop MSI.
- Chain the pinned `usbipd-win` MSI conditionally.
- Package the provisioner, `.wsl`, kernel, modules, and manifest.
- Use standard Burn UI and standard reboot continuation initially.
- Present only valid actions: Install when absent; Repair and Uninstall when present or incomplete.
- Keep the visible action name **Repair**.

**Exit gate:** the bundle is one distributable Setup EXE with deterministic payload hashes, Apps & Features registration, reboot continuation, and no dependency on the source folder after installation.

### Phase 7 — Integrate first run and post-install hardware addition

- Make the launcher read the active-runtime record.
- Make the desktop consume provisioner status JSON.
- Add `Set up a Wi-Fi adapter`, `Rescan`, `Diagnose`, `Change adapter`, and `Set up later` actions.
- Keep supported and experimental adapter profiles data-driven.
- Run USB share/attach, driver, PHY, and RX gates only after an adapter is selected.

**Exit gate:** a machine with no Wi-Fi adapter can Install, Repair, launch, browse software settings, and later add a supported adapter without rerunning Setup.

### Phase 8 — Implement legacy migration

- Detect the current fixed-name `SwitchTrade` distribution and legacy transaction files read-only.
- Preserve persistent data and the most trustworthy available pre-kernel backup.
- Remove the legacy distro only when its ownership marker and registered path are proven.
- Convert any interrupted legacy state into a normal Repair request.
- Block ambiguous foreign ownership with one stable error and no mutation.

**Exit gate:** every legacy state captured in the current issue register either migrates through Repair or fails closed without changing the machine.

### Phase 9 — Automated qualification

Run clean snapshots for Windows 10 22H2 x64 and Windows 11 x64 covering:

- No WSL installed
- Modern WSL with no distributions
- Existing unrelated WSL distributions
- Existing and malformed `.wslconfig`
- Non-ASCII user profile and paths with spaces
- No `usbipd-win`
- No Wi-Fi adapter
- Adapter added after installation
- Interrupted Install, Repair, and Uninstall at every mutation point
- Repair of healthy, corrupt, partial, and legacy installations
- Repeated Repair
- Repeated Uninstall
- Low disk, UAC cancellation, policy-blocked custom kernel, and reboot continuation

**Exit gate:** no software-verifiable P0/P1 remains; every failure names its exact stage and recovery action; unrelated WSL state is byte-for-byte/configuration-equivalent after rollback or Uninstall.

### Phase 10 — Physical qualification and cutover

- Install on two clean PCs without adapters attached.
- Add RTL8192EU adapters post-install and pass hardware health.
- Complete the two-PC Switch-to-Switch trade flow.
- Verify Repair returns both PCs to a clean software state.
- Verify Uninstall restores each PC's prior WSL kernel configuration.
- Publish the new package only after these gates pass.

**Exit gate:** the replacement bundle becomes the only supported installer and the legacy package is removed from user-facing releases.

## 7. Work intentionally excluded from installer execution

- Relay deployment
- Protocol changes
- Trade behavior changes
- UI visual overhaul outside setup and hardware onboarding
- Physical adapter qualification beyond the final gate
- Experimental adapter trading guarantees
- Privacy/analytics UI

These resume only after the replacement installer passes its software qualification gates.

## 8. Definition of complete

The replacement is complete only when all of the following are proven:

- Artifact cleanup safely recovered space without losing retained inputs or evidence.
- One immutable `.wsl` artifact contains the complete local backend.
- The mandatory custom kernel is installed on Install/Repair and restored on Uninstall.
- Install is fresh-only.
- Repair always produces a verified fresh replacement and retains the visible name Repair.
- Uninstall removes only SwitchTrade-owned resources while retaining Microsoft WSL, unrelated distributions, and `usbipd-win`.
- Installation and Repair succeed without a Wi-Fi adapter.
- A supported Wi-Fi adapter can be added later entirely through the application.
- Win10/Win11 lifecycle and interruption matrices pass.
- The final Setup EXE is reproducible, integrity-verified, and independent of the extracted source package.

