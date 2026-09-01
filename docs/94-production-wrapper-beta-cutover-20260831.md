# ABC+D production wrapper and beta cutover

Status: normative execution decision, 2026-08-31

This document records the product boundary chosen after the standalone A/B physical qualification,
real-relay C/D qualification, and the focused single-PC dual-adapter campaign. It updates the
execution milestones in the [rewrite plan](81-abcd-orchestration-rewrite-plan-20260829.md) without
changing the ordered P0/A/B/C/D contracts in the
[ABC+D architecture](80-abc-connection-architecture-20260829.md).

## 1. Product decisions

1. A production PC owns one selected radio. Two simultaneous adapters on one PC were required only
   to qualify two isolated C/D sides without two distant PCs; dual-adapter ownership is not a beta
   feature, UI mode, or production API requirement.
2. The shipped application contains no AI or agent dependency. Every transition, timeout, retry,
   cancellation, recovery, and cleanup decision is encoded in one deterministic state machine with
   stable error codes and persisted identity.
3. A production Debug menu is no longer required. The earlier
   [debug-menu design](79-production-debug-menu-design-20260828.md) is retained as historical design
   evidence only. It must not drive product scope or create a second connection stack.
4. The replacement observability requirement is one explicit **Export support logs** action. It
   exports the bounded, redacted evidence accumulated since application startup to one archive on
   the Windows Desktop, including failures that occur before the local service or WSL endpoint starts.
5. Further qualification-only feature work and repetition stop here. The next implementation work is
   the production wrapper, then the minimal GUI, then one immutable package and the final physical
   acceptance sequence.

## 2. Current evidence boundary

The ABC+D core is admitted for product wrapping:

- P0 radio/runtime ownership and cleanup have installed and live-radio evidence;
- Direct A and Direct B have accepted one-Switch evidence on both PCs;
- C0/C1 and C2 have real hosted-relay, ordering, reconnect, role-reversal, and failure evidence;
- D has software, real-process, restart, fault-injection, and exact resource-return evidence;
- the focused Switchless C+D campaign passed 10/10 with two exact radios and no residual ownership.

This is component and composed-software qualification, not final product certification. The remaining
physical gap is simultaneous A and B through the production wrapper: real `A_READY`/`B_READY`, real
RFU in both directions, trade/save/return/close, and distributed D on two PCs and two Switches.

## 3. Production wrapper boundary

There must be one neutral connection-run service used by both the product and qualification tools.
Do not implement a second product copy of ABC+D and do not launch the qualification CLI as the
product runtime.

The service owns:

- one persisted coordinator/run and one selected adapter lease;
- `P0a -> C0.1 -> P0b -> C0.2/C0.3 -> A/C1/B/C2 -> D` ordering;
- one identity-bound WSL wrapper and endpoint launch per side attempt;
- monotonic deadlines, heartbeat, bounded idempotent network retries, cancellation, and fail-closed
  ambiguity handling;
- startup adoption or exact recovery from persisted run/attempt/room/adapter/PID/nonce identity;
- normal Connect, Stop, End, Leave, Close, Retry, application shutdown, and restart behavior;
- immutable read-only status projections for the desktop UI.

The production wrapper never depends on an LLM, console prompt, operator-entered recovery command,
dual-adapter coordinator, selectable AP engine, or debug-menu-only checkpoint. Human input is limited
to normal product intent and the physical Switch actions shown by the UI.

## 4. Application-session logging and export

The desktop launcher creates an `app_session_id` before starting the local service. All product-owned
processes append bounded structured evidence under that session:

- launcher, release/runtime verification, and local-service startup;
- coordinator transitions and stable failure codes;
- P0/USB/WSL wrapper and endpoint stdout/stderr;
- redacted A/B/C/D gate and cleanup reports;
- relay capability/result metadata and process identity evidence;
- application shutdown, startup recovery, and installer/provisioner identity relevant to the run.

Logs rotate by size/count and survive a backend startup failure. **Export support logs** creates one
atomic ZIP on the Windows Desktop containing a manifest and the current session's bounded files. It
must work even when the local service never became ready. The archive never contains credentials,
room passcodes, raw packets, keys, MAC addresses, exact adapter InstanceIds, or trainer/Pokémon data.

## 5. Mini milestone plan

### M8 — Deterministic headless production wrapper

1. Extract the already-qualified generic lifecycle from the distributed harness into one neutral
   connection-run service; keep the harness as a thin adapter.
2. Bind the service to the existing coordinator, P0 owner, distributed endpoint, relay client, and
   D recovery owners without changing the A/B/C/D contracts.
3. Implement normal product actions, process supervision, persisted startup recovery, and immutable
   status projection. Production uses one selected adapter only.
4. Prove one launch, no mutation on status reads, first-cause preservation, app/control interruption,
   and verified cleanup using the existing source/software gates. Do not add another repetition
   campaign before this exit gate.

Exit gate: the headless product entry point completes one normal side against a bounded
test-controlled complementary peer, plus expected failure, cancellation, and restart recovery,
without invoking legacy orchestration or exposing test-only dual-adapter logic.

### M9 — Minimal GUI, support export, and atomic cutover

1. Connect a small desktop UI to the typed connection-run API: create/join, factual progress,
   Stop/End/Leave/Close/Retry, recovery guidance, main-screen adapter selection, and Export support
   logs. A separate Settings scene is not part of the owner-approved minimal flow.
2. Keep all connection decisions in the service. The GUI contains no USB, relay, retry, timeout,
   cleanup, or diagnosis engine.
3. Make the old endpoint/orchestration and Debug menu unreachable, then remove them only after import,
   API, startup, shutdown, and recovery tests prove the new route is exclusive.
4. Verify cold launch, close/relaunch, local-service failure export, non-ASCII paths, log redaction,
   and bounded retention.

Exit gate: one user action launches one product run, polling is pure, every terminal result can be
exported from the Desktop UI, and no legacy or debug-only connection path is reachable.

### M10 — Immutable package and production-beta acceptance

1. Build one immutable Windows/WSL package from the accepted M8/M9 source and verify all release,
   payload, kernel, dependency, and contract hashes.
2. Verify install, upgrade, Repair, reboot, normal launch, close/relaunch, log export, uninstall, and
   reinstall on the two beta PCs, including the non-ASCII profile boundary.
3. Run one packaged Direct A and Direct B smoke, then two nearby two-PC/two-Switch role assignments
   through the normal product wrapper. Finish with the separated-distance case.
4. Accept only real `C_TRADE_COMPLETE`, bilateral save/return/close evidence, D11 on both PCs, and
   zero endpoint, room, credential, interface, PHY, USB, lock, or recovery residue.

Exit gate: the packaged normal application—not a repository CLI or Debug menu—passes the final
two-PC/two-Switch sequence and produces a valid redacted support archive.

## 6. Meaning of “production beta complete”

M8 plus M9 produces a code-complete beta candidate. It becomes a production beta only after M10
proves the exact installer and normal GUI path with two PCs and two Switches. A working wrapper plus
a simple GUI is therefore necessary, but packaging and the final physical acceptance gate are also
mandatory.

## 7. Explicitly deferred or removed

- production Debug menu and `production-diagnostic.v2` UI workflow;
- packaging the dual-adapter qualification entry point as a user feature;
- concurrent two-radio support on one production PC;
- an LLM/agent runtime dependency;
- alternate AP engines, plugin architecture, or generic diagnostic framework;
- more qualification repetition before the production wrapper exists.

## 8. Source implementation checkpoint — 2026-09-01

The M8/M9 design is now implemented in the current source worktree, but it is not yet an installed
beta claim:

- `ConnectionRunService` is the single serialized mutation owner. `P0Harness` is now a thin
  qualification adapter over the neutral `ConnectionRunExecutor`; production does not invoke a
  qualification CLI or maintain a second A/B/C/D stack.
- The enforced product order is `P0a -> C0.1 -> P0b -> C0.2/C0.3 -> A/C1/B/C2 -> D`. Relay room
  authority and complementary-role pairing complete before the first USB lease. One run ID flows
  through the service, coordinator, wrapper launch, relay attempt, endpoint heartbeat, and report.
- All mutating local API calls require a UUID command ID; run-bound calls also require the exact run
  ID and expected revision. Repeated identical commands are idempotent, stale UI commands fail
  closed, and all GET projections are read-only.
- The endpoint emits a two-second identity-bound heartbeat. Cleanup uncertainty blocks new work;
  shutdown requests the same service-owned cleanup instead of racing a separate USB/endpoint stop.
- The Desktop creates an application evidence session before backend launch. Component-owned logs,
  worker streams, WSL snapshots, failure summary, retention, redaction, and backend-independent
  atomic Desktop ZIP export are implemented with the specified bounds.
- The retired Debug menu and legacy room/session mutation routes are unreachable from the packaged
  production app. Qualification factories remain available only to preserve historical regression
  comparisons until the cutover is accepted.
- Existing relay `app-readiness.v2` and coordinator `connection-run.v1` contracts were not
  overwritten. The local Desktop projections are deliberately named `local-app-readiness.v2` and
  `production-connection-run.v1` to prevent two incompatible payloads sharing one versioned name.

Current source evidence is 588 Python tests passed with 3 environment-dependent skips, 140 focused
P0/A/B/C/D regressions passed, zero-warning Desktop and Provisioner Release builds, Provisioner
contract tests passed, and Desktop/session self-tests passed under the non-ASCII repository path.

### 8.1 Switchless source dry-run checkpoint — 2026-09-01

The source implementation is accepted to proceed to the minimal-GUI rework, with the following exact
evidence boundary:

- the production API, serialized service, neutral executor, role/checkpoint command adapter, endpoint
  command parser, cancellation, first-cause, pure-GET, stale-revision, heartbeat, shutdown, and restart
  recovery regressions pass without an AI or agent runtime;
- one hosted-relay Switchless C+D normal run passed ordered peer readiness, retained advertisement,
  one-sided activation blocking, bidirectional unpredictable RFU evidence, D6, room close, and
  credential removal with no forced worker;
- one hosted-relay worker-death run preserved `CD_WORKER_EXITED` as the expected first failure and
  still verified cleanup, room close, credential removal, and zero forced worker;
- the pre-mutation audit found and corrected two composed Stop defects: a physical checkpoint now
  accepts the one identity-bound D closing intent, and the production adapter maps the exact service
  cancellation to `DistributedCanceled` rather than functional failure;
- post-run residue checks found no worker or endpoint process, both selected-class radios remained
  Windows-owned and unattached, and the private recovery files were absent.

This is a **source-level deterministic wrapper dry-run**, not an installed-product or physical pass.
It intentionally leaves A/B Switch behavior untested. The exact immutable packaged normal entry point,
live WPF-to-control flow, backend-dead installed export, and startup interruption/recovery still belong
to M9/M10 acceptance. Two-PC/two-Switch RFU and trade acceptance remains wholly separate.
