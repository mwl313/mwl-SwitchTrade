# ABC+D Milestone 7 distributed D checkpoint

> Branch: `codex/abcd-orchestration-rework`
> Source commit: `d815562`
> Endpoint D2-D4 commit: `fdbdd12`
> Validation-smoke commit: `40fecf3`
> Status: M7 authority and endpoint D2-D4 slices complete; Milestone 7 remains open.
> Scope: D1 closing intent, endpoint D2-D4, D5 authority acknowledgement, D6 two-side/forced
> barrier, and relay transport retirement. This checkpoint does not implement or claim D7-D11 or
> production control wiring for measured D5 evidence.

## 1. Boundary

This checkpoint introduces one authority-owned distributed-D path on top of the admitted v2 attempt.
It does not reuse the legacy room terminalization path and it is not advertised as a completed relay
capability. Only a P0-admitted v2 attempt may enter it.

The relay owns the shared outcome and barrier. The new endpoint stage owns only its local D2-D4
resources. Local control still must prove endpoint exit, interfaces, radio, USB lease, and recovery
state in later M7 slices. A local acknowledgement proves only the credential-derived seat that
submitted it.

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
- Source-identical local uvicorn smoke passed both normal and reversed role assignments through C0-C2,
  D1, one-sided D5 non-terminal behavior, two-sided D6, post-terminal retry, and room close. Final
  metrics were zero for active credentials, v1/v2 sessions, and v2 admissions.
- The source-identical public relay deployment passed normal and reversed-role HTTPS/WSS smoke
  through C0-C2 and D1/D5/D6. Private metrics are access-controlled and still require the operator's
  zero-orphan confirmation for this deployed checkpoint.
- Endpoint tests prove exact D2 -> D3 -> D4 call order, native close-tail success and timeout,
  continued cleanup after faults, immutable run/attempt/seat/activation/launch binding, queue
  accounting, admission sealing, transport/thread/LDN evidence, and idempotent replay.
- Tests cover two-sided cancellation, failed outcomes, false completion rejection, stale launch
  identity, legacy-path rejection, primary/secondary error separation, forced-side evidence, barrier
  timeout, relay restart, exact post-terminal HTTP retry, and transport retirement.
- JSON contracts were parsed independently and the persisted authority projection was checked against
  the strict required field set.

## 6. Remaining Milestone 7 work

This checkpoint is not the M7 exit gate. The following must be implemented and verified in order:

1. Production control wiring that invokes D2-D4 only after authoritative D1 and constructs D5 from
   the persisted endpoint report plus measured process/radio state, not caller claims.
2. D7 diagnostic-only peer/room/token cleanup.
3. D8 exact endpoint/child/launch verification, D9 stable Linux radio quiescence, D10 conditional
   return of only the run-owned USB adapter, and D11 recovery-state/lock release.
4. Stop, Leave, Close, app/control/PC restart, endpoint hang, and fault injection at every gate.
5. Private zero-orphan deployed relay confirmation and the complete C0-C2 plus distributed-D harness.

Until those checks pass, normal rooms, production diagnostics, desktop UI, and installers remain on
their existing paths and no installer should be built from this checkpoint.
