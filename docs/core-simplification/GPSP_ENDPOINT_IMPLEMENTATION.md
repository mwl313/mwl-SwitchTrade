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
| P1 | Borrowed-process probe, local listener, hardened Netplay and RFU translator | NOT_STARTED |
| P2 | Real Core endpoint, lifecycle, reconnect and next Generation | NOT_STARTED |
| P3 | Native dev/CLI routing, diagnostics and user messages | NOT_STARTED |
| P4 | Full integration, two Generations, long waits/soak, CI and VMware runbook | NOT_STARTED |

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
  (displayed `v1.0-74db5e6`, netpacket protocol `gpSP v1.0`).
- Homebrew SHA256:
  `cfb0a21e1504931d7589a30b125ff3bbdf9211116a7bea690cfecadf031a2720`.
  Two independent builds agree; provenance is beside the fixture.
- Passing local raw evidence: `.qualification/gpsp-p0-attach-10/report.json`.
  Earlier probes are preserved locally, not overwritten. Probe 02's test-profile
  isolation failure and its retained options-file residue are MTA-QA-025.
- The isolated config records RFU mode before test game startup. The product
  will only observe the user's independently configured frontend.

This proves attach-only feasibility, not real Core integration, a 30-minute
soak, Windows/Ubuntu final-SHA CI, VMware or a physical Pokemon trade. P1-P4
remain open. New stock versions require another binary-bound qualification.

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
