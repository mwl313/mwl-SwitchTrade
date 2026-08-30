# M7 two-PC/two-Switch distributed qualification

> Harness contract: `distributed-invitation.v2` plus `distributed-control-state.v1`.
> PC A creates the qualification room; PC B joins it.
> Use only `scripts/windows/Invoke-M7DistributedHarness.ps1`; do not assemble direct Python commands.

This qualification runner is independent of the retiring desktop GUI. Setup/provisioning installs the
immutable WSL runtime and writes the Windows adapter selection. The old GUI is not a control,
checkpoint, or execution dependency.

## Release gate

Both PCs must have the same clean source commit and an installed runtime whose release ID is exactly
`beta-<first 12 characters of that source SHA>`. A source fix is not installed evidence. The launcher
checks the interpreter, dependencies, imported module path, source cleanliness, runtime identity,
explicit WSL working directory, and canonical Windows adapter selection before it can create or join
a relay room.

From any working directory, run on each PC:

```powershell
$repo = 'C:\path\to\the\clean\switchtrade\checkout'
$harness = Join-Path $repo 'scripts\windows\Invoke-M7DistributedHarness.ps1'
& $harness preflight
```

`status: ready` is necessary but does not attach USB or certify the radio. Do not use
`-AllowDirtyForDevelopment` for qualification evidence.

## Non-negotiable safety order

1. Keep both PCs and both Switches together. Do not operate either Switch.
2. Run canonical `preflight` on both PCs and compare exact source, release, and control contract.
3. Use a new named state root on each PC. Never reuse or delete a prior state root.
4. Start PC A `create`, transfer its fresh invitation once, then start PC B `join`.
5. Both runners must publish `coordination_paired` with the same test ID and
   `usb_attached:false`.
6. In separate controller terminals, read `status`. Both must be `awaiting_user` at
   `PAIRING_CONFIRMED`, with `run_id:null`.
7. Submit identity-bound `continue` on both PCs. There is no Enter/stdin checkpoint.
8. Follow later role-specific Switch checkpoints only when `status` exposes that exact checkpoint.
9. Accept a case only after both reports verify D11 and each adapter returns to its exact prior state.
10. Complete two nearby cases with clean residue before increasing physical distance.

Any v1 invitation, identity mismatch, dirty source, missing pairing state, early USB attachment,
duplicate endpoint, unknown cleanup, or retained session is a stop condition. Do not reuse an
invitation, manually edit control files, or delete state to bypass recovery.

## Case 1 — PC A joins the Switch room, PC B hosts the mirrored AP

Choose a campaign name that has never been used, for example `D-PHYS-1-R9`.

PC A runner terminal:

```powershell
$stateRoot = Join-Path $env:LOCALAPPDATA 'SwitchTrade\qualification-m7-distributed\D-PHYS-1-R9'
& $harness create -StateRoot $stateRoot -Role a_room_joiner -Action end
```

Transfer only the new `ONE_TIME_INVITATION=...` value. PC B uses its own local path with the same
campaign name:

```powershell
$stateRoot = Join-Path $env:LOCALAPPDATA 'SwitchTrade\qualification-m7-distributed\D-PHYS-1-R9'
& $harness join -StateRoot $stateRoot -Invitation '<ONE_TIME_INVITATION_FROM_PC_A>'
```

On each PC, open a second PowerShell terminal and read status:

```powershell
& $harness status -StateRoot $stateRoot
```

After both sides show the same `test_id`, `PAIRING_CONFIRMED`, and `run_id:null`, continue each side
using the exact ID copied from that PC's status:

```powershell
& $harness continue -StateRoot $stateRoot `
  -TestId '<EXACT_TEST_ID>' -Checkpoint PAIRING_CONFIRMED
```

P0 now begins and may take USB ownership. Wait for `attempt_locked` and the later checkpoint. All
post-P0 control commands must include the exact `run_id` shown by `status`.

When PC A reports `CREATE_SWITCH_ROOM`:

1. On Switch A, open the trade room as Group Leader and leave it open.
2. Submit:

```powershell
& $harness continue -StateRoot $stateRoot -TestId '<EXACT_TEST_ID>' `
  -RunId '<EXACT_RUN_ID>' -Checkpoint CREATE_SWITCH_ROOM
```

When PC B reports `JOIN_SWITCH_GROUP`:

1. Submit the exact continue command first.
2. Only then use Switch B to choose Join Group before the bounded association deadline.

```powershell
& $harness continue -StateRoot $stateRoot -TestId '<EXACT_TEST_ID>' `
  -RunId '<EXACT_RUN_ID>' -Checkpoint JOIN_SWITCH_GROUP
```

Later `D_ACTION_CONFIRMED` and owner finalization checkpoints use the same command shape with their
exact checkpoint. PC A closes the authority room only after PC B reports D11 verified.

## Case 2 — roles reversed

Use fresh `D-PHYS-2-R9` roots and a new invitation. PC A starts with:

```powershell
& $harness create -StateRoot $stateRoot -Role b_ap_host -Action close
```

PC B receives the complementary room-joiner role. Switch B becomes Leader; Switch A selects Join
Group only at its published AP checkpoint. Apply the same pairing, exact ID, D11, and residue gates.

## Cancellation and recovery

To stop before P0, omit `RunId`. After P0 starts, provide the exact run ID:

```powershell
& $harness cancel -StateRoot $stateRoot -TestId '<EXACT_TEST_ID>'
& $harness cancel -StateRoot $stateRoot -TestId '<EXACT_TEST_ID>' -RunId '<EXACT_RUN_ID>'
```

Cancellation requests work; the runner remains the sole cleanup owner. A cancel command is rejected
once cleanup/finalization owns the run. Ctrl+C is normalized into the same cancellation request and
must not be used to kill cleanup.

If a runner was interrupted or cleanup is not verified, do not start another case:

```powershell
& $harness recover -StateRoot $stateRoot
```

If recovery waits at `RECOVERY_FINALIZATION_CONFIRMED`, read status and submit the exact identity-bound
continue command. Recovery never converts an interrupted case into a pass.

## Acceptance evidence

For both PCs record source SHA, installed release ID, role, test ID, run ID, attempt ID, functional
status, cleanup status, last passed gate, D11 result, and redacted residue result. Never return an
invitation, room code, credentials, Windows InstanceId, MAC addresses, or packet data.

M7 physical qualification closes only after both nearby full cases and the separated case leave zero
endpoints, PHYs, temporary interfaces, active relay credentials, nonterminal rooms, locks, recovery
records, or unintended USB ownership.
