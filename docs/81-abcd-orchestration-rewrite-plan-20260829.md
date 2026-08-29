# ABC+D selective orchestration rewrite plan

## 1. Decision and execution rule

Rebuild the ABC+D connection orchestration from scratch on
`codex/abcd-orchestration-rework`, while reusing only low-level components that pass explicit
admission tests. This is not a clean-room product rewrite and it is not another series of patches to
the current orchestration.

This work is deliberately incremental. Every milestone produces a reviewed commit, test evidence,
an accepted/rejected component ledger, and a rollback point. Work stops after each milestone until
its exit gate is accepted. The normative behavior and ordering remain defined by
[`80-abc-connection-architecture-20260829.md`](80-abc-connection-architecture-20260829.md) and the
definitive [`FUTURE_TODO.md`](FUTURE_TODO.md).

Three independent audits were completed against those documents, the root README, the current code,
and existing tests. Their corrections are incorporated here:

- Direct A and B are admitted before C integration.
- Existing transport classes are conditional candidates, not approved dependencies.
- One WSL worker retains Linux radio ownership continuously through the attempt.
- C frames are attempt-scoped and strictly ordered.
- D remains distributed through verified local release.
- The separate validation relay is staging for the identical production artifact, never an alternate
  diagnostic stack.

## 2. Architecture and interface decisions

- Add one concrete ABC+D connection package containing a serialized `ConnectionCoordinator`, one
  persisted `connection-run.v1`, one long-lived WSL worker per local run, and dedicated P0/A/B/C/D
  stage owners. Do not add a plugin framework, selectable AP engine, or legacy fallback.
- Keep functional and cleanup outcomes separate. A functionally completed run with
  `cleanup_verified=false` requires recovery, cannot appear as Passed, and blocks another run.
- Use separate closed enums for relay seat, A/B Switch-side role, LDN station/AP role, RFU
  parent/child role, and tunnel direction. Legacy `host`/`guest` strings may exist only inside a
  compatibility adapter.
- Serialize start, continue, cancel, endpoint events, timeouts, recovery, and shutdown through the
  coordinator. GET requests read immutable snapshots and never launch, retry, recover, or mutate.
- Preserve current HTTP route paths. Introduce `connection-run.v1`, `room-control.v2`,
  `rfu-tunnel.v2`, `app-readiness.v2`, and `production-diagnostic.v2`. Store their canonical shapes
  in versioned JSON schemas and validate Python models and C# DTOs against them.
- Restrict the production ABC+D path to the qualified RTL8192EU `0bda:818b`. Experimental adapters
  remain available only to standalone hardware diagnostics.
- Reserve `0.3.0-beta.1`, with MSI/bundle version `0.3.0`, for the first packaged ABC+D release.
  Preserve existing MSI and bundle UpgradeCodes.

## 3. Milestones

### Milestone 0 — Baseline and reuse admission

- Review the current dirty worktree and preserve documentation, prior fixes, and characterization
  tests in separate baseline commits before rewriting.
- Record known failures as failures. Existing tests may characterize behavior but cannot certify
  ABC+D readiness.
- Create a reuse ledger covering ownership, stop behavior, privacy, error bounds, test evidence, and
  physical evidence.
- Conditionally consider only proven `ldn.scan/connect` mechanics, canonical
  `ldn.create_network()` construction and compatibility patches, low-level Windows inventory and
  usbipd helpers, three-state Linux probes, authority transaction/membership/version primitives,
  a strictly read-only `PassivePartyObserver`, and a demonstrably feature-neutral Pia/Reliable bridge.
- Reject the current control/session orchestration, endpoint orchestration, diagnostic orchestration,
  current v1 tunnel implementation, implicit transport retries, legacy role axes, `RemoteTransport`,
  prototype AP engines, and legacy relay sessions.

Exit gate: baseline tests are reproducible, every candidate is admitted or rejected with evidence,
and no known defect is reclassified as passing.

### Milestone 1 — Coordinator, identity, and launch ownership

- Implement `created -> preflight -> running/awaiting_user -> closing -> cleaning -> terminal` with
  the current gate, last passed gate, primary functional result, secondary cleanup result, cleanup
  proof, recovery state, and immutable run/attempt/launch identities.
- Distinguish `wrapper_acquired`, `P0_SIDE_READY`, and `endpoint_started`. Enforce one coordinator,
  worker, endpoint launch, and adapter lease per local run. Retry is explicit and follows cleanup.
- Capture every attempted PID, bounded stdout/stderr, exit code, launch nonce, and terminal record in
  backend-owned storage rather than desktop-owned pipes.

Exit gate: GET polling causes zero launches/mutations; an early wrapper failure creates one PID and
one factual terminal record; Stop during attach prevents launch; Retry is explicit; desktop
close/reopen leaves no backend on dead pipes; unverified cleanup blocks new work.

### Milestone 2 — P0 and continuous WSL radio ownership

- Implement passive P0a release, runtime, tool, privilege, relay path, exclusivity, adapter identity,
  module, firmware, regulatory, and payload-hash validation without changing hardware ownership.
- Implement one long-lived WSL worker that acquires the Linux radio lock, runs P0b, emits one atomic
  machine-readable report, waits for one C0.2 launch ticket, replaces itself with the endpoint while
  retaining ownership, and cleans up if control disappears.
- Windows control owns USB attach/return and recovery; the worker owns the Linux lock and PHY; the
  endpoint owns A or B, its tunnel, and local protocol resources.
- Load and verify in order: `usbip-core`, `vhci-hcd`, Linux enumeration, `cfg80211`, `libarc4`,
  `mac80211`, `led-class`, `rtl8xxxu`, firmware, `ccm`, `cmac`, `tun`, `/dev/net/tun`, exclusive PHY
  preparation, and actual RX.
- Keep the proven 30-second driver-probe allowance inside a 45-second containing budget. Record prior
  ownership, attach once only when required, and detach only if this run attached the adapter.

Exit gate: cold-boot P0 passes on both PCs; delayed enumeration, partial probe, stale sysfs, command
timeout, inactive usbip port, and adapter changes classify correctly; cleanup restores prior ownership.

### Milestone 3 — Direct A admission

- Build a new A stage owner around admitted LDN station mechanics rather than reusing the current
  `LiveTransport` lifecycle wholesale.
- Remove implicit retry, broad cleanup, communication-ID fallback, shared global mutation, and raw
  advertisement/MAC logging from the new path.
- Execute A0-A9 and a bounded local hold, then emit the validated advertisement to the direct harness.

Exit gate: each PC joins one Switch-hosted room through A0-A9 and cleans up correctly. This is local A
evidence only, not A10, C1, or `A_READY`.

### Milestone 4 — Direct B admission

- Build a new B stage owner around canonical `ldn.create_network()` mechanics and admitted
  compatibility patches.
- Use one immutable release-owned advertisement fixture and execute B2-B10, including externally
  observable advertisement, real Switch association, control-port readiness, and bounded hold.
- Do not treat AP-open as Switch association or `B_READY`.

Exit gate: each PC passes B2-B10 with one searching Switch and cleans up correctly. This is local B
evidence only, not B1 or live A-to-B delivery.

### Milestone 5 — C0/C1 and `rfu-tunnel.v2`

- Deploy a validation environment running the exact immutable relay artifact and configuration model
  intended for production. It is not user-selectable and is not acceptance evidence by itself.
- Give v2 authority its own store namespace and enforce
  `P0a -> C0.1 -> P0b on both PCs -> C0.2 -> C0.3` before A begins.
- Implement an attempt-scoped envelope containing attempt, source seat, source epoch, contiguous
  sequence, kind, and bounded payload. Support `PEER_READY`, `PROBE_CHALLENGE`, `PROBE_RESPONSE`,
  `ADVERTISEMENT`, `SIDE_READY`, and `PEER_CLOSE`.
- Use one contiguous sequence gate for live and retained frames. Reject gaps, duplicates, stale
  attempts/epochs, wrong seats/directions, and mismatched credentials.
- Reproduce the confirmed late-peer defect and prove sequence 0 readiness arrives before sequence 1
  advertisement exactly once. Verify the A advertisement hash before B4 and erase retention at
  attempt retirement.

Exit gate: both role assignments, unpredictable nonces, late-peer, reconnect, restart, stale/gap,
and wrong-attempt tests pass through the validation relay with factual C0/C1 errors and no orphan room.

### Milestone 6 — C2 activation and sustained data plane

- Admit `TunnelSim` only if no game/trade controller is reachable in tunnel mode; otherwise extract
  the smallest feature-neutral Pia/Reliable bridge.
- Preserve byte-exact Reliable application payloads. Never relay raw Wi-Fi, LDN control frames, keys,
  captures, MAC addresses, trainer data, or Pokémon data.
- Arm each side with a bounded 256-frame pre-barrier queue and explicit overflow/backpressure failure.
- Send one `SIDE_READY` only after A11 or B10. Bind its A/B projection to attempt, seat, role, launch
  identity, advertisement hash, and stage generation. Relay authority allocates one activation
  generation; both endpoints must accept it before `C_BRIDGE_READY`.
- Only real post-barrier bidirectional RFU counters may produce `C_RFU_ACTIVE`. Any physical, endpoint,
  tunnel, heartbeat, or authority loss invalidates readiness exactly once.

Exit gate: delayed A/B, stale/duplicate readiness, reconnect, overflow, loss, cancellation, mapping,
and byte-exact payload tests pass. AP-open or one-sided readiness never becomes bridge-active.

### Milestone 7 — Distributed D and recovery

Implement D1-D11 in order: authoritative closing intent; native Switch close tail; bridge drain; local
LDN teardown; persistent `D_SIDE_QUIESCENT`; two-side terminal barrier; diagnostic-only resource
cleanup; endpoint proof; Linux radio quiescence; conditional USB return; recovery and lock release.

- Keep functional and cleanup results independent and preserve the first A/B/C cause.
- Retain an authority cleanup guard after attempt terminalization until both controls acknowledge
  verified local release.
- End Connection performs D but may retain membership. Leave and Close perform D first, then their
  requested room action. Cleanup is idempotent.

Exit gate: success, Stop, room close, peer loss, endpoint hang, app/control/relay/PC restart, and fault
injection at every D gate preserve outcome and ownership. The complete C software harness passes C0-C2
and distributed D.

### Milestone 8 — Production diagnostics migration

- Keep the automated, guided A, guided B, and recommended actions and the existing start/read/continue/
  cancel route operations, but make them request stages from the production coordinator.
- One suite owns one adapter lease; every sub-attempt receives fresh room, credentials, attempt,
  nonce, generation, endpoint, and verified sub-cleanup while the radio remains attached.
- Preserve explicit Start, Continue, Retry, Cancel, and Finish commands. Reports record last passed
  gate, first failure, functional and cleanup results, bounded timing/logs, hashes, and source-redacted
  evidence.
- Automated diagnostics prove no physical A/B; guided A reports its last A gate; guided B reports at
  most B8 unless B9/B10 pass; a one-PC suite never claims bridge, RFU, trade, or two-PC D qualification.

Exit gate: all actions run once on each PC, reports validate against `production-diagnostic.v2`, UI
states are factual, and no private room, credential, endpoint, lock, or radio residue remains.

### Milestone 9 — Normal application and production relay cutover

- Route normal Connect, Stop, End, Leave, Close, Retry, recovery, and shutdown through the coordinator.
  Keep HTTP paths stable and update typed desktop DTOs to v2.
- Remove hard-coded `0.2.*` compatibility assumptions and compare exact release and payload hashes.
- Prove no desktop, diagnostic, API, retry, recovery, import, or shutdown path reaches legacy
  orchestration before deleting it. Do not ship a fallback flag.
- Deploy the exact validation-relay artifact/hash to production for a coordinated v2 cutover and
  retain matching relay/application rollback artifacts. The shipped UI has no relay selector.
- Rerun production capability, persistence, restart, late-peer, C0/D, and guided checks against the
  production hostname.

Exit gate: normal and diagnostic traffic use the same coordinator and production path; polling is
pure; launch count is one; errors remain factual; no legacy path is reachable.

### Milestone 10 — Qualification and release

Run P0 cold boot, direct A, direct B, production-relay C harness, one-PC guided diagnostics, the
two-PC/two-Switch test, and only then repetition and packaging.

- Run 30 consecutive automated suites on each PC.
- Run three consecutive guided A and three guided B tests on each PC.
- Cover cancellation during attach, scan, join, AP wait, bridge wait, and cleanup plus app/control/
  relay restart and recovery.
- Complete two physical trades with PC roles reversed, including room entry, RFU, trade, bilateral
  save, stable return, native close, and distributed D, plus one cancel-and-retry cycle.
- Require zero duplicate launches, orphan PIDs, stale interfaces/PHYs, unintended USB ownership,
  unresolved rooms/recovery records/locks, or false diagnostic qualification.
- Build `0.3.0-beta.1` only after those gates. Verify source/package hashes, clean install, upgrade from
  `0.2.6-beta.2`, Repair, uninstall, reinstall, and coordinated rollback on clean Windows 10 22H2 and
  Windows 11. Repair must not reinstall healthy WSL or usbipd components.

## 4. Critical TODO closure mapping

| Critical blocker | Implemented in | Closed only after |
| --- | --- | --- |
| Missing WSL LDN prerequisites | M2 | Cold A and B pass on both PCs |
| Relay ordering and false diagnostics | M5, M8, M9 | Production late-peer and truthful-report tests |
| Missing A_READY/B_READY barrier | M6 | Physical two-PC activation agreement |
| Missing distributed D | M7 | Two-sided physical cleanup and recovery tests |
| Launch storm/false startup | M1, M9 | Packaged proof on both PCs |
| Hot driver-probe race | M2 | Cold installed proof on both PCs |
| Production diagnostics qualification | M8 | Final 30-run and guided qualification |

After each milestone, update the architecture document, definitive TODO, and README only with evidence
actually obtained. Do not begin a later milestone or build an installer until the current exit gate is
reviewed and accepted.
