# PC B handoff — M7 physical distributed runner

> PC A: the computer hosting the main repository/Codex task.
> PC B: this other computer and its separate Codex task.
> Canonical source: `0caafce6803549fa26a50bb7c2d34e16a54c71a3`.
> Installer: GitHub prerelease `v0.2.7-beta.1`.
> Installed release ID: `beta-0caafce68035`.

The previous PC B cold P0, Direct A, and Direct B evidence remains accepted. This handoff upgrades PC
B to the first GUI-independent distributed runner; it does not ask PC B to repeat those isolated
tests.

## PC B preparation

1. Download `SwitchTradeSetup.exe` from `v0.2.7-beta.1` and verify SHA-256
   `a5cec5a92b42a75d7c7df59e15053ac6a849d617986f84fe41c7f0ab2ee7db1e`.
2. Install it, open the installed app once, authorize/select PC B's own RTL8192EU adapter, and close
   the SwitchTrade GUI.
3. In PC B's clean clone run:

```powershell
git fetch origin codex/abcd-orchestration-rework
git switch --detach 0caafce6803549fa26a50bb7c2d34e16a54c71a3
git status --short

$bridgeDistro = @((@(& wsl.exe --list --quiet) -replace ([char]0), '') |
  Where-Object { $_ -like 'SwitchTrade-*' })[0]
if (-not $bridgeDistro) { throw 'No installed SwitchTrade runtime' }
$localAppDataWsl = (& wsl.exe -d $bridgeDistro -u root -- wslpath -u `
  $env:LOCALAPPDATA.Replace('\','/')).Trim()
$active = ((& wsl.exe -d $bridgeDistro -u root -- cat `
  "$localAppDataWsl/SwitchTrade/state/active-runtime.json") | Out-String) | ConvertFrom-Json
$manifest = ((& wsl.exe -d $bridgeDistro -u root -- cat `
  "$localAppDataWsl/Programs/SwitchTrade/release-manifest.json") | Out-String) | ConvertFrom-Json
$activeDistro = $active.active_runtime
$selectionWsl = "$localAppDataWsl/SwitchTrade/runtime/hardware-selection.json"
$selection = "\\wsl.localhost\$activeDistro$($selectionWsl.Replace('/','\'))"
$selectionValue = Get-Content -Raw -LiteralPath $selection | ConvertFrom-Json

if ((git rev-parse HEAD) -ne '0caafce6803549fa26a50bb7c2d34e16a54c71a3') { throw 'Wrong source' }
if (git status --short) { throw 'Source tree is dirty' }
if ($manifest.release_id -ne 'beta-0caafce68035') { throw 'Wrong installed release' }
if ($active.release_id -ne 'beta-0caafce68035') { throw 'Wrong active runtime' }
if ($selectionValue.usb_id -ne '0bda:818b') { throw 'Wrong or absent local adapter selection' }
if (((& wsl.exe -d $activeDistro -u root -- cat /opt/switchtrade/.switchtrade-release.json |
    Out-String) | ConvertFrom-Json).release_id -ne 'beta-0caafce68035') {
  throw 'Runtime marker mismatch'
}

$health = Invoke-RestMethod 'https://relay.pangyostonefist.org/health'
if ($health.status -ne 'ready' -or $health.room_contract -ne 'room-control.v1' -or
    $health.rfu_contracts -notcontains 'rfu-tunnel.v2') { throw 'Relay contract unavailable' }
```

Return only:

```text
M7/PC_B/PRECHECK/PASS
source_sha: 0caafce6803549fa26a50bb7c2d34e16a54c71a3
release_id: beta-0caafce68035
runtime_release_id: beta-0caafce68035
adapter_profile: 0bda:818b
cleanup_guard: clear
residue: clean
```

Do not return the raw Windows InstanceId, invitation, room code, credentials, MAC address, or packet
data.

## PC B test command

Wait for the fresh one-time invitation from PC A. Then, from the detached canonical source:

```powershell
$python = '.\.audit-venv\Scripts\python.exe'
$stateRoot = Join-Path $env:LOCALAPPDATA 'SwitchTrade\qualification-m7-distributed\D-PHYS-1'

& $python -m switchtrade.connection.distributed_harness `
  --distro $activeDistro --runtime-root /opt/switchtrade `
  --selection-file $selection --state-root $stateRoot `
  join --invitation '<ONE_TIME_INVITATION_FROM_PC_A>'
```

Use the case name supplied by PC A for later state roots (`D-PHYS-2`, `D-ACTION-STOP`, or
`D-ACTION-LEAVE`). The invitation determines PC B's complementary role and action; do not add local
role flags.

- As `b_ap_host`, wait for the AP/user checkpoint before the PC B Switch selects `Join Group`.
- As `a_room_joiner`, make the PC B Switch select `Become Leader` and leave that room open when
  instructed.
- Report structured gates only. After `D11_VERIFIED`, tell PC A before either side finalizes the room.

If interrupted, reuse the same state root with `recover`. Do not create a new invitation or delete
state. Follow all stop conditions and the complete four-case campaign in
`docs/HANDOFF-M7-TWO-PC-DISTRIBUTED-20260830.md`.
