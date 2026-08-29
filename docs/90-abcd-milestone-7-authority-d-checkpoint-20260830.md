# ABC+D Milestone 7 distributed D checkpoint

> Branch: `codex/abcd-orchestration-rework`
> Source commit: `d815562`
> Endpoint D2-D4 commit: `fdbdd12`
> Measured local-control commit: `f52fe93`
> Local recovery/probe hardening commit: `62f93fa`
> Validation-smoke commit: `40fecf3`
> Installed D8-D10 qualification commit: `0d7549d`
> Deployed relay artifact checkpoint: `ed382db`
> Status: M7 authority, endpoint D2-D4, and measured local D5/D7-D11 happy-path slices complete;
> the installed PC A D8-D10 path is qualified. Milestone 7 remains open for PC B, fault/restart,
> diagnostic-resource, and product-action qualification.
> Scope: D1 closing intent, endpoint D2-D4, D5 authority acknowledgement, D6 two-side/forced
> barrier, relay transport retirement, measured local D5 evidence, and ordered local release.

## 1. Boundary

This checkpoint introduces one authority-owned distributed-D path on top of the admitted v2 attempt.
It does not reuse the legacy room terminalization path and it is not advertised as a completed relay
capability. Only a P0-admitted v2 attempt may enter it.

The relay owns the shared outcome and barrier. The endpoint stage owns only its local D2-D4
resources. Local control measures its own launch and radio evidence, verifies that exact evidence at
D6, and releases only its own diagnostic, endpoint, radio, USB, and lock resources. It never claims
the remote PC's local release.

## 2. Implemented ordering and invariants

1. `POST .../closing` records an idempotent `d-closing-intent.v1` before either side is allowed to
   tear down. It binds the attempt ID and relay-owned activation generation.
2. `completed` is rejected unless the last passed gate is `C_TRADE_COMPLETE`. `failed` requires a
   stable primary failure code; canceled/completed outcomes cannot smuggle in one.
3. The first accepted intent freezes outcome, primary failure, and last passed gate. A conflicting
   later intent fails closed.
4. While the attempt is `closing`, expected WebSocket or presence loss cannot replace the recorded
   outcome with `relay.peer_lost`.
5. `POST .../quiescent` accepts `d-side-quiescent.v1` only for the bearer-derived seat and the exact
   admitted endpoint launch identity: run ID, stage generation, nonce/PID-derived hash, attempt, and
   activation generation.
6. The first valid side acknowledgement leaves the attempt in `closing`. Only the second matching
   side acknowledgement performs the D6 terminal transition and retires both v2 transports and the
   process-local admission.
7. A 30-second authority deadline prevents an absent side from holding the barrier forever. A relay
   restart forces the same terminal path because process-local transport admissions cannot survive
   restart. Both cases mark cleanup failed without overwriting the functional outcome or first A/B/C
   failure.
8. Identical intent and acknowledgement retries remain valid after terminalization and admission
   retirement. Conflicting retries still fail. This covers a lost HTTP response without reopening
   resources or incrementing the room revision.

## 3. Contracts and redaction

- `d-closing-intent.v1`: immutable D1 request.
- `d-side-quiescent.v1`: one launch-bound seat acknowledgement with Boolean-only resource evidence.
- `distributed-d.v1`: persisted authority projection, including deadline, both side records, barrier
  state, cleanup result, secondary cleanup code, and terminal timestamp.
- `d-endpoint-stage.v1`: launch-bound D2-D4 result with Boolean resource evidence, bounded queue
  counts, stable cleanup failures, and no payload data.
- `d5-control-state.v1`: private response-loss retry state containing the endpoint-report hash,
  UUIDv7 command ID, Boolean measurement-known flags, and exact redacted D5 payload.
- `d-local-release.v1`: redacted D6-D11 report containing bounded launch/radio/USB evidence and
  stable secondary cleanup failures.

The contracts contain no bearer credentials, reconnect tokens, launch nonce, raw RFU frames, MAC
addresses, packet captures, or game/trainer data. The launch nonce and PID are represented only by the
existing SHA-256 launch identity.

## 4. Failure semantics

- A cleanup failure is secondary. A failed functional result retains its original primary code.
- Forced timeout produces `D_BARRIER_TIMEOUT`; relay restart produces `D_RELAY_RESTART`.
- A side that reports forced termination, a live endpoint/transport/thread/LDN resource, or a
  remaining interface makes shared cleanup `failed` even when both sides respond.
- A legacy attempt cannot call the D endpoints. A stale or unadmitted endpoint cannot acknowledge a
  different seat or generation.
- The normal room stays available after `End Connection`; later product wiring will distinguish that
  from explicit Leave and owner Close, which must run D first.

## 5. Evidence

- Focused authority and real-process tunnel matrix: `62 passed`.
- Full audit runtime after the endpoint slice: `455 passed, 3 skipped`.
- Full audit runtime after measured local control, WSL self-exclusion review, and restart recovery:
  `480 passed, 3 skipped`.
- Source-identical local uvicorn smoke passed both normal and reversed role assignments through C0-C2,
  D1, one-sided D5 non-terminal behavior, two-sided D6, post-terminal retry, and room close. Final
  metrics were zero for active credentials, v1/v2 sessions, and v2 admissions.
- The source-identical public relay deployment passed normal and reversed-role HTTPS/WSS smoke
  through C0-C2 and D1/D5/D6. The exact-artifact and private-metric confirmation is recorded below.
- The operator redeployed the exact `ed382db` artifact and verified the deployed relay/import files
  have zero diff from that checkpoint. One launchd-managed uvicorn worker was running; legacy
  `/session/create` remained 404; health was ready with writable storage; and relay smoke passed.
  Private metrics were all zero for live v2 attempts, admitted v2 attempts, and active member
  credentials. The deployment backup is `/tmp/relay-backup-ed382db-080150/`. The server checkout's
  local HEAD pointer remained at another commit, so artifact file identity—not that pointer—is the
  deployment authority.
- After that redeployment, public HTTPS/WSS smoke passed again in both normal and reversed role
  assignments.
- Endpoint tests prove exact D2 -> D3 -> D4 call order, native close-tail success and timeout,
  continued cleanup after faults, immutable run/attempt/seat/activation/launch binding, queue
  accounting, admission sealing, transport/thread/LDN evidence, and idempotent replay.
- Tests cover two-sided cancellation, failed outcomes, false completion rejection, stale launch
  identity, legacy-path rejection, primary/secondary error separation, forced-side evidence, barrier
  timeout, relay restart, exact post-terminal HTTP retry, and transport retirement.
- JSON contracts were parsed independently and the persisted authority projection was checked against
  the strict required field set.
- Measured-control tests prove report immutability, exact run/attempt/seat/activation/launch binding,
  stable temporary-interface measurement, response-loss replay, no credential persistence, and
  forced false evidence for live or unknown state.
- Local-release tests prove D7 -> D8 -> D9 -> D10 -> D11 order, exact D6 evidence comparison,
  endpoint-active and unknown-radio detach prevention, diagnostic cleanup failure, software-only
  ownership, failed-cleanup guard retention, and verified retry.
- A real local HTTP/WSS relay process passes C2 activation, authoritative D1, endpoint D2-D4,
  measured D5 on each coordinator, two-seat D6, and independent D7-D11 local release.
- Restart tests prove that a persisted UUIDv7 D5 request can be replayed without remeasurement after
  coordinator recovery, and that forced D6 timeout can still drive conservative D8-D11 recovery when
  no local D5 acknowledgement reached the authority. The WSL `/proc` inventory excludes its own
  probe process so a clean run cannot falsely look active forever.
- Commit `0d7549d` makes the cold P0 qualification path use the same fail-closed D8 launch and stable
  D9 radio evidence policy as `LocalDRelease`; `UsbLease.release()` is reached only after both pass.
  The policy is shared rather than copied, and restart recovery uses the same exact PID, interface,
  and PHY evidence before a recovered lease can be returned.
- PC A passed a real cold run against installed runtime `abcd-m4-9635a1f` and public relay through a
  Korean Windows profile path. Run `a21db4a1-a217-4985-8dce-b7984fcde9b9` proved D8 endpoint,
  wrapper, child, session, and token absence; D9 observed zero owned interfaces, zero matching driver
  processes, and an inactive selected PHY for three consecutive samples; only then did D10 prove
  Windows detach and matching Linux USB absence. The run ended terminal with verified cleanup, no
  recovery file, and no Linux USB, interface, or PHY residue.
- The post-change full audit remains `480 passed, 3 skipped`.

## 6. Remaining Milestone 7 work

This checkpoint is not the M7 exit gate. The following must be implemented and verified in order:

1. Wire the D7 diagnostic callback to the production diagnostic peer/temporary-room/credential owner;
   its strict gate exists but product diagnostics are intentionally not migrated before M8.
2. Repeat the now-qualified real WSL PID/interface/PHY and conditional `UsbLease` path on PC B. PC A
   and its non-ASCII profile boundary are complete.
3. Complete app/control/PC restart recovery and endpoint-hang/fault injection at every D gate.
4. Prove Stop, End, Leave, and Close room-action semantics without bypassing D; product routing remains
   a Milestone 9 migration boundary.
5. Extend the deployed check from the completed public two-role smoke and zero-orphan authority
   metrics to the complete measured distributed-D harness when a second installed PC is available.

Until those checks pass, normal rooms, production diagnostics, desktop UI, and installers remain on
their existing paths and no installer should be built from this checkpoint.
