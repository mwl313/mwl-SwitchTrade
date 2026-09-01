# SwitchTrade Future TODO

This is the definitive implementation and qualification ledger. Together with
`80-abc-connection-architecture-20260829.md`, it supersedes older connection plans. Items are ordered
within each section; historical beta notes remain as evidence, not as authority for the new ABC+D
path. No open item may be presented as a current production capability.

Before working an item, read [Mistakes to Avoid](MISTAKES_TO_AVOID.md), the source of truth for prior
failures and mandatory recurrence-prevention gates. Add newly discovered failure evidence there
before retrying; keep the implementation status and acceptance debt in this TODO.

## Current product phase — 2026-09-01

Standalone P0/A/B evidence, hosted C/D evidence, and the focused one-PC/two-adapter 10/10 C+D
campaign are sufficient to stop qualification-only development. Production owns one selected radio
per PC; dual-adapter concurrency remains a source qualification tool only. The shipped runtime has no
AI/agent dependency.

The production Debug menu requirement is canceled. The deterministic headless ABC+D connection-run
service, owner-approved minimal typed GUI, and **Export support logs** implementation now exist in source.
They archive bounded redacted evidence accumulated since application startup to the Windows Desktop.
The GUI uses the existing typed production gateway for room actions, adapter selection, immutable status,
and lifecycle commands; the separate no-backend playtest executable has been retired. Installed-runtime
cutover and physical acceptance remain open. The updated
M8-M10 sequence and beta definition are normative in
[`94-production-wrapper-beta-cutover-20260831.md`](94-production-wrapper-beta-cutover-20260831.md).
No additional repetition campaign begins before the production wrapper exists.

## Critical and urgent blockers

0A. **CRITICAL — URGENT: Eliminate false installed-runtime corruption and qualify desktop launch.**
    **Status (2026-08-31): root cause confirmed and corrected in source; focused provisioner contract
    tests pass. New immutable package and installed qualification are pending.** PC A's installed
    `0.2.14-beta.1` desktop reported `SOFTWARE_NOT_READY` / `corrupt` before creating a control log even
    though the release/runtime/kernel identities and a direct installed `verify-software` were healthy.
    Read-only status had ignored the successful WSL CLI inventory and trusted one transient Lxss
    registry lookup. It now accepts either independent positive view, repeats a simultaneous negative
    observation once within a bound, and fails closed only on durable absence from both. Keep this item
    open until the exact installed desktop passes cold launch, normal close, relaunch, control shutdown,
    non-ASCII-profile execution, upgrade on both PCs, and zero USB/endpoint/interface residue. Add that
    desktop entry-point sequence to the release workflow so provisioner-only verification cannot publish
    another package with an untested application startup boundary.

0. **CRITICAL — URGENT: Qualify the M7 distributed harness only through the safe pairing barrier.**
   **Status (2026-08-31): the invitation/pairing fixes and the later explicit-WSL-cwd,
   identity-bound control, cancellation, and concurrent-status corrections are implemented in source.
   `v0.2.14-beta.1` at `f57038e` packages the canonical launcher as a separately hashable qualification
   kit. PC A passed full source regression, repeated mutation-free kit verification, disposable WSL
   lifecycle plus packaged auto-discovery preflight, versioned upgrade, installed software health,
   runtime/kernel identity, adapter-selection preservation, and Windows USB ownership. PC B installation
   and the close-range then separated two-PC/two-Switch run are still required.**
   The rejected `D-PHYS-1-R3` runner stored its campaign binding in the `note` supplied while creating
   a private room, but the relay intentionally stores directory notes only for public rooms. PC B then
   read a nonexistent top-level `room.note`, so every otherwise-correct private join failed as
   `DISTRIBUTED_INVITATION_IDENTITY_MISMATCH`. The same run let PC A acquire USB before PC B proved
   room identity, and its abort path deleted distributed recovery state before local USB cleanup was
   verified.

   `distributed-invitation.v2` now binds the handoff to the relay's authoritative room UUID and code,
   validates the private room contract and unique seats, and rejects v1 invitations. Both members must
   reach `coordination_paired` while `usb_attached=false`; an operator confirmation barrier remains
   ahead of P0 and the first USB action. Local cleanup must verify before authority is released, and
   recovery state is removed only after both local cleanup and authority release are proven. Explicit
   room-version conflicts are retried with the same idempotent command after a fresh snapshot; semantic
   409s still fail closed. Operator stdin is no longer used: `distributed-control-state.v1` exposes
   read-only status and exact test/run/checkpoint-bound continue/cancel actions, while one runner owns
   cleanup. All WSL probes set the immutable runtime cwd and retain factual failure identity. Use only
   the canonical Windows launcher; direct Python commands are no longer a supported qualification
   path. Keep this item open until that launcher kit is built, verified on both PCs, and the new
   release passes two consecutive
   close-range full runs, verified residue checks on both PCs, and then the separated-distance run.

1. **CRITICAL — URGENT: Restore the complete WSL LDN prerequisite gate.**
   **Status (2026-08-29): PC A passed the immutable installed cold P0 and verified cleanup. The owner
   accepted that result as sufficient to begin Milestone 3. The direct A0-A9 endpoint/harness is
   complete and PC A passed its one-Switch installed-runtime qualification with verified cleanup.
   Direct B2-B10 is source-complete and final immutable PC A run
   `12e6a535-4770-47ae-9fb3-8d06915af053` physically passed B2-B10 plus verified cleanup. PC B's
   P0/direct A/direct B evidence has now also been reviewed and accepted. The corrected GUI-independent
   distributed harness is source-complete for the `0.2.10-beta.1` candidate; installed
   two-PC/two-Switch qualification and production-path cutover remain open.**
   The installed `0.2.6-beta.2` runtime contains the correct kernel and the `ccm`, `cmac`, and `tun`
   modules, but the production wrapper does not load them and does not verify `/dev/net/tun` before
   entering the LDN path. A real Switch-hosted room was observed and decoded three times, then every
   join failed at ABC+D gate A6, `NL80211_CMD_NEW_KEY`, with `ENOENT`. This is the same WSL failure
   previously fixed in the standalone `run_trade.sh` path by explicitly loading `ccm`, `cmac`, and
   `tun`; that block was lost when the product moved to `run-beta-endpoint.sh`.

   Put the complete ordered prerequisite check in the one shared production radio gate: exact WSL
   runtime and module-tree match; `usbip-core`/`vhci-hcd`; exact USB enumeration;
   `cfg80211`/`libarc4`/`mac80211`/`led-class`/profile driver and firmware; explicit `ccm`, `cmac`,
   and `tun`; `/dev/net/tun`; driver/PHY/netdev; stale-vif cleanup; and actual RX. Normal rooms and
   diagnostics must call this same gate. Cold-boot acceptance requires
   all modules initially unloaded, one successful A-side Switch room join, one successful B-side AP
   association, and verified cleanup without manual `modprobe` or a warm-runtime dependency.

   The new source-only P0 path now loads and verifies the complete ordered module set, verifies
   `/dev/net/tun`, performs actual RX, keeps one Linux radio lock through an identity-bound endpoint
   canary, attaches the exact saved InstanceId at most once, and returns only a run-acquired adapter.
   Passive and active runtime, module, firmware, and integrity hashes must agree. Unknown cleanup,
   an active interface, a changed bus identity, an inactive usbip port, or missing recovery evidence
   fails closed and blocks another run. This path is deliberately isolated from `0.2.6-beta.2`; close
   this item only after the new installed runtime passes cold P0 and direct A/B on both PCs. The same
   qualification must run from a non-ASCII Windows profile and prove locale-independent UTF-8/
   UTF-16LE process output, JSON, log, and Windows/WSL path handling; encoding failures retain their
   own factual gate instead of being mislabeled as radio or relay failures.

   The new direct A path does not import the rejected `LiveTransport` lifecycle. It admits only one
   exact FRLG advertisement, performs no fallback or orchestration retry, exposes ordered A0-A9
   checkpoints around the run-local station/CCMP/control-port objects, opens the Pia UDP/raw sockets,
   completes a bounded local hold, and persists only the advertisement length/hash. PC A physical run
   `88f8e357-2e8c-4981-ad87-4cfaa1f93c31` passed every A0-A9 gate in immutable runtime
   `abcd-m3-80c4e13`, returned `A_CONTROL_READY`, and verified normal endpoint exit, radio quiescence,
   Windows/Linux USB restoration, and absence of Linux interface/PHY/process residue. This is direct A
   evidence only and does not claim A10, C1, `A_READY`, B, C, D, or a trade.

   The new direct B path does not import the rejected `HostTransport` lifecycle or prototype AP
   engines. It validates one immutable package-owned fixture, resets only the selected PHY, constructs
   the exact FRLG network, applies compatibility behavior to run-owned instances, and requires
   AP/monitor/TAP, data-plane, real Switch association, control-port, and hold evidence in B2-B10
   order. Source commit `9635a1f` passed 414 tests with three intentional skips. Runtime
   `abcd-m4-d41a284` made the room visible and physically recorded B2-B10, but a peer destroy stall
   after B10 falsely rewrote the report as `B_HOLD_TIMEOUT`. The corrected lifecycle keeps the Trio
   timeout outside the complete LDN context lifetime, bounds the destroy notification, and separates
   functional success from factual context cleanup. A subsequent physical run passed B2-B10 and all
   worker/USB cleanup but confirmed that the joined LDN AP context still exceeded its ten-second exit
   deadline. The ldn 0.0.17 STOP_AP wait is now bounded before authoritative interface deletion, with
   ordered teardown checkpoints retained in the report. Immutable runtime `abcd-m4-9635a1f` then
   passed the final real-Switch PC A run through B2-B10, `factory_released`, verified radio/USB
   cleanup, and zero endpoint/interface/PHY/recovery residue; no B1, `B_READY`, relay delivery, or
   trade is claimed.

   **Completed qualification debt (2026-08-30):** PC A run
   `12e6a535-4770-47ae-9fb3-8d06915af053` against runtime `abcd-m4-9635a1f` passed B2-B10, exited
   through `factory_released`, reported `ldn_context_released=true`, verified radio/USB cleanup, and
   left no endpoint, interface, PHY, lock, or recovery residue. PC B's returned P0, Direct A, and
   Direct B reports were subsequently reviewed and accepted with the same immutable runtime
   integrity and verified cleanup.

2. **CRITICAL — URGENT: Preserve relay frame order and truthful P0/A/B/C/D product stages.**
   **Status (2026-08-30): the M5 v2 source and deployed validation-relay functional exit gate passed;
   M8 headless product wrapping, M9 factual UI/log projection, and reproducible production deployment
   remain open. The retired Debug menu is not an acceptance gate.**
   In the guided AP diagnostic, the synthetic host sends `PEER_READY` at sequence 0 and the retained
   advertisement at sequence 1. When the endpoint connects later, the relay replays the advertisement
   before the ready frame. `SequenceGate` accepts sequence 1 and rejects sequence 0 as stale, leaving a
   relay-connected endpoint waiting for a peer that is already online. The AP path never starts, yet
   the report incorrectly emits `DIAG_RELAY_UNREACHABLE`. The same bundle reports a detected and parsed
   Switch room's A6 CCMP-key join failure as generic `DIAG_RADIO_GATE_FAILED`.

   Retained frames from one source epoch must reach a late peer in source sequence order. Readiness
   must precede advertisement delivery, stale advertisements must not cross attempts/epochs, and the
   endpoint must distinguish connected from authenticated, peer-ready, and data-plane-proven.
   Diagnostics must report the last completed gate defined in
   `80-abc-connection-architecture-20260829.md`: P0 passive/attached/enumerated/driver/LDN/RX; A
   observed/parsed/associated/control/ready; B AP-created/advertised/associated/control/ready; C
   authenticated/peer-ready/data-plane-proven/advertisement-delivered/bridge-ready/RFU-active; and D
   closing/local-quiescent/two-side-terminal/USB-returned. Acceptance requires a real-relay late-peer test
   that reproduces the previous ordering, proves no stale-frame drop, reaches B AP startup, and maps
   failures to their factual A/B/C gate.

   Source checkpoint `162f779` now keeps v2 admission separate from legacy attempts, requires two
   distinct matching P0 attestations and bound launch identities, replays retained frames in strict
   source order, rejects gaps/duplicates/stale epochs/wrong attempts, repeats unpredictable nonce
   proof after reconnect, verifies the advertisement hash, and erases admission/retention at attempt
   retirement. Local uvicorn and hosting smoke passed. The deployed validation relay then passed both
   roles, late-peer, reconnect, active-attempt restart, stale/gap/wrong-attempt rejection, and private
   zero-orphan metrics. The host is a single launchd-supervised native uvicorn process whose critical
   source hashes match `bbc549f`, not the reference Docker image. Before M9 production cutover, either
   deploy that reference image or commit and verify a complete native release manifest including the
   clean source tree, dependencies, Python runtime, launchd configuration, environment, and rollback
   hashes. Keep this critical item open until M8/M9 migrate the normal application and its factual
   UI/support-log projections to the v2 C gates.

3. **CRITICAL — URGENT: Add the attempt-scoped A_READY/B_READY activation barrier.**
   **Status (2026-08-30): M6 software/deployed exit accepted at `d2130fe`; source-identical public
   C2 smoke, single-worker identity, and private zero-orphan checks passed. A GUI-independent
   physical runner now sustains the admitted Direct A/B contexts and feeds their exact readiness into
   C2. Physical two-PC proof and M8/M9 product cutover remain open.**
   The current `rfu-tunnel.v1` controls include `PEER_READY` and `ADVERTISEMENT`, but no physical
   side-ready message. In the normal finder path, `HostTransport.start()` returns when the AP opens,
   before `_peer` proves that the Joining Switch associated; the endpoint then constructs
   `TunnelSim` and reports `session_ready`. The room-side endpoint likewise has no authoritative
   evidence that B reached association/control/TAP readiness. Relay authentication is therefore able
   to masquerade as a physically complete two-sided bridge.

   Implement the C2 barrier in `80-abc-connection-architecture-20260829.md`: arm each local
   Pia/Reliable bridge with a bounded pre-barrier queue so early Switch frames are not lost; publish
   exactly one identity-bound `A_READY` or `B_READY` after that side's complete hold gate; accept only
   the remote message for the same attempt/seat/role/launch generation/advertisement hash; and expose
   `C_BRIDGE_READY` only after both endpoints hold both signals. Reconnect must create a new epoch and
   re-prove the barrier without admitting stale side readiness.

   Acceptance requires delayed-B, delayed-A, stale-attempt, reconnect, duplicate-message, queue-limit,
   endpoint-loss, and cancellation tests. A real two-PC test must prove that an AP merely opening does
   not advance C, that early local RFU is bounded and preserved, and that both sides agree on the same
   activation generation before real RFU counters are called active.

   Source checkpoint `d2130fe` implements canonical `side-ready.v1`, relay-bound activation
   generation, one current readiness per source epoch, the 256-frame pre-barrier queue, exact Pia
   Reliable byte/flag transport, and current-generation bidirectional RFU activation. Disconnect and
   peer-send loss revoke both owned transport slots and require fresh nonce and side-ready proof.
   Focused tests passed 49 cases; the full fixed audit runtime passed 443 tests with three intentional
   skips; and the extended local hosting smoke passed C0-C2. The source-identical deployed relay then
   passed repeated public C2 smoke in both role assignments, delayed A/B, single-worker identity, and
   private zero-orphan metrics. Keep this product blocker open until a later two-PC/two-Switch run
   proves simultaneous physical A_READY/B_READY through the production coordinator.

4. **CRITICAL — URGENT: Make D cleanup two-sided, attempt-scoped, and outcome-preserving.**
   **Status (2026-08-30): authority D1/D5/D6 is implemented at `d815562`, ordered endpoint D2-D4 at
   `fdbdd12`, and measured local D5 plus the D7-D11 release state machine at `f52fe93`, hardened for
   restart recovery and WSL probe self-exclusion at `62f93fa`. Commit `0d7549d` shares the D8/D9
   fail-closed policy with cold P0 and PC A passed the installed-runtime D8-D10 sequence under a
   non-ASCII profile with verified USB return and no residue. The exact `ed382db` deployed artifact
   also passed renewed two-role smoke and zero-orphan metrics. The software happy path is complete,
   and `9e1621d` adds bounded D2/D3/D10 failure injection plus restart-safe D11 response-loss report
   finalization without repeating teardown. Commit `f739f53` wires the production diagnostic
   peer/private-room/credential owner into the strict D7 callback and startup recovery; real
   single-PC public-relay cleanup and post-close restart recovery passed, as did the full
   `491 passed, 3 skipped` regression. Commit `9f30374` completes the executable single-PC D1-D11
   restart/fault matrix, including independent D7 resource failures, probe exceptions, partial USB
   evidence, corrupted response-loss recovery, and relay restart; focused, local real-process, both
   public role assignments, and the full `500 passed, 3 skipped` suite pass. PC B matching
   qualification and product action migration remain open, so this blocker is
   not closed. Commit `153365c` and installed PC A runs now prove that run-owned endpoint residue blocks
   USB return, exact PID/start-tick termination permits verified recovery, and an interrupted local
   control process can resume the same durable run through D8-D11. Commit `4e3e932` and real reboot run
   `39b09970-447a-405d-9e04-8252a0738a6e` additionally prove local Windows-restart recovery with
   fail-closed D8, stable Linux device/interface/PHY absence, normal USB bus renumbering, and verified
   D11.**
   Local session Stop currently stops the endpoint and releases hardware before it publishes the
   authoritative cancellation. A WebSocket disconnect while the authority is still in any
   non-terminal phase—including `closing`—is converted by the relay into `relay.peer_lost`. The relay
   has no `D_SIDE_QUIESCENT` barrier and one local control cannot prove the remote PC's endpoint,
   interfaces, or USB ownership were cleaned. This conflicts with distributed D and can overwrite a
   normal/canceled outcome or claim terminal cleanup without both sides.

   Implement D1–D11 from the ABC+D source of truth. Record an idempotent closing intent and original
   outcome first; allow a bounded native Switch close-link tail; have each endpoint/control prove its
   own transport/thread/PID/interface state; terminalize and disconnect the relay only after both
   side-quiescent acknowledgements or an explicit forced-failure deadline; then verify local Linux
   quiescence and return only the exact run-owned USB device to Windows. Expected closing disconnects
   must not become `relay.peer_lost`, and cleanup errors remain secondary to the first A/B/C failure.

   The authority checkpoint enforces a v2-only immutable closing intent, exact launch-bound side
   acknowledgements, a two-seat terminal barrier, post-response-loss idempotency, and bounded
   timeout/restart terminalization without replacing the first functional cause. The local checkpoint
   rejects caller-supplied D5 success: it hashes and validates the persisted D2-D4 report, independently
   measures the exact PID generation and run-owned temporary interfaces, reuses one persisted UUIDv7
   command after response loss, and accepts D6 only when the authority contains that exact evidence.
   It then orders diagnostic cleanup, endpoint/child/token proof, a bounded stable WSL radio probe,
   conditional release through the existing `UsbLease`, and lock release at D11. Unknown remains
   failure and USB return is skipped while endpoint or radio state is unproven.

   Acceptance covers successful trade, Stop, room close, peer loss, endpoint hang, app close, relay
   restart, and PC restart at every D gate. No new attempt is enabled until both shared authority and
   the local resource owner have a terminal verified record; repeated cleanup commands are idempotent.
   The `0.2.8-beta.1` physical runner now routes End, Stop, Leave, and Close through D1 before its
   reused endpoint D2-D4 and measured D5/D7-D11 owners. This is source evidence only until all four
   installed two-PC/two-Switch cases pass with shared cleanup verified. Commit `82e7dcc` fixes the
   M7-only relay polling limit failure and pre-attempt recovery crash found during the first physical
   launch; the production desktop and relay contracts were not changed. `D-PHYS-1-R4` subsequently
   proved both P0 sides and C0 data plane but exposed a non-blocking operator checkpoint, loss of the
   original Direct-stage failure code, and premature launch-admission retirement during D closing.
   Source now requires an exact Continue command before physical A/B action, preserves the Direct
   failure identity, and retains D launch admission until D6 or bounded D timeout. Relay redeployment,
   matching installed payloads on both PCs, and the physical acceptance sequence remain required.

5. **CRITICAL — URGENT: Stop false-positive endpoint startup and unbounded relaunch storms.**
   **Status (2026-08-28): implemented in source; the current-PC single-launch and close/reopen smoke
   cases passed, while packaged fault injection, PC B, and physical qualification remain.**
   The PC B support bundle `20260828T075317Z-8036dd6a` recorded 128 `session_started` events in seven
   bursts even though almost all of those processes died before creating an endpoint run or state.
   The final two room attempts alone launched 6 and 51 endpoint PIDs at roughly two-second intervals.
   The selected RTL8192EU was attached and visible in WSL, so this is not evidence that the Switch was
   undetectable; the production endpoint never reached Switch scanning in those attempts.

   The confirmed failure chain is: the shell wrapper publishes its launch acknowledgement before its
   radio preparation and health gate have succeeded; the control process treats that acknowledgement
   as `session_started`; the read-only room-status request is polled every two seconds but also launches
   a replacement whenever no endpoint state exists; and failures before Python starts create neither an
   endpoint run nor a user-visible terminal error. The persistent control process also inherits
   desktop-owned stdout/stderr pipes while desktop shutdown does not stop that process. In this bundle,
   those pipes were orphaned before the launch bursts. A gate write to the broken output stream is the
   high-confidence immediate trigger, although the missing pre-Python stderr prevents proving that final
   syscall from the bundle. Premature acknowledgement, launch-on-GET, unbounded replacement, and missing
   launcher diagnostics are independently confirmed defects.

   Treat one authoritative connection attempt as at most one automatic endpoint launch. A launch must
   not become started until the radio gate has passed and matching endpoint initialization state exists;
   if useful, expose `wrapper_acquired` as a separate non-ready stage. Make room-status GET requests
   side-effect free, require an explicit Connect or Retry action after an early exit, and publish that
   exit as the terminal failure for the attempt. Either stop the local backend with the desktop or give
   the persistent backend output destinations whose lifetime is independent of the desktop process.
   Capture bounded, redacted wrapper stdout/stderr, exit code, launch nonce, PID, and attempt ID even when
   Python never starts, and include every recent attempt in the support bundle.

   Regression acceptance: an early radio-gate exit launches exactly one process and reports its cause;
   repeated room-status polling launches zero processes; desktop close/reopen cannot orphan a backend on
   dead pipes; every attempted PID has a terminal record in the bundle; Stop cancels in-flight launch;
   and repeated failed attempts leave no child processes, locks, or attached-radio state behind. This
   blocker must be fixed before more physical two-PC qualification because the current behavior can hide
   the real fault, exhaust resources, and produce a false impression that a Switch scan occurred.

   The source fix now makes room-status GET launch-free, serializes endpoint starts, limits one automatic
   launch to one authoritative attempt, requires explicit Retry after failure, and makes Stop invalidate an
   in-flight launch even while hardware attach is still running. The wrapper acknowledges only after the
   radio gate passes, and control requires both that acknowledgement and nonce-matched Python endpoint
   state before publishing `session_started`. Each launcher writes bounded, redacted stdout/stderr and a
   terminal launch record to the support bundle. Normal desktop close requests backend shutdown; endpoint
   output is written to backend-owned files rather than desktop-owned pipes. Automated regressions cover
   the launch, polling, failure, Retry, cancellation, and evidence boundaries. Keep this item open as a
   release gate until the packaged runtime passes the same cases in real WSL on both PCs and a close/reopen
   cycle leaves no control or endpoint process behind.

   Packaging checkpoint (2026-08-28): internal release
   `beta-2088aaaa25da-launchstorm-20260828` passed package and embedded-payload validation and installed
   successfully on the current development PC. Its active side-by-side runtime reports `software_ready`
   and contains the launch-free GET and post-radio-gate acknowledgement changes. Normal close/reopen left
   no backend, endpoint, open port, or running distro. One installed Group Leader click against a synthetic
   relay peer produced exactly one launcher record, one `session_started` event, and one endpoint PID; the
   endpoint passed adapter RX and tunnel connection, performed three LDN scans, and terminated with the
   expected `radio.switch_room_not_found` because no Switch room was hosted. Installed fault injection,
   PC B installation, repeated-run cleanup, and physical qualification are still pending. The same smoke
   exposed the separate diagnostic and state-projection bugs tracked below; they block treating the whole
   workflow as qualified even though the one-click launch-storm regression passed.

6. **CRITICAL — URGENT: Gate hot-attached radios on completed Linux driver probe.**
   **Status (2026-08-28): fixed and qualified on the current PC in the installed
   `beta-2088aaaa25da-probe30-20260828` candidate; PC B and physical two-machine qualification remain.**
   The installed `beta-2088aaaa25da-statefix-20260828` candidate reproduced a deterministic readiness
   race after a successful active RTL8192EU diagnostic. `usbipd` reported the selected device attached,
   and Linux exposed its `0bda:818b` USB sysfs node, while the already-loaded `rtl8xxxu` driver still
   needed roughly 4–5 seconds to read EFuse, load firmware, register the PHY, and create `wlan0`. The
   wrapper saw the temporary `driver bound + no netdev` state, immediately attempted monitor-interface
   recreation before a PHY existed, and failed the only launch as `endpoint_start_failed`. Cleanup then
   detached the device while probe was still active, producing misleading inactive-port and EFuse errors.

   Installed candidate `beta-2088aaaa25da-probeready-20260828` proved that the initial ten-second wait
   was still shorter than this adapter's real cold/warm probe path (roughly 14 seconds before the PHY and
   netdev are usable). It therefore failed the same Group Leader qualification and remains rejected.

   The production wrapper now treats an allowed bound driver without a netdev as an in-progress probe,
   waits up to 30 seconds for the exact device interface, refreshes the binding, and enters
   missing-interface recovery only when a PHY exists. If neither a PHY nor netdev appears, it reports a
   bounded `DRIVER_PROBE_TIMEOUT` instead of mutating a half-probed device. The control-plane startup
   budget is 45 seconds so it properly contains the radio gate. A shell regression models usbipd's
   staged USB -> driver -> PHY/netdev publication and proves the wrapper waits rather than failing early.
   The corrected installed candidate passed active diagnostic -> detach -> Group Leader against an
   isolated synthetic peer. It produced one launcher and one endpoint, connected the RFU tunnel, reached
   the expected stable `radio.switch_room_not_found` result after three scans, and released the exact
   adapter. Retain PC B and repeated physical qualification before closing the wider release gate.

7. **CRITICAL — NEXT: Wrap admitted ABC+D as the only deterministic production connection path.**
   **Status (2026-09-01): source implementation, Switchless source dry-run, and minimal production-GUI
   cutover are accepted for installed qualification. The dry-run passed production API/service command semantics, full source
   regressions, hosted-relay C+D normal and worker-death paths, and verified residue cleanup without
   an AI runtime. It also found and corrected checkpoint Stop handling at both the endpoint parser and
   production-adapter outcome boundary before hardware mutation.
   The neutral executor/service, single mutation queue, identity-bound command/revision API,
   heartbeat supervision, recovery guard, typed WPF projection, application-session evidence, and
   backend-independent Desktop export are implemented. The simplified WPF shell now exposes only
   create/join/browse, main-screen adapter selection, factual status/checkpoints, lifecycle controls,
   credits, and support export; Settings and the alternate no-backend executable are unreachable/removed.
   All 588 Python regressions, Desktop/Provisioner Release builds, Provisioner contract tests, and
   Desktop/session self-tests pass. Installed immutable entry-point, interruption/recovery, and
   backend-dead export acceptance remain open;
   the source dry-run is not an installed or physical result.**
   Extract one neutral connection-run service from the generic lifecycle already exercised by the
   distributed harness. The product and qualification adapters must call that service rather than
   cloning orchestration or launching a harness as the product runtime. Production owns one selected
   adapter per PC and no AI, console prompt, dual-adapter mode, selectable engine, or fallback path.

   M8 must route Connect, Stop, End, Leave, Close, Retry, shutdown, and startup recovery through one
   persisted coordinator with one identity-bound WSL wrapper/endpoint launch, immutable status reads,
   first-cause preservation, bounded retries, and verified D cleanup. M9 then attaches the minimal GUI,
   makes the legacy path and Debug menu unreachable, and adds one **Export support logs** action.

   The launcher creates an application-session identity before local-service startup. Bounded redacted
   launcher, release/runtime, wrapper, endpoint, P0/A/B/C/D, relay-result, shutdown, and recovery logs
   must survive early startup failure and export atomically to one ZIP on the Windows Desktop. Never
   include credentials, keys, room passcodes, packets, MAC addresses, exact adapter InstanceIds, or
   trainer/Pokémon data. See
   [`94-production-wrapper-beta-cutover-20260831.md`](94-production-wrapper-beta-cutover-20260831.md).

## 1. Post-installer application stabilization

1. **Before the next installer upload, stop Repair from reconfiguring healthy external prerequisites.**
   Microsoft WSL and `usbipd-win` must be installed or upgraded only when absent or below the pinned
   minimum; SwitchTrade Repair must replace only SwitchTrade-owned desktop, runtime, kernel, and
   configuration state. Add a regression for a healthy WSL MSI whose registered original source name
   differs from Burn's cached payload name (for example `wsl.2.7.12.0.x64 (2).msi` versus
   `wsl.2.7.12.0.x64.msi`) and prove Repair never invokes MSI maintenance for that prerequisite.
2. **Preserve the endpoint's specific failure across relay teardown.**
   **Status (2026-08-28): the client projection and relay-authority refinement are implemented and their
   focused regressions pass, but the hosted relay is running an older authority behavior and must be
   redeployed before packaged two-PC requalification.**
   A local `radio.switch_room_not_found` must reach both clients and the support summary without being raced
   or overwritten by the later generic `relay.peer_lost`; add an end-to-end regression for this order.
   In the installed `probe30` smoke, the desktop correctly kept the specific local result, but the hosted
   attempt and synthetic partner both ended as `relay.peer_lost`. Local relay tests prove that the current
   source refines that transport failure to the later endpoint-specific failure and that End retires the
   terminal attempt. Deploy this relay source, then repeat the hosted failure-order and End/retry test.
3. **Make connection readiness atomic with local hardware preparation and stop.**
   **Status (2026-08-28): implemented in source. Adapter preparation now precedes authoritative ready;
   Stop cancels an in-flight preparation; terminal attempts retire explicitly; and exact physical-device
   ownership is persisted for Stop, room close, failure, normal exit, and crash recovery. Installed and
   physical cleanup qualification remains.**
   Validate and attach the selected adapter before publishing authoritative ready, return `adapter_selection_required`
   when no Windows device is selected, roll ready back on launch failure, and prove Stop prevents an
   in-flight attach from launching an endpoint afterward. End must also retire or locally acknowledge a
   terminal authoritative attempt: the 2026-08-28 installed smoke test showed the desktop briefly enter
   Idle after `/api/v1/session/stop`, then room polling rehydrated the same failed attempt and re-enabled
   End while competing status and room projections flickered between `relay.peer_lost` and a generic
   relay message. Add an end-to-end regression where Stop is pressed after a terminal radio failure;
   the endpoint must remain stopped, the room may remain open, and polling must not resurrect the ended
   attempt or any recovery banner. Track ownership of adapter mutations and restore the pre-run state on
   every terminal path. In this smoke test the RTL8192EU began shared-but-unattached, but remained USB/IP
   Attached after End, Close Trade Room, and normal desktop shutdown, which kept the dedicated WSL distro
   running. A successful run, expected failure, cancellation, room close, and app close must each detach
   only an adapter attached by that run, restore its prior interface state, and leave the distro stopped;
   never detach hardware that was already attached before SwitchTrade started.
4. **Keep enough endpoint evidence in support bundles to diagnose every attempt in one app run.**
   **Status (2026-09-01): implemented in source. The Desktop creates the session before backend
   startup; launcher/service/wrapper/endpoint streams, WSL snapshots, failure summary, retention,
   allowlist export, redaction, hashes, partial-file handling, and non-ASCII path round-trip have
   automated coverage. Installed backend-dead export and privacy inspection remain M9 acceptance.**
   Include a bounded set of recent endpoint runs plus pre-endpoint launcher/gate failures, so a middle
   attempt is not lost when a later attempt overwrites `endpoint-state.json`. Preserve JSON value types
   during redaction: the 2026-08-28 bundle changed an inactive `session_id: null` into the string
   `"<redacted>"`, which falsely suggests that a value existed and weakens automated evidence checks.
   Redact only present sensitive values, keep `null` as `null`, and add schema validation for every
   generated summary and report. Create the session before local-service launch, retain launcher and
   installer/runtime identity even if startup fails, rotate bounded files, and export one atomic
   redacted ZIP to the Windows Desktop without requiring the backend to be healthy.
5. **Remove stale authority-sync noise and contradictory readiness output.**
   **Status (2026-08-28): implemented in source with stable repeated-poll, open-room Stop, authority-loss,
   and desktop projection regressions; installed requalification remains.**
   Do not publish a terminal endpoint phase after local room authority has been released, deduplicate repeated sync warnings,
   and never report the relay axis as both failed and reachable in the same snapshot. In the 2026-08-28
   installed smoke test, after End stopped the endpoint and Close Trade Room removed all authority,
   `/api/status` still returned `failed` with `relay.peer_lost`; readiness simultaneously reported relay
   `failed` with the message "The online relay is reachable" and session `failed` with "No Switch
   connection is active." Clear or archive the active endpoint snapshot on a confirmed Stop, distinguish
   historical attempt outcome from current app readiness, and add a regression proving an open-room Stop
   and a room close converge to one stable idle projection across every polling endpoint. The exported
   bundle also contained 120 identical `authority_phase_sync_failed` events at the two-second polling
   interval after authority was gone; stop publishing terminal phases without authority and rate-limit or
   state-deduplicate any genuinely actionable sync warning.
6. Validate the replacement installer on clean Windows 10 22H2 and Windows 11 systems.
7. Deploy and verify a relay supporting `rfu-tunnel.v1` and `manual-switch-role.v1`.
8. Create one shared API contract source for Python and C#.
   **Status (2026-09-01):** canonical schemas exist for the internal `connection-run.v1`, relay
   `app-readiness.v2`, Desktop `production-connection-run.v1`, and Desktop
   `local-app-readiness.v2` projections. Python routes and C# DTO/self-tests use the non-colliding
   Desktop names. Generation from one language-neutral model remains developer-experience debt.
9. Build a real WPF ↔ local control ↔ relay integration harness.
10. Split the oversized backend orchestration module along existing responsibility boundaries.
    **Status (2026-08-29):** the new serialized connection coordinator exists as an isolated package;
    the legacy backend remains untouched and active until the later atomic cutover, so this item is
    not closed.
11. Split the oversized frontend API and state classes without changing the frozen contracts.
12. Add WPF UI Automation for dropdowns, navigation, room state, reconnect, leave/close, and stale
   errors.
13. Run complete two-PC/two-Switch RTL8192EU qualification after items 2–5 pass their regressions.

## 2. Post-release qualification

1. Run the complete production topology with two Windows PCs, two RTL8192EU adapters, two Switch
   consoles, and the hosted relay across two independent NATs.
2. Repeat full create/join, room entry, movement, trade, save, menu return, graceful exit, second
   attempt, reconnect, and room reuse cycles.
3. Run long-duration radio and relay soak tests with loss, reorder, latency, endpoint restart, relay
   restart, and temporary internet loss.
4. Qualify a second physical RTL8192EU unit and record hardware revision, USB topology, driver, signal,
   channel, and receive-health results.
5. Validate Install, Update, Repair, Rollback, Uninstall, reboot continuation, and custom-kernel restore
   on clean supported Windows machines, including non-ASCII usernames and managed-policy failures.
6. Test recovery from relay database backup and verify active-room expiration after an intentional
   authority reset.
7. Add Windows code signing and trusted timestamping before a wider public release. The private beta
   remains intentionally unsigned.
8. Complete physical Windows 10 22H2 qualification: clean install, reboot resume, custom-kernel boot,
   USB/IP attach, RTL8192EU health gate, full two-console trade, update, rollback, and uninstall.
9. Implement the GUI-independent
   [single-PC dual-adapter, Switchless C+D suite](93-single-pc-dual-adapter-switchless-cd-suite-20260831.md).
   **Status (2026-08-31): campaign closed after Q0-Q5 and the user-approved Q6 10/10; production
   packaging is intentionally not required.** PC A detects and authorizes two distinct supported RTL8192EU adapters;
   Q0-Q2 made no USB/WSL radio or Switch mutation. The versioned state/report contract,
   immutable fixture identity, random challenge evidence, stable failure model, and optional exact
   Linux sysfs lease identity are implemented. Two same-VID/PID fake devices prove independent
   attach/probe/recovery and reverse cleanup while the default production single-adapter evidence and
   recovery shapes remain unchanged. The latest full qualified Python suite passed `567 passed, 3
   skipped`. Two canonical isolated workers then passed hosted C0/C1,
   mutation-free status, a deliberately delayed C2 barrier, bidirectional synthetic RFU, and D cleanup
   in `q2-normal-20260831-04`; the worker-death case preserved its first failure and verified cleanup.
   Q3 passed exact attach-delta mapping, distinct per-PHY/netdev actual RX, and B-to-A cleanup in
   `q3-radio-20260831-03`. Q4 passed a real hosted integrated C+D run while both exact leases remained
   held. Q5 passed 125 focused faults plus a real-relay worker-death expected failure. Q6 then passed
   10/10 valid integrated runs (the user reduced the target from 30), with zero forced workers, open
   rooms/credentials, recovery files, attached Linux USB devices, or non-restored Windows ownership.
   This source qualification tool is not a concurrent-radio product feature. Further repetition and
   dedicated Q3/Q4 packaging stop here; M8 now wraps the admitted one-radio production path.
   Switchless evidence never replaces the final two-PC/two-Switch run.

## 3. Reliability and product operations

1. Add an update channel and verified in-app update flow with rollback.
2. Add crash reporting that preserves the existing redaction and opt-in boundaries.
3. Add relay dashboards/alerts, backup automation, capacity limits, and an operator runbook.
4. Design shared live-peer routing, distributed presence, ordered events, and rate limits before using
   multiple relay workers or replicas.
5. Improve reconnect UX for endpoint restart, adapter reattachment, and expired room attempts.
6. Continue movement/jitter optimization using timestamped VBlank, queue-depth, RTT, retransmission,
   and user-visible motion measurements.
7. Perform a complete accessibility pass: keyboard-only, screen reader, high contrast, 200% scaling,
   localization length, and reduced motion.
8. Continue owner-led visual polish without changing server authority or protocol contracts.
9. **Potential issue: reconcile credentialless complementary-role rooms.** On 2026-08-30 the hosted
   relay reported two rooms in `waiting_for_complementary_role` while
   `active_member_credentials` was zero. Aggregate metrics cannot prove that these rooms came from
   D8-D10, and this is not currently a functional or release blocker. Inspect their room events and
   member-presence history before changing behavior. If a room has no active credentials, no
   reconnectable member, and no live or admitted RFU attempt, make its terminal/expiry transition
   explicit and keep `rooms_by_state` truthful; never expire a legitimately reconnecting room. Add a
   lifecycle regression covering complementary-role wait, credential loss, reconnect grace, global
   TTL expiry, and metrics projection.

## 4. Additional Switch-to-Switch features

1. FireRed/LeafGreen link battles.
2. Union Room flows.
3. Other Direct Connection multiplayer modes exposed by the Switch application.
4. Feature-neutral session negotiation so both endpoints select the same protocol module before radio
   roles lock.
5. Native captures and replay fixtures for every added feature's opening, blocks, commands, barriers,
   cancellation, and teardown.

All product features remain Switch-to-Switch. PC-to-Switch trading is a development harness, not a
future product mode.

## 5. Hardware and driver expansion

This section is post-beta optional work. It does not restore the retired Debug menu or make an
Adapter Test button a current production-beta requirement; the current beta exposes support-log
export only.

1. Add an **Adapter Test** button beside **Use selected adapter**. It must work with any detected USB
   Wi-Fi adapter and report staged compatibility results for Windows authorization, WSL attachment,
   driver binding, PHY/interface creation, supported radio modes, channel control, and RX health.
   Clearly distinguish a software capability pass from physical Switch qualification.
2. Diagnose and fix RTL8188EU control-port association, AP+monitor concurrency, and receive-death
   behavior under WSL; keep it quarantined until it passes the same gates as RTL8192EU.
3. Physically qualify the already-profiled MT7610U, MT7612U, RT2770, RT3070, RT3572, and RTL8821CU
   candidates through observe → join → host → full trade → soak.
4. Re-evaluate AR9271 only after the known association failures have a reproducible driver-level fix.
5. Add other upstream-supported adapters through the data-driven matrix and diagnostic promotion
   process.
6. Add 5 GHz-capable hardware and validate LDN channels 36, 40, 44, and 48.
7. Automate firmware inventory and package validation for newly supported adapters.
8. Build a new custom kernel only when a required driver/configuration is absent; do not fork the core
   application for a chipset.

## 6. Party display, history, and optional statistics

1. Complete live two-party 2×3 presentation with validated hover/focus stat details during a native
   Switch-to-Switch session.
2. Expand the decoder fixture corpus across languages, versions, party conditions, mail, ribbons, and
   malformed records.
3. Add a local trade history backed only by fail-closed committed-trade evidence.
4. If separately approved, design an optional server ingestion service for committed trades with
   explicit consent, data minimization, retention, deletion/export, coarse location, and
   pseudonymization. This service must remain separate from the opaque RFU relay.
5. Never upload raw RFU frames or complete Pokémon records merely to produce statistics.

## 7. Developer experience

1. Add deterministic protocol traces generated from synthetic/replay data so contributors do not need
   private captures.
2. Add API schema generation for the local and relay v1 contracts.
3. Add reproducible clean-machine CI for WPF publish, installer audit, package inventory, relay smoke,
   and kernel manifest validation.
4. Publish hardware qualification templates and a driver contribution guide.
5. Keep `TECHNICAL_GUIDE.md`, `FRLG_PROTOCOL.md`, and this file updated with every behavior change.
