# SwitchTrade full-stack reliability audit

Last updated: 2026-08-27

## Decision

The software audit started from frozen `audit` commit
`6c52e13a5fb86f8503537fbb8b8ec1b16929650c`. Discovery was read-only. Fixes were
implemented only after the first register was reviewed, and every cross-layer P0/P1 correction was
reviewed by an agent other than its author.

At reviewed code revision `33712f3`, there are no known open **software-verifiable** P0 or P1
defects inside the supported beta boundary. This is not a zero-bug guarantee and it is not a physical
qualification result. RTL8192EU, clean-host Windows lifecycle, hosted-relay deployment, and the final
two-PC/two-Switch trade remain explicitly pending external validation.

## Supported beta boundary

- Windows 10 22H2 x64 build 19045 and Windows 11 x64.
- Current Microsoft Store WSL2 with the packaged custom kernel.
- Production adapter RTL8192EU `0bda:818b`.
- Native WPF client, isolated `SwitchTrade` WSL distro, local control service, hosted relay,
  installer, update, repair, rollback, and uninstall lifecycle.
- FireRed/LeafGreen Direct Connection trading.
- Experimental adapters may be selected for diagnostics, but are not trading-qualified.

Privacy/analytics UI, visual redesign, code signing, experimental-adapter trading, battles, Union
Room, 5 GHz, and physical Switch qualification were intentionally excluded.

## Audit method

The work used one coordinator and three specialists in two discovery waves. Windows lifecycle,
radio/runtime, client/control, relay authority, RFU/protocol, packaging, and adversarial QA were
reviewed separately. The second wave cross-reviewed assumptions across boundaries. Findings were
deduplicated only when a common root cause was demonstrated.

Each blocker below records the affected requirement, evidence/root cause, correction, regression,
and validation state. **Fixed** means the software correction and regression passed. **Fix ready for
physical validation** means the software defect is closed but the hardware or two-PC acceptance gate
has not been run.

## P0 register

| ID | Requirement and evidence/root cause | Correction and regression | Status |
|---|---|---|---|
| STB-001 / CCA-001 / REL-005 | Connection coordination must be non-blocking. The old control request owned a hidden 20-second rendezvous and WPF mapped unrelated 409 responses to “room full.” | Relay authority now records explicit Group Leader/Joining roles, creates one attempt only for two complementary ready members, and returns structured state immediately. Both role orders, simultaneous requests, stale attempts, and two-control cleanup are tested repeatedly. | **Fix ready for two-PC validation** |
| STB-002 / RADIO-002 | A transient USB bus ID was used as device identity. Replug/reboot could select the wrong adapter, and identical VID:PID devices were ambiguous. | APIs and persisted selection carry Windows InstanceId plus current bus ID. Bus ID is resolved at mutation time and named gates expose detected/shared/attached/USB-visible/driver/PHY/RX state. Re-enumeration and duplicate-device simulations pass. | **Fix ready for physical validation** |
| STB-003 / RADIO-001 | A cold RTL8192EU could be USB-visible but driver-unbound because the production profile relied on module autoload. | The profiled in-tree module is explicitly loaded before driver/PHY/interface/channel/RX gates. Fake-sysfs cold-start, fatal-driver, PHY handoff, lock, and RX recovery workflows pass. | **Fix ready for physical validation** |
| RADIO-003 | Health gating could select a nonzero PHY while the endpoint or diagnostic later hard-coded `phy0`. | The gated PHY is exported and required by the workload. Nonzero-PHY and missing-handoff regressions pass. | **Fix ready for physical validation** |
| RADIO-004 | Setup treated firmware embedded in the custom kernel as missing external firmware. | Kernel/package integrity now validates the bundled firmware identity and exact kernel/module release coherently. Built-in, external, absent, tampered, and mismatched fixtures are covered. | Fixed; clean-host boot pending |
| WIN-001 / STB-004 | Install/Repair/Update could commit WSL/kernel before Windows and leave mixed releases after failure. | One persisted release transaction stages and validates Windows, WSL, kernel, configuration, and rollback metadata. Fault injection covers every forward stage and compensation stage. | Fixed; clean-host lifecycle pending |
| WIN-002 / XIR-001 | A same-name or copied-marker WSL distro could be adopted or unregistered. Purge could mutate Windows before reliable WSL enumeration and could race a distro replacement. | Every destructive action requires a per-install UUID and the exact current Lxss BasePath. Purge requires known enumeration before any mutation and rechecks identity immediately before unregister. Foreign/copy, enumeration-failure, and swap-race tests prove zero destructive action. | Fixed |
| WIN-003 / XIR-003 | Kernel rollback could restore the wrong generation. Later review found that process death between WSL, kernel, Windows, and metadata swaps corrupted lifecycle state; reverse rollback recovery also had no satisfiable package identity. | Rollback journals source/target releases, exact Windows/WSL/kernel/config anchors, and independently verified initiating-package root/release/manifest SHA before the first mutation. Fresh Repair classifies actual axes, compensates or finalizes, then publishes one rotated completed record. Separate PowerShell processes die after every axis and before publish, enter the actual Repair wrapper/package gate, converge, and complete reverse Rollback. Same-release replacement packages are rejected without mutation. | Fixed |

## P1 register

| ID | Requirement and evidence/root cause | Correction and regression | Status |
|---|---|---|---|
| CCA-002 / REL-006 | Errors were inferred from English text or generic HTTP status. | Control and relay use `code`, `message`, `stage`, `recoverable`, `primary_action`, and `correlation_id`; WPF maps codes only. Unknown/error-envelope tests pass. | Fixed |
| CCA-003 / CCA-004 | Retry had a wrong call signature and remote close left stale UI/session state. | Retry uses the authoritative attempt contract; terminal room events clear or recover state deterministically. Direct and two-control regressions pass. | Fixed |
| CCA-005 | Desktop/control/relay revisions could appear compatible when capabilities differed. | Health advertises explicit release and capability contracts and rejects incompatibility before room creation. | Fixed; hosted relay redeploy required |
| CCA-006 / CCA-008 | Hardware polling exceptions could escape `async void`; arbitrary loopback origins could mutate control state. | Polling contains timeout/parse failures and preserves the last good inventory. Control restricts mutation origins and tests malformed, timeout, and rejected-origin cases. | Fixed |
| CCA-RX-001 | A valid but unmatched reconnect credential was hidden as Home while local authority blocked all new rooms. | WPF exposes structured recovery. The user must explicitly confirm a local-only authority reset; Cancel preserves state and endpoint cleanup precedes reset. | Fixed |
| CCA-RX-002 | `reconnect_deadline_expired` was collapsed to `room_not_active`, and readiness could consume it while an endpoint remained live. | The exact relay envelope reaches WPF. Terminal transition adopts/verifies and stops only the matching endpoint before clearing credentials; readiness probing is non-destructive. Recovery, cancel, immediate relaunch, and endpoint A/B isolation tests pass. | Fixed |
| END-001 | Control used a 250 ms launch heuristic and could mistake a different process after restart/PID reuse. | The shell acquires a global `flock`, writes a nonce-bound acknowledgement, and retains the lock through `exec`. Endpoint state binds PID start ticks, argv, session, nonce, and WSL distro. Linux and Windows-in-WSL signaling pin pidfd before identity validation. | Fixed |
| END-002 | A control restart between acknowledgement and endpoint-state creation lost the session; natural exit during stop left stale state; Windows validated then separately killed a numeric PID. | Late verified state is adopted, disappearance is idempotent, live mismatch fails closed, and Windows uses one in-WSL pidfd validate-and-signal helper. Real shell lock and focused race regressions pass. | Fixed |
| RADIO-006 / RADIO-010 | Capture, diagnostics, endpoint, and repair could race; subprocesses could wait indefinitely. | Mutating radio workflows share an ownership lock and bounded process policy. Contention, timeout, cancellation, and cleanup simulations pass. | Fixed |
| RADIO-007 / RADIO-008 | Cleanup could remove interfaces while a worker lived; packetless RX triggered an unsafe automatic USB reset. | Cleanup refuses while the worker is alive. Normal packetless launch is `RX_INCONCLUSIVE`; reset is explicit recovery only. | **Fix ready for physical validation** |
| RADIO-009 / WIN-012 | Reboot continuation reused a stale bus ID and could leave auto-attach state. | Resume persists stable identity, resolves the current bus, and rollback/uninstall remove owned continuation state. | **Fix ready for physical validation** |
| WIN-004 through WIN-013 | Release identity, rollback validation, concurrent Setup, prerequisite versions, path quoting, elevation identity, diagnostics, `.wslconfig`, resume state, and staged readiness had independent lifecycle gaps. | Exact release/hash/capability checks, a global Setup mutex, argument-safe launches, invoking-user path capture, owned-block `.wslconfig` edits, durable diagnostics, and staged control validation were added. Win10/non-ASCII/space-path/prerequisite/fault fixtures pass. | Fixed; clean-host validation pending |
| WIN-014 | Reopening Setup after process death at WSL import required the user to guess Repair; an unrelated legacy `.previous` tree could block recovery; re-extracting the same package changed its path identity; and default uninstall retained a distro that the next install could not coherently adopt. | The original action and Repair now re-enter one recovery path, pre-runtime fresh installs can be safely compensated by a verified successor package, legacy trees are moved to a non-destructive recovery archive, new transactions bind the manifest SHA rather than the extraction path, Setup exposes only state-valid actions for the invoking user, ambiguous imports remain recoverable, and uninstall removes the owned distro then publishes `uninstalled`. Focused entry, process-death, package-identity, and uninstall-state regressions pass. | Fixed; clean-host lifecycle pending |
| XIR-002 | Recovery could finalize missing/corrupt files, and an unanchored WSL candidate could self-authenticate with a regenerated manifest. | Complete trusted Windows/WSL artifact manifests are anchored before exposure. An unanchored candidate is discarded/restaged from the verified package; tampered-artifact/manifest tests cannot promote it. | Fixed |
| XIR-004 | WSL enumeration failure was interpreted as “distro absent,” allowing invalid compensation state. | Enumeration has an explicit unknown/error result that cannot mutate phase. Timeout/failure then retry converges. | Fixed |
| REL-001 through REL-016 | Relay review found retention, stale WebSockets, state regression, unlocked roles, retry storms, nontransactional expiry, weak idempotency, multi-writer risk, spoofable limits, shallow health, offline directory entries, backup, and dependency-image reproducibility gaps. | Authority mutations use SQLite transactions and monotonic versions; credentials rotate; WebSockets bind room/attempt/direction; terminal errors stop retry; one writer is enforced; storage readiness, trusted-proxy identity, pruning, backup/restore, locked dependencies, and bounded limits have focused regressions. | Fixed |
| PRT-001 through PRT-008 | Peer readiness, reconnect epochs, restart advertisement, sequence eviction/wrap, K-ACK backlog, malformed payloads, passive decoder integrity, and shutdown/resource bounds could drop, replay, mutate, or leak RFU data. | Attempt-bound opaque forwarding, generation-isolated queues, ordered bounded dedup, backpressure, deterministic replay/property/fuzz seeds, passive fail-closed decoding, and bounded shutdown were added. | Fixed; staging/two-Switch validation pending |
| QA-001 through QA-006 | No root CI; fixtures were Windows-incompatible; dependencies and package output depended on ambient state/timestamps. | Windows/Linux CI uses Python 3.12 locks, .NET 10.0.302, PowerShell 5.1/7 parsing and simulations, ShellCheck, vulnerability audits, portable fixtures, offline wheelhouse validation, exact manifests, and deterministic archive metadata. | Fixed |

## Final automated evidence

The final source validation must be rerun after the last documentation commit. The latest code-only
checkpoint produced:

- Python 3.12 locked root suite: **311 passed, 3 expected platform skips** on Windows. The three skips
  require native Linux/WSL (`nl80211` and the real POSIX shell-lock test); Linux CI runs them.
- Role/order/concurrency/restart selection: **70/70** across ten repeated rounds.
- PowerShell 5.1 and PowerShell 7 Setup lifecycle: PASS.
- PowerShell 5.1 and PowerShell 7 kernel lifecycle: PASS.
- PowerShell 5.1 and PowerShell 7 separate-process rollback-death lifecycle: PASS.
- Tracked shell syntax, full ShellCheck, and fake-sysfs radio workflow: PASS.
- Desktop and Setup Release builds: zero warnings and zero errors; desktop `--self-test`: PASS.
- Locked Python dependency audit: no unreviewed known vulnerability; reviewed exceptions are
  version-bound and expiring. Both .NET dependency graphs report no known vulnerable package.
- Local production-mode relay smoke: legacy unauthenticated endpoint rejected, two authoritative
  members/roles established, opaque RFU forwarded in both directions, and room closed.
- A real production-mode local relay resource soak forwarded **4,096 deterministic frames in each
  direction (8,192 total)** with exact payload/order and bounded queues, RSS, threads, logs, and
  platform resource counts (Windows handles; Linux FDs/sockets). Cleanup and credential redaction
  assertions passed on Windows; Linux CI owns the `/proc` FD/socket assertions.
- Deterministic malformed-frame, property, sequence-wrap, decoder, restart, backup, and redaction
  suites: PASS.

## Requirement-to-test traceability

| Requirement | Automated evidence | External evidence still required |
|---|---|---|
| Win10/Win11 Install/Repair/Update/Rollback/Uninstall | Setup build, complete transaction/fault matrix, separate-process rollback death and reverse rollback | Clean Win10 and Win11 lifecycle, reboot, UAC cancellation, low disk |
| Isolated WSL/custom kernel | Ownership UUID/BasePath, hash/release/config and rollback journal simulations | Clean-host import, boot, rollback, uninstall |
| RTL8192EU lifecycle | Stable ID, cold module, dynamic PHY, named gates, RX semantics, lock tests | Two real adapters; cold boot/replug/RX on Win10/11 |
| Desktop/control | WPF build/self-test, control integration, reconnect/recovery and endpoint race tests | Two-PC UX qualification |
| Relay authority | Concurrency, rotation, expiry, restart, storage, backup and WebSocket tests | Deploy current relay; proxy/backup/restart drill |
| Opaque RFU | Production-mode bidirectional 8,192-frame resource soak plus replay/property/fuzz and bounded-queue tests | Public staging two-NAT smoke and two-Switch trade |
| FRLG Direct Connection | Golden vectors, partial trade-state fixtures, observer commit fixtures, and one `.pk3` tunnel payload | Full discovery-to-teardown RFU transcript and final two-PC/two-Switch complete trade |
| Logging/support | Structured envelopes and credential/header/key redaction tests | Human review of a clean-machine support bundle |
| Reproducible package | Deterministic builder and synthetic archive regression | Two clean production builds with byte comparison, then install the final archive on clean Win10/11 |

## External blockers and honest completion boundary

1. The public relay observed during the audit still advertised only `room-control.v1` and
   `public-directory.v1`; it did not advertise the current `rfu-tunnel.v1` and manual-role
   capability. The server operator must deploy the current repository revision before the new
   client can use public rooms.
2. STB-002 and STB-003 remain **Fix ready for physical validation**. Simulation cannot prove USB/IP,
   kernel, firmware, driver, channel, and RX behavior on every physical Win10/Win11 host.
3. The final two-PC/two-Switch FireRed/LeafGreen trade is not claimed. It is the release-qualification
   test for the already-built software path.
4. The package remains unsigned by owner decision. Signing is outside this audit.

## P2/P3 backlog

- Resolve the existing repository-wide lint/style modernization backlog without mixing broad
  refactors into the reliability fixes.
- Complete UI Automation labels, keyboard navigation, and accessibility QA.
- Improve visual design separately from the frozen backend contracts.
- Qualify experimental adapters, battles, Union Room, 5 GHz, analytics, and future server features
  only in their own test plans.

The software audit is complete only when the final package checks pass from a clean committed tree
and their artifact hashes are reported with the handoff. No
simulation in this report should be represented as physical Switch or clean-host qualification.
