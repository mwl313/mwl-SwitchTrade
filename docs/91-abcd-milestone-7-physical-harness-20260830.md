# ABC+D Milestone 7 physical distributed harness

> Branch: `codex/m7-safe-pairing`
> Canonical release tag: `v0.2.10-beta.1`
> Application version: `0.2.10-beta.1` (Windows/MSI version `0.2.10`)
> Status: source complete and automated regression passed; installed two-PC/two-Switch evidence is
> still required.

## Boundary

The physical qualification path is a CLI because the previous desktop GUI is a retirement target.
It neither imports nor calls the legacy desktop/control session orchestration. A future GUI may call
the same coordinator, but it is not an acceptance dependency for this milestone.

`switchtrade.connection.distributed_harness` is the single Windows-side runner. It extends the
existing `P0Harness` at four explicit lifecycle points—authority binding, admitted endpoint
preparation, live endpoint driving, and measured D cleanup. It does not copy the P0 USB lease or D
release implementation.

Inside the immutable WSL runtime, `radio_worker` preserves its PID and executes exactly one
`distributed_endpoint`. The endpoint holds one admitted Direct A or Direct B LDN context open,
passes its live advertisement through `rfu-tunnel.v2`, and attaches the proven feature-neutral
`TunnelSim`/C2 path. It releases those resources only through `EndpointDStage`.

## Ordered run

1. PC A creates a private authority room and emits a bounded v2 invitation. The invitation binds the
   authoritative room UUID/code, source, release, action, and roles; it never contains a credential.
2. PC B validates source/release before joining, then validates the returned private-room contract,
   UUID/code, local seat, and unique two-seat membership. Both PCs must emit `coordination_paired`
   with `usb_attached=false` and wait for operator confirmation.
3. Only after the pairing confirmation does each PC pass passive P0, acquire its selected adapter once,
   and publish a
   `p0-attestation.v2` hash.
4. The relay admits exactly two distinct P0 runs with complementary roles. Each coordinator binds the
   authoritative room, seat, attempt, role-lock version, activation generation, launch nonce, and
   PID before endpoint execution.
5. The A endpoint joins one real Switch-hosted room and publishes the exact validated advertisement.
   The B endpoint receives that advertisement and creates the mirrored AP for the other Switch.
6. `A_READY` and `B_READY` enter the existing C2 barrier. `C_BRIDGE_READY` requires current proof
   generation and `C_RFU_ACTIVE` requires real bidirectional RFU.
7. `end`/`close` wait for `C_TRADE_COMPLETE`; `stop`/`leave` may freeze a canceled result at
   `C_RFU_ACTIVE`. A functional failure freezes its original stable code.
8. Authority D1 is recorded before either endpoint tears down. The endpoint performs D2-D4, local
   control measures and submits D5, both sides reach D6, and `LocalDRelease` performs D7-D11 and the
   sole USB return.
9. Only after both PCs report D11 does the responsible operator finalize Leave/Close. End/Stop rooms
   are subsequently closed as qualification cleanup, separately from the frozen action result.

## Reliability and privacy

- One coordinator, one wrapper PID, one endpoint launch, one USB acquisition, and one USB return per
  side and run.
- Normal starts refuse a dirty source tree, incompatible installed release, stale invitation,
  unresolved prior session, active cleanup guard, changed adapter, or non-complementary role lock.
- The endpoint configuration and session recovery state are private files. They contain credentials
  required for the live run but are deleted only after verified cleanup and room finalization.
- NDJSON status and terminal reports contain no room code, member/reconnect token, MAC, packet,
  trainer, or Pokémon data.
- Repeated GET polling is read-only. Launch and readiness mutations use existing authority
  idempotency and exact generation checks.
- An interrupted run is never restarted as a new attempt. Recovery state is retained until local
  cleanup and authority release are both proven. The `recover` command records a failed D1
  when possible, invokes the existing exact PID/radio/USB recovery path, waits for authority
  terminalization, and preserves a non-pass result.
- A failed or unknown D8/D9 observation blocks USB return. A D or room-finalization failure remains
  visible and cannot satisfy the command's pass exit criteria.

## Automated evidence

The corrected source suite passes `521 passed, 3 skipped`. Focused tests
cover strict invitation/config/closing contracts, complementary attempt validation, PID-preserving
normal-mode ticket validation, sustained Direct-stage ownership, exact payload handoff, UDP data
plane framing, and one P0 lease/one delegated D release.

Automated evidence cannot prove real A/B RF conditions or a physical trade. The two role assignments
and End, Close, Stop, and Leave actions remain the installed physical exit gate documented in
`HANDOFF-M7-TWO-PC-DISTRIBUTED-20260830.md`.

The first operator-assisted launch exposed a qualification-runner defect before either physical
endpoint was paired: 250 ms relay polling exhausted the server's authenticated 120-request/60-second
limit after about 30 seconds. Recovery also assumed an attempt already existed. Release
`beta-82e7dccdda08` centralizes relay polling at one second and makes pre-attempt owner recovery close
the temporary room without an invalid attempt lookup. These fixes do not alter the production desktop
or relay protocol.

The rejected `D-PHYS-1-R3` case exposed that private rooms do not persist public-directory `note`
metadata, while the old client tried to use top-level `room.note` as its campaign binding. Version 2
uses the authority's room UUID/code instead, adds the pre-USB pairing barrier, retries only explicit
optimistic version conflicts, and retains recovery state when local cleanup is unverified. Local
real-authority pairing passed 30/30 cycles with no active credential or nonterminal room, and a hosted
software-only pairing passed both roles without touching hardware. Installed physical qualification
remains open until the new release package passes its lifecycle checks on both PCs.

## 2026-08-31 control and launch-context correction

The R5-R8 attempts found qualification-infrastructure defects after the original milestone record:
inherited Windows cwd broke Linux imports, an interpreter shim did not forward operator stdin,
bypassing that shim removed dependencies, and normal cancellation emitted a traceback. Those attempts
are rejected and do not change the ABC+D stage results.

The source harness now uses explicit immutable WSL cwd for every subprocess and preserves factual
probe error classes. Human checkpoints are persisted in `distributed-control-state.v1` and advanced
only by exact test-ID/run-ID/checkpoint-bound `continue` commands. `status` is read-only; `cancel`
requests cancellation while the active runner remains the only cleanup owner. The canonical Windows
entry point validates the composed environment before any relay-room mutation. See
`HANDOFF-M7-TWO-PC-DISTRIBUTED-20260830.md` for the superseding operator sequence. Installed physical
qualification remains open.
