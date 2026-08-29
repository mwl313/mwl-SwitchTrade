# SwitchTrade Future TODO

This is the definitive implementation and qualification ledger. Together with
`80-abc-connection-architecture-20260829.md`, it supersedes older connection plans. Items are ordered
within each section; historical beta notes remain as evidence, not as authority for the new ABC+D
path. No open item may be presented as a current production capability.

## Critical and urgent blockers

1. **CRITICAL — URGENT: Restore the complete WSL LDN prerequisite gate.**
   **Status (2026-08-29): PC A passed the immutable installed cold P0 and verified cleanup. The owner
   accepted that result as sufficient to begin Milestone 3. The direct A0-A9 endpoint/harness is
   complete and PC A passed its one-Switch installed-runtime qualification with verified cleanup.
   Direct B2-B10 is source-complete and its final immutable PC A runtime passed installed no-hardware
   smoke. A prior PC A run physically passed B2-B10 but exposed post-B10 teardown misclassification;
   final PC A confirmation, PC B P0/direct A/direct B, and production-path cutover remain open.**
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
   ordered teardown checkpoints retained in the report. Immutable runtime `abcd-m4-9635a1f` passed
   package and installed-runtime smoke on PC A and is waiting for final physical confirmation; no B1,
   `B_READY`, relay delivery, or trade is claimed.

   **Deferred qualification debt (owner-directed, 2026-08-30):** retain one PC A run with a real
   searching Switch against runtime `abcd-m4-9635a1f`. It must pass B2-B10, exit through
   `factory_released`, report `ldn_context_released=true`, verify radio/USB cleanup, and leave no
   endpoint, interface, PHY, lock, or recovery residue. Work may proceed to Milestone 5, but this item
   remains open and Milestone 4 must not be represented as formally accepted until that run passes.

2. **CRITICAL — URGENT: Preserve relay frame order and truthful P0/A/B/C/D diagnostic stages.**
   **Status (2026-08-30): core M5 v2 source and local relay validation implemented; external
   validation deployment plus M8/M9 diagnostic/application migration remain open.**
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
   retirement. Local uvicorn and hosting smoke passed. This does not close the item until the exact
   immutable relay artifact passes the same matrix through validation HTTPS and the production
   diagnostic/UI projections migrate to the factual v2 C gates.

3. **CRITICAL — URGENT: Add the attempt-scoped A_READY/B_READY activation barrier.**
   **Status (2026-08-29): confirmed architecture gap; not implemented.**
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

4. **CRITICAL — URGENT: Make D cleanup two-sided, attempt-scoped, and outcome-preserving.**
   **Status (2026-08-29): confirmed architecture gap; not implemented.**
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

   Acceptance covers successful trade, Stop, room close, peer loss, endpoint hang, app close, relay
   restart, and PC restart at every D gate. No new attempt is enabled until both shared authority and
   the local resource owner have a terminal verified record; repeated cleanup commands are idempotent.

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

7. **URGENT: Add a production-path, single-machine diagnostic before resuming separated testing.**
   **Status (2026-08-28): the existing adapter-check workflow is fixed in source and now uses the
   production attach, Linux-enumeration, radio-preparation, driver, RX, and exact-device cleanup gates.
   The `production-diagnostic.v1` debug menu, synthetic peer, and guided checks are implemented in source.
   Installed qualification (including repeated one-PC runs) and physical qualification remain pending.**
   Implement the approved design in
   [`79-production-debug-menu-design-20260828.md`](79-production-debug-menu-design-20260828.md).
   Extend the existing hardware diagnostics instead of creating mock wrappers. The automated tier must
   run the real wrapper, radio preparation, selected-adapter gate, endpoint initialization, hosted-relay
   connection, and a bidirectional nonce exchange against an isolated synthetic peer. It must exercise
   the Group Leader and Joining policies sequentially, prove exactly one PID per attempt, and verify full
   cleanup. The guided tier must then use the same production transports to (a) detect and join a room
   created by a nearby Switch and (b), after teardown, create the mirrored AP and wait for a Switch to
   associate. A captured advertisement may drive an optional software-only AP check, but that result must
   not be called physical radio qualification.

   The debug room must be private, short-lived, and absent from public search. The UI must use explicit
   Start, Continue, Retry, Cancel, and Finish actions with no polling-triggered launches, show each stage
   and stable failure code, and save a redacted diagnostic report in the normal support bundle. Result
   levels must distinguish automated wrapper/relay/adapter pass, physical room detected, physical AP
   association, and the final two-PC/two-Switch end-to-end pass. Thirty consecutive runs of both roles on
   each PC, including cancellation and expected failure cases, must produce no duplicate launch, orphan
   process, stale lock, or altered adapter state.

   Integrate the current Connection diagnostic into this same production hardware lifecycle. On
   2026-08-28, `hardware-diagnostic.v1` reported `USB_NOT_FOUND` for an RTL8192EU that Windows had
   detected and authorized because the diagnostic inspected WSL without first attaching the selected
   physical device. After the production attach path ran, `usbipd` published `ClientIPAddress` before
   Linux had enumerated `0bda:818b`; the immediate radio check then failed generically. A bounded retry
   after Linux enumeration loaded `rtl8xxxu`, passed actual RX, and left `wlan0` in monitor mode on
   channel 6. Treat Windows shared, USB/IP attached, Linux enumerated, driver bound, interface ready,
   and actual RX as separate ordered gates. Reuse the exact selected-device attach helper, wait for the
   matching VID:PID sysfs device and expected driver/interface rather than trusting `ClientIPAddress`
   alone, and retain bounded redacted attach/radio-gate stderr with the stable failure code. If the test
   attaches or reconfigures the adapter, label it an active production diagnostic rather than read-only
   and restore its prior state during cleanup. A freshly installed, shared-but-unattached adapter must
   reach a factual terminal result in one run without a false `USB_NOT_FOUND` or manual retry.

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
   **Status (2026-08-28): the confirmed evidence-retention and null-redaction defects are fixed in source
   with bounded/redacted launcher evidence regressions. Broader schema validation remains future work.**
   Include a bounded set of recent endpoint runs plus pre-endpoint launcher/gate failures, so a middle
   attempt is not lost when a later attempt overwrites `endpoint-state.json`. Preserve JSON value types
   during redaction: the 2026-08-28 bundle changed an inactive `session_id: null` into the string
   `"<redacted>"`, which falsely suggests that a value existed and weakens automated evidence checks.
   Redact only present sensitive values, keep `null` as `null`, and add schema validation for every
   generated summary and diagnostic report.
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
   **Status (2026-08-29):** `connection-run.v1` now has a canonical JSON schema and Python projection
   tests in Milestone 1. C# validation and the remaining v2 contracts are still open for their cutover
   milestones.
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
