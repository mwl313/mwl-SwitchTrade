# ABC+D Milestone 5 C0/C1 source checkpoint

> Branch: `codex/abcd-orchestration-rework`
> Source commit: `162f779`
> Status: Milestone 5 functional exit gate accepted on 2026-08-30. The deployed validation relay
> passed the full C0/C1 matrix and restart/no-orphan checks. Production deployment reproducibility
> remains an explicit Milestone 9 gate because this host uses native launchd rather than the reference
> container artifact.
> Scope: P0-bound authority admission, endpoint identity, ordered `rfu-tunnel.v2`, bidirectional
> nonce proof, and exact A-to-B advertisement delivery.

## 1. Boundary carried forward

The owner directed the final PC A Direct B cleanup rerun to remain explicit qualification debt while
Milestone 5 proceeds. Runtime `abcd-m4-9635a1f` still needs one real searching-Switch run that reaches
`factory_released` and verifies all radio/USB cleanup. This document does not close Milestone 4.

Milestone 5 starts a new C path. It does not extend the rejected v1 tunnel orchestration and it does
not route the normal application or diagnostics through v2 yet.

## 2. Implemented checkpoint

- Added the binary `rfu-tunnel.v2` envelope with attempt ID, credential-derived source seat, uint64
  source epoch, contiguous uint64 sequence, closed message kind, and bounded payload.
- Added strict rejection codes for invalid envelopes, wrong attempt/seat, gaps, duplicates, stale
  epochs, invalid epoch starts, repeated readiness, payload bounds, and hash/probe mismatches.
- Added a separate `/v2/trade-rooms/{room_code}/attempts/{attempt_id}/ws` transport namespace. The
  legacy query-string role cannot select a v2 seat.
- Added `/v2/trade-rooms/{room_id}/ready`. It requires two distinct `p0-attestation.v2` records with
  the same release before the existing admitted room primitives may produce a v2 attempt. A legacy
  attempt cannot be promoted afterward.
- Bound every v2 WebSocket to the member credential, P0 run ID, stage generation, launch nonce, and
  endpoint PID. A changed or duplicate launch identity fails closed.
- Buffered at most 32 frames and 128 KiB per source epoch. A late peer receives sequence 0
  `PEER_READY` before sequence 1 `ADVERTISEMENT`, under the session lock, exactly once.
- Reconnect clears retained state, creates a fresh source epoch, makes the still-connected peer
  rotate its epoch, and repeats the bidirectional unpredictable nonce proof. A repeated identical
  advertisement is suppressed at the receiving attempt projection; changed content fails.
- Relay restart explicitly fails active attempts and starts with no v2 transport or admission
  namespace. Terminal room actions, protocol failure, and reconnect expiry erase both retention and
  admission state.
- Added a small `CStage` projection that distinguishes `C0_AUTHENTICATED`, `C0_PEER_READY`,
  `C0_DATA_PLANE_PROVEN`, and `C1_ADVERTISEMENT_DELIVERED`. Reports retain only the advertisement
  SHA-256, never the advertisement bytes or credentials.
- Updated the hosting smoke and deployment contract to exercise this exact v2 path.

The canonical contracts are:

- `contracts/abcd/rfu-tunnel.v2.schema.json`;
- `contracts/abcd/p0-attestation.v2.schema.json`;
- `contracts/abcd/app-readiness.v2.schema.json`;
- `contracts/abcd/c0-c1-stage.v1.schema.json`.

## 3. Evidence

- Fixed audit runtime: `282 passed, 1 skipped` across `tests/`.
- Focused v2/C/tunnel matrix after the final compatibility refinement: `31 passed`.
- Production-mode local uvicorn instance with legacy relay disabled:
  `python -m relay.smoke http://127.0.0.1:8791 --allow-http` passed.
- Covered both creator/finder seat assignments, distinct/mismatched P0 proofs, legacy-attempt
  rejection, changed launch identity, unpredictable two-way probes, late peer, exact hash delivery,
  duplicate advertisement suppression, reconnect re-proof, gap, duplicate, stale epoch, wrong
  attempt, protocol retirement, and relay restart.
- Existing v1 room, transport, control, installer, P0, direct A, direct B, diagnostics, and soak tests
  remained green in the fixed audit runtime.

The Windows default Python lacks `trio` and therefore cannot load the Direct A/B test modules. It is
not the qualification interpreter; `.audit-venv\Scripts\python.exe` contains the pinned `trio 0.33.0`
runtime and produced the complete result above.

## 4. Deployment gate and recorded deviation

Docker is not installed on the development PC, so the exact
`switchtrade-relay:0.3.0-validation.1` container could not be built locally. The original handoff
required the relay operator to:

1. build the committed Compose/Dockerfile artifact from `162f779` or a documentation-only descendant;
2. record the immutable image digest and single-worker configuration;
3. deploy it behind the validation HTTPS/WebSocket ingress without a user-selectable relay option;
4. run `python -m relay.smoke https://<validation-relay>`;
5. repeat restart, late-peer, both-role, stale/gap/wrong-attempt, and no-orphan checks against that
   deployed artifact.

The validation host is actually supervised by launchd and runs one native uvicorn worker. It has no
Docker image. The M5 behavioral matrix was therefore executed against that real native deployment,
not against the reference container. This is accepted for the M5 C0/C1 functional exit because the
running critical source files match the committed checkpoint and every M5 exit behavior passed.
It is not accepted as proof of a reproducible production artifact. Before Milestone 9 cutover, the
operator must either deploy the reference container or provide a committed native release manifest
covering the clean Git tree, complete relay source tree, pinned dependency set, Python runtime,
launchd unit/configuration, environment contract, and rollback artifact with full hashes.

No `SIDE_READY`, `C_BRIDGE_READY`, RFU data plane, physical A/B integration, distributed D, normal
application cutover, diagnostic migration, production deployment, or trade is claimed here.

## 5. Deployed validation relay evidence

The operator deployed documentation checkpoint `bbc549f` (source checkpoint `162f779`) to
`https://relay.pangyostonefist.org`. On 2026-08-30, the external health contract reported `ready`,
`single-writer`, opaque payloads, `room-control.v1`, and both `rfu-tunnel.v1` and
`rfu-tunnel.v2`. The following checks then passed through the public HTTPS/WSS ingress:

- the production hosting smoke once, followed by 10 consecutive reruns;
- creator/finder with both seat assignments, including member B as creator;
- exact fixture advertisement delivery in both directions;
- two-way unpredictable nonce proof and reconnect re-proof with fresh epochs;
- late-peer replay ordered as `PEER_READY` sequence 0 then `ADVERTISEMENT` sequence 1, exactly once;
- suppression of an identical advertisement after reconnect;
- rejection of mismatched releases and duplicate P0 run identities;
- rejection of a changed launch nonce for an already admitted seat;
- factual attempt failure for sequence gap, duplicate sequence, stale epoch, and wrong attempt;
- successful idempotent room deletion after every completed or deliberately failed case.

The ingress intentionally returns HTTP 403 for `/metrics`, so the operator read the private endpoint.
During a controlled restart with a nonce-proven active v2 attempt, the public client observed the
attempt fail factually as `relay.restart`, cleaned the room, and passed a fresh post-restart v2 smoke.
The private metrics then reported:

- `live_rfu_sessions=0`;
- `live_rfu_v2_attempts=0`;
- `admitted_rfu_v2_attempts=0`;
- `active_member_credentials=0`.

The operator also reported exactly one `uvicorn relay.server:app` process under launchd. The running
checkout was identified as `bbc549f`; the supplied hash prefixes were independently matched to the
complete Git-object hashes:

- `relay/server.py`:
  `615e83e0e12fdb62c3d8a98bbf4efcedab13c368b82049e3636fa61ed914b511`;
- `relay/authority.py`:
  `d0b628cf4d1665e08eb6e874453fdf422b4dea7e40e39442a63f20fb25a0a24f`.

This closes the Milestone 5 exit gate: both role assignments, unpredictable probes, late-peer,
reconnect, restart, stale/gap/wrong-attempt behavior, factual C0/C1 errors, and zero orphan authority
state passed through the validation relay. It does not claim `SIDE_READY`, C2, physical A/B
integration, distributed D, diagnostic/application migration, production cutover, or a trade.
