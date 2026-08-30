# PC B handoff — M7 two-PC/two-Switch preflight

> PC A is the computer hosting the main repository/Codex task.
> PC B is the other computer and its separate Codex task.
> Date: 2026-08-30.
> Branch: `codex/abcd-orchestration-rework`.
> Current installed candidate: `abcd-m7-pcb-586d123` / `0.2.6-beta.2`.
> Current status: **machine preflight ready; physical distributed runner not yet committed**.

## 1. Facts already accepted

PC B's returned handoff and raw reports were reviewed on PC A. The following PC B evidence is
accepted and does not need to be repeated merely for this handoff:

- cold P0: passed, cleanup verified;
- Direct A: exact A0-A9 sequence, `A_CONTROL_READY`, cleanup verified;
- Direct B: exact B2-B10 sequence, `B_CONTROL_READY`, one real Switch participant, cleanup verified;
- runtime integrity manifest SHA-256:
  `3f1ed433ac70c2dfea09f64f787ceb75d944b5ceb9be2cb344a40f3c728468c9`;
- installed release: `abcd-m7-pcb-586d123`;
- the locally created Windows hardware selection resolves the same PC B adapter used by all three
  reports.

PC A has now also reached the common preflight baseline:

- installed release `abcd-m7-pcb-586d123`;
- cold P0 run `05a56402-2877-4847-9233-0925bef16d00` passed;
- cleanup is `verified` and the adapter returned to detached Windows ownership;
- no matching Linux USB, interface, or PHY residue remains;
- the production relay reports `room-control.v1` and `rfu-tunnel.v2` ready.

## 2. PC B action now — read-only verification only

Close the SwitchTrade GUI. From a normal, non-elevated PowerShell, run:

```powershell
$manifestPath = Join-Path $env:LOCALAPPDATA 'Programs\SwitchTrade\release-manifest.json'
$activePath = Join-Path $env:LOCALAPPDATA 'SwitchTrade\state\active-runtime.json'
$selectionPath = Join-Path $env:LOCALAPPDATA 'SwitchTrade\runtime\hardware-selection.json'

$manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
$active = Get-Content -Raw -LiteralPath $activePath | ConvertFrom-Json
$selection = Get-Content -Raw -LiteralPath $selectionPath | ConvertFrom-Json

if ($manifest.release_id -ne 'abcd-m7-pcb-586d123') { throw 'PC B installed release changed' }
if ($active.release_id -ne 'abcd-m7-pcb-586d123') { throw 'PC B active runtime changed' }
if ($selection.schema -ne 1 -or $selection.usb_id -ne '0bda:818b' -or
    [string]::IsNullOrWhiteSpace($selection.instance_id)) {
  throw 'PC B Windows hardware selection is absent or invalid'
}

wsl.exe -d $active.active_runtime -u root -- cat /opt/switchtrade/.switchtrade-release.json
wsl.exe -d $active.active_runtime -u root -- /opt/switchtrade/bridge/.venv/bin/python -c `
  "import json; from switchtrade.connection.p0 import linux_usb_probe; print(json.dumps(linux_usb_probe('0bda:818b'),sort_keys=True,separators=(',',':')))"
usbipd state

$health = Invoke-RestMethod 'https://relay.pangyostonefist.org/health'
if ($health.status -ne 'ready' -or $health.room_contract -ne 'room-control.v1' -or
    $health.rfu_contracts -notcontains 'rfu-tunnel.v2') {
  throw 'Required production relay contract is unavailable'
}
```

Return this redacted acknowledgement only:

```text
M7/PC_B/PREFLIGHT
release_id: abcd-m7-pcb-586d123
runtime_release_id: abcd-m7-pcb-586d123
adapter_profile: 0bda:818b
windows_selection: present
linux_residue: absent
usb_attached: false
relay_v2: ready
```

Do not include the raw InstanceId, MAC address, room credential, token, passcode, or packet bytes.

## 3. Do not start the physical run yet

Commit `20707f625ddd381eb548e3ebf31daecda8bc878b` and candidate
`abcd-m7-pcb-586d123` contain the P0, Direct A, Direct B, C2, and distributed-D components, but do
not contain a supported CLI that keeps A and B alive simultaneously and binds them to one physical
attempt. Independent Direct A and Direct B commands tear down after their local test and therefore
cannot be combined into a two-Switch qualification.

Until PC A supplies all three final values below, report `BLOCKED: DISTRIBUTED_HARNESS_ABSENT` and
do not use the legacy GUI or `switchtrade.endpoint` as a substitute:

```text
DISTRIBUTED_HARNESS_COMMIT=<full committed SHA>
PC_A_COMMAND=<exact committed command>
PC_B_COMMAND=<exact committed command>
```

This is a software entrypoint blocker, not a failed PC B hardware qualification.

## 4. Physical roles after the runner checkpoint

The first run will use:

- PC A: `A_ROOM_JOINER`; its Switch chooses `Become Leader` and keeps the room open.
- PC B: `B_AP_HOST`; its Switch chooses `Join Group` only after the runner reports the AP-ready
  checkpoint.

The second run reverses those roles. For every run:

1. both Codex tasks verify the same source commit and release;
2. PC A creates the one-time private relay invitation through the committed runner;
3. neither side sends credentials through chat or commits them to the repository;
4. both sides require `A_READY`, `B_READY`, `C_BRIDGE_READY`, and real bidirectional
   `C_RFU_ACTIVE` for the same attempt;
5. the Switches complete the requested trade/save/return action;
6. both sides complete D5, the same D6 barrier, and verified D11 before another run.

Follow the shared campaign contract in
`docs/HANDOFF-M7-TWO-PC-DISTRIBUTED-20260830.md` once its harness placeholders have been replaced by
real committed values.

## 5. Stop conditions

Stop and preserve evidence if any of the following is true:

- release, runtime marker, source commit, role, attempt, or activation generation differs;
- the Windows selection is missing or resolves zero/multiple adapters;
- the adapter is unexpectedly attached before the run;
- Linux already contains a matching USB device, interface, or PHY;
- an old endpoint, cleanup guard, recovery record, or temporary radio interface remains;
- cleanup is `failed` or `unknown` on either PC.

Do not delete a WSL distribution, hardware state, or recovery record to force a pass.
