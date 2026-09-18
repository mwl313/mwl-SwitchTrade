# Switch ↔ RetroArch/gpSP: VMware Windows 11 physical test

**2026-09-18: the next diagnostic candidate preserves every translator-authorized
WK receipt, including the NI phase. Trials13/14 stalled after approval; the
native cause and trade acceptance remain open.** See
[receipt repair, evidence and next gates](GPSP_TRIAL13_ANALYSIS_20260918.md#11-lossless-receipt-repair-and-service-bound-checks-2026-09-18).
Trial12's delayed room entry and later communication error remain separate
[full-log evidence](GPSP_TRIAL12_ANALYSIS_20260917.md).
See [current repair and qualification limits](GPSP_UNI_TRANSITION_REPAIR_20260914.md).
Use an empty English FR/LG Direct Corner **Trade** Group Leader room. Other
activities and unqualified nonzero discovery fields fail closed; do not test
battle/Mystery Gift as if they were supported by this repair.

For qualified use, execute only after `GPSP_ACCEPTANCE.final.json` and both platform jobs for the
same literal SHA are successful. This document is preparation, not a Pokémon
trade result. Keep `main` and existing work intact; use the qualified feature
branch SHA in all three checkouts. Do not merge unqualified changes.
The current candidate is for a separately authorized diagnostic trial, not
qualified use. Its acceptance intentionally remains blocked by the unresolved
native UNI stall; successful software jobs must not relabel that as completion.

## Next diagnostic trial: update, then stop at the first failure

This tests the new Simplified Architecture application. The pre-simplification
desktop is legacy preservation, not a GUI/Room compatibility gate for this
candidate. Switch-to-Switch and endpoint/driver ownership boundaries remain
regression requirements.

Do not repeat the unchanged `f427535` VM build. Both endpoints must identify
the new committed receipt-repair candidate. Close the previous independent VM
socket/residue check before a new connection. Reuse the host-local relay route
from trial14 for this comparison when freshly verified reachable; do not change
receipt policy and Internet routing together. Its exact URL is a per-run fact,
not a permanent address or authorization to widen a firewall.

No new RetroArch/core/Python install or relay deployment is needed for this
endpoint-only repair. Stop the prior SwitchTrade clients normally; preserve
their logs and prove owned cleanup first. Keep the user's emulator/content
independent. No reset/reload or settings overwrite is part of the update.

Use PowerShell **7** (`pwsh.exe`), not Windows PowerShell 5 (`powershell.exe`):
the launcher uses `ProcessStartInfo.ArgumentList`. In the VM, run each block
separately (copy commands only, no `PS ...>` prompt).
Replace `C:/path/to/switchtrade-gpsp` with the existing VM checkout path:

```powershell
Set-Location -LiteralPath 'C:/path/to/switchtrade-gpsp'
```

```powershell
git status --short
```

If user changes are present, preserve them; do not reset or overwrite them.

```powershell
git pull --ff-only origin codex/gpsp-endpoint
```

```powershell
git log -1 --oneline
```

Also preserve `git rev-parse HEAD` from both checkouts, and the Host overlay
content-id from its normal verified sync. A pull is not runtime evidence.
If this PowerShell session refuses scripts, allow only this session before
running the trusted checkout's command (do not change machine-wide policy):

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

```powershell
.\dev.ps1 doctor --emulator gpsp
```

The Host checkout must use the same exact commit, with its normal verified
`dev.ps1 sync` and source-bound WSL/radio gates. Do not run an old overlay if
sync fails. Host starts `dev.ps1 run host` with the common relay and a fresh
opt-in log directory. Obtain a **new** Pair code; none in an earlier chat is
valid evidence for this attempt.

In the VM, replace `NEW_CODE` below with that actual six-digit code before
executing. Use trial13 or another **unused** directory; never append a retry
to the first failure's files.

```powershell
.\dev.ps1 run join NEW_CODE --emulator gpsp --relay https://relay.pangyostonefist.org --log-dir .qualification/physical-gpsp-13
```

Manually connect RetroArch Netplay to `127.0.0.1:55435`; wait for `Choose Join
Group in the emulator.` before choosing the game action. Confirm the intended
trainer, select it once and accept on Switch. Keep game foreground and menus
closed. `Bridge active.` means RFU data, not game room success. First require
both games to leave the acceptance/member-wait screens. For this diagnostic
trial, do **not** proceed to trade/save: perform the separate movement checks
below first. Never interrupt a save.

If it stalls, do not reconnect or reselect repeatedly. Capture both screens,
action times and both complete opt-in logs. In a second VM PowerShell window:

```powershell
Get-Content -LiteralPath (Join-Path 'C:/path/to/switchtrade-gpsp' '.qualification/physical-gpsp-13/switchtrade-core.log') -Tail 20
```

`transfer.uni`, `uni_inflight`, `uni_waiting`, `recent_transfers`,
`uni_wire_start` and `wire_recent` distinguish first UNI, local callback
receipt, child response and actual Core admission. The tail command is only a
live status glance. **Always collect both entire log files**, including their
initial identity/trace header and final cleanup; tails are not diagnostic
evidence coverage. Share only redacted copies, not private
keys, credentials or raw game captures. The same-Pair second-room and Ctrl+C
checks below still apply; do not call the first accepted request a trade pass.

The latest diagnostic adds per-direction `recent`, `command_counts`,
`last_age_ms`/`max_gap_ms`, and child `tag_discontinuities` with a sticky first
event. These are output-boundary observations, not a game's error code or a
timeout. `closing` retains pending state before `closed` reports cleanup.
Do not use an empty post-cleanup queue as proof that no backlog existed before.
Before any next trial, copy the actual `git log -1 --oneline` output from both
machines; a successful pull alone is not an exact-source measurement.

### Trial13 checkpoints and evidence gate

Record action times and both screens at each checkpoint. Do not treat PC clocks
as synchronized. One video showing both screens is useful but remains private;
do not commit screen recordings, logs, ROMs or saves to the repository.

1. Confirm both exact SHAs, clean worktrees, Host overlay/radio ownership and
   VM doctor. Preserve the Host startup output and VM process/core identity.
2. Connect Netplay, select the trainer once, and accept on Switch. Record those
   actions separately. Observe both screens for room entry without moving.
3. If still waiting after 30 seconds, mark `entry_wait_30s` and preserve evidence;
   do not advance to movement or repeatedly rejoin. This is a **test checkpoint**,
   not a product timeout or a claim about the normal game's exact time limit.
   Preserve another 30 seconds of untouched logs, then coordinate normal stop.
4. If both entered, record `both_in_room`. Move **Host only** one tile on open
   floor, away from chairs/exit tiles. Record whether/when both screens respond.
   If they do not settle within 10 seconds, stop progression and collect logs.
5. Only after that succeeds, move **Guest only** one tile on open floor and
   record both responses. Do not press further buttons after the first error.
6. Keep 10 seconds of post-symptom logging without retrying. Then stop the VM
   SwitchTrade client with Ctrl+C, followed by the identity-bound Host shutdown.
   Do not terminate RetroArch, force a game reload, or perform blanket process/
   WSL/USB cleanup. Record shutdown order and prove owned residue separately.

New `rfu_trace` batches retain observation sequence, same-process monotonic
elapsed time, WT/WK timestamps, UNI command headers/tags and Reliable attempts/
window movement. `local_delivery` is converter intent; `local_write_returned`
is socket-send return; `local_receipt` is the gpSP callback ACK, **not** game
consumption. No game arguments or payload fingerprints are recorded.

Each observer buffers at most 4096 metadata entries between existing diagnostic
flushes. Overflow is sticky (`dropped`/`first_dropped`); missing batches or final
flushes invalidate complete coverage. Logging/Host scheduling overhead is
observable through `scheduler.max_diagnostic_work_ms`, `max_tick_work_ms` and
`max_tick_gap_ms`. Guest `loop` reports diagnostic work and advertiser iteration
gaps (sleep, scheduling, lock waits and I/O combined, not pure CPU latency).
Emulated game clocks and internal queues remain outside those measurements.
Normalized hashes of nine diagnostic/data-path source files detect stale
Host/VM copies, but do not replace exact Git/overlay or ROM identity evidence.

After both stopped, bring **copies** of the complete Host and Guest logs into
a new private `.qualification/physical-gpsp-13-evidence` directory on this PC,
named `host.log` and `guest.log`. Preserve originals and record their SHA256.
From the repository's existing audit environment, run this read-only tool:

```powershell
.\.audit-venv\Scripts\python.exe tools/audit_rfu_trace.py .qualification/physical-gpsp-13-evidence/host.log .qualification/physical-gpsp-13-evidence/guest.log
```

If there are multiple Generations, rerun with `--generation` and the **actual**
common generation ID in those logs; never combine two rooms. Exit 2 means
incomplete/insufficient evidence, exit 1 means a recorded boundary mismatch,
and exit 0 means only matched captured metadata boundaries. `TRACE_COMPLETE`
is **not** communication success; `functional_verdict` remains `NOT_ASSESSED`.
A mismatch may be cancellation/cleanup after the initiating fault; correlate
it with the first symptom and pre-clear queue snapshot, not the last exception.

Decision after the trial: missing source/coverage => repair evidence collection;
boundary mismatch => inspect the first differing boundary; matching boundaries
with a stalled game => investigate native clock/game consumption and gpSP FIFO
admission using a separately scoped reproduction. Do not fabricate ACKs or
declare a radio fault merely because all recorded queues are empty. Only after
stable entry and both movement directions should a later authorized trial
attempt trade/save, normal exit and a same-Pair second room.

## Topology and prerequisites

| Location | Runs | Does not need |
| --- | --- | --- |
| Physical Windows Host PC | Existing managed WSL + selected USB Wi-Fi + SwitchTrade Host beside Group Leader Switch | RetroArch |
| VMware Windows 11 guest | User-started RetroArch/gpSP + native Windows SwitchTrade Guest | WSL, USB passthrough, radio gate |
| Common trusted Internet relay | One Core relay worker reachable by both Windows sessions | Emulator or Wi-Fi stack |

The VM's NAT or bridged Internet connection must reach the common relay. It
does not carry LDN/radio itself. The emulator listener stays inside the VM on
loopback; do not expose port 55435 to the Internet or point RetroArch at the relay.
Use distinct Internet and test-radio interfaces on the physical Host. VM/WSL,
drivers and firewall provisioning are separate owner-approved work, not done by
these commands. Follow the existing [Switch physical prerequisites and owned
radio recovery procedure](SWITCH_TO_SWITCH_PHYSICAL_RUNBOOK.md), including the
managed distro, proven radio, legitimate private keys and opt-in logging.

Supported initial combination is **Switch Group Leader → gpSP Join Group**.
Only these measured Windows x64 binaries are accepted (not every same-version
build):

- RetroArch **1.22.2** exe SHA256:
  `81c11b6f24932bf7918f05eee8928035bff3887335fd2a081507c75e9d94d06a`.
- gpSP **v1.1.0-74db5e5** DLL SHA256:
  `c84f619c1077a7fbae84c385df752fbeb867d301880400add7cce6a380dbd516`;
  stock Netpacket protocol `gpSP v1.0`.
- Test inputs came from the [official RetroArch 1.22.2 x64 archive directory](https://buildbot.libretro.com/stable/1.22.2/windows/x86_64/).
  Archive hashes are in `tools/gpsp_qualification/prepare_stock.py`. That tool is
  CI preparation only, not a product installer. Never silently replace a user's
  frontend/core. A core update changes identity and requires new qualification.

## Common relay

For deployment/cutover use the canonical [Core relay handoff](../../relay/DEPLOYMENT.md).
The direct-TLS command below is an alternative, not a second concurrent service.

On an already prepared trusted Linux server, Python 3.12, qualified checkout:

```bash
python3.12 -m venv .relay-venv
.relay-venv/bin/python -m pip install --require-hashes -r relay/requirements.txt
.relay-venv/bin/python -m pip check
export SWITCHTRADE_RELAY_REVISION="$(git rev-parse HEAD)"
.relay-venv/bin/python -m uvicorn relay.core_server:create_app --factory \
  --host 0.0.0.0 --port 8788 --workers 1 --no-access-log --log-level warning \
  --no-proxy-headers --ws-max-size 1048832 --ws-max-queue 8 \
  --timeout-graceful-shutdown 10 \
  --ssl-certfile /path/to/fullchain.pem --ssl-keyfile /path/to/private-key.pem
```

Replace certificate paths with existing valid TLS material, or use an existing
trusted TLS/WebSocket reverse proxy. Do not disable certificate verification.
Use Core, not legacy `relay.server`. One worker is required: Pair state is
in-memory; relay restart requires a new Pair. Relay is trusted (hop TLS, not
end-to-end RFU encryption against its operator). This runbook does not deploy
the server or change firewall rules.

In **both** Host and VM PowerShell 7 sessions, set the same real URL:

```powershell
$env:SWITCHTRADE_CORE_RELAY = 'https://relay.example:8788'
Invoke-RestMethod "$env:SWITCHTRADE_CORE_RELAY/core/health"
```

Expect `status: ok`. `127.0.0.1` on different PCs is not a common relay.

## One-time VM preparation (explicit user action)

Have native Windows x64 CPython 3.12 or 3.14 (standard, not free-threaded) and
PowerShell 7 installed first. In the
qualified checkout:

```powershell
git rev-parse HEAD
git status --short
py -3.14 -m venv .gpsp-venv
.\.gpsp-venv\Scripts\python.exe -m pip install --require-hashes -r requirements-gpsp.lock
```

The minimal environment contains websockets 17.0.1, not LDN/WSL dependencies.
Run/doctor never install anything. Do not overwrite an existing user environment;
inspect it first if `.gpsp-venv` already exists.
Use `py -3.12` instead to retain Python 3.12; existing 3.12 environments need no
migration. Changing the system Python does not change an existing venv's Python.
Other minor versions/free-threaded builds are not qualified. The physical Host's
managed WSL and relay stay on their existing Python 3.12; peers do not need
matching Python versions. Windows CI qualifies both supported native versions,
including the actual-process two-room/30-minute test, with separate Python-bound
`gpsp-software-preflight-<version>-<SHA>` evidence artifacts.

In RetroArch, manually load the supported gpSP core and your legitimately owned
game. Choose **Quick Menu → Core Options → Link Cable Connectivity → GBA Wireless Adapter**
(`gpsp_serial = rfu`), save the option manually, and reload content yourself if
that supported frontend requests it. Save the game before any manual reload.
Set the Netplay connection address to **127.0.0.1**, port **55435**. Disable
unrelated Netplay sessions; do not enable a remote command/control interface.
SwitchTrade never starts or closes RetroArch, reloads games, edits settings or
touches saves. Prefer normal speed for the first physical test.

```powershell
.\dev.ps1 doctor --emulator gpsp
```

Doctor checks process/core identity and local port availability. It explicitly
does **not** declare RFU/game readiness. If several RetroArch candidates run,
inspect them and supply the intended `--emulator-pid <PID>`. Query failure is
not “not running”. Never pick a different process automatically.

## First room

Host PC, with its existing managed WSL/radio preparation verified:

```powershell
.\dev.ps1 doctor
.\dev.ps1 sync
.\dev.ps1 run host --log-dir /opt/switchtrade-dev/logs/gpsp-host-01
```

Expect `Pair code: 381742` (example only), then `Waiting for a Group Leader room...`.
Share the current six-digit code privately. On the **Switch**, create the game's
**Group Leader** room; Host automatically reports `Group Leader room detected.`
and waits for its peer. No browser, Ready, Continue, countdown or timing race.

VM, RetroArch/gpSP game already running:

```powershell
.\dev.ps1 run join 381742 --emulator gpsp --log-dir .qualification/physical-gpsp-01
```

Replace the example code. Missing RetroArch fails before Pair admission with an
instruction to start the game. Default log directory above is ignored; inspect
and redact it before sharing. Advanced port/PID selection, only if necessary:

```powershell
.\dev.ps1 run join 381742 --emulator gpsp --emulator-port 55436 --emulator-pid 1234
```

Change RetroArch's saved Netplay target to that same explicit port yourself.
A collision is an error, never an automatic alternate port.

Guest status sequence:

```text
RetroArch and supported gpSP core found.
Connect RetroArch Netplay to 127.0.0.1:55435.
Waiting for the host's room and local Netplay connection...
Local Netplay connected. GBA Wireless Adapter verified.
Choose Join Group in the emulator.
Bridge active.
RFU link established; game-room entry and trade are not yet confirmed.
```

At the `Connect RetroArch...` instruction, manually select **Netplay → Connect**
to the saved local address. Only after **Choose Join Group in the emulator**,
choose **Join Group** in the game. Waiting for either action has no arbitrary
human timeout; cancellation/process/transport/Pair lease failure still ends it.
“Bridge active” on the Guest requires actual RFU child data, not a running PID,
loaded DLL, socket accept or frontend handshake alone.

Verify that the intended Group Leader appears, the intended two players see
each other, and both games progress through the same normal communication
action. Record the visible result and log timestamps. First use disposable
test saves/backups made by the user; software qualification is homebrew-based,
not proof that a real Pokémon trade has already succeeded. Do not overwrite a
valuable save to diagnose a failure.

## Second room and ending

Leave the Group Leader room normally on the Switch. Expect Host
`Generation ended. Pair retained.` and Guest
`Generation ended. Pair and local Netplay retained.`. Keep both commands and
RetroArch running. Do not reconnect Netplay, restart content or re-enter the
code. Create the next Group Leader room; after the new Guest Join Group prompt,
join again and verify a second bidirectional game communication.

Press Ctrl+C once in the owning SwitchTrade console to stop the program. Expect
`SwitchTrade stopped. RetroArch was not closed.` on the VM, then inspect
`$LASTEXITCODE`. RetroArch/game must remain open; no other process is selected
or restarted. Explicit emulator or local-Netplay exit ends the bridge; the user
may run the command again after correcting it. Normal room end is different
from closing the whole client or losing its local transport.

Use `Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 55435` as a read-only
VM check (use the selected port). An owned listener/established connection must
not remain after CLI exit; TCP TIME_WAIT is not a live owned listener. A query
permission error is unknown, not a clean result. Do not terminate by image name.
For Host-owned VIF/TAP/process residue, follow the exact distro and radio-binding
checks in the linked Switch runbook; preserve the pre-existing proven interface.

## Failure evidence and extension boundary

For the paused physical trial, new RFU progress fields and next diagnostic steps,
see [the 2026-09-08 diagnosis handoff](GPSP_PHYSICAL_DIAGNOSIS_20260908.md).
Physical game compatibility is unresolved; do not read software/homebrew evidence
as a completed Pokemon trade.

For the later connected-but-unavailable trial, see
[trial08 NI/Reliable diagnosis](GPSP_JOIN_DIAGNOSIS_20260909.md). It separates
native NI ACKs from gpSP socket ACKs and records the remaining causal uncertainty.
The preceding repair is documented in
[trial10 NI cadence and receipt recovery](GPSP_JOIN_CADENCE_REPAIR_20260910.md).
Its timed software model passed; commercial trade and native tolerance of the
new retry/receipt cadence still require a separately authorized physical trial.
The current [trial11 UNI candidate](GPSP_UNI_TRANSITION_REPAIR_20260914.md)
adds actual clock-change/burst qualification and leaves native closure open.
When copying VM commands, copy only the command inside its code block, never
the PowerShell `PS ...>` prompt or previous error output. Run commands separately.

For the current [trial12 investigation](GPSP_TRIAL12_ANALYSIS_20260917.md),
record the exact time of acceptance, actual room entry, Host-only movement,
then Guest-only movement. Move on open floor, away from chairs/exit tiles;
wait for both screens after each separate action. Stop progression at the
first stall/error: do not retry, interact, or proceed to a trade/save. A
four-minute wait is an unresolved symptom, not normal initialization.
Host `rfu_boundary` now correlates admitted/queued native timestamps, UNI tags,
Reliable sequences and scheduled WK positions with the Guest progress log.
These fields never claim game consumption; preserve both complete logs.

Preserve the **first** error and cleanup status separately. Collect exact branch
SHA, overlay content-id on Host, frontend/core hashes, selected process start
identity, VM networking mode, sanitized commands, both opt-in
`switchtrade-core.log` files and game-action timestamps. Technical code/traceback
requires `--verbose` or `--log-dir`; default errors are short next actions.
Logs can contain private process paths: redact before sharing. Never share Pair
credentials, keys, raw captures or commercial ROM/save/Pokémon data. Unknown or
partial cleanup blocks retry until the exact owned residue is understood.

Next endpoint onboarding is static and capability-based: distinguish frontend
(RetroArch), core (gpSP/mGBA/etc.), and communication (RFU versus wired cable).
Implement `EndpointDriver`/`LocalGeneration` inside its own endpoint package,
register lazily in composition/CLI, and prove its public local interface, roles,
protocol compatibility, cancellation and two-generation cleanup first. Reuse
the RFU converter only where semantics actually match; RFU1 is not a universal
emulator protocol. Relay remains opaque; emulator knowledge stays out of Core.
Do not advertise mGBA/VBA, reverse gpSP origin, or emulator↔emulator capability
before a separately qualified implementation exists. No generic plugin manager,
automatic emulator launcher or placeholder adapter was introduced.
