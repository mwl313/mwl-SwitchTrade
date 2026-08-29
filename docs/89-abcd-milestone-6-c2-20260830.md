# ABC+D Milestone 6 C2 source checkpoint

> Branch: `codex/abcd-orchestration-rework`
> Source commit: `d2130fe`
> Status: Milestone 6 software and deployed validation exit gate accepted on 2026-08-30. Source,
> local real-process, public HTTPS/WSS C0-C2, exact deployed identity, single-worker, and private
> zero-orphan checks passed.
> Scope: identity-bound A_READY/B_READY activation, bounded pre-barrier RFU, byte-exact sustained
> RFU, and reconnect re-proof. No physical A/B, distributed D, product cutover, or trade is claimed.

## 1. Boundary and component admission

Milestone 6 starts from the admitted Milestone 5 `rfu-tunnel.v2` path. It does not import the legacy
normal-room lifecycle or use the legacy `CStage` as an activation authority. `TunnelSim` is admitted
only as the low-level feature-neutral Pia Reliable bridge: it forwards opaque application bytes and
flags and has no game controller, trade callback, or product lifecycle responsibility.

The owner-deferred final Direct B cleanup run and PC B P0/A/B qualification remain open. Software C2
evidence cannot replace either physical side and does not imply that AP-open means Switch-associated.

## 2. Implemented contracts and ordering

- Added strict canonical `side-ready.v1` and redacted `c2-stage.v1` contracts.
- The room authority allocates one positive `activation_generation` per attempt. Its v2 admission
  projection carries the same value to both seats.
- A local bridge may emit exactly one `SIDE_READY` per current proof generation, and only after its
  role-specific `A_READY` or `B_READY` gate. It binds attempt, seat, A/B role, local gate, P0 run,
  stage generation, hashed launch identity, advertisement hash, and proof generation.
- The relay validates every binding against the credential-derived seat, complementary locked role,
  admitted launch, current attempt generation, and one immutable advertisement hash before forwarding
  readiness. Duplicate readiness in one source epoch fails closed.
- RFU is rejected by the relay until both current source epochs have accepted readiness. `SIDE_READY`
  and RFU are never retained; only `PEER_READY` and the bounded advertisement are replayable.
- `C2Bridge` owns a 256-frame local pre-barrier queue and a bounded receive backlog. Overflow,
  invalid Reliable flags, early RFU, stale or duplicate readiness, cancellation, and transport errors
  preserve one stable first failure.
- `C_BRIDGE_READY` requires both current readiness records. `C_RFU_ACTIVE` additionally requires at
  least one real post-barrier Reliable frame sent and received in the current proof generation;
  cumulative counters from an earlier connection cannot pass it.
- RFU payload bytes and uint8 Reliable flags are preserved exactly. Reports contain only identities,
  hashes, gates, bounded counts, timing, and failure codes—not credentials or RFU payloads.

## 3. Loss and reconnect ownership

Each relay seat is represented by one `V2Peer` slot that owns its WebSocket and reset event together.
There are no parallel socket/event maps that can drift apart. On disconnect or peer-send failure the
relay clears both side-ready epochs, emits the existing ordered `PEER_CLOSE` transport control when
possible, revokes both slots, and starts the bounded reconnect deadline. WebSocket ping/close policy
also bounds silent transport-loss detection.

Both clients must reconnect, create fresh source epochs, repeat unpredictable bidirectional proof,
and send fresh readiness. A transient seat handoff conflict is retryable; credential, launch, and
attempt conflicts remain permanent. RFU activation resets to false until new bidirectional traffic
crosses the new barrier.

## 4. Evidence

- Fixed audit runtime full suite: `443 passed, 3 skipped`.
- Focused C2/tunnel/endpoint/real-process matrix: `49 passed`.
- Production-mode local uvicorn with legacy relay disabled:
  `python -m relay.smoke http://127.0.0.1:8791 --allow-http` passed.
- The hosting smoke now verifies matching authority activation generations, both readiness signals,
  both bridge projections, unpredictable byte-exact RFU in both directions, and current-generation
  RFU-active counters before deleting the temporary room.
- Tests cover delayed A and delayed B, one-sided non-activation, reversed local role mapping,
  stale/changed/duplicate readiness, 256-frame overflow, invalid input, cancellation, early RFU,
  same-batch readiness ordering, sustained traffic beyond the retained-frame limit, disconnect,
  replacement reconnect, fresh barrier proof, and byte/flag preservation.
- The final maintainability review replaced parallel peer state with one owned slot, kept timeout
  constants centralized, reused the existing transport close kind, and found no game-specific or
  legacy orchestration dependency in the C2 path.

The Windows default Python still lacks `trio`; `.audit-venv\Scripts\python.exe` is the pinned full
qualification interpreter. The three skipped cases are the repository's existing intentional skips.

## 5. Completed validation gate

The completed validation gate required:

1. deploy `d2130fe` or a documentation-only descendant to the validation relay;
2. confirm one supervised relay worker and the exact source identity;
3. run `python -m relay.smoke https://<validation-relay>`;
4. combine public reversed-role and delayed-side smoke with the source-identical local real-process
   early-RFU, reconnect, stale, and duplicate matrix;
5. confirm `live_rfu_v2_attempts=0`, `admitted_rfu_v2_attempts=0`, and
   `active_member_credentials=0` after cleanup.

Milestone 7 is the next implementation boundary: distributed, outcome-preserving D. Normal rooms,
production diagnostics, desktop UI, and installers remain on the old path until their later planned
cutovers; no installer should be built from this checkpoint.

## 6. Public validation evidence received

After deployment, the authenticated public health request reported `ready`, `single-writer`, opaque
payloads, writable storage, `room-control.v1`, and `rfu-tunnel.v2`. The extended C0-C2 hosting smoke
then passed ten consecutive runs through `https://relay.pangyostonefist.org`, followed by one normal
and one reversed-role run. Each run used distinct P0 attestations and credentials, required matching
activation generations, held one side ready without activating, accepted the complementary side,
and exchanged unpredictable byte-exact RFU in both directions before room deletion. Normal ordering
proved delayed B; reversed ordering proved delayed A.

The operator confirmed deployed tip `2db57f5`, a documentation descendant of source checkpoint
`d2130fe`, with zero diff across the relay, v2 tunnel, and C2 protocol files. One launchd-supervised
uvicorn PID (`26522`) ran with one worker. Private metrics after the public matrix reported
`live_rfu_v2_attempts=0`, `admitted_rfu_v2_attempts=0`, `active_member_credentials=0`, and
`live_rfu_sessions=0`. Together with the source-identical real-process negative/reconnect tests, this
closes the Milestone 6 software/deployed exit gate.
