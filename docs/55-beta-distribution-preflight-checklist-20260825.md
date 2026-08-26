# Beta distribution preflight checklist — updated 2026-08-26

> Status: Repository-controlled preflight implementation is complete as of 2026-08-26, excluding all
> client privacy/consent work by explicit owner direction. This is not release approval: final owner/GPT
> visual/legal approval, relay operational
> qualification, clean-machine qualification, and two-PC/two-Switch hardware qualification remain.
> The relay is live at `https://relay.pangyostonefist.org` and its credentialed opaque smoke passes;
> backup/restore, staged restart, and two-NAT tests remain. The owner explicitly waived Windows code
> signing for this private beta, so the package must remain visibly labeled unsigned.
> UI baseline: `docs/56-native-ui-ux-redesign-handoff-20260825.md` and the owner overrides in
> `docs/57-native-ui-overhaul-implementation-report-20260825.md` are the preliminary redesign source.
> Latest UI evidence: `docs/74-stitch-dark-ui-overhaul-3-implementation-report-20260826.md` and
> `docs/assets/ui-overhaul-3/`.
> Latest installer candidate: `SwitchTrade-unsigned-private-beta-8667888.zip`, built from the same
> `production-beta` commit and recorded with its SHA-256 in `docs/75`.
> Second-overhaul audit: `docs/63-second-native-ui-overhaul-codex-handoff-20260825.md`.
> Final-overhaul handoff: `docs/62-final-ui-overhaul-gpt-handoff-20260825.md`.
> Frozen contracts: `room-control.v1` (`docs/58`), `party-commit.v1` (`docs/59`), and
> `privacy-statistics.v1` (`docs/60`), with the private-beta baseline in `docs/61`.
> Distribution target: one `SwitchTradeSetup.exe`, one installed `SwitchTrade.exe`, one hidden isolated
> SwitchTrade WSL runtime, and a separately hosted authoritative group/opaque relay. Any future
> analytics/consent service is externally administered and absent from the current client/relay.

## Already-established foundations

- [x] Native browser-free WPF client builds as a self-contained Windows EXE.
- [x] Minimal SwitchTrade WSL rootfs builds and imports as an isolated named distribution.
- [x] Python control service, RFU endpoint, relay, hardware profiles, health gate, and diagnostics exist.
- [x] The Gen III payload decoder can reassemble RFU blocks and validate/decode complete `.pk3` and
  `.ek3` Pokémon records in fixtures and captured endpoint traffic.
- [x] Source package includes SHA-256 verification for the rootfs and native EXE.
- [x] Throwaway-distro install, repair, retained rollback runtime, uninstall, and explicit purge passed.
- [x] Fully pinned WSL runtime suite passed 221 tests (3 skipped) without Switch hardware on 2026-08-26.

## Current gate summary and execution order

| Order | Gate | Current state | Release-blocking result still needed |
|---:|---|---|---|
| 1 | Gate 4 local integration | Internally implemented | Hardware-qualify authoritative role transition, retry, and recovery in Gate 7 |
| 2 | Gate 0 | Visual Overhaul 3 implemented as native dark WPF; icon, real GitHub Issues link, embedded fonts, and factual third-party notices complete | Owner visual acceptance and legal-notice approval |
| 3 | Gates 4–5 contracts | Implemented and internally tested | Qualify the ordered room path across two production endpoints |
| 4 | Gate 5 remote services | Public TLS deployment, credentialed smoke, and public metrics denial passed | Pass backup/restore, staged restart/reconnect, and two-NAT qualification |
| 5 | Gates 1–3 | Visual Overhaul 3 runtime `b2c9d36` reinstalled successfully from an unrelated working directory; candidate `8667888` adds the native progress UI and passed build, integrity, WPF self-test, and ZIP checks | Approve notices and qualify the latest package on a separate clean machine |
| 6 | Gate 6 | Automated subset passed; physical lifecycle not qualified | Pass clean-machine, reboot, coexistence, unsigned-publisher warning, and destructive lifecycle matrix |
| 7 | Gate 7 | Waiting for production stack and second RTL8192EU | Pass two-PC/two-Switch hardware, trade, decoder, teardown, reuse, and network-fault qualification |
| 8 | Gate 8 | Windows signing waived; labeled unsigned candidate and sibling checksum built | Retain externally, publish privately, review, and approve |

The owner explicitly authorized an unsigned private beta. It must never be described as signed or
publisher-verified, and the signed release path remains preserved for a future public release.

## Remaining qualification tranche — candidate packaging is complete

1. [x] Give GPT the final handoff/audit and implement its contract-grounded WPF overhaul without
   reintroducing the removed Privacy tab. Visual Overhaul 3 evidence is in `docs/73`, `docs/74`, and
   `docs/assets/ui-overhaul-3/`.
2. [ ] Owner-deferred: obtain final visual approval and approve the tracked factual legal-notice inventory.
   Icon wiring/build validation, the real GitHub Issues support destination, and the dark redesign
   implementation are complete; only owner acceptance remains.
3. [x] Implement and internally test the authenticated server-authoritative two-member room state
   machine, reconnect tokens, atomic room-creator claims, ordered events, expiration, and recovery.
4. [x] Connect the endpoint/control split to authoritative immutable seats and atomic per-attempt
   creator/finder assignment; WPF polls the same authoritative room snapshot.
5. [x] WSL lifecycle, versioned readiness, retained recovery state, redacted support summaries, and
   passive live party snapshots are implemented internally. Add allowlisted repair routing and the
   idempotent successful-trade classifier without making trading depend on decoding or analytics.
6. [x] Run no-Switch internal tests for simultaneous claims, reconnects, restarts, malformed/stale
   events, decoder fixtures, failed/rolled-back trades, analytics disabled/offline, and UI transitions.
7. [x] Implement the Gates 1–3 build/lifecycle foundations and begin Gate 6 automation. Physical,
   network, signing, and private-beta qualification remain open.

## Immediate-task scope imported from the current product TODO

This preflight checklist is the release-blocking superset of the immediate tasks in
`docs/50-current-product-demo-todo-20260825.md`. The backlog remains outside beta preflight.

- [x] Freeze and version the application/relay production-beta repository and pinned dependencies.
  The separately produced versioned kernel/modules/firmware checksum bundle remains a Gate 3/8 input.
- [x] Lock the RTL8192EU beta policy while preserving profile-driven driver/hardware expansion.
  Covered by Gates 0, 2, 3, and 7.
- [x] Finish the fail-closed Windows/WSL hardware launcher. Physical qualification remains in Gate 7.
- [x] Finish the universal health gate, all-permitted-channel discovery, bounded watchdog, recovery,
  and safe teardown. Physical failure/reuse qualification remains in Gate 7.
- [x] Finish structured, redacted, rotating run logs and one-action support bundles. Covered by Gates
  4-6.
- [ ] Certify both physical RTL8192EU adapters. Covered by Gate 7.
- [x] Finish and harden the feature-neutral RFU tunnel, deterministic player mapping, bounded queues,
  backpressure, stale-frame rejection, counters, and reconnect behavior. Covered by Gates 4, 5, and 7.
- [x] Validate the tunnel without Switch hardware, including byte-exact recorded payload replay,
  stale/duplicate/reordered envelope rejection, relay restart/reconnect, bounded queues, and teardown.
  Real WAN impairment qualification remains in Gate 7.
- [x] Complete the local JSON control API for readiness, hardware, authoritative groups, sessions,
  diagnostics, recovery, and shutdown. Covered by Gates 4 and 5.
- [x] Complete and freeze the native presentation baseline without synthetic previews. Private and
  public rooms use the live authoritative contracts, the public directory is capability-gated by
  relay health, and passive party projections publish only checksum-valid observations.
- [x] Integrate the EXE with the installed WSL control service, launcher, health gate, endpoint, logs,
  authoritative lobby, decoder observer, and clean shutdown. Covered by Gates 1, 2, 4, and 5.
- [x] Finish the production-hosting package for the opaque relay and authoritative lobby, including
  a hardened container, persistent authority store, deployment runbook, and credentialed smoke test.
- [x] Hosting operator deployed the relay at `https://relay.pangyostonefist.org`; health, legacy-endpoint
  rejection, authenticated room lifecycle, opaque bidirectional WebSocket smoke, and public `/metrics`
  denial passed. Backup, restart, and two-NAT qualification remain in Gate 5. Evidence: `docs/71`.
- [ ] Run the first real two-endpoint, two-Switch production test. Covered by Gate 7.
- [ ] Run LAN/WAN reliability, fault, recovery, and immediate-reuse testing. Covered by Gate 7.
- [x] Implement and internally test build, install, repair, update, atomic app/WSL/kernel rollback,
  uninstall, manifest/signature verification, and guided native setup.
- [x] Build the explicitly labeled Visual Overhaul 3 unsigned private-beta package from commit
  `8667888`; internal manifest, desktop self-test, product tests, kernel lifecycle, and ZIP checksum
  checks pass. Its unchanged runtime base passed the actual non-ASCII-profile reinstall from an
  unrelated working directory at `b2c9d36`. Evidence: `docs/75` and `docs/76`.
- [ ] Externally qualify that package. Windows code signing is an accepted owner exception; covered by
  Gates 1-8 and `docs/71`.

## Gate 0 — freeze the beta experience

- [x] Save and incorporate the owner's complete native UI/UX handoff as the redesign baseline.
- [x] Replace the old Emerald/pixel shell with the Linkline WPF presentation foundation and honest
  UI-only flows; backend-dependent screens remain subject to later gates.
- [x] Implement the second native pass: Fluent Light primitives, split views and view models,
  adaptive layouts, stable focus geometry/restoration, High Contrast resources, reduced-motion
  handling, and coordinator-owned active-room state.
- [x] Apply the 2026-08-26 owner correction pass: persistent Connection/Support/Advanced tabs,
  normalized ComboBox geometry, distinct fixed Back/action bars, and Partner-first compact party order.
- [x] Apply Visual Overhaul 3: native dark Stitch-derived tokens, embedded Space Grotesk/Inter/Space
  Mono, left-aligned stable shell, real capability-gated public directory, persistent Trade Room
  state, and explicit high-contrast closed/popup ComboBox templates.
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
- [ ] Approve the tracked license/legal notice inventory. The real GitHub Issues support destination and
  app/setup/favicon wiring are complete; final visual approval is owner-deferred. No Privacy tab or
  client analytics control is part of this approval.

Gate 0 normally precedes installer work. The owner's written exception allowed repository-side
installer implementation to proceed, but final public packaging and release approval remain blocked.

## Gate 1 — build the one-piece Windows distribution

- [x] Implement one ordinary double-click `SwitchTradeSetup.exe` path for an explicitly labeled unsigned
  private beta. The setup warns that Windows cannot verify the publisher. The signed Authenticode/CMS
  path remains available for a future public release.
- [x] Embed or checksummably bundle `SwitchTrade.exe`, the minimal rootfs, application runtime,
  hardware profiles, license notices, and release manifest.
  Candidate `beta-91f5a3e` contains all inputs in a 129-file schema-2 manifest and passed both staged and
  post-ZIP integrity verification. Owner approval of the tracked notice text remains Gate 0.
- [x] Bundle and install the local Python control API and endpoint runtime with the isolated WSL distro;
  the daily EXE must not depend on a developer checkout, terminal command, browser, or separately
  installed Python environment.
- [x] Install one isolated distro named `SwitchTrade`; never reuse, reset, or delete another distro.
- [x] Install the daily application under the user's Windows application directory and create one
  normal SwitchTrade shortcut.
- [x] Hide PowerShell, WSL consoles, and implementation details during ordinary use.
- [x] Support detect, install, repair, update, rollback, and uninstall modes.
- [x] Persist non-secret installer state and resume safely through per-user RunOnce after a required
  Windows reboot; reverify the original package before resumed mutation.
- [x] Refuse missing, unexpected, or mismatched artifacts using a complete SHA-256 manifest. Signed
  releases require a trusted detached signature; the owner-approved unsigned beta requires an explicit
  manifest marker, visible warning, and complete input set.

## Gate 2 — prerequisites and first-run setup

- [x] Detect Windows build, architecture, virtualization, free space, pending reboot, and WSL version.
- [x] Enable WSL 2 and Virtual Machine Platform only behind an explicit prerequisite-change flag.
- [x] Detect and install a checksummed pinned `usbipd-win` MSI when absent.
- [x] Detect VMware USB ownership and require explicit consent before changing it.
- [x] Detect the profiled adapter and distinguish duplicate USB IDs by bus ID.
- [x] Enumerate physically connected profiled radios from Windows `usbipd`, allow an explicit device
  choice, retain that bus/USB selection for the next session, and keep quarantined devices blocked.
  Experimental devices are selectable without repeated confirmation and carry an untested/may-not-work
  disclaimer plus diagnostics.
- [x] Perform administrator-only USB binding during setup; avoid a daily UAC prompt when normal attach
  can be performed without elevation.
- [x] Run the same fail-closed USB, driver, module, RX, channel, and role health gate used by sessions.
- [x] Discover across every protocol-permitted 2.4 GHz LDN channel. For `ldn 0.0.17` that set is
  exactly 1/6/11—not generic Wi-Fi channels 1–13—and surface the likely-5-GHz recreation case.
- [x] Put the health gate in front of every production session/room endpoint and its decoder observer;
  standalone capture tools must use the same prepare wrapper.
- [x] Offer exact stage-specific repair guidance when automatic recovery is unsafe, including explicit
  Update, relay, radio, session, decoder, and local-control routes without advising a WSL reset.

## Gate 3 — SwitchTrade custom WSL kernel

Decision: the beta uses the project-maintained custom WSL kernel because it is the qualified runtime.

- [x] Reconcile the application-repository SSOT with the later expandable kernel work: default to the
  qualified 6.18.35.2 ref, retain validated extra driver/firmware inputs, require the LDN runtime modules,
  preserve the opt-in pinned RTL8188EU experiment, and emit a checksum manifest. The execution mirror and
  fresh artifact are handled by the next item.
- [x] Consume a versioned kernel/modules/firmware artifact and checksum manifest from the separate kernel
  build mirror. Actions run `32929972152` produced release `6.18.35.2-microsoft-standard-WSL2+`; the
  independent verifier confirmed every declared hash, required module, firmware identity, and the
  intentional absence of the quarantined vendor RTL8188EU module. Hardware qualification remains Gate 7.
- [x] Warn before installation that WSL custom-kernel selection is global to all WSL 2 distributions.
- [x] Back up the user's complete existing `.wslconfig` before making any change.
- [x] Merge only the required `kernel` and `kernelModules` values; preserve unrelated settings.
- [x] Store the previous configuration and kernel-selection metadata for one-action rollback.
- [x] Use a bounded `wsl --shutdown` when applying or removing the kernel; never unregister unrelated
  distributions.
- [ ] Verify the running kernel, module ABI, firmware, RTL8192EU driver binding, and actual packet RX.
  Setup now performs all five checks and correctly installs tar modules under `/lib/modules` instead of
  treating them as a `kernelModules` VHD; final artifact/hardware qualification remains Gate 7.
- [x] Restore the prior configuration during rollback/uninstall when SwitchTrade owns the change.
- [x] Treat corporate policy that blocks custom WSL kernels as an explicit unsupported condition,
  restore the previous WSL configuration, and report `CUSTOM_KERNEL_BLOCKED_BY_POLICY`.

## Gate 4 — make the EXE and WSL behave as one app

- [x] Add single-instance protection for the Windows client and local runtime.
- [x] Start the isolated WSL distro and control service automatically and without a terminal window.
- [x] Prove the installed local control API is healthy and version-compatible before enabling Host,
  Join, Ready, or Configuration actions; use a bounded startup/retry/repair flow instead of leaving the
  user at an unexplained `BACKEND OFFLINE` screen.
- [x] Replace the ambiguous `BACKEND` label with separate control, relay, radio, and session states.
- [x] Add bounded local-service startup probes, retry, a recovery screen, and actionable generic errors.
- [x] Add startup cancellation so retry and shutdown safely supersede an in-flight probe.
- [x] Add version mismatch handling, retained failure stage, and allowlisted recovery-action metadata.
- [x] Implement retained-session `/api/v1/app/retry`, an allowlisted adapter health-gate repair, and
  bind radio-stage failures to the native repair action without accepting free-form commands.
- [ ] Publish and qualify the labeled unsigned private-beta update package. Candidate
  `SwitchTrade-unsigned-private-beta-8667888.zip` is built and integrity-qualified; its runtime base is
  installed on the development PC. External
  retention, clean-machine/hardware qualification, private publication, and approval remain. The signed
  update path remains implemented for a future public release.
- [x] Finish stage-specific native routing for control, version, relay, session, decoder, and radio
  failures with exact recovery guidance and no unsafe free-form repair command.
- [x] Prevent duplicate control, endpoint, or development-relay processes.
- [x] Split endpoint configuration into two independent axes: a stable member/tunnel identity and a
  per-attempt room creator/joiner radio role. Do not derive local radio
  behavior from group ownership or from the words host/guest in the UI.
- [x] Replace the temporary local owner/member-to-seat and locally selected radio-role values with the
  authoritative assignments from Gate 5; never let ownership become tunnel identity in production.
- [x] Support role transition safely: the selected creator-side endpoint discovers/joins the real
  Switch room, while the other endpoint opens the mirrored room. Teardown, re-election, and retry must
  return both adapters to a known healthy state.
- [x] Poll for server-authoritative group membership, both members' ready/online states,
  room-role assignment, radio readiness, Switch connection, trading-room entry, session failure, and
  leave state; never infer the remote member's state from local button clicks.
- [x] Passively tee both local and remote Reliable AppData streams to a bounded decoder observer at the
  endpoint boundary without delaying, mutating, or making the RFU tunnel depend on decoding.
- [x] Reassemble party blocks independently by member/direction, publish only complete checksum-valid
  party snapshots through the local control API, and clear them on session teardown.
- [x] Detect confirmed trading-room entry and render the two side-by-side 2-by-3 party grids; update or
  invalidate the view when the game sends a newer party state.
- [x] Detect a successful trade commit separately from offer, acceptance, animation, save attempt,
  rollback, communication error, or disconnect. Generate one idempotent committed-trade event only
  after the protocol evidence proves the trade completed.
- [x] Keep local party presentation functional when statistics upload is disabled or unavailable.
- [x] Decide and document the current close policy: stop an active endpoint session after confirmation,
  close the UI, and leave the installed local control service available for later reuse.
- [x] On full shutdown, stop the endpoint, development relay, and control service cleanly, release the
  adapter, and allow WSL to become idle.
- [x] Recover safely after an EXE crash, WSL crash, USB removal, or interrupted previous session;
  physical USB-removal and WSL-crash qualification remains in Gates 6–7.
- [x] Keep radio, driver, and protocol implementation outside the WPF process and behind the local API.
- [x] Expose run ID, structured state transitions, RFU/tunnel counters, decoder completeness, recovery
  actions, and a redacted one-action support bundle without exposing passcodes or raw Pokémon data.

## Gate 5 — production relay and authoritative groups; analytics owner-deferred

- [x] Deploy a reachable TLS-protected relay at `https://relay.pangyostonefist.org`; credentialed room
  and opaque bidirectional WebSocket smoke passed on 2026-08-26.
- [x] Configure the relay URL through manifest-hashed installation configuration rather than hardcoded
  UI state; private-beta builds reject loopback/non-HTTPS URLs and daily launch revalidates the config
  hash. A future signed release also authenticates that manifest.
- [x] Add authenticated member identities or scoped reconnect tokens so possession of a passcode alone
  cannot overwrite an occupied member, claim both roles, publish readiness, or impersonate a reconnect.
- [x] Make the service authoritative for group metadata, exactly two member seats, membership version,
  online/ready state, room-creator claim, per-attempt role assignment, session phase, reconnect, leave,
  close, and expiration. Both clients must receive the same ordered state.
- [x] Implement the room-creator claim as an atomic server operation. If both members claim it, exactly
  one wins and the other receives the join-room instructions; allow an explicit transfer only before
  the RFU session reaches its locked phase.
- [x] Add session expiration, participant limits, heartbeats, message-size limits, rate controls,
  idempotency keys, and bounded reconnect behavior.
- [x] Keep the real-time relay an opaque RFU-envelope forwarder. Lobby authority remains a separate
  module, and the relay data path does not decode or persist game payloads.
- Owner-excluded from this beta: add a separately authorized committed-trade ingestion API, if later
  approved, that accepts only locally validated,
  idempotent post-commit records; never upload a mere offer, animation, failed save, rollback, canceled
  trade, or full unrelated party snapshot as a completed trade.
- Owner-excluded from this beta: define and version any committed-trade record and its approved fields.
  The client/relay currently uploads none. A future record may include UTC timestamp, session/attempt ID, direction and
  member IDs, the two exchanged Pokémon records with validation provenance, and the two trainers'
  explicitly approved trainer/link metadata.
- Owner-excluded from this beta: if IP and location collection is separately enabled, treat it as sensitive.
  No IP/location analytics collection is implemented in the client or relay. A future service must record the
  server-observed source IP in a restricted short-retention security record, use a keyed pseudonymous
  network identifier for statistics, derive only the disclosed coarse region/country from IP, and do
  not claim precise physical location or collect GPS without separate explicit consent.
- Owner-excluded from this beta: encrypt any future committed-trade records in transit and at rest; separate operational, identity, and
  analytics access; audit reads; prevent trainer IDs, raw IPs, or Pokémon payloads from ordinary logs;
  and implement retention expiry, deletion, export, and consent withdrawal.
- Owner-excluded from this beta: build any aggregate statistics from a minimized approved record rather than exposing raw trainer,
  IP, location, or Pokémon records to dashboards.
- [x] Add operational health checks, structured server logs, metrics, retention, and incident procedures.
- [ ] Verify two endpoints behind different NATs and ordinary consumer firewalls.
- [x] Confirm in network integration tests that the relay forwards opaque envelopes and does not require Pokémon payload decoding.

## Gate 6 — install and lifecycle qualification

- [ ] Test a clean supported Windows machine with neither WSL nor `usbipd-win` installed.
- [ ] Test a machine with existing WSL distributions and a pre-existing `.wslconfig`.
- [ ] Test installation with and without a reboot, including resume after sign-in.
- [ ] Test install, first launch, repeated launch, repair, upgrade, rollback, uninstall, and reinstall.
- [ ] Confirm uninstall removes only SwitchTrade files and optionally only the named SwitchTrade distro.
- [x] Confirm in a non-destructive simulation that kernel rollback restores the exact prior WSL configuration.
- [x] Confirm application logs and support bundles contain no keys, captures, passcodes, or private data
  outside the documented privacy manifest.
- Owner-excluded from this beta: verify the externally administered consent is explicit and versioned, declining analytics does
  not block trading or local party display, and uninstall/account deletion can exercise the documented
  server-data deletion path. The client contains no optional analytics/privacy setting.
- Owner-excluded from this beta: verify any future server-side committed-trade ingestion idempotency across retries and records none
  for cancel, rollback, save failure, communication error, or pre-commit disconnect.
- [ ] Verify Windows Defender/SmartScreen behavior and the expected unsigned/unknown-publisher warning;
  document any managed-system block as an unsupported private-beta condition.

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
- Owner-excluded from this beta: if committed-trade analytics are later authorized, verify that the
  stored record matches the actual exchange and that failures/rollbacks create no completed record.
  The present client and relay collect or upload no trainer, Pokémon, IP, or location analytics.
- [ ] Run LAN and WAN loss, delay, duplicate, reordering, endpoint restart, relay restart, and recovery
  tests with run IDs and support bundles.
- [ ] Confirm the production path does not depend on the PC-to-Switch emulator peer.
- [x] Keep RTL8188EU quarantined unless it separately passes the full qualification matrix.

## Gate 8 — release approval

- [x] Owner exception: Windows Authenticode/CMS signing is skipped for this private beta. Preserve the
  signed path for a future public release and label every current package as unsigned.
- [x] Publish the current hardware/Windows/WSL limitations and recovery guide in `docs/70`; the native
  Support tab links to the enabled repository Issues page.
- Owner-excluded from this beta: complete security/privacy review of trainer, Pokémon, source-IP, coarse-location, consent,
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
