# M7 two-PC/two-Switch distributed qualification

> PC A: the computer hosting the main repository/Codex task.
> PC B: the other computer and its separate Codex task.
> Branch: `codex/abcd-orchestration-rework`.
> Canonical source: `0caafce6803549fa26a50bb7c2d34e16a54c71a3`.
> Installer: GitHub prerelease `v0.2.7-beta.1`.
> Installed release ID: `beta-0caafce68035`.
> Supported qualification radio: RTL8192EU `0bda:818b`.

This is the source of truth for the first physical M7 qualification. The runner is a CLI and has no
dependency on the retiring desktop GUI. PC labels never change; the A/B radio roles change in the
reversed-role case.

## What the runner proves

One command on each PC performs the production sequence:

1. passive P0 validation and one USB lease;
2. private relay room membership and complementary role lock;
3. one PID-preserving WSL endpoint launch;
4. sustained Direct A room detection or Direct B AP hosting;
5. C2 bridge admission and real bidirectional RFU;
6. ordered D1-D11 shutdown and one verified USB return.

The invitation contains a room code and non-secret test binding. It does not contain member or
reconnect credentials. Reports exclude room codes, credentials, MAC addresses, packet bodies, and
trainer/Pokémon data.

## Install and source preflight — both PCs

Install `SwitchTradeSetup.exe` from prerelease `v0.2.7-beta.1`. Close the SwitchTrade GUI after setup.
From a normal, non-elevated PowerShell in a clean clone run:

```powershell
git fetch origin codex/abcd-orchestration-rework
git switch --detach 0caafce6803549fa26a50bb7c2d34e16a54c71a3
git status --short

$manifestPath = Join-Path $env:LOCALAPPDATA 'Programs\SwitchTrade\release-manifest.json'
$activePath = Join-Path $env:LOCALAPPDATA 'SwitchTrade\state\active-runtime.json'
$selectionPath = Join-Path $env:LOCALAPPDATA 'SwitchTrade\runtime\hardware-selection.json'
$manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
$active = Get-Content -Raw -LiteralPath $activePath | ConvertFrom-Json
$selection = Get-Content -Raw -LiteralPath $selectionPath | ConvertFrom-Json

if ((git rev-parse HEAD) -ne '0caafce6803549fa26a50bb7c2d34e16a54c71a3') { throw 'Wrong source' }
if (git status --short) { throw 'Source tree is dirty' }
if ($manifest.release_id -ne 'beta-0caafce68035') { throw 'Wrong installed release' }
if ($active.release_id -ne 'beta-0caafce68035') { throw 'Wrong active runtime' }
if ($selection.usb_id -ne '0bda:818b') { throw 'Wrong or absent adapter selection' }

$health = Invoke-RestMethod 'https://relay.pangyostonefist.org/health'
if ($health.status -ne 'ready' -or $health.room_contract -ne 'room-control.v1' -or
    $health.rfu_contracts -notcontains 'rfu-tunnel.v2') { throw 'Relay contract unavailable' }
```

The setup UI may be used only to install the immutable runtime and authorize the local adapter. It
does not control the test. A missing `hardware-selection.json` is normal only before that one-time
local adapter selection; the physical runner intentionally refuses to guess a device.

Define the common command inputs on each PC:

```powershell
$active = Get-Content -Raw (Join-Path $env:LOCALAPPDATA 'SwitchTrade\state\active-runtime.json') |
  ConvertFrom-Json
$selection = Join-Path $env:LOCALAPPDATA 'SwitchTrade\runtime\hardware-selection.json'
$python = '.\.audit-venv\Scripts\python.exe'
```

## Case 1 — PC A joins a room, PC B hosts the mirrored AP, End

PC A starts first:

```powershell
$stateRoot = Join-Path $env:LOCALAPPDATA 'SwitchTrade\qualification-m7-distributed\D-PHYS-1'
& $python -m switchtrade.connection.distributed_harness `
  --distro $active.active_runtime --runtime-root /opt/switchtrade `
  --selection-file $selection --state-root $stateRoot `
  create --role a_room_joiner --action end
```

PC A securely transfers only the printed `ONE_TIME_INVITATION=...` value to PC B. PC B runs:

```powershell
$stateRoot = Join-Path $env:LOCALAPPDATA 'SwitchTrade\qualification-m7-distributed\D-PHYS-1'
& $python -m switchtrade.connection.distributed_harness `
  --distro $active.active_runtime --runtime-root /opt/switchtrade `
  --selection-file $selection --state-root $stateRoot `
  join --invitation '<ONE_TIME_INVITATION_FROM_PC_A>'
```

- The Switch beside PC A selects `Become Leader` and keeps the room open when instructed.
- The Switch beside PC B selects `Join Group` only when its runner reports the AP/user checkpoint.
- Continue the trade until the runner reaches `C_TRADE_COMPLETE`.
- At the End prompt, complete the Switch-side end action and press Enter.
- Each Codex reports `D11_VERIFIED`. PC A presses the final Enter only after PC B reports it.

## Case 2 — roles reversed, Close

Use a fresh state root. PC A starts:

```powershell
$stateRoot = Join-Path $env:LOCALAPPDATA 'SwitchTrade\qualification-m7-distributed\D-PHYS-2'
& $python -m switchtrade.connection.distributed_harness `
  --distro $active.active_runtime --runtime-root /opt/switchtrade `
  --selection-file $selection --state-root $stateRoot `
  create --role b_ap_host --action close
```

PC B uses the Case 1 `join` command with its own `D-PHYS-2` state root and the new invitation. In
this case PC B's Switch chooses `Become Leader`; PC A's Switch chooses `Join Group` at the AP
checkpoint. Complete the Close prompt and wait for both D11 results before PC A finalizes the room.

## Stop and Leave coverage

After both normal cases pass, repeat the shortest connection to `C_RFU_ACTIVE` with fresh state roots
and invitations:

- `create --role a_room_joiner --action stop`
- `create --role b_ap_host --action leave`

These are accepted canceled outcomes only when both sides still complete the same D6 barrier and
verify D11. They are not substitutes for the End and Close cases.

## Recovery

If a terminal, app, or computer is interrupted, do not start a fresh case and do not delete state.
On that PC rerun the same common arguments and state root with:

```powershell
& $python -m switchtrade.connection.distributed_harness `
  --distro $active.active_runtime --runtime-root /opt/switchtrade `
  --selection-file $selection --state-root $stateRoot recover
```

The recovery command operates on the recorded run identity. It cannot convert an interrupted run
into a pass.

## Immediate stop conditions

Stop and preserve the report if source/release/role/attempt/generation differs; a second endpoint or
USB attachment appears; a stale readiness event advances the stage; cleanup is failed or unknown;
or either PC retains an endpoint, interface, PHY, relay membership, lock, recovery record, or
unintended USB ownership. Never unregister WSL, delete recovery state, or use the old GUI to force a
pass.

## Acceptance evidence

For each case return the terminal `distributed-harness-report.v1` path and this redacted summary:

```text
test_id:
campaign_case:
pc:
source_sha: 0caafce6803549fa26a50bb7c2d34e16a54c71a3
release_id: beta-0caafce68035
local_role:
run_id:
attempt_id:
functional_status:
cleanup_status:
last_passed_gate:
rfu_bidirectional: true | false
d11_verified: true | false
residue_check: clean | details
primary_failure_code: none | CODE
report_path:
```

M7 closes only after End, Close, Stop, and Leave pass with both PCs at D11 and the relay reports no
live/admitted attempt or active member credentials. The next milestone is M8: route production
diagnostics through the new coordinator. Normal GUI cutover remains the separate M9 milestone.
