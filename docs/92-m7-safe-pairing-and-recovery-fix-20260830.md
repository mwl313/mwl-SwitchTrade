# M7 safe pairing and recovery correction

## Rejected evidence

`D-PHYS-1-R3` is rejected. PC B failed before P0 with
`DISTRIBUTED_INVITATION_IDENTITY_MISMATCH`; PC A subsequently timed out and required exact local
recovery. Neither result is physical ABC+D evidence.

## Definitive cause

The old runner put a campaign string in `note` while creating a private room and later expected the
join response to expose `room.note`. The room authority stores directory metadata, including `note`,
only for public rooms. A hosted create/join probe proved that the private room had two valid members
but no top-level note, profile note, or directory. The temporary probe room was closed.

This was a client harness contract defect. The hosted authority behaved according to its contract and
requires no deployment for this correction.

## Corrected order

1. PC A creates a private room and emits `distributed-invitation.v2` containing the non-secret room
   UUID and room code plus the source, release, test, action, and complementary roles.
2. PC B validates source and release before joining, then validates the returned private room contract,
   exact UUID/code, local seat, two distinct member IDs, and the two unique authority seats.
3. Both runners emit `coordination_paired` with `usb_attached=false` and keep their relay membership
   alive while waiting.
4. Neither side constructs the passive hardware validator, starts P0, attaches USB, or launches WSL
   until the operator confirms that both terminals show the same pairing checkpoint.
5. Versioned relay mutations refresh and retry only `room_version_conflict`; every other conflict or
   identity difference remains terminal.
6. On a pre-endpoint failure, the worker exits and the selected netdev is explicitly quiesced before
   D8/D9 evidence and the single USB return.
7. A failed or unknown local cleanup retains the live session and recovery credentials. Authority is
   released only after local cleanup is verified; the session is removed only after authority release
   is also proven. Recovery can rotate an expired member credential or finish a room that is already
   closed/expired, including a pairing-only failure with no P0 run.

## Evidence before packaging

- Focused private-room, pairing, room-version, P0 cleanup, D-control, and authority tests pass.
- Full Python suite: `521 passed, 3 skipped`.
- Local real-authority software pairing: 30/30 cycles, zero active credentials, zero nonterminal rooms.
- Hosted relay software pairing: creator and peer checkpoints passed, UUID/code bindings matched,
  both authorities released, both recovery files removed, and no hardware action executed.

## Installer qualification correction

The first local `0.2.9 -> 0.2.10` package qualification exposed a separate release-lifecycle defect:
the provisioner trusted one `wsl --list --quiet` snapshot before removing the previous runtime. A
transiently omitted name could therefore clear `PreviousName` and the committed cleanup journal while
the WSL registration and runtime directory still existed. That candidate package is rejected.

Runtime cleanup now treats the per-user WSL registration as authoritative, verifies the ownership
marker and exact managed location before unregistering, and verifies registration, name, and managed
directory absence before clearing recovery state. A bounded false-success check retains the committed
journal. Repair also reconciles older verified runtimes and unregistered managed directories strictly
inside its own runtime root, while an ambiguous marker fails closed and unrelated distributions or
other isolated SwitchTrade roots remain untouched. Contract tests cover the
transient-name omission, unregister false success, orphan reconciliation, and ambiguous-ownership
paths, plus cross-root isolation. The replacement package must repeat static bundle, disposable Unicode-path WSL lifecycle, and
real `0.2.10` same-version Repair qualification after this correction.

Installed physical evidence remains deliberately open. The acceptance sequence is software pairing on
both nearby PCs, P0/cleanup on both PCs, two consecutive nearby two-Switch end-to-end passes, verified
zero residue, and only then the separated-distance run.

## D-PHYS-1-R4 rejection and correction

`D-PHYS-1-R4` is also rejected as physical evidence. Both PCs proved pairing, P0, the locked attempt,
and `C0_DATA_PLANE_PROVEN`, but no Switch was operated and neither Direct A nor Direct B produced a
stage report. The run exposed three orchestration defects before any physical gate:

1. `CREATE_SWITCH_ROOM` and `JOIN_SWITCH_GROUP` were notifications rather than approval barriers. The
   endpoint continued immediately, so Direct A could exhaust its bounded scan before the operator
   acted. Both checkpoints now require an exact run- and role-bound Continue command. Direct A starts
   only after the Switch A room is open; Direct B pauses at its AP checkpoint until PC B continues.
2. `StageSession` replaced a Direct A/B report failure such as `A_ROOM_NOT_OBSERVED` with a generic
   `DISTRIBUTED_ENDPOINT_FAILED`. It now carries the stable code, failed gate, last passed gate, and
   bounded message to D1. A completed failed stage is not misreported as an LDN teardown failure when
   its thread and context have already exited.
3. Relay transport expiry unconditionally erased the process-local launch admission after 15 seconds,
   even when D1 had already frozen the attempt in `closing`. This allowed a valid D5 report to fail as
   `d_launch_not_admitted`. Peer expiry and fatal transport paths now retire admission only when the
   authority actually converts an active attempt to `relay.peer_lost`; D closing retains the binding
   until D6 or the bounded D timeout retires it.

Focused distributed/authority/tunnel/D regression passed 115 tests. The complete available audit
environment passed 365 tests with one intentional skip. This is source-level evidence only. Because
the correction changes both the relay and installed endpoint/harness payload, the relay must be
redeployed and both PCs must install one matching immutable build before another physical run.
