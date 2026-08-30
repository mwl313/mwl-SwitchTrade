# M7 two-PC distributed qualification handoff

> Status: coordination contract; the physical distributed run is **not executable yet**.
> PC A: the computer currently hosting this repository and Codex task.
> PC B: the other computer and its separate Codex task.
> Branch: `codex/abcd-orchestration-rework`.
> Candidate installer: GitHub prerelease `v0.2.6-beta.2`, release ID
> `abcd-m7-pcb-586d123`.
> Supported qualification radio: RTL8192EU `0bda:818b` only.

This is the single handoff that both Codex tasks must follow for the first physical two-PC ABC+D
qualification. PC labels never change. A/B connection roles do change during the reversed-role run.

## 1. Current truth

- PC B's returned handoff and three raw reports were reviewed on PC A. Cold P0, Direct A0-A9, Direct
  B2-B10, common runtime integrity, and verified cleanup are accepted.
- PC A now has installed/active release `abcd-m7-pcb-586d123`, a locally resolved Windows hardware
  selection, and cold P0 run `05a56402-2877-4847-9233-0925bef16d00` passed with verified cleanup.
  Its post-run Linux USB/interface/PHY probe is absent and Windows reports the adapter detached.
- Commit `20707f625ddd381eb548e3ebf31daecda8bc878b` contains the coordinator, C2, D, and independent
  P0/A/B harnesses, but it contains no supported two-PC physical CLI entrypoint.
- Therefore neither Codex may start a distributed test, combine the independent Direct A and Direct B
  commands, use `pytest` as physical evidence, or use the legacy GUI as a substitute.

The common machine preflight is ready. The remaining stop condition is the missing canonical
distributed runner, not an unqualified PC A or PC B radio.

The next code checkpoint must add one canonical distributed qualification CLI. The commit that adds
it must replace `DISTRIBUTED_HARNESS_COMMIT=TBD` in this document. Both PCs must then detach at that
exact commit. Local, uncommitted, or improvised runner changes are not acceptance evidence.

## 2. Scope

This campaign proves the first physical M7 boundary:

1. both installed PCs acquire their own exact radio safely;
2. the room-side reaches current-generation `A_READY`;
3. the AP-side reaches current-generation `B_READY`;
4. the real relay admits the same attempt and produces `C_BRIDGE_READY`;
5. real bidirectional RFU produces `C_RFU_ACTIVE`;
6. each requested action enters D without losing the frozen functional outcome;
7. both sides reach the D6 terminal barrier and independently verify D7-D11 cleanup.

It does not certify the GUI, production diagnostics migration, repeated trades, save behavior, or the
final release. Those remain M8-M10 work.

## 3. Permanent machine ownership and dynamic roles

| Item | PC A | PC B |
| --- | --- | --- |
| Permanent identity | This computer | Other computer |
| Codex responsibility | Test coordinator and combined evidence owner | Responder and local evidence owner |
| Physical ownership | Its own Switch and RTL8192EU | Its own Switch and RTL8192EU |
| Run 1 role | `A_ROOM_JOINER` | `B_AP_HOST` |
| Run 1 Switch action | `Become Leader` and remain hosting | `Join Group` only after AP-ready instruction |
| Run 2 role | `B_AP_HOST` | `A_ROOM_JOINER` |
| Run 2 Switch action | `Join Group` only after AP-ready instruction | `Become Leader` and remain hosting |

No adapter identity, bus ID, WSL distribution, state directory, or result file may be copied between
machines. Only the exact source commit, release ID, test ID, non-secret stage acknowledgements, and
redacted evidence are shared.

## 4. Required implementation checkpoint

PC A Codex owns this step. PC B Codex waits at preflight.

The canonical runner must be a thin CLI over the existing production modules, not a second
orchestration stack. It must:

- use `ConnectionCoordinator`, the production relay authority/client, P0 lease, Direct A/B stages,
  C2 bridge, measured D control, and D7-D11 release code;
- accept an explicit side role and a one-time invitation created through normal relay APIs;
- bind run ID, attempt ID, seat, role, source/release identity, endpoint launch nonce, PID, and C2
  generation before accepting readiness;
- expose explicit `stop`, `end`, `leave`, and `close` actions without calling the legacy GUI/control
  orchestration;
- print bounded structured status and one redacted terminal JSON report;
- preserve the first functional failure independently from cleanup;
- refuse a second launch, stale invitation, mismatched release/source, active cleanup guard, or changed
  adapter;
- recover the same run after interruption and make all cleanup idempotent.

The implementation commit must also add automated identity, pairing, polling, cancellation, restart,
and cleanup tests. PC A Codex must push that commit and update this document with:

```text
DISTRIBUTED_HARNESS_COMMIT=TBD
PC_A_COMMAND=TBD
PC_B_COMMAND=TBD
```

Until all three values are real and committed, both Codex tasks must report `BLOCKED: HARNESS_ABSENT`.

## 5. Common preflight after the harness checkpoint exists

Run from a normal, non-elevated PowerShell on each PC. Do not discard local work; use a clean clone or
worktree when necessary.

```powershell
git fetch origin codex/abcd-orchestration-rework
git switch --detach <DISTRIBUTED_HARNESS_COMMIT>
git status --short
git rev-parse HEAD

$manifestPath = Join-Path $env:LOCALAPPDATA 'Programs\SwitchTrade\release-manifest.json'
$activePath = Join-Path $env:LOCALAPPDATA 'SwitchTrade\state\active-runtime.json'
$selectionPath = Join-Path $env:LOCALAPPDATA 'SwitchTrade\runtime\hardware-selection.json'
$manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
$active = Get-Content -Raw -LiteralPath $activePath | ConvertFrom-Json
$selection = Get-Content -Raw -LiteralPath $selectionPath | ConvertFrom-Json

if ($manifest.release_id -ne 'abcd-m7-pcb-586d123') { throw 'Wrong installed release' }
if ($selection.usb_id -ne '0bda:818b') { throw 'Wrong adapter profile' }
wsl.exe -d $active.active_runtime -u root -- cat /opt/switchtrade/.switchtrade-release.json
usbipd state

$health = Invoke-RestMethod 'https://relay.pangyostonefist.org/health'
if ($health.status -ne 'ready' -or $health.room_contract -ne 'room-control.v1' -or
    $health.rfu_contracts -notcontains 'rfu-tunnel.v2') { throw 'Relay contract unavailable' }
$health | Select-Object status,room_contract,rfu_contracts
```

Preflight passes only when:

- `git status --short` is empty and both PCs report the same exact source SHA;
- both Windows and WSL release markers report `abcd-m7-pcb-586d123`;
- each selection file was created locally and resolves one shared `0bda:818b` device;
- SwitchTrade GUI is fully closed;
- no endpoint, temporary interface/PHY, active connection run, diagnostic recovery record, or stale
  USB attachment remains;
- the relay advertises `room-control.v1` and `rfu-tunnel.v2`.

PC A must install `v0.2.6-beta.2`, select/authorize its local adapter, and pass the same-candidate cold
P0 before it may report preflight ready. If any preflight fails, do not repair by deleting WSL state.

## 6. Codex-to-Codex synchronization protocol

The human may relay these messages between tasks. They deliberately contain no credentials.

Each side first sends:

```text
M7/PRECHECK/PASS
pc: PC_A | PC_B
source_sha: <full SHA>
release_id: abcd-m7-pcb-586d123
runtime_release_id: abcd-m7-pcb-586d123
adapter_profile: 0bda:818b
local_p0: passed
cleanup_guard: clear
residue: clean
```

PC A sends an arm message only after both prechecks match:

```text
M7/ARM
test_id: <UUID>
campaign_case: D-PHYS-1 | D-PHYS-2 | D-ACTION-STOP | D-ACTION-LEAVE
pc_a_role: A_ROOM_JOINER | B_AP_HOST
pc_b_role: B_AP_HOST | A_ROOM_JOINER
source_sha: <full SHA>
release_id: abcd-m7-pcb-586d123
```

PC B replies `M7/ARM/ACK <test_id>`. PC A then creates the one-time invitation through the committed
runner and transfers it only through the runner's intended transient mechanism. Never paste member
tokens, room passcodes, or credentials into chat, logs, this document, or committed files.

Both sides report only these stage messages:

```text
M7/STAGE <test_id> <PC_A|PC_B> A_READY|B_READY|C_BRIDGE_READY|C_RFU_ACTIVE
M7/CLEANUP <test_id> <PC_A|PC_B> D5_SIDE_QUIESCENT|D6_TWO_SIDE_TERMINAL|D11_VERIFIED
M7/FAIL <test_id> <PC_A|PC_B> <stable_code> <last_passed_gate>
```

No side advances because of elapsed time or a screenshot. Structured current-generation evidence from
both sides is authoritative.

## 7. Physical campaign

Run one case at a time. Review terminal cleanup before starting the next case.

### D-PHYS-1 — fixed roles, normal End

1. PC A starts the committed room-side command and waits for the instruction to operate its Switch.
2. The Switch beside PC A selects `Become Leader` and remains hosting.
3. PC B starts the committed AP-side command.
4. Only after PC B reports its AP-started checkpoint does its Switch select `Join Group`.
5. Wait for both `A_READY` and `B_READY`, then `C_BRIDGE_READY` and real bidirectional
   `C_RFU_ACTIVE`.
6. PC A requests the runner's explicit `end` action.
7. Both sides must report D5, the same D6 barrier generation, and verified D11.

### D-PHYS-2 — reversed roles, normal Close

Repeat with PC A as `B_AP_HOST` and PC B as `A_ROOM_JOINER`. After `C_RFU_ACTIVE`, the authoritative
room owner requests the runner's explicit `close` action. Both sides again require D5/D6/D11.

### D-ACTION-STOP and D-ACTION-LEAVE

Use fresh rooms, credentials, attempts, nonces, generations, endpoints, and state directories. Repeat
the shortest successful connection to `C_RFU_ACTIVE`, then request `stop` in one case and `leave` in
the other. Neither action passes if it bypasses D, changes the frozen functional outcome, or leaves the
peer unable to reach a truthful terminal result.

## 8. Immediate stop conditions

Both Codex tasks stop new work and preserve evidence when any of these occurs:

- different source SHA, release ID, runtime marker, attempt, role lock, or C2 generation;
- a second endpoint or adapter attachment;
- stale/duplicate readiness changes the stage;
- the GUI launches or controls the session;
- one side reports cleanup `failed` or `unknown`;
- the exact adapter cannot be proven detached from WSL after D10;
- endpoint, interface, PHY, relay room, credential, lock, or recovery residue remains;
- a command would require manual WSL unregister/delete, raw capture, or credential disclosure.

Do not start a new run to hide a failed cleanup. Retry only the same committed recovery path.

## 9. Pass criteria

Each campaign case passes only when all are true:

- one launch and one endpoint per side;
- complementary current-generation A/B readiness for one attempt;
- `C_BRIDGE_READY` followed by real bidirectional `C_RFU_ACTIVE`;
- functional outcome frozen before cleanup;
- both authenticated D5 reports admitted to the same D6 barrier;
- D7-D11 are ordered and both local cleanups are `verified`;
- relay authority has no live/admitted attempt or active member credential for the test;
- neither PC has an orphan process, interface, PHY, lock, recovery record, or unintended USB ownership.

A Switch UI message, AP visibility, room entry, or one-sided readiness is not a pass.

## 10. Evidence returned by each Codex

Return one redacted block per case:

```text
test_id:
campaign_case:
pc:
source_sha:
release_id:
local_role:
run_id:
attempt_id:
functional_status:
cleanup_status:
last_passed_gate:
a_ready_generation:
b_ready_generation:
c_bridge_generation:
rfu_bidirectional: true | false
d6_barrier_generation:
d11_verified: true | false
launch_count:
endpoint_count:
residue_check: clean | details
primary_failure_code: none | CODE
report_path:
```

Do not include MAC addresses, trainer/Pokémon data, packet bytes, passcodes, member tokens, reconnect
tokens, or credentials. PC A Codex owns the combined comparison and records mismatches rather than
normalizing them away.

## 11. Exit and next milestone

M7 physical qualification can close only after PC B local evidence is reviewed, PC A is brought to the
same candidate, all four campaign cases pass, and the relay operator confirms zero orphan state.
After that, proceed to M8: route production diagnostics through the new coordinator. Do not route the
normal GUI through ABC+D until the separate M9 cutover.
