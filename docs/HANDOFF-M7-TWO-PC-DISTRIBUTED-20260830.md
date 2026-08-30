# M7 two-PC/two-Switch distributed qualification

> Current qualification release: `v0.2.10-beta.1`.
> Invitation contract: `distributed-invitation.v2`.
> PC A creates the qualification room; PC B joins it.

This CLI runner is independent of the retiring desktop GUI. The installed app is used only to install
the immutable WSL runtime and select each PC's own supported adapter.

## Non-negotiable safety order

1. Keep both PCs and both Switches together. Do not move or operate either Switch yet.
2. Check out the exact release tag and install that release on both PCs.
3. Start PC A, transfer its fresh invitation once, and start PC B.
4. Both terminals must print `coordination_paired` with `usb_attached:false`.
5. Do not press Enter on either PC until both pairing lines are visible. Before this Enter, the adapter
   must still be Windows-owned and no P0 run or WSL radio may exist.
6. Press Enter on both PCs to begin P0. Follow later role-specific Switch prompts only when displayed.
7. Accept a case only when both sides verify D11 and return their adapter to its exact prior state.
8. Run two complete close-range cases with clean residue. Increase physical distance only after both
   pass.

Any v1 invitation, source/release difference, missing pairing checkpoint, early USB attachment,
duplicate endpoint, failed cleanup, or retained session is a stop condition. Never reuse an invitation
or delete the state root to bypass recovery.

## Install and source preflight — both PCs

Install `SwitchTradeSetup.exe` from GitHub prerelease `v0.2.10-beta.1`, using the SHA-256 published in
that release. Open SwitchTrade once, select the local RTL8192EU adapter, and close the GUI. Then run in
the clean repository clone:

```powershell
git fetch origin --tags
git switch --detach v0.2.10-beta.1
if (git status --short) { throw 'Source tree is dirty' }

$source = (git rev-parse HEAD).Trim().ToLowerInvariant()
$expectedRelease = "beta-$($source.Substring(0,12))"
$candidateDistros = @((@(& wsl.exe --list --quiet) -replace ([char]0), '') |
  Where-Object { $_ -like "SwitchTrade-$expectedRelease-*" })
$matchingDistros = @(
  foreach ($candidate in $candidateDistros) {
    try {
      $marker = ((& wsl.exe -d $candidate -u root -- cat `
        /opt/switchtrade/.switchtrade-release.json 2>$null) | Out-String) | ConvertFrom-Json
      if ($marker.release_id -eq $expectedRelease) { $candidate }
    } catch {}
  }
)
if ($matchingDistros.Count -ne 1) { throw 'Expected exactly one matching installed runtime' }
$activeDistro = $matchingDistros[0]
$selection = "\\wsl.localhost\$activeDistro\root\.local\state\switchtrade\runtime\hardware-selection.json"
if (-not (Test-Path -LiteralPath $selection)) { throw 'Adapter selection is absent' }
$selectionValue = Get-Content -Raw -LiteralPath $selection | ConvertFrom-Json
if ($selectionValue.usb_id -ne '0bda:818b') { throw 'Wrong adapter selection' }

$health = Invoke-RestMethod 'https://relay.pangyostonefist.org/health'
if ($health.status -ne 'ready' -or $health.room_contract -ne 'room-control.v1' -or
    $health.rfu_contracts -notcontains 'rfu-tunnel.v2') { throw 'Relay contract unavailable' }
$python = '.\.audit-venv\Scripts\python.exe'
```

The source SHA is derived from the release tag rather than copied from prose. The runtime must report
`beta-` followed by that SHA's first twelve characters. This prevents running one harness checkout
against a different installed runtime.

## Case 1 — PC A joins the Switch room, PC B hosts the mirrored AP

PC A starts first:

```powershell
$stateRoot = Join-Path $env:LOCALAPPDATA 'SwitchTrade\qualification-m7-distributed\D-PHYS-1-R4'
& $python -m switchtrade.connection.distributed_harness `
  --distro $activeDistro --runtime-root /opt/switchtrade `
  --selection-file $selection --state-root $stateRoot `
  create --role a_room_joiner --action end
```

Transfer only the new `ONE_TIME_INVITATION=...` value. PC B runs with its own state root:

```powershell
$stateRoot = Join-Path $env:LOCALAPPDATA 'SwitchTrade\qualification-m7-distributed\D-PHYS-1-R4'
& $python -m switchtrade.connection.distributed_harness `
  --distro $activeDistro --runtime-root /opt/switchtrade `
  --selection-file $selection --state-root $stateRoot `
  join --invitation '<ONE_TIME_INVITATION_FROM_PC_A>'
```

Stop at the pairing checkpoint. Verify both terminals show the same test ID and
`coordination_paired`, and that both adapters remain Windows-owned. Then press Enter on both PCs.

- When instructed, Switch A selects `Become Leader` and keeps its room open.
- Only after the AP checkpoint, Switch B selects `Join Group`.
- Complete the trade through `C_TRADE_COMPLETE` and the End prompt.
- PC A closes the qualification room only after PC B reports `D11_VERIFIED`.

## Case 2 — roles reversed

Use fresh `D-PHYS-2-R4` state roots and a new invitation. PC A starts with:

```powershell
create --role b_ap_host --action close
```

PC B receives the complementary room-joiner role. Switch B becomes Leader; Switch A selects Join
Group only at its AP checkpoint. Apply the same pairing, D11, and residue gates.

## Recovery

If either command is interrupted or reports failed cleanup, do not create another case. On that PC run
the same common arguments and exact state root with:

```powershell
& $python -m switchtrade.connection.distributed_harness `
  --distro $activeDistro --runtime-root /opt/switchtrade `
  --selection-file $selection --state-root $stateRoot recover
```

Recovery supports failures before P0, expired member credentials, closed/expired rooms, and active
distributed runs. It never converts an interrupted case into a pass.

## Acceptance

For both PCs record source SHA, release ID, role, run ID, attempt ID, functional status, cleanup status,
last passed gate, D11 result, and a redacted residue result. Do not return invitation, room code,
credentials, Windows InstanceId, MAC addresses, or packet data.

M7 physical qualification closes only after two consecutive nearby full cases and the later separated
case leave zero endpoints, PHYs, temporary interfaces, active relay credentials, nonterminal rooms,
locks, recovery records, or unintended USB ownership.
