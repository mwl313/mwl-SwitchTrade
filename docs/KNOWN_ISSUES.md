# SwitchTrade beta bug register

Last updated: 2026-08-28

This is the field-validation register for the four release blockers observed during private-beta
testing. It separates observed evidence from suspected causes. An issue remains open until its
acceptance checks pass on the affected Windows versions and the relevant two-PC workflow. The full
software and external-validation register is `docs/AUDIT_REPORT.md`.

The 2026-08-27 software audit closed the reproducible code-level causes and added regression tests.
The four entries remain here because their final acceptance requires clean-host, physical-radio, or
two-PC evidence. See `docs/AUDIT_REPORT.md` for the reviewed software finding register.

The replacement installer candidate on `codex/installer-replacement` supersedes the legacy
PowerShell release path for STB-004 validation. It uses an immutable side-by-side WSL runtime, one
atomic active pointer, a desktop-owned release manifest, pre-commit rollback, and deferred
post-commit cleanup. Automated fault injection and a disposable real-WSL lifecycle pass; STB-004
still requires the clean Windows 10/11 Burn lifecycle matrix before closure.

## Resolved installer lifecycle defects

The following observed failures are closed in source and remain part of clean-host qualification:

- Reopening the same Install after interruption now performs deterministic recovery instead of
  returning `SETUP_TRANSACTION_INCOMPLETE`; explicit Repair uses the same path.
- A verified newer package may compensate only an early fresh-install transaction that cannot yet
  contain committed runtime data. Later phases still require the exact manifest identity.
- Unrelated legacy `SwitchTrade.previous` or uncommitted application trees are preserved under the
  local recovery directory instead of blocking Setup or being deleted.
- New transactions bind the package manifest SHA-256, so moving or re-extracting byte-identical setup
  files does not prevent Repair; a changed manifest is rejected.
- An unconfirmed WSL import remains nonterminal for the next recovery pass instead of being falsely
  published as compensated.
- Setup actions are derived from the invoking user's committed/transaction state. Standard uninstall
  removes the owned isolated distro and publishes `uninstalled`, allowing a clean later Install.
- Burn's package-cache directory ends with a separator. The replacement provisioner previously
  appended another separator during containment checks and falsely returned `PAYLOAD_PATH_ESCAPE`
  as Windows error `0x8007001e`. Package roots are now normalized, Burn passes the cache root
  safely through its executable location, and a Burn-layout lifecycle regression test covers the
  exact execution path. Burn also receives a sanitized structured provisioner log and a standard
  installer failure code.
- Candidate `beta-d0e3f825439f` was rejected after field testing proved that WiX incremental output
  had embedded the older `beta-test` bundle, `beta-31d37b3b2707` manifest, and old provisioner even
  though the outer build result named the new release. Release builds now force WiX `Rebuild`, extract
  the finished Setup EXE, and compare the embedded release, provisioner, and payload hashes before
  accepting the artifact.
- Candidate `beta-9a58b1a82612` reached the real WSL runtime stage but failed with
  `WSL_E_CUSTOM_KERNEL_NOT_FOUND` when the custom kernel was stored below a non-ASCII Windows user
  profile. The earlier disposable lifecycle used a fake profile path, so WSL ignored that test
  `.wslconfig` and silently booted its stock kernel. The provisioner now keeps the verified kernel in
  SID-scoped, ACL-protected ASCII ProgramData storage. The package lifecycle gate uses the real user
  `.wslconfig`, proves the packaged custom kernel boots, and restores the prior file exactly. Direct
  default-path Repair, backend health, and Uninstall now pass on the affected Korean-profile host.

## Status and priority

- **Confirmed**: reproduced or proven from runtime evidence and source inspection.
- **Investigating**: the failure is real, but the lowest failing layer is not yet proven.
- **Fix ready for validation**: code is complete but has not passed the required external test.
- **Closed**: the acceptance checks passed and the result was recorded.
- **P0**: blocks or seriously misdirects the core two-player trading workflow.
- **P1**: important reliability or recovery defect that does not always block trading.

## Open issues

### STB-001 — Connect reports a full/in-use room when the partner is absent

- **Priority:** P0
- **Status:** Root cause confirmed; software fix implemented; physical validation pending
- **Scope:** Windows 10 and Windows 11 desktop clients; creator and joiner paths must both be tested.
- **Observed build:** `0.2.0-beta.1`

#### User-visible behavior

Pressing **Connect this Switch** in a room containing only the local trainer eventually shows:

> This Trade Room already has two players or is already in use.

The authoritative snapshot from the reproduced room contained one online member, no partner, and no
active connection attempt. The room was therefore neither full nor already in use.

#### Confirmed cause

`POST /api/v1/trade-room/connect` marks the local member ready and waits up to 20 seconds for exactly
two online, ready members. When that condition is not reached, the control service returns HTTP 409
with the correct detail:

> both trainers must press Connect this Switch before the attempt starts

The desktop client's error mapper replaces every unrecognized HTTP 409 response with the unrelated
room-full message. The UI also enables Connect before the partner is present and does not explain the
20-second coordination window.

#### Temporary workaround

Both trainers must first be visible in the same Trade Room, then both press **Connect this Switch**
within the current coordination window. Do not reinstall WSL for this message.

#### Required fix

1. Give control/relay failures stable machine-readable error codes and preserve their specific user
   messages in the desktop client. Only an actual `room_full` response may display the full-room text.
2. Disable or replace Connect with **Waiting for partner** until two online members are present.
3. Display each member's ready state and an explicit waiting state after the local trainer presses
   Connect; do not present normal coordination as an error.
4. Replace the hidden request-bound 20-second rendezvous with an asynchronous authoritative ready
   flow, or visibly expose a bounded timeout with a safe retry.
5. Clear stale attention banners when a newer authoritative room snapshot resolves their cause.

#### Candidate implementation

The `audit` candidate replaces automatic creator assignment with two explicit actions: **I am the
Group Leader** and **I am Joining**. The buttons remain unavailable until both room members are
present. The relay atomically accepts exactly one of each role, and the desktop preserves the
specific coordination errors instead of converting them to a room-full message. Automated
authority/control tests pass; real two-PC validation is still required before closure.

#### Acceptance checks

- With one member, Connect cannot produce a room-full error and the UI clearly waits for a partner.
- With two members, either trainer may press first and remain ready without a fragile timing race.
- Creator-first and joiner-first role-inversion paths both create exactly one attempt.
- A genuinely full public room still produces a distinct, correct room-full message.
- Disconnect, reconnect, room close, and retry do not retain a stale 409 banner.

---

### STB-002 — A post-install RTL8192EU is detected but cannot attach when connection starts

- **Priority:** P0
- **Status:** Fix ready for validation
- **Scope:** Product-wide when RTL8192EU `0bda:818b` is selected before Windows has shared it.
- **Observed builds:** `v0.2.0-win10test.3` lineage and replacement release
  `beta-ebe588645b48`.

#### User-visible behavior

The installed application and local backend start, and the adapter appears valid and selectable. On
**Connect this Switch**, the attempt stops with:

> The selected adapter could not be attached. Run SwitchTrade Setup Repair once if it is not shared.

This is not evidence that WSL is absent: the installed client reached the running local control
service and hardware-selection path. It is a failure between Windows USB ownership, `usbipd-win`, the
isolated SwitchTrade distro, and Linux driver/radio readiness.

#### Confirmed evidence (2026-08-28 laptop support bundle)

- The control service selected exact Windows InstanceId `USB\\VID_0BDA&PID_818B\\...` at current
  bus `2-4`; the relay and local control service were both ready.
- Two independent quick diagnostics, at 02:19 and 02:37 UTC, produced the same result: WSL
  `lsusb -d 0bda:818b` returned no device and no USB driver-binding path existed.
- The packaged custom kernel was running as `6.18.35.2-microsoft-standard-WSL2+`.
- The kernel contained and could inspect `rtl8xxxu.ko`; its aliases explicitly included
  `usb:v0BDAp818B`, and the matching `rtl8192eu_nic.bin` firmware declaration was present.
- Therefore this incident failed before Linux driver binding. It is not evidence of receive death,
  missing firmware, a bad RTL8192EU, or an absent WSL backend.
- A similarly worded error must not be treated as one condition: **detected**, **shared**, **attached**,
  **USB-visible in WSL**, **driver-bound**, and **radio-ready** are separate gates.

#### Confirmed software root cause

The replacement installer correctly permits installation without a radio and installs
`usbipd-win`, but the post-install UI only persisted the selected adapter. The local control service
then ran `usbipd attach` without first checking or performing the administrator-only `usbipd bind`.
Its Repair endpoint called the same attach function, so an unshared card entered a deterministic
repair loop. The attach subprocess output was discarded, which is why the support bundle could prove
that USB never reached WSL but could not preserve the Windows error explaining why.

#### Temporary recovery

For builds before this fix, run elevated `usbipd bind --busid <CURRENT_BUSID>` once, then retry the
connection. Do not use `--force`. The current bus ID must be read from `usbipd list` immediately before
binding. New builds expose this as **Authorize adapter** and re-resolve the exact InstanceId before
mutation.

#### Required fix

1. Authorize a selected physical device on demand with elevation and verify the final `usbipd-win`
   state. Install remains independent of hardware availability.
2. Resolve devices by stable USB identity and current bus ID at action time; never reuse an obsolete
   bus ID after restart or replug.
3. Make normal launch attach an already-shared adapter to the isolated `SwitchTrade` distro and report
   the exact failed stage.
4. Add an end-to-end radio gate: Windows presence -> shared -> attached -> `lsusb` visibility -> kernel
   driver bound -> `iw phy`/interface available -> RX health.
5. Show those stages separately in Settings and offer a targeted recovery action for the failed gate.
6. Ensure the packaged app, Setup repair flow, and post-reboot continuation use the same manifest,
   distro name, relay configuration, and hardware profile on Windows 10.

#### Evidence required from the affected machine

- Redacted SwitchTrade support bundle and Setup log from the failed run.
- `usbipd list`, Windows build, installed `usbipd-win` version, and `wsl --list --verbose`.
- Inside the `SwitchTrade` distro: `lsusb`, `iw dev`, `iw phy`, bound driver/module, and filtered USB
  probe messages. No Nintendo keys or unrelated machine inventory are required.

#### Acceptance checks

- Clean Windows 10 22H2 install, required reboot, first launch, and RTL8192EU selection succeed.
- Install and Repair both leave the selected adapter in a verified recoverable ownership state.
- Unplug/replug and reboot may change bus ID without breaking device selection or attach.
- A healthy adapter reaches radio-ready twice consecutively without manual shell commands.
- Each injected failure reports its exact stage and recovery action; no generic attach message hides a
  Linux driver or RX-health failure.
- The same package retains the existing Windows 11 lifecycle behavior.

#### Implemented correction

The control API now publishes separate `shared` and `attached` gates and returns stable
`adapter_not_shared`, `adapter_attach_failed`, and `adapter_attach_verification_failed` envelopes.
The native client presents **Authorize adapter**, elevates the installed native provisioner, and the
provisioner re-resolves the exact InstanceId and current bus ID before non-forced bind. It verifies the
shared state before the unprivileged control service attaches to WSL. Attach exit details are now
redacted into the support log. Automated unshared, changed-bus, identity-mismatch, final-verification,
and desktop recovery tests pass; clean Windows 10/11 physical RTL8192EU repetition remains required.

---

### STB-003 — Cold WSL start leaves RTL8192EU attached but driver-unbound

- **Priority:** P0
- **Status:** Fix ready for validation
- **Scope:** Any cold isolated-WSL start where module autoload does not run; reproduced on Windows 11
  with RTL8192EU `0bda:818b`.

#### Evidence

Windows and `usbipd-win` reported bus `4-18` as attached, and WSL `lsusb` saw `0bda:818b`. The tested
custom kernel, matching `rtl8xxxu` module, device alias, and firmware were present. Nevertheless,
`rtl8xxxu`, `cfg80211`, and `mac80211` were not loaded, the USB interface had no driver, and `iw`
reported no `nl80211` PHY. RX testing therefore never began.

The preparation script labels RTL8192EU as strategy `vanilla` and fails immediately when automatic
binding produced no interface. It explicitly loads a module only for `vanilla-then-module` profiles,
so success currently depends on module state left by an earlier run.

#### Required fix and acceptance

- Explicitly load the profiled vanilla module before declaring that no interface exists.
- Verify USB alias, module ABI, firmware, driver binding, PHY, interface, channel change, and RX as
  separate named gates.
- Pass from a cold WSL shutdown, after Windows reboot, and after unplug/replug without manual shell
  commands; repeat twice to catch retained-module false positives.

The audit candidate explicitly loads `rtl8xxxu`, captures fatal dmesg signatures across module load,
serializes radio ownership, exports the actual PHY, and separates non-destructive RX-inconclusive from
explicit USB reset recovery. A fake-sysfs Linux workflow now exercises cold load, PHY handoff, lock
contention, both RX paths, and fatal driver warnings. Physical cold-start repetition remains pending.

---

### STB-004 — Failed Repair can leave Windows and WSL components on different revisions

- **Priority:** P0
- **Status:** Fix ready for clean-machine validation
- **Scope:** Install/Update/Repair transaction ordering.

#### Evidence

Repair was launched from package `9d048d4`. It provisioned `/opt/switchtrade`, retained
`/opt/switchtrade.previous`, then failed the radio gate before the Windows application swap. The
installed Windows manifest remained older main build `ece57f9`. Setup therefore crossed a commit
boundary before all required gates passed and did not restore the previous WSL runtime on failure.

The progress dialog also discarded the actionable child output and displayed only the umbrella text
“SwitchTrade driver/RX health gate failed,” hiding whether USB, driver, PHY, channel, or RX failed.

#### Required fix and acceptance

- Stage both Windows and WSL revisions, validate them, then commit both or roll back both.
- Persist the complete Setup log and display the exact failed gate plus one recovery action.
- Fault-inject every stage of Install, Update, and Repair and verify that the active Windows manifest,
  WSL runtime, kernel state, and rollback metadata always describe one coherent release.

The audit candidate introduces one persisted release transaction, staged WSL readiness, distro
ownership markers, exact Windows/WSL/control release identity, kernel A/B hash validation, reverse-order
compensation, and a global Setup mutex. A pre-mutation rollback journal binds the verified initiating
package and exact Windows/WSL/kernel anchors. Separate PowerShell processes now terminate after every
rollback axis and before metadata publication; a fresh Repair converges and reverse Rollback passes.
Temp-root Setup, kernel, and process-death simulations pass. Clean-host
Install/Repair/Update/Rollback/Uninstall remain external gates.

---

### STB-005 — Diagnostic exports expose an internal WSL path instead of a Windows file

- **Priority:** P2
- **Status:** Partially fixed; support-file export remains open
- **Scope:** Settings → Connection → Run read-only diagnostics and Settings → Support → Create
  support file.

The backend creates the diagnostic report and redacted support ZIP under `/root/.local/state/...`
inside the isolated WSL runtime. The desktop displays that Linux path directly, so a normal Windows
user cannot browse to the generated file and may reasonably assume the export was lost.

The desktop now writes the complete diagnostic JSON atomically to the current user's redirected
Windows Desktop and displays that Windows path. This passed a live Unicode-profile check on
2026-08-28. The redacted support ZIP still exposes its WSL path, and neither export has an **Open
folder** action yet, so this combined issue is not closed.

#### Required fix and acceptance

- Copy each user-requested export to a documented Windows directory and return that Windows path.
- Add an **Open folder** action; do not require PowerShell or `\\wsl.localhost` navigation.
- Keep the internal WSL copy private and preserve the existing redaction rules.
- Verify Unicode Windows profiles and filenames, repeated exports, missing destination directories,
  and copy failures with an actionable structured error.
- The UI must never present `/root/...` as the only location of a user-requested export.

## Regression rule

Every P0 fix must add automated coverage for its state/error contract and must also pass the relevant
clean-machine or two-PC acceptance checks above. Internal unit tests alone cannot close a USB,
driver, radio, or cross-machine coordination issue.

## Resolved installer incident: markerless post-import distro

An interrupted fresh install on 2026-08-27 completed `wsl --import` but stopped before writing the
per-install distro marker. The registered `SwitchTrade` distro still had the exact transaction-owned
BasePath, but Repair rejected the missing marker as foreign. Recovery now distinguishes missing from
malformed markers and may bootstrap ownership only while the original schema-3 transaction is still
at `importing_distro`, had no prior distro, and the current Lxss BasePath exactly matches the recorded
dedicated path. Malformed markers, changed paths, prior distros, and later phases remain fail-closed.
Package construction also rejects rootfs archives that omit the generic installer marker.
