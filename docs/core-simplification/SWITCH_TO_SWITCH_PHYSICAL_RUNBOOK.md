# Switch ↔ Switch physical test runbook

Prepared for `Simple-Architecture`. This is a procedure to execute **after** the
software closure and its exact-SHA CI are green, not a claim of physical success.
No Switch, USB radio, installed WSL runtime or Internet deployment was operated
while preparing this procedure. Obtain the exact qualified SHA from the final
closure record/report and use that SHA on both PCs and the relay.

## Preconditions and ownership

- Two stock Nintendo Switch consoles with the intended Pokémon FireRed/LeafGreen
  local-communication mode available. Use the game's normal Group Leader/Join
  Group actions; SwitchTrade adds no Ready/Continue/countdown or room browser.
- Two Windows PCs with PowerShell **7**, an existing healthy SwitchTrade-managed
  WSL runtime, its pinned Python dependencies, appropriate kernel/firmware, and
  one supported external USB Wi-Fi radio per PC. PC Internet connectivity must
  use a different network interface. A registry candidate is not a claim of
  physical certification; see `config/wsl-radio-hardware.tsv`.
- The selected USB adapter must already be attached to that PC's exact managed
  distro through the existing installation/USB ownership procedure. Do not use
  an unrelated distro or detach another process's adapter. If attachment or
  provisioning is missing, stop and perform that separately with its owner;
  this runbook does not install/reset WSL or blindly run USB recovery.
- The managed runtime must have the user's legitimately supplied, readable
  `/opt/switchtrade/config/prod.keys`. LDN v3 requires `master_key_12`,
  `aes_kek_generation_source` and `aes_key_generation_source`, each 16 bytes.
  Do not print, upload, copy into the overlay, or commit key material. Software
  tests use synthetic keys only. Never treat a repository file as proof that
  the installed runtime has valid keys.
- One common, reachable, trusted relay, with valid TLS for an Internet test.
  Both PCs must use the same URL. `127.0.0.1` on two PCs means two different
  machines and is **not** a common relay.
- One running SwitchTrade owner per selected adapter. Keep unrelated interfaces,
  TAPs, processes, Pair sessions and installed files intact.

## Common relay (operator, on a separate Linux host)

For deployment/cutover use the canonical [Core relay handoff](../../relay/DEPLOYMENT.md).
The direct-TLS command below is an alternative, not a second concurrent service.

In a checkout of the qualified SHA, using Python 3.12:

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

Replace the certificate paths with the operator's existing valid certificate
and private key; do not use self-signed TLS bypasses. Alternatively, place this
single worker behind an already configured trusted TLS/WebSocket reverse proxy,
binding the backend to loopback. Expose only the intended relay service according
to that host's firewall policy. This document does not deploy or alter a firewall.

Use the **Core** application above, not `relay.server` or the old Room authority.
`GET /core/health` returns `status=ok` plus service/contract/source identity.
Check `source_revision` against the qualified SHA. The Pair store is in-memory:
use one worker; restarting it invalidates Pairs, so both clients must create/join
a new Pair. TLS protects each PC-to-relay hop, not RFU from the trusted relay
operator; this is not an end-to-end-encrypted untrusted relay design.

## Prepare each PC (PowerShell 7, repository directory)

```powershell
git branch --show-current
git rev-parse HEAD
git status --short
.\dev.ps1 doctor
.\dev.ps1 sync
```

Confirm the expected branch/SHA and preserve any unrelated worktree changes.
Doctor verifies the exact registered/owned distro, Python executable and
dependency-file hashes. Sync copies only allowlisted source into an immutable
`/opt/switchtrade-dev/releases/<content-id>` and verifies path-bound hashes
before switching `current`. It does not install packages or copy keys. Record
`git_head`, `content_id` and `dirty` from sync output. Do not bypass a mismatch.

Set the common relay in **both PowerShell sessions** (replace this example):

```powershell
$env:SWITCHTRADE_CORE_RELAY = 'https://relay.example:8788'
Invoke-RestMethod "$env:SWITCHTRADE_CORE_RELAY/core/health"
```

The dev dispatcher forwards this Windows setting explicitly to the Linux CLI;
it does not rely on implicit WSL environment inheritance. An explicit `--relay`
option overrides it. Do not embed passwords/tokens in the URL.

## Host PC

Basic command after the common setting:

```powershell
.\dev.ps1 run host
```

For first-test evidence, use a fresh Linux log directory:

```powershell
.\dev.ps1 run host --relay https://relay.example:8788 --usb-id 0bda:818b --channel 6 --log-dir /opt/switchtrade-dev/logs/physical-host-01
```

Use the actual supported adapter ID on this PC. If exactly one supported adapter
is attached, omission selects it; multiple candidates are rejected rather than
guessed. Host uses Direct **A** (station beside the Group Leader), so its internal
radio gate role is `guest`. This inversion is automatic, not a user role choice.

Expected sequence:

```text
[driver] PASS ...
[health] PASS; ... restored to channel 6
Starting SwitchTrade...
Pair code: 003817                 # example only; use the printed six digits
Pair code expires at: ...
Waiting for a Group Leader room...
```

Now create the native **Group Leader** room on the Host Switch. No synchronized
timing with Guest is required. Then expect:

```text
Group Leader room detected.
Waiting for peer...
Peer connected.
Remote mirror ready.
Bridge active.
```

The last two lines require Guest's physical local readiness. A ten-minute unused
invite expires with `S_PAIR_CODE_EXPIRED`; do not reuse that code. Consuming the
invite does not impose its TTL on the established Pair. Reconnect credentials
have a one-hour new-stream admission deadline, not an ACTIVE idle deadline.

## Guest PC

Use Host's **current exact six digits**, including leading zeros:

```powershell
.\dev.ps1 run join 003817
```

Or, with evidence and explicit settings:

```powershell
.\dev.ps1 run join 003817 --relay https://relay.example:8788 --usb-id 0bda:818b --channel 6 --log-dir /opt/switchtrade-dev/logs/physical-guest-01
```

Guest uses Direct **B**, the mirrored AP. Expected messages:

```text
Starting SwitchTrade...
Connecting with code 003817...
Waiting for the host's Switch...
Peer connected.
Preparing the mirror access point...
Choose Join Group on the Switch when it appears.
Mirror access point and Switch ready.
Bridge active.
```

After the Join Group instruction, select the advertised native room on Guest's
Switch when it appears. The instruction may precede AP creation while Host is
still discovering; wait for the game's room to appear. Human association waiting
has no arbitrary 120/180-second cutoff, but cancellation, transport/lease loss
and real technical failures still terminate safely. Guest may connect before
Host creates the room; Host may create it before Guest connects.

## First functional check

Both consoles must enter the intended native local-link interaction and both
PCs must display `Bridge active.`. That message alone is **not** RFU success.
Verify the two games recognize each other and progress through a normal mutual
interaction (for example, the native communication/trade selection screens).
If testing a trade, use expendable test saves/Pokémon and confirm completion on
both consoles; do not start with valuable save data. No fabricated game commands
are injected by Core. Record the visible result and approximate timestamps.

Failure to progress after Bridge active is a functional failure, even if LDN
association and cleanup succeed. Preserve evidence; do not repeatedly reconnect
or reset the adapter until the first failure and residue are understood.

## Second Generation, same Pair

1. End/leave the first local-link room through the game on the leader side.
2. Both PCs should print `Generation ended. Pair retained.` and return to waiting.
3. Do **not** rerun the CLI, enter a new code, or press an application checkpoint.
4. Create another Group Leader room; on Guest select Join Group when it appears.
5. Both PCs reach a second `Bridge active.` and repeat the actual mutual game
   interaction. Confirm a new Generation in logs, not stale first-session data.

## Failure evidence, Ctrl+C and residue

Press Ctrl+C once in the owning PowerShell session. The lifetime pipe cancels
the owned Linux radio-gate/CLI process group; Core/endpoint cleanup is awaited.
Normal cancellation has no traceback. Unexpected failure or unverified cleanup
is nonzero. The other PC may report `S_PEER_CLOSED`; that is distinct from a
normal generation end, because one client has ended the entire Pair session.

Record `$LASTEXITCODE`. Collect each opt-in `switchtrade-core.log`, the exact
SHA/content-id, command options without the Pair code, timestamps, stable error
codes, and the visible game result. Logs contain radio binding/owned interface
names, Direct gates/elapsed times, cleanup resource states, generation IDs and
Pia counters. They do not dump keys, advertisement bytes, RFU payloads or MACs.
`--verbose` adds technical console traceback; inspect/redact private paths before
sharing it. Pair codes, bearer credentials, keys, raw captures and save/Pokémon
data must not be included in public evidence.

To inspect residue, first read the exact distro name from
`%LOCALAPPDATA%\SwitchTrade\state\active-runtime.json`, then use read-only commands:

```powershell
$runtimeName = (Get-Content "$env:LOCALAPPDATA\SwitchTrade\state\active-runtime.json" -Raw | ConvertFrom-Json).active_runtime
wsl --distribution $runtimeName --user root -- iw dev
wsl --distribution $runtimeName --user root -- ip -j link show
wsl --distribution $runtimeName --user root -- pgrep -af 'switchtrade.core_cli|switchtrade.parent_lifetime'
```

Compare against the exact `st-...`, `ap-...`, `mon-...`, `tap-...` names in that
run's `radio_binding` record. Its created VIFs/TAPs and owned CLI/guardian should
be absent after verified stop; inspect threads only for an observed remaining
owned PID (`ps -T -p <PID>`). The pre-existing proven radio interface is a runtime
baseline, not a generation-created VIF; its continued existence is expected.
Do not delete all interfaces on a PHY, kill by broad process name, remove lock
files blindly, or run `dev.ps1 clean` as radio recovery. Do not publish raw netdev
output containing MACs without redaction.

If cleanup is unknown, `ap_stop_timed_out` is true, or
`DEV_CHILD_CLEANUP_UNVERIFIED` appears, stop. Preserve the owner/PID/PHY/interface
evidence and use the identity-bound recovery procedure; forced process exit is
not proof that the physical radio has been cleaned. Retry only after ownership
and residue are verified. Physical RF timing, chipset/driver behavior and actual
console interoperability remain to be tested by executing this runbook.
