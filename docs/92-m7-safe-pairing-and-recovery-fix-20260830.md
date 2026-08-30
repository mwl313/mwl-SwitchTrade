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
journal. Repair also reconciles older verified runtimes and unregistered managed directories, while an
ambiguous marker fails closed and unrelated distributions remain untouched. Contract tests cover the
transient-name omission, unregister false success, orphan reconciliation, and ambiguous-ownership
paths. The replacement package must repeat static bundle, disposable Unicode-path WSL lifecycle, and
real `0.2.10` same-version Repair qualification after this correction.

Installed physical evidence remains deliberately open. The acceptance sequence is software pairing on
both nearby PCs, P0/cleanup on both PCs, two consecutive nearby two-Switch end-to-end passes, verified
zero residue, and only then the separated-distance run.
