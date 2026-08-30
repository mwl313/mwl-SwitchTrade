# PC B temporary ABC+D M7 qualification handoff

> Audience: the Codex task operating PC B and the human controlling its real Switch.
> Source checkpoint: `586d1230c22e46182e9f9d6ba189dec01c191d78` on
> `codex/abcd-orchestration-rework`.
> Installer release: GitHub prerelease `v0.2.6-beta.2`, release ID
> `abcd-m7-pcb-586d123`.
> Supported production radio for this qualification: RTL8192EU `0bda:818b` only.

## 1. Scope and truth boundary

Qualify PC B's independent physical environment in this order:

1. detached cold P0;
2. Direct A0-A9 with one real Switch hosting a room;
3. Direct B2-B10 with one real Switch searching for the app-hosted room.

The installer supplies the immutable WSL runtime. The current desktop GUI is still the legacy
product path and does **not** launch the rewritten ABC+D harness. Run the qualification CLIs from the
exact source checkpoint below. Do not use an ordinary GUI trade as ABC+D evidence.

These runs do not prove C2, a full trade, or two-PC distributed D. Stop after Direct B and return the
evidence to PC A. A later coordinated procedure will use both installed PCs.

## 2. Safety rules

- Do not manually unregister, delete, rename, or move a WSL distribution.
- Do not detach the adapter while a harness is running.
- Do not retry after `cleanup_status` is `failed` or `unknown`; run the same command once so its
  recovery path can finish, then stop and report if cleanup is still unverified.
- Never collect raw packet captures, MAC addresses, room passcodes, credentials, trainer data, or
  Pokémon data.
- Keep the app closed while a CLI harness owns the radio. Use only one harness at a time.
- Do not report a functional pass unless `functional_status=passed` and
  `cleanup_status=verified` are both present in the final JSON.

## 3. Download, verify, and install

Download these assets from GitHub prerelease `v0.2.6-beta.2`:

- `SwitchTradeSetup.exe`;
- `SwitchTradeSetup.exe.sha256`;
- this handoff document.

In PowerShell, from the download directory:

```powershell
$expected = ((Get-Content -Raw .\SwitchTradeSetup.exe.sha256).Trim() -split '\s+')[0]
$actual = (Get-FileHash -Algorithm SHA256 .\SwitchTradeSetup.exe).Hash.ToLowerInvariant()
if ($actual -ne $expected) { throw "SwitchTradeSetup.exe checksum mismatch" }
Start-Process -FilePath .\SwitchTradeSetup.exe -Wait
```

Accept a restart if Setup requires it. After signing back in, allow Setup to resume and complete.
Verify the installed release and active immutable runtime:

```powershell
$manifest = Get-Content -Raw "$env:LOCALAPPDATA\Programs\SwitchTrade\release-manifest.json" |
  ConvertFrom-Json
if ($manifest.release_id -ne 'abcd-m7-pcb-586d123') { throw "Wrong installed release" }
$activePath = Join-Path $env:LOCALAPPDATA 'SwitchTrade\state\active-runtime.json'
$active = Get-Content -Raw $activePath | ConvertFrom-Json
wsl.exe -d $active.active_runtime -u root -- cat /opt/switchtrade/.switchtrade-release.json
```

The WSL marker must also identify `abcd-m7-pcb-586d123`. If installation or verification fails,
preserve the Setup/provisioner error code and stop before hardware testing.

## 4. Prepare the exact source and host Python

Use a normal, non-elevated PowerShell. Clone if the repository is absent; otherwise fetch it. Keep
the path under the real PC B user profile, including a non-ASCII profile name if applicable.

```powershell
git clone https://github.com/mwl313/mwl-SwitchTrade.git switchtrade-pcb
Set-Location .\switchtrade-pcb
git fetch origin codex/abcd-orchestration-rework
git switch --detach 586d1230c22e46182e9f9d6ba189dec01c191d78
py -3.12 -m venv .audit-venv
.\.audit-venv\Scripts\python.exe -m pip install --requirement requirements.txt `
  --requirement test-requirements.txt
```

If the repository already exists, do not discard local work. Use a clean, separate clone or worktree
at the exact checkpoint instead.

## 5. Select and authorize PC B's adapter

Attach exactly one RTL8192EU `VID_0BDA&PID_818B` adapter. Open SwitchTrade once, go to Settings,
select that exact adapter, and choose **Use selected adapter**. Complete the administrator prompt,
then close SwitchTrade completely.

Confirm the selection file exists and the selected instance still resolves exactly once:

```powershell
$selection = Join-Path $env:LOCALAPPDATA 'SwitchTrade\runtime\hardware-selection.json'
$selected = Get-Content -Raw $selection | ConvertFrom-Json
if ($selected.usb_id -ne '0bda:818b') { throw "Wrong adapter selected" }
$selected
usbipd state
```

Do not copy PC A's InstanceId or BusId. They are machine-specific.

## 6. Test 1 — detached cold P0

```powershell
$active = Get-Content -Raw (Join-Path $env:LOCALAPPDATA `
  'SwitchTrade\state\active-runtime.json') | ConvertFrom-Json
$stateRoot = Join-Path $env:LOCALAPPDATA 'SwitchTrade\qualification-pc-b'
wsl.exe --shutdown
.\.audit-venv\Scripts\python.exe -m switchtrade.connection.p0_harness `
  --distro $active.active_runtime `
  --runtime-root /opt/switchtrade `
  --selection-file $selection `
  --state-root (Join-Path $stateRoot 'p0') `
  --relay-url https://relay.pangyostonefist.org
```

Accept only exit code `0`, `functional_status=passed`, and `cleanup_status=verified`.

## 7. Test 2 — Direct A0-A9

On one Switch, enter FireRed/LeafGreen's Wireless Club Direct Corner, open the Trade Center, select
**Become Leader**, and remain on the hosting screen. Do not use a second Switch.

```powershell
wsl.exe --shutdown
.\.audit-venv\Scripts\python.exe -m switchtrade.connection.direct_a_harness `
  --distro $active.active_runtime `
  --runtime-root /opt/switchtrade `
  --selection-file $selection `
  --state-root (Join-Path $stateRoot 'direct-a')
```

Accept only exit code `0`, both statuses above, `result_level=A_CONTROL_READY`, and ordered A0-A9
evidence.

## 8. Test 3 — Direct B2-B10

Do not host a room on any Switch. Start the command first. When the app-hosted room is advertising,
use one Switch to enter the Trade Center, choose **Join Group**, and select the visible room.

```powershell
wsl.exe --shutdown
.\.audit-venv\Scripts\python.exe -m switchtrade.connection.direct_b_harness `
  --distro $active.active_runtime `
  --runtime-root /opt/switchtrade `
  --selection-file $selection `
  --state-root (Join-Path $stateRoot 'direct-b')
```

Accept only exit code `0`, both statuses above, `result_level=B_CONTROL_READY`, and ordered B2-B10
evidence. The Switch message “The other trainer appears unavailable” does not by itself fail this
local B test; the structured B gates and cleanup result are authoritative.

## 9. Post-run residue check and hand-back

After every run:

```powershell
usbipd state
wsl.exe -d $active.active_runtime -u root -- sh -lc "pgrep -af 'switchtrade.connection|wsl-radio' || true; find /sys/class/net -maxdepth 1 -type l -printf '%f\n'; find /sys/class/ieee80211 -maxdepth 1 -mindepth 1 -printf '%f\n' 2>/dev/null"
```

The target adapter must be returned to its prior Windows ownership, with no run endpoint, target
interface, PHY, or recovery guard left behind. Do not delete failed state; it is diagnostic evidence.

Return one compact report per test:

```text
PC: B
release_id: abcd-m7-pcb-586d123
test: P0 | Direct A | Direct B
exit_code:
run_id:
functional_status:
cleanup_status:
result_level_or_last_gate:
primary_failure_code: none | CODE
residue_check: clean | details
report_path:
```

Do not begin the two-PC distributed-D test until PC A has reviewed all three PC B results.
