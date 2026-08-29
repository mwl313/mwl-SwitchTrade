# ABC+D Milestone 2 qualification guide

This guide qualifies P0 only. A pass proves the installed runtime, relay path, selected USB radio,
ordered kernel/driver/PHY preparation, actual RX, single launch boundary, and verified cleanup. It
does not prove Switch room detection, AP creation, relay data delivery, or a trade.

## 1. Fixed candidate

Use the same candidate on both PCs. Do not rebuild it on PC B:

- source commit: `975e68b`;
- release: `abcd-m2-975e68b`;
- content ID: `369f7774aad3e7a8aa6e15b6dcaf8eae512685e7d693463c0e10fe41064c6358`;
- WSL SHA-256: `b0116b52876bed5ef97c74d0e717961d184e90f746d3fce7f344cf419833e96e`;
- package directory: `artifacts\qualification\m2-975e68b\package`;
- provisioner: `artifacts\qualification\m2-975e68b\provisioner\SwitchTradeProvisioner.exe`.

Keep the package and repository under a path that may contain spaces or non-ASCII characters. Moving
them to an ASCII-only path would avoid, rather than test, a required product boundary.

## 2. Install or repair the qualification runtime

Close any SwitchTrade process. In an elevated PowerShell opened at the exact `975e68b` checkout:

```powershell
$candidate = (Resolve-Path 'artifacts\qualification\m2-975e68b').Path
& "$candidate\provisioner\SwitchTradeProvisioner.exe" repair `
  --package-root "$candidate\package" `
  --log "$candidate\provisioner-repair.log"
& "$candidate\provisioner\SwitchTradeProvisioner.exe" status --json `
  --package-root "$candidate\package"
```

Continue only when status reports `software_ready`, release `abcd-m2-975e68b`, and the expected
custom kernel. The provisioner owns side-by-side import, verification, activation, rollback, and
removal of the prior SwitchTrade-owned runtime; do not manually delete a WSL distribution.

## 3. Resolve and authorize exactly one adapter

Run `usbipd state`. Select the physical `VID_0BDA&PID_818B` adapter and record its complete Windows
InstanceId and current BusId. If zero or more than one eligible adapter is present, stop instead of
guessing. Authorize the exact instance once if it is not already shared:

```powershell
$instanceId = 'USB\VID_0BDA&PID_818B\REPLACE_WITH_PC_SPECIFIC_SERIAL'
& "$candidate\provisioner\SwitchTradeProvisioner.exe" authorize-hardware `
  --instance-id $instanceId --usb-id '0bda:818b'
```

Create the machine-specific selection contract without a BOM. Replace the instance and bus values
with values observed on that PC:

```powershell
$selection = Join-Path $candidate 'hardware-selection.json'
$value = [ordered]@{
  schema = 1
  usb_id = '0bda:818b'
  instance_id = $instanceId
  bus_id = 'REPLACE_WITH_CURRENT_BUSID'
} | ConvertTo-Json
[IO.File]::WriteAllText($selection, $value + [Environment]::NewLine,
  [Text.UTF8Encoding]::new($false))
```

## 4. Run one cold P0

Use a separate state root per PC. The harness reads the active runtime instead of accepting a typed
distribution name:

```powershell
$active = Get-Content -Raw (Join-Path $env:LOCALAPPDATA `
  'SwitchTrade\state\active-runtime.json') | ConvertFrom-Json
wsl.exe --shutdown
python -m switchtrade.connection.p0_harness `
  --distro $active.active_runtime `
  --runtime-root /opt/switchtrade `
  --selection-file $selection `
  --state-root (Join-Path $candidate 'p0-state-this-pc') `
  --relay-url https://relay.pangyostonefist.org
```

Accept the run only when the process exits `0`, `functional_status` is `passed`, and
`cleanup_status` is `verified`. A functional pass with failed or unknown cleanup is a failed run and
must block retry until the same command completes recovery.

## 5. Post-run checks

Confirm all of the following before another run:

- `usbipd state` shows the adapter detached if the run acquired it;
- the report shows one wrapper, one endpoint launch, and normal worker exit;
- the active coordinator record is terminal with verified cleanup;
- no `p0-usb-recovery.json` remains for the terminal run;
- the selected WSL runtime contains no matching USB device, wireless interface, or PHY.

Preserve the run directory and provisioner log as evidence. They contain stable failure codes and
redacted adapter identity; do not add raw MAC addresses, room data, credentials, or packet captures.

## 6. Qualification order

On each PC, first pass one detached cold run. Then run the pre-attached, cancellation,
control-interruption/recovery, delayed-enumeration, inactive-port, adapter-change, and unknown-cleanup
cases defined by the Milestone 2 plan. Only after both PCs pass those gates, run 30 consecutive cold
P0 cycles per the agreed qualification count. Any cleanup failure stops the sequence and must be
resolved before the count restarts.
