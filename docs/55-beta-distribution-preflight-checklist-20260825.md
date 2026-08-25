# Beta distribution preflight checklist — 2026-08-25

> Status: Gate 0 contracts are frozen and the second native UI audit has been implemented; final
> GPT/owner visual, asset, legal-notice, and support approval remains before Gates 1–8.
> UI baseline: `docs/56-native-ui-ux-redesign-handoff-20260825.md` and the owner overrides in
> `docs/57-native-ui-overhaul-implementation-report-20260825.md` are the preliminary redesign source.
> Latest UI evidence: `docs/64-second-native-ui-overhaul-implementation-report-20260825.md`.
> Second-overhaul audit: `docs/63-second-native-ui-overhaul-codex-handoff-20260825.md`.
> Final-overhaul handoff: `docs/62-final-ui-overhaul-gpt-handoff-20260825.md`.
> Frozen contracts: `room-control.v1` (`docs/58`), `party-commit.v1` (`docs/59`), and
> `privacy-statistics.v1` (`docs/60`), with the private-beta baseline in `docs/61`.
> Distribution target: one `SwitchTradeSetup.exe`, one installed `SwitchTrade.exe`, one hidden isolated
> SwitchTrade WSL runtime, and separately hosted authoritative group, relay, and consented statistics
> services.

## Already-established foundations

- [x] Native browser-free WPF client builds as a self-contained Windows EXE.
- [x] Minimal SwitchTrade WSL rootfs builds and imports as an isolated named distribution.
- [x] Python control service, RFU endpoint, relay, hardware profiles, health gate, and diagnostics exist.
- [x] The Gen III payload decoder can reassemble RFU blocks and validate/decode complete `.pk3` and
  `.ek3` Pokémon records in fixtures and captured endpoint traffic.
- [x] Source package includes SHA-256 verification for the rootfs and native EXE.
- [x] Throwaway-distro install, repair, retained rollback runtime, uninstall, and explicit purge passed.
- [x] Pinned WSL runtime suite passed 174 tests without Switch hardware.

## Current gate summary and execution order

| Order | Gate | Current state | Release-blocking result still needed |
|---:|---|---|---|
| 1 | Gate 0 | Second overhaul implemented; final approval pending | Approve the native build plus public icons/assets, legal notices, and real support destination |
| 2 | Gates 4–5 contracts | Frozen, not implemented | Build the authoritative two-member room service and the frozen versioned UI/control contracts |
| 3 | Gate 4 local integration | Partial foundations | Make the installed EXE, isolated WSL runtime, health gate, endpoint, decoder observer, logs, and shutdown behave as one product |
| 4 | Gate 5 remote services | Development relay only | Deploy authenticated authoritative rooms, production opaque relay, and optional consented commit ingestion |
| 5 | Gates 1–3 | Packaging foundations only | Build the signed one-piece installer, first-run prerequisite flow, and reversible custom-kernel integration |
| 6 | Gate 6 | Not qualified | Pass clean-machine install, repair, update, rollback, uninstall, privacy, and signing tests |
| 7 | Gate 7 | Waiting for production stack and second RTL8192EU | Pass two-PC/two-Switch hardware, trade, decoder, teardown, reuse, and network-fault qualification |
| 8 | Gate 8 | Not started | Sign, publish, archive, review, and approve the private beta |

Installer implementation remains blocked until the final GPT/owner review closes the last Gate 0 item.

## Next implementation tranche — do this before packaging

1. [x] Give GPT the final handoff/audit and implement its contract-grounded WPF overhaul without
   reintroducing the removed Privacy tab. Evidence is in `docs/64`.
2. [ ] Obtain final owner/GPT visual approval and approve the remaining public icon/logo, legal-notice,
   and real support-destination decisions. This closes Gate 0.
3. [ ] Implement and internally test the authenticated server-authoritative two-member room state
   machine, reconnect tokens, atomic room-creator claims, ordered events, expiration, and recovery.
4. [ ] Refactor the endpoint/control API so stable member/tunnel identity is independent of each
   attempt's room creator/joiner radio role, then connect the WPF state model to verified live events.
5. [ ] Integrate the installed WSL lifecycle, full health/recovery state, logs/support bundles, passive
   decoder party snapshots, and idempotent successful-trade detection without making trading depend on
   decoding or analytics.
6. [ ] Run no-Switch internal tests for simultaneous claims, reconnects, restarts, malformed/stale
   events, decoder fixtures, failed/rolled-back trades, analytics disabled/offline, and UI transitions.
7. [ ] Only after steps 1–6 pass, implement Gates 1–3 packaging and then run Gates 6–8 lifecycle,
   hardware, network, signing, and private-beta qualification.

## Immediate-task scope imported from the current product TODO

This preflight checklist is the release-blocking superset of the immediate tasks in
`docs/50-current-product-demo-todo-20260825.md`. The backlog remains outside beta preflight.

- [ ] Freeze and version the production-beta repository, dependencies, runtime, kernel, driver,
  firmware, and hardware baseline. Covered by Gates 0 and 8.
- [ ] Lock the RTL8192EU beta policy while preserving profile-driven driver/hardware expansion.
  Covered by Gates 0, 2, 3, and 7.
- [ ] Finish the fail-closed Windows/WSL hardware launcher. Covered by Gates 1-4.
- [ ] Finish the universal health gate, all-permitted-channel discovery, watchdog, recovery, and safe
  teardown. Covered by Gates 2, 4, and 7.
- [ ] Finish structured, redacted, rotating run logs and one-action support bundles. Covered by Gates
  4-6.
- [ ] Certify both physical RTL8192EU adapters. Covered by Gate 7.
- [ ] Finish and harden the feature-neutral RFU tunnel, deterministic player mapping, bounded queues,
  backpressure, stale-frame rejection, counters, and reconnect behavior. Covered by Gates 4, 5, and 7.
- [ ] Validate the tunnel without Switch hardware, including recorded replay and network-fault
  injection. Covered by Gates 4 and 7.
- [ ] Complete the local JSON control API for readiness, hardware, authoritative groups, sessions,
  diagnostics, recovery, and shutdown. Covered by Gates 4 and 5.
- [x] Complete and freeze the first-demo native presentation baseline and honest UI-only previews.
  Live authoritative room and party state remain implementation work in Gates 4–5.
- [ ] Integrate the EXE with the installed WSL control service, launcher, health gate, endpoint, logs,
  authoritative lobby, decoder observer, and clean shutdown. Covered by Gates 1, 2, 4, and 5.
- [ ] Deploy the production relay plus authoritative lobby and consented committed-trade statistics
  services. Covered by Gate 5.
- [ ] Run the first real two-endpoint, two-Switch production test. Covered by Gate 7.
- [ ] Run LAN/WAN reliability, fault, recovery, and immediate-reuse testing. Covered by Gate 7.
- [ ] Build, sign, install, repair, update, rollback, uninstall, and qualify the private beta package.
  Covered by Gates 1-8.

## Gate 0 — freeze the beta experience

- [x] Save and incorporate the owner's complete native UI/UX handoff as the redesign baseline.
- [x] Replace the old Emerald/pixel shell with the Linkline WPF presentation foundation and honest
  UI-only flows; backend-dependent screens remain subject to later gates.
- [x] Implement the second native pass: Fluent Light primitives, split views and view models,
  adaptive layouts, stable focus geometry/restoration, High Contrast resources, reduced-motion
  handling, and coordinator-owned active-room state.
- [x] Update `docs/54-native-ui-flow-and-runtime-structure-20260825.md` with the implemented screen flow.
- [x] Mark functional, demonstration-only, experimental, and unavailable UI actions explicitly.
- [x] Freeze a two-member private-group model with server-authoritative membership, connection,
  readiness, room-role, reconnect, leave, and expiration state.
- [x] Formalize stable online membership (`member A`/`member B`) and group ownership separately from
  the per-attempt Switch room roles (`room creator`/`room joiner`). Either member must be able to create
  the Direct Connection room without understanding endpoint, RFU parent/child, AP, monitor, host, or
  guest roles.
- [x] Freeze the authoritative transitions behind the approved room flow: both users prepare, either
  user chooses **Create the room on my Switch**, the server atomically assigns that member as room
  creator, and the other UI automatically changes to **Search for your partner's room** with
  step-by-step Switch instructions.
- [x] Define and freeze conflict/recovery UX against the final server event model for simultaneous
  room-creator claims, creator cancellation, a 5 GHz
  room, radio failure, timeout, member disconnect, and transferring the creator role before RFU starts.
- [x] Freeze the connected-trading-room layout: two side-by-side player panels, each containing that
  player's party in a 2-by-3 grid with empty slots represented explicitly.
- [x] Freeze Pokémon detail behavior: pointer hover toggles a compact stat popover, with keyboard focus
  and click/tap equivalents for accessibility. Only complete, checksum-valid observed records may be
  presented as fact; incomplete or unknown fields must be labeled.
- [x] Freeze the displayed Pokémon fields and terminology, including species, nickname, level, nature,
  held item, moves, IVs, EVs, party stats, OT/trainer identifiers, checksum confidence, and whether a
  field is observed, derived, or unavailable.
- [x] Freeze the committed-trade statistics contract and external privacy/consent workflow before
  implementation: explicit informed consent, purpose, fields, location precision, raw-IP handling,
  retention, deletion/export, access control, and an option that does not upload party or trade
  analytics. Per owner direction, this workflow is administered outside the client.
- [x] Freeze the first beta version, supported Windows versions, and RTL8192EU hardware policy.
- [ ] Approve the final public icon/logo assets, license/legal notices, and real support destination.
  The SwitchTrade name and Linkline direction are frozen; no Privacy tab or client analytics control
  is part of this approval.

Do not begin installer implementation until Gate 0 is approved.

## Gate 1 — build the one-piece Windows distribution

- [ ] Produce one signed `SwitchTradeSetup.exe` bootstrapper.
- [ ] Embed or checksummably bundle `SwitchTrade.exe`, the minimal rootfs, application runtime,
  hardware profiles, license notices, and release manifest.
- [ ] Bundle and install the local Python control API and endpoint runtime with the isolated WSL distro;
  the daily EXE must not depend on a developer checkout, terminal command, browser, or separately
  installed Python environment.
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
- [ ] Discover across every permitted 2.4 GHz channel rather than treating channels 1/6/11 as complete
  coverage, and recognize the likely-5-GHz case with an exact room-recreation instruction.
- [ ] Put the health gate in front of every capture, room-create, room-join, decoder-observer, and
  production session workflow.
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
- [ ] Prove the installed local control API is healthy and version-compatible before enabling Host,
  Join, Ready, or Configuration actions; use a bounded startup/retry/repair flow instead of leaving the
  user at an unexplained `BACKEND OFFLINE` screen.
- [ ] Replace the ambiguous `BACKEND` label with separate control, relay, radio, and session states.
- [x] Add bounded local-service startup probes, retry, a recovery screen, and actionable generic errors.
- [x] Add startup cancellation so retry and shutdown safely supersede an in-flight probe.
- [ ] Add version mismatch handling, retained failure stage, and stage-specific
  automatic/manual repair routing.
- [ ] Prevent duplicate control, endpoint, or development-relay processes.
- [ ] Split endpoint configuration into two independent axes: a stable server-assigned member/tunnel
  identity and a per-attempt server-assigned room creator/joiner radio role. Do not derive local radio
  behavior from group ownership or from the words host/guest in the UI.
- [ ] Support role transition safely: the selected creator-side endpoint discovers/joins the real
  Switch room, while the other endpoint opens the mirrored room. Teardown, re-election, and retry must
  return both adapters to a known healthy state.
- [ ] Subscribe or poll for server-authoritative group membership, both members' ready/online states,
  room-role assignment, radio readiness, Switch connection, trading-room entry, session failure, and
  leave state; never infer the remote member's state from local button clicks.
- [ ] Passively tee both local and remote Reliable AppData streams to a bounded decoder observer at the
  endpoint boundary without delaying, mutating, or making the RFU tunnel depend on decoding.
- [ ] Reassemble party blocks independently by member/direction, publish only complete checksum-valid
  party snapshots through the local control API, and clear them on session teardown.
- [ ] Detect confirmed trading-room entry and render the two side-by-side 2-by-3 party grids; update or
  invalidate the view when the game sends a newer party state.
- [ ] Detect a successful trade commit separately from offer, acceptance, animation, save attempt,
  rollback, communication error, or disconnect. Generate one idempotent committed-trade event only
  after the protocol evidence proves the trade completed.
- [ ] Keep local party presentation functional when statistics upload is disabled or unavailable.
- [x] Decide and document the current close policy: stop an active endpoint session after confirmation,
  close the UI, and leave the installed local control service available for later reuse.
- [ ] On full shutdown, stop the endpoint and control service cleanly, release the adapter, and allow
  WSL to become idle.
- [ ] Recover safely after an EXE crash, WSL crash, USB removal, or interrupted previous session.
- [x] Keep radio, driver, and protocol implementation outside the WPF process and behind the local API.
- [ ] Expose run ID, structured state transitions, RFU/tunnel counters, decoder completeness, recovery
  actions, and a redacted one-action support bundle without exposing passcodes or raw Pokémon data.

## Gate 5 — production relay, authoritative groups, and consented statistics

- [ ] Deploy a reachable TLS-protected relay; the localhost relay remains internal-test-only.
- [ ] Configure the relay URL through signed installation configuration rather than hardcoded UI state.
- [ ] Add authenticated member identities or scoped reconnect tokens so possession of a passcode alone
  cannot overwrite an occupied member, claim both roles, publish readiness, or impersonate a reconnect.
- [ ] Make the service authoritative for group metadata, exactly two member seats, membership version,
  online/ready state, room-creator claim, per-attempt role assignment, session phase, reconnect, leave,
  close, and expiration. Both clients must receive the same ordered state.
- [ ] Implement the room-creator claim as an atomic server operation. If both members claim it, exactly
  one wins and the other receives the join-room instructions; allow an explicit transfer only before
  the RFU session reaches its locked phase.
- [ ] Add session expiration, participant limits, heartbeats, message-size limits, rate controls,
  idempotency keys, and bounded reconnect behavior.
- [ ] Keep the real-time relay an opaque RFU-envelope forwarder. Lobby authority and analytics may be
  separate services or modules, but the relay data path must not decode or persist game payloads.
- [ ] Add a separately authorized committed-trade ingestion API that accepts only locally validated,
  idempotent post-commit records; never upload a mere offer, animation, failed save, rollback, canceled
  trade, or full unrelated party snapshot as a completed trade.
- [ ] Define and version the committed-trade record: UTC timestamp, session/attempt ID, direction and
  member IDs, the two exchanged Pokémon records with validation provenance, and the two trainers'
  explicitly approved trainer/link metadata.
- [ ] If IP and location collection remains enabled, treat them as sensitive personal data: record the
  server-observed source IP in a restricted short-retention security record, use a keyed pseudonymous
  network identifier for statistics, derive only the disclosed coarse region/country from IP, and do
  not claim precise physical location or collect GPS without separate explicit consent.
- [ ] Encrypt committed-trade records in transit and at rest; separate operational, identity, and
  analytics access; audit reads; prevent trainer IDs, raw IPs, or Pokémon payloads from ordinary logs;
  and implement retention expiry, deletion, export, and consent withdrawal.
- [ ] Build aggregate statistics from the minimized analytics record rather than exposing raw trainer,
  IP, location, or Pokémon records to dashboards.
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
- [ ] Verify the externally administered consent is explicit and versioned, declining analytics does
  not block trading or local party display, and uninstall/account deletion can exercise the documented
  server-data deletion path. The client contains no optional analytics/privacy setting.
- [ ] Verify server-side idempotency records exactly one committed trade across retries and records none
  for cancel, rollback, save failure, communication error, or pre-commit disconnect.
- [ ] Verify Windows Defender/SmartScreen behavior and signed artifact trust.

## Gate 7 — hardware and product qualification

- [ ] Qualify both physical RTL8192EU adapters through cold attach, detach/reattach, reboot, RX/TX soak,
  teardown, and immediate reuse.
- [ ] Run two-PC, two-WSL, two-Switch room discovery and entry.
- [ ] Repeat room discovery and entry with member A as the Switch room creator and with member B as the
  creator; verify simultaneous claims, role transfer, cancellation, timeout, and immediate retry.
- [ ] Complete movement, chair interaction, trade, animation, save, menu return, graceful exit, and a
  second immediate session.
- [ ] On confirmed trading-room entry, compare both 2-by-3 UI party grids and stat popovers against known
  parties on both Switches, including empty slots and an intentionally incomplete/corrupt negative
  fixture that must not be shown as valid.
- [ ] Verify the stored committed-trade event matches the actually exchanged Pokémon, trainers,
  timestamp, consent state, and disclosed network/region fields, while failed or rolled-back attempts
  create no completed-trade record.
- [ ] Run LAN and WAN loss, delay, duplicate, reordering, endpoint restart, relay restart, and recovery
  tests with run IDs and support bundles.
- [ ] Confirm the production path does not depend on the PC-to-Switch emulator peer.
- [ ] Keep RTL8188EU quarantined unless it separately passes the full qualification matrix.

## Gate 8 — release approval

- [ ] Sign the bootstrapper, native EXE, kernel, modules, rootfs, manifest, and update metadata.
- [ ] Publish supported hardware, Windows/WSL versions, limitations, privacy behavior, and recovery guide.
- [ ] Complete security/privacy review of trainer, Pokémon, source-IP, coarse-location, consent,
  retention, deletion, and aggregate-statistics behavior before enabling server-side collection.
- [ ] Preserve one tested previous release for atomic rollback.
- [ ] Archive reproducible build inputs and checksums outside the user package.
- [ ] Approve a private beta only after Gates 0–7 pass or each accepted exception is written here.

## Release result

The beta user experience is considered complete only when a user can download one setup executable,
complete guided installation, launch one native application, connect a supported adapter, and complete
a two-Switch session without opening a browser, WSL terminal, PowerShell, or developer tool. Optional
analytics must remain disabled unless the separate external consent workflow has been completed. The EXE
must automatically reach its installed backend, both members must share one authoritative lobby state,
either member must be able to create the Switch room, and the connected-room party UI must remain
functional even when optional server statistics are declined or offline.
