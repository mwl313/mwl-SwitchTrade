# Switch ↔ RetroArch/gpSP: VMware Windows 11 physical test

**2026-09-09: advertisement/native WA repair; final qualification is still required.**
See [repair evidence and support limits](GPSP_ADVERTISEMENT_REPAIR_20260909.md).
Use an empty English FR/LG Direct Corner **Trade** Group Leader room. Other
activities and unqualified nonzero discovery fields fail closed; do not test
battle/Mystery Gift as if they were supported by this repair.

Execute only after `GPSP_ACCEPTANCE.final.json` and both platform jobs for the
same literal SHA are successful. This document is preparation, not a Pokémon
trade result. Keep `main` and existing work intact; use the qualified feature
branch SHA in all three checkouts. Do not merge unqualified changes.

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
When copying VM commands, copy only the command inside its code block, never
the PowerShell `PS ...>` prompt or previous error output. Run commands separately.

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
