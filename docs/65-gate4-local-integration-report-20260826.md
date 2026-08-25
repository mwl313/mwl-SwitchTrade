# Gate 4 local integration report — 2026-08-26

> Status: implemented and internally tested where no authoritative service, installed distro, USB
> adapter, or Switch is required. Gate 0 was owner-deferred for this engineering pass, not approved.

## Outcome

The native EXE and local WSL runtime now share a versioned product boundary instead of treating a
single `BACKEND` flag as truth. The endpoint's stable tunnel seat is independent from its temporary
Switch room creator/finder role. Both locally terminated RFU AppData directions are copied to a bounded
passive decoder, and complete checksum-valid party generations can reach the native 2-by-3 party UI
without affecting RFU forwarding.

This does not make the process-local room dictionary authoritative. Authentication, stable remote seat
assignment, ready/presence state, atomic creator claims, reconnect tokens, and ordered remote events
remain Gate 5 work.

## Implemented

- WPF single-instance mutex plus control, endpoint, and development-relay process locks.
- Serialized PowerShell startup, health-before-spawn probes, hidden WSL process launch, and duplicate
  development-relay avoidance.
- `app-readiness.v1` at `GET /api/v1/app/readiness`, including compatible product/contract versions,
  separate control/relay/radio/session/decoder axes, retained failure stage, safe recovery action,
  stable run ID, and bounded counters.
- Native startup blocks real room/session actions on incompatible runtime versions and routes to an
  explicit recovery screen. The status popup reports component axes separately.
- Endpoint arguments `--tunnel-seat member_a|member_b` and
  `--switch-room-role creator|finder`. The development relay's `host/guest` terminology is now an
  internal seat-to-wire compatibility mapping only.
- Atomic duplicate-session check inside the control runtime.
- Persistent endpoint and party state outside a control run folder. A restarted control process
  validates `/proc/<pid>/cmdline` before adopting or terminating a surviving endpoint, avoiding PID
  reuse and unrelated-process termination.
- Early signal handling so shutdown during radio acquisition still reaches endpoint cleanup.
- Bounded passive decoder queue using non-blocking copies. Overflow invalidates only presentation
  state; it does not backpressure or alter RFU forwarding.
- Direction/member-isolated RFU block assemblers, three-block party generation, checksum-valid record
  gating, six ordered slots, atomic snapshots, and teardown invalidation.
- The package source manifest now includes the live decoder, PK3 validator, and their four data/helper
  modules; a regression test prevents a repository-only decoder that disappears from the provisioned
  WSL distro.
- `GET /api/v1/trade-room/parties` plus WPF polling/projection into verified live Partner/You 2-by-3
  grids and stat detail panels. Live party display has no statistics-service dependency.
- Full-shutdown primitive for endpoint, local development relay, and control service. Ordinary window
  close retains the previously approved policy of leaving the healthy local service reusable.
- Retained-session retry plus an allowlisted adapter repair route that invokes only the profiled RX
  health gate; the native UI exposes it only for a radio-stage failure.
- Fail-closed trade-commit classification requiring both selected slots, `START_TRADE`, the follower's
  `READY_FINISH_TRADE`, leader `CONFIRM_FINISH_TRADE`, save counts 5 through 10 from both members, and
  a checksum-valid post-save party rebuild proving the selected record hashes swapped. The projection
  is deterministic/idempotent and the native room reports it once; animation-only and rollback tests
  emit no commit.
- Redacted one-action support bundle with a runtime summary. `session_id` and `room_code` now receive
  the same secret-field treatment as passcodes; party records and raw RFU bytes are excluded.

## Internal verification

- `python -m unittest discover -s tests -p 'test_*.py'`: 44 passed.
- Native Release build: zero warnings, zero errors.
- Native `--self-test`: passed.
- Published self-contained EXE self-test: passed; SHA-256
  `4182EDA0D9735FCACE97B4167531B03A6CA21955FF57201B4D42B2AECCB80BEB`.
- PowerShell launcher parse check: passed.
- Bash endpoint-launcher syntax check: passed.

The tests cover duplicate locks and release, independent seat/radio axes, readiness schema, neutral
party unavailability, bounded decoder overflow, checksum-gated six-slot projection, bidirectional
observer tee behavior, successful commit evidence, rollback rejection, redaction, RFU forwarding, and
local tunnel integration. Hardware behavior was not claimed by these internal checks.

## Still open in Gate 4

1. Add the signed update path and finish safe native routing for non-radio retained failure stages.
2. Connect the local API to Gate 5's authenticated authoritative room snapshots and ordered event
   stream. Until then, owner/member is only a compatibility mapping and cannot be production tunnel
   authority.
3. Implement safe creator transfer, role lock, cancel, teardown, re-election, and retry against that
   authoritative attempt state.
4. Validate the new fail-closed classifier against full successful, rolled-back, and native-error live
   captures; unit fixtures already prove its evidence policy and idempotency.
5. Run installed-distro and physical RTL8192EU/Switch qualification in Gates 6–7. The current checks
   prove software behavior, not USB passthrough, RF reception, or complete live trade correctness.
