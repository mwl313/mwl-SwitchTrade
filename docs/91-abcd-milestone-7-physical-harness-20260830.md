# ABC+D Milestone 7 physical distributed harness

> Branch: `codex/abcd-orchestration-rework`
> Canonical source: `0caafce6803549fa26a50bb7c2d34e16a54c71a3`
> Application version: `0.2.7-beta.1` (Windows/MSI version `0.2.7`)
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

1. PC A creates a private authority room and emits a bounded one-time invitation. The invitation
   contains the room code and non-secret test binding, never a bearer or reconnect credential.
2. PC B validates the exact source SHA, installed release, test action, and complementary role before
   joining.
3. Each PC independently passes passive P0, acquires its own selected adapter once, and publishes a
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
- An interrupted run is never restarted as a new attempt. The `recover` command records a failed D1
  when possible, invokes the existing exact PID/radio/USB recovery path, waits for authority
  terminalization, and preserves a non-pass result.
- A failed or unknown D8/D9 observation blocks USB return. A D or room-finalization failure remains
  visible and cannot satisfy the command's pass exit criteria.

## Automated evidence

The source suite passes `508 passed, 3 skipped` after the physical harness additions. Focused tests
cover strict invitation/config/closing contracts, complementary attempt validation, PID-preserving
normal-mode ticket validation, sustained Direct-stage ownership, exact payload handoff, UDP data
plane framing, and one P0 lease/one delegated D release.

Automated evidence cannot prove real A/B RF conditions or a physical trade. The two role assignments
and End, Close, Stop, and Leave actions remain the installed physical exit gate documented in
`HANDOFF-M7-TWO-PC-DISTRIBUTED-20260830.md`.

The replacement installer was built from the clean canonical source as release
`beta-0caafce68035`. Static embedded-bundle verification and the disposable WSL
install/verify/repair/uninstall lifecycle both passed. `SwitchTradeSetup.exe` SHA-256 is
`a5cec5a92b42a75d7c7df59e15053ac6a849d617986f84fe41c7f0ab2ee7db1e`.
