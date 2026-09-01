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

Execution status:

- Milestone 0 passed in `fd9e50a`; see
  [`82-abcd-milestone-0-baseline-20260829.md`](82-abcd-milestone-0-baseline-20260829.md).
- Milestone 1 passed in `b7c5c9a`; see
  [`83-abcd-milestone-1-coordinator-20260829.md`](83-abcd-milestone-1-coordinator-20260829.md).
- Milestone 2 passed cold installed-runtime qualification on PC A; the later returned PC B P0
  evidence was reviewed and accepted with verified cleanup.
- Milestone 3 passed A0-A9 on PC A in immutable runtime `abcd-m3-80c4e13`; the later returned PC B
  Direct A evidence was also reviewed and accepted.
- Milestone 4 is source-complete at `9635a1f`. Immutable PC A runtime `abcd-m4-9635a1f` passed
  installation, integrity, dependency, kernel, contract, CLI, residue, and detached-USB smoke. Final
  PC A physical run `12e6a535-4770-47ae-9fb3-8d06915af053` passed B2-B10, returned
  `B_CONTROL_READY`, reached `factory_released`, and verified LDN/radio/endpoint/USB cleanup without
  residue. The later returned PC B Direct B evidence was reviewed and accepted with matching runtime
  integrity and verified cleanup, closing the standalone local-B debt.
- Milestone 5 source checkpoint `162f779` added P0/launch-bound `rfu-tunnel.v2`, strict contiguous
  ordering, reconnect nonce re-proof, exact advertisement-hash delivery, and factual C0/C1 stages.
  Local validation and the deployed HTTPS/WSS role, ordering, reconnect, restart, failure, and
  zero-orphan matrix passed, so the M5 functional exit gate was accepted on 2026-08-30. The validation
  host uses one launchd-supervised native uvicorn worker rather than the reference container; a fully
  reproducible native manifest or reference image remains mandatory before Milestone 9 production
  cutover. See
  [`88-abcd-milestone-5-c0-c1-20260830.md`](88-abcd-milestone-5-c0-c1-20260830.md).
- Milestone 6 source checkpoint `d2130fe` added the authority-owned activation generation,
  identity-bound A_READY/B_READY barrier, bounded byte-exact RFU bridge, current-generation active
  counters, and explicit reconnect re-proof. The full fixed-runtime suite and local real-process C2
  hosting smoke passed. The source-identical deployed relay passed repeated public happy-path,
  reversed-role, delayed-side, single-worker, and private zero-orphan checks, so the M6
  software/deployed exit gate was accepted on 2026-08-30. See
  [`89-abcd-milestone-6-c2-20260830.md`](89-abcd-milestone-6-c2-20260830.md).
- Milestone 7's distributed authority, endpoint shutdown, measured local release, restart recovery,
  and GUI-independent physical runner are source-complete. Software, real-process, hosted-relay, and
  fault-injection paths pass; final simultaneous two-PC/two-Switch evidence remains open.
- The focused one-PC/two-adapter C+D campaign passed Q0-Q5 and the user-approved 10/10 Q6 run with
  no residual radio, process, room, credential, or recovery ownership. That campaign is closed and is
  not a production dual-radio requirement.
- On 2026-08-31 the owner ended qualification-only development and directed the project to the
  deterministic production wrapper, minimal GUI, and support-log export plan in
  [`94-production-wrapper-beta-cutover-20260831.md`](94-production-wrapper-beta-cutover-20260831.md).

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
  `rfu-tunnel.v2`, and `app-readiness.v2`. Store their canonical shapes in versioned JSON schemas
  and validate Python models and C# DTOs against them. A production diagnostic/debug-menu contract is
  no longer required.
- Restrict the production ABC+D path to the qualified RTL8192EU `0bda:818b`. Experimental adapters
  remain available only to standalone hardware diagnostics.
- Production owns one selected adapter per PC. Concurrent two-adapter ownership remains an isolated
  qualification tool and is not exposed through the application.
- Reserve `0.3.0-beta.1`, with MSI/bundle version `0.3.0`, for the first packaged ABC+D release.
  Preserve existing MSI and bundle UpgradeCodes.
- Treat Unicode paths, non-English Windows locales, and mixed native output encodings as release
  invariants. Process launches use typed argument vectors; JSON remains UTF-8; redirected UTF-16LE
  Windows output is decoded at its boundary; Windows/WSL path conversion is structural and tested.

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
- Run P0 from a non-ASCII Windows profile and cover UTF-8 Linux output, UTF-16LE redirected Windows
  output, spaces/non-ASCII paths, malformed output, and locale-independent version/JSON parsing.

Exit gate: cold-boot P0 passes on both PCs; delayed enumeration, partial probe, stale sysfs, command
timeout, inactive usbip port, adapter changes, and encoding/path faults classify correctly; cleanup
restores prior ownership.

### Milestone 3 — Direct A admission

> Status (2026-08-29): implemented and regression-tested. PC A immutable installed-runtime run
> `88f8e357-2e8c-4981-ad87-4cfaa1f93c31` passed A0-A9 with verified cleanup. The owner explicitly
> accepted PC A's verified cold P0 as sufficient to begin this milestone. The later returned PC B P0
> and Direct A evidence was reviewed and accepted with verified cleanup on 2026-08-30.

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

### Milestone 8 — Deterministic headless production wrapper

> Source status (2026-09-01): implementation and the Switchless source dry-run are accepted to begin
> the minimal-GUI rework. Production API/service cancellation and recovery regressions, 588 complete
> source regressions, and hosted-relay C+D normal/worker-death runs pass with verified cleanup and no
> AI runtime. This is not formal installed M8 closure: the exact immutable packaged normal entry point
> and startup-interruption recovery still require qualification.

- Extract the generic, already-qualified connection lifecycle from the distributed harness into one
  neutral connection-run service. The qualification CLI becomes a thin adapter; the product never
  launches a harness as its runtime and never gains a second ABC+D implementation.
- Bind the service to the serialized coordinator, one selected-adapter P0 owner, distributed endpoint,
  relay client, and D recovery owners. Production does not expose concurrent dual-adapter operation.
- Route Connect, Stop, End, Leave, Close, Retry, shutdown, and startup recovery through the service.
  Every transition is deterministic and persisted; no LLM, console prompt, or operator-authored
  recovery command exists in the shipped runtime.
- Supervise one identity-bound WSL wrapper/endpoint launch, backend-owned bounded output, heartbeats,
  monotonic deadlines, first-cause preservation, and fail-closed cleanup. GET/status stays immutable.
- Keep HTTP paths stable and use typed local DTOs. The existing relay `app-readiness.v2` and internal
  coordinator `connection-run.v1` names are already occupied, so the Desktop contracts are
  `local-app-readiness.v2` and `production-connection-run.v1`; compare exact release/payload
  contracts instead of hard-coded `0.2.*` assumptions.

Exit gate: the headless product entry point—not the repository harness—passes one normal side against
a bounded test-controlled complementary peer, plus expected failure, cancellation, control
interruption, and restart recovery with one launch, pure polling, and verified cleanup. Additional
repetition testing is deferred until this gate.

### Milestone 9 — Minimal GUI, support export, and atomic cutover

> Source status (2026-09-01): application-session logging, bounded/redacted backend-independent
> Desktop export, typed WPF projection, physical checkpoints, and production-route cutover are
> implemented and pass local builds/self-tests. The current screen is only a replaceable adapter;
> minimal GUI flow rework is now the next implementation stage. Live WPF-to-control and installed
> failure-export qualification remain open, so M9 is not yet closed.

- Connect a small desktop UI to the typed connection-run service for create/join, factual progress,
  Stop/End/Leave/Close/Retry, recovery guidance, Settings, and **Export support logs**.
- Keep USB, relay, timeout, retry, cleanup, and diagnostic decisions out of the GUI. It presents the
  service state and normal physical Switch instructions only.
- Create an application-session identity before local-service launch and retain bounded structured
  launcher, runtime, wrapper, endpoint, A/B/C/D, relay-result, shutdown, and recovery evidence.
- Export one atomic redacted ZIP to the Windows Desktop. Export must work when the local service or WSL
  endpoint never became ready and must exclude credentials, keys, passcodes, packets, MAC addresses,
  exact adapter identities, and trainer/Pokémon data.
- Make the legacy endpoint/orchestration and retired Debug menu unreachable, then delete them only
  after import, API, launch, shutdown, recovery, and support-export tests prove exclusive cutover.
- Deploy the exact accepted relay artifact/manifest for the coordinated v2 production path; ship no
  relay selector or legacy fallback.

Exit gate: one user action creates one product run, polling is pure, terminal evidence is exportable
from the UI even after early startup failure, errors remain factual, and no legacy/debug-only path is
reachable.

### Milestone 10 — Immutable package and production-beta acceptance

- Build `0.3.0-beta.1` from the accepted M8/M9 source. Verify application, MSI/bundle, runtime, relay,
  kernel/module/firmware, dependency, schema, and payload identities plus preserved UpgradeCodes.
- Verify install, upgrade, Repair, reboot continuation, cold launch, normal close/relaunch, support
  export, uninstall, reinstall, and rollback on the two beta PCs, including non-ASCII user paths and
  supported English/Korean Windows output boundaries.
- Run one packaged Direct A and Direct B smoke to catch packaging/runtime drift, then two nearby
  two-PC/two-Switch trades with roles reversed through the normal application. Finish with the
  separated-distance case and one cancel/recover path.
- Require real `C_TRADE_COMPLETE`, bilateral save/stable return/native close, D11 on both PCs, and zero
  duplicate launches, orphan PIDs, stale interfaces/PHYs, unintended USB ownership, rooms,
  credentials, recovery records, or locks.

Exit gate: the exact installed GUI and production wrapper—not a Debug menu or repository CLI—pass the
physical sequence and export a valid redacted support archive. M8+M9 is a code-complete beta candidate;
only this M10 gate makes it a production beta.

## 4. Critical TODO closure mapping

| Critical blocker | Implemented in | Closed only after |
| --- | --- | --- |
| Missing WSL LDN prerequisites | M2 | Cold A and B pass on both PCs |
| Relay ordering and truthful product state | M5, M8, M9 | Production late-peer and factual UI/log projection tests |
| Missing A_READY/B_READY barrier | M6 | Physical two-PC activation agreement |
| Missing distributed D | M7 | Two-sided physical cleanup and recovery tests |
| Launch storm/false startup | M1, M9 | Packaged proof on both PCs |
| Hot driver-probe race | M2 | Cold installed proof on both PCs |
| Deterministic production wrapping | M8 | Headless normal-product lifecycle, interruption, and recovery |
| Support evidence without Debug menu | M9 | Startup-failure-capable redacted Desktop export |

After each milestone, update the architecture document, definitive TODO, and README only with evidence
actually obtained. The final simultaneous physical test intentionally occurs after M8/M9 so it
qualifies the product path users will run. Do not build the beta installer until the M8/M9 exit gates
are reviewed and accepted.
