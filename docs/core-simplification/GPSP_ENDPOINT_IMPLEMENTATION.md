# gpSP attach-only endpoint implementation

## Authority and baseline

This implements the user's approved attach-only plan, not the legacy emulator
launcher/Room workflow. Implementation branch: `codex/gpsp-endpoint`.
Local and remote Simple-Architecture baseline:
`5f27ea95c7d39fa8537df4ee7606244e94bae471`.
Preserved remote main: `950aa778d9b1cc7a26168ea7b1e2348848cb45ee`.
Selective reuse source: `codex/emulator-endpoint` at
`fbd2776d7f7a52f24d25ba4d7bc1196e7210ca2f`.

## Product contract

- Users start RetroArch, load gpSP/game, configure GBA Wireless Adapter, and
  connect the frontend to the local Netplay listener themselves.
- SwitchTrade never launches/stops/resets the emulator, loads content, changes
  its settings/saves, injects code, or takes ownership of the user's process.
- `dev.ps1 run join CODE --emulator gpsp` and `doctor --emulator gpsp` run native
  Windows Python, without WSL/radio/USB preparation. Existing Switch commands stay.
- Default local listener: `127.0.0.1:55435`; explicit `--emulator-port` overrides.
  Ambiguous running processes require `--emulator-pid`. Unknown is not absent.
- Process identity is not readiness: validate the actual selected process's
  local connection, supported core/protocol handshake, and RFU separately.
- No arbitrary human-wait deadline. Cancellation, actual transport failures,
  process disappearance and existing Pair lease rules remain effective.
- First supported pairing: Switch origin/Group Leader to gpSP mirror/Join Group.
- Normal Generation close preserves Pair, frontend process and healthy local
  Netplay session; retire all generation-bound RFU/ACK/queue state first.
- On application stop, release SwitchTrade-owned sockets/tasks only. Preserve
  first functional failure and secondary cleanup evidence; unknown cleanup blocks.

## Extension boundary

Keep the existing EndpointDriver/LocalGeneration and opaque Core wire contracts.
Separate frontend observation/connection from generation-scoped RFU conversion.
Lazy composition registration selects endpoint, native/WSL runtime and capability.
Do not import Switch/LDN dependencies from the native gpSP path or generic package.
Future mGBA/VBA adapters must prove their own frontend/core/link interfaces and
roles; RFU1 and wired Link Cable are not universal emulator protocols. Do not add
unsupported capabilities or placeholder implementations. Relay remains opaque.

## Sequential acceptance ledger

| Packet | Scope | State |
| --- | --- | --- |
| P0 | Stock runtime identity; attach/exchange/detach/reattach without game reload/reset | PASS (local Windows; not full integration) |
| P1 | Borrowed-process probe, local listener, hardened Netplay and RFU translator | PASS (packet scope; local Windows) |
| P2 | Real Core endpoint, lifecycle, reconnect and next Generation | PASS (packet scope; local Windows) |
| P3 | Native dev/CLI routing, diagnostics and user messages | PASS (packet scope; local Windows) |
| P4 | Full integration, two Generations, long waits/soak, CI and VMware runbook | IN_PROGRESS; final mandatory real-process CI not yet attested |

P0 is a hard gate: a stock compatibility failure must be recorded and reported,
not replaced with automatic launch/reset or an unqualified implementation.

### P0 evidence (2026-09-08)

`tools/gpsp_qualification/p0_attach.py` uses a non-displayed, harness-owned Windows
desktop and the stock frontend's public menu key events. No network command
server, memory read/write, process injection, `--connect`, content reload or
emulator reset is used. Product code does not import this launcher/controller.
The real homebrew sends RAM round 1, verifies a host response, ends its RFU link,
and sends round 2 after local Netplay detach/reattach on the same process. Both
directions and rounds passed; both connections, process handle and desktop
closed. The original runtime tree's metadata remained unchanged on the passing
run. The test-owned process exits only after the full continuity assertion.

- RetroArch 1.22.2 executable SHA256:
  `81c11b6f24932bf7918f05eee8928035bff3887335fd2a081507c75e9d94d06a`.
- Stock gpSP DLL SHA256:
  `c84f619c1077a7fbae84c385df752fbeb867d301880400add7cce6a380dbd516`
  (displayed `v1.1.0-74db5e5`, netpacket protocol `gpSP v1.0`; label corrected
  from the physical screenshot, binary hash unchanged).
- Homebrew SHA256:
  `cfb0a21e1504931d7589a30b125ff3bbdf9211116a7bea690cfecadf031a2720`.
  Two independent builds agree; provenance is beside the fixture.
- Passing local raw evidence: `.qualification/gpsp-p0-attach-10/report.json`.
  Earlier probes are preserved locally, not overwritten. Probe 02's test-profile
  isolation failure and its retained options-file residue are MTA-QA-025.
- The isolated config records RFU mode before test game startup. The product
  will only observe the user's independently configured frontend.

This proves attach-only feasibility, not real Core integration, a 30-minute
soak, Windows/Ubuntu final-SHA CI, VMware or a physical Pokemon trade.
New stock versions require another binary-bound qualification.

### P1 evidence (2026-09-08)

The selected RFU converter and stock wire layout are ported under
`switchtrade/endpoints/retroarch_gpsp/`. No legacy Room/C2, launcher, settings
writer or installer is imported. Product observation uses only standard-library
Windows read-only APIs: PID/executable/start FILETIME, loaded gpSP module/hash,
and the accepted loopback socket's TCP owner tuple. No process termination or
emulator control API exists on the observer. Query failure is never absence.

`LocalNetplay` keeps a cancellable unbounded human accept wait, a separate bounded
technical handshake, bounded incremental reads/queues, observation of process
exit/core unload, and one sticky close result. It supports an ordered Netplay
PING/PONG barrier; this is explicitly not proof of game RFU readiness. The RFU
converter validates all flags before duplicate lookup, retains its first error,
rejects reserved header bits, and cannot partially reset itself for a new
Generation. A fresh converter is required for new ACK/timestamp/queue state.

- 52 focused fixture/process/socket/converter/agent-context tests pass, no skips.
- Actual stock process + production observer/TCP owner check/Netplay handshake
  and barrier + two RFU exchanges across local detach/reattach pass.
  Sanitized result: `GPSP_P1_EVIDENCE.json`; local raw evidence:
  `.qualification/gpsp-p1-local-05/`.
- Stock v7 details verified against the pinned RetroArch 1.22.2 source and actual
  process: client header word 3 is the highest supported protocol, word 4 the
  lowest; fixed INFO strings are NUL-terminated, not necessarily zero-padded.
- Only the test-owned fixture/runtime is launched/configured/closed by the
  separate qualification harness. Original runtime metadata is unchanged in
  passing runs, and reader/observer/connection/process/desktop resources close.

Remaining P2-P4 gates include generation retirement on a retained local Netplay
session, stale RFU rejection and game-versus-frontend lifetime separation;
actual Core/Relay/Switch stack integration; CLI/native routing and truthful RFU
mode/readiness diagnostics; >180-second waits, 30-minute process soak, full tests,
same-SHA Windows/Ubuntu CI and the VMware runbook. No final qualification claim.

### P2 evidence (2026-09-08)

`RetroArchGpspEndpointDriver` now owns the retained local connection; each
`GpspGeneration` owns a fresh converter, queues, ACK/timestamp state and RFU IDs.
Accept returns before game RFU ACK; the normal Core activation starts metadata
and advertisements. `wait_link_ready()` is separate and requires actual gpSP
child data. A normal RFU disconnect drains its final Core frame before the
Generation closes. Cleanup sends CONNECT_NACK/DISCONNECT and requires the stock
ordered PING/PONG barrier. Unknown/failed cleanup stays dirty on repeated close.
Retired device IDs are not reused on that frontend connection; old requests are
rejected, old data is discarded, and contradictory new/old connection order fails.

Core has only generic optional lifecycle hooks: observe a retained driver's
`wait_failed()` even without a Generation, and `abort_opening()` without closing
its healthy local connection. Existing drivers retain their close/prepare fallback.
`GenerationEnded` from the local receive pump now means normal ordered completion.
No gpSP/RetroArch imports or protocol parsing were added to Core/Relay.

- Real stock RetroArch/gpSP + native identity/TCP observation + new driver and
  converter + both CoreSupervisors/WireClients + real Uvicorn/WebSocket relay:
  two bidirectional homebrew exchanges passed on the same Pair/process/local
  Netplay session, with one manual Netplay connection and RAM counters 1 then 2.
  Local raw evidence: `.qualification/gpsp-p2-core-03/report.json`.
  The opposite Switch local packet boundary is **modeled in this P2 test**;
  this is not the required P4 Direct A/StageSession/TunnelSim proof.
- 101 focused endpoint/process/wire/converter/Core/lifecycle/context tests pass.
  Coverage includes opening transport loss, peer close while local Netplay is
  pending, observation during peer wait, repeated cleanup cancellation, stale
  RFU IDs and two Generations through the actual relay with a modeled gpSP peer.
- The disabled-setting negative stock probe connected Netplay and answered its
  barrier but emitted no RFU response. Silence is not labeled game readiness.
  A live non-host RFU dispatcher answers a connection probe with NACK before
  human game input is needed. No RFU response is reported as mode **unproven**,
  not a timeout on the user's game action; ambiguous cleanup remains blocked.
- Wrong in-game Host role is rejected after retiring only the probe-created RFU
  slot. The actual stock host fixture accepted a second request on the same
  local connection after DISCONNECT/barrier; it would ignore that request if
  the old slot remained. `.qualification/gpsp-host-role-01/report.json` passed.
  Host probe fixture SHA256:
  `48bfc8c0d31a06f80644632739d65897a1263dff9f634d5610fc8e084ef5da0c`.
- Source runtime metadata remained unchanged; owned sockets, harness thread,
  test process handle and private desktop closed. Product code never launched,
  reset or terminated the frontend or wrote its configuration/content/saves.

P3/P4 remain open: lazy composition/native dev/CLI, final actual Switch-side path,
long human waits/30-minute process soak, complete acceptance and full pytest,
same-final-SHA Windows/Ubuntu CI, and the VMware physical test runbook.
No final software-ready or physical-success claim is made at P2.

### P3 evidence and native use (2026-09-08)

The real `dev.ps1` dispatches `join CODE --emulator gpsp` and
`doctor --emulator gpsp` to native Windows Python before any WSL/radio/runtime
lookup. Switch host/join keep their existing radio-gated route. gpSP rejects
Switch-only options, unsupported emulator names, invalid PID/port and Host role.
Python composition and CLI import Switch/LDN dependencies only when selected;
a fresh minimal native environment imports/constructs gpSP without them.

Prepare explicitly in PowerShell 7 with native 64-bit Python 3.12 already installed:

```powershell
py -3.12 -m venv .gpsp-venv
.\.gpsp-venv\Scripts\python.exe -m pip install --require-hashes -r requirements-gpsp.lock
.\dev.ps1 doctor --emulator gpsp
.\dev.ps1 run join 381742 --emulator gpsp
```

The native lock contains only `websockets==17.0.1` with official PyPI wheel
SHA256s; no LDN/WSL/installer dependency. Run and doctor do not install anything.
`SWITCHTRADE_NATIVE_PYTHON` is an explicit advanced interpreter override and is
validated against the same native Python/dependency contract.

Before running: manually start the qualified RetroArch/gpSP game and apply its
GBA Wireless Adapter setting; save/reload manually if the frontend requires it.
Then join the Pair and manually connect Netplay to `127.0.0.1:55435`, not the
Internet relay. `--emulator-port` changes that exact local port; collision fails.
Use `--emulator-pid` only to select among multiple running candidates.

The CLI checks the process/bind before consuming the Pair code, prints the local
Netplay target, waits for the Host's offer, and tells the user when to choose
Join Group. `Bridge active.` is withheld until actual gpSP child data proves its
RFU handshake completed. Normal room end retains Pair/local Netplay; Ctrl+C
uses the existing owned parent-pipe cancellation path, never process-name kills.
Doctor explicitly states that its process/core/port check is not RFU/game proof.
Ordinary errors are short actions; stable codes/tracebacks go only to requested
verbose/file logs. The product never manages the user's emulator/content/save.

- 88 focused native CLI/PowerShell/Switch CLI/boundary/endpoint tests pass.
  Existing real Windows Ctrl+C -> CLI -> StageSession cleanup still passes.
- `.qualification/gpsp-p3-native-doctor-01/` runs actual PowerShell/dev/doctor
  against the harness-owned stock process using default `.gpsp-venv` containing
  only pip and websockets. Doctor exits zero without claiming RFU readiness.
  Subsequent real-Core/stock two-Generation P2 exchange still passes, all owned
  handles/sockets/desktop close, and original runtime metadata is unchanged.
- P4 remains required: actual **join** CLI and real Direct A/StageSession/LDN/
  TunnelSim on the opposite side, long waits/soak, full tests and final-SHA CI.
  The P3 doctor result does not stand in for that final full-path qualification.

### P4 qualification implementation

The short full-path local probe (`.qualification/gpsp-p4-full-02`) passes two
Generations through actual native `dev.ps1 run join`, CLI, WireClient/Core/relay,
Switch driver/Direct A/StageSession/LDN/Pia/Reliable/TunnelSim and stock gpSP.
Only Linux radio/kernel primitives, synthetic keys and physical game input are
substituted. The physical-console substitute itself uses real Direct B and
TunnelSim. No production CoreTunnelAdapter send/poll shortcut is used.
The native process uses only the dedicated minimal Python environment.

The separate qualification homebrew waits for a public Start input, exchanges
round/sequence-tagged RFU payloads until the physical-input radio is closed,
then accepts a second room in the same RAM. It independently rebuilds to
`91168322aa3b7d1f73784c3b1c152bd064b02001f5460d46d6b0466f3f745ad4`.
It contains no commercial content. The user-owned product cannot load it.

First failed full probe retained `OSError: closed` from a test-owned ticker
outliving its virtual radio; MTA-QA-026 records the first failure, verified
residue and corrected cancel/join-before-radio-stop ordering. It is not a
product or physical qualification pass. MTA-QA-025's earlier options-file
residue remains retained; all passing subsequent original-tree checks are clean.

Final Windows CI runs both real attach/detach continuity and full-path two-room
qualification, including two >180s waits and >=1800s sustained traffic. Resource
counters are read-only process statistics, not emulator memory inspection:
post-warmup handle growth <=8 and private-memory growth <=16MiB are explicit
finite-soak bounds, not a proof of unlimited operation. No required actual
process test can be skipped into a passing closure. Ubuntu runs the shared
Core/protocol/Switch regression. See `GPSP_ACCEPTANCE.json` G01–G24 and
[the VMware test runbook](GPSP_VMWARE_RUNBOOK.md). Existing ABC I01–I18/T01–T44
remain required and generate a separate exact-SHA artifact after both jobs.

This tracked document does not claim final completion. Only the generated
`GPSP_ACCEPTANCE.final.json` after validated real-process reports and both
exact-SHA CI jobs can close P4. Raw frontend/native logs and private paths stay
local/ignored; CI uploads only sanitized successful report JSON.

## Required final evidence

- Real dev/CLI, CoreSupervisor, WireClient, WebSocket relay, gpSP adapter, stock
  RetroArch/gpSP and licensed homebrew. Real Switch driver/Direct A/StageSession/
  LDN/TunnelSim on the opposite side with only OS/hardware/game-input substitutes.
- Same process and Pair for two real RFU Generations; attach/detach preservation;
  stale/invalid/partial/overflow frames; waiting/opening/active cancellation/loss;
  >180-second human wait and 30-minute bounded real-process soak.
- No false absence on process query failure, wrong core/version, PID reuse,
  multiple candidates or foreign socket owner. No emulator/settings/save mutation.
- Full pytest and Windows + Ubuntu CI at the same final SHA; real-process tests
  mandatory, not silently skipped. Preserve ABC evidence and add separate gpSP
  acceptance, supported binary hashes, commits, results and remaining physical risks.
- VMware Windows 11 runbook: physical host Switch/WSL, native guest emulator,
  common relay, setup, exact commands, game actions, next room, logs and cleanup.

Physical Switch testing, WSL/VM installation/reset, deployment, mGBA/VBA
implementation and main/release changes are excluded. Only claim software-ready
after every software gate passes; never claim an actual Pokemon trade was proven.
