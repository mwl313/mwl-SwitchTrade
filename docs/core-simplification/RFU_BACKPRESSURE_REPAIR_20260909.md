# Trade RFU backpressure repair

Branch: `codex/gpsp-endpoint`. Clean local/remote implementation base:
`865eb54aea0e65a0f40fd5203e24ad5caea7e30a`.
Scope: the latest physical trade trial's first RFU backlog failure; no battle
support, hardware operation, emulator/core installation or relay deployment.

## Diagnosis and limits

The Host had accepted the local Switch room and forwarded initial RFU traffic.
Its first exception was `RFU receive backlog overflow`, not the Guest's later
peer-close error. A standalone reproduction showed the same overflow with a
progressing, slower Reliable ACK cadence. This establishes a software admission
defect; it does not establish the physical radio's exact ACK timing or identify
the first cause of earlier trials whose Host error was not preserved.

Room listing and `Bridge active` are intermediate evidence. Complete NI/game
compatibility exchange, party selection, trade completion and saved results
remain unproven on real Switch/gpSP. Fixing this failure is necessary, not a
guarantee that it was the final commercial-game interoperability defect.

## Implementation

- TunnelSim polls only the free space in its bounded pending queue. The existing
  Reliable window and retransmission scheduler consume it without read-ahead
  overflow. No queue/window enlargement or RFU packet dropping.
- CoreTunnelAdapter waits asynchronously for capacity, outside the radio thread.
  Waiting producers remain ordered; cancellation, close, seal, failure and
  epoch replacement interrupt admission. A waiter cannot bind to a reset link.
- The opposite direction does not ACK or remember a local Reliable frame until
  it is admitted. Opaque tunnel input is contiguous; gaps wait for retransmission
  instead of forwarding later timestamps first. Pure ACK/control receive still
  progresses when the application queue is full. The legacy game engine retains
  its original fragment-oriented receive behavior.
- gpSP generation output and local Netplay input use bounded producer waiting.
  A generation close wakes blocked producers and drains retired frontend traffic
  so it cannot hide the ordered cleanup barrier response. The same Pair and
  healthy local Netplay connection may then receive a new generation.
- `switch_rfu_progress` logs counts/window positions at five-second intervals.
  No advertisements, RFU payloads, game saves, keys or device identities are added.
- The stock full-path homebrew probe no longer adds an artificial half-second
  delay after each RFU exchange. The actual game's RFU request/reply paces it.
  This increases regression workload; it is still not a commercial-game test.

Core/Relay remain emulator-neutral and RFU-opaque. No packet format, endpoint
capability, deployment configuration, Python dependency or battle gate changed.
This shared Switch boundary also protects Switch-to-Switch traffic under pressure.

## Verification

- Before repair, nine admission/slow-ACK regression cases failed. After repair,
  both parent/child TunnelSim modes transmit 1,600 frames in order with bounded
  queues under progressing slow ACKs; cancellation and epoch retirement are tested.
- A full endpoint-path regression uses real WebSocket relay, WireClient,
  CoreSupervisor, Switch/gpSP drivers, Direct A/B, StageSession, LDN encryption,
  TunnelSim and CoreTunnelAdapter. Only OS/radio primitives and console/frontend
  inputs are modeled. Each of two generations transmits 1,024 child frames
  through a 100 ms modeled console cadence, fills the bounded queues, waits for
  admission and verifies exact ordered delivery plus reverse data/ACKs.
  Actual LDN room closure returns to the same Pair/local Netplay connection.
- Additional tests cover full local Netplay/endpoint queues, no false ACK or
  deduplication, gaps, process failure, cleanup under pressure, sticky cleanup,
  and stale data isolation on the next generation.
- Local Python3.12.14 full pytest: **1,047 passed, 6 skipped**, 787.39 seconds.
  Skips are existing Linux-only checks; Ubuntu CI owns their platform coverage.
  This includes the new full endpoint pressure regression and existing real CLI
  Switch/Switch two-generation, reconnect, cleanup and >180-second wait coverage.
- Python3.14.7 focused: **106 passed**, 60.37 seconds, including the new pressure
  path. Incident/index checks: **5 passed**; whitespace and compileall passed.
- Same-SHA Windows/Ubuntu CI, including actual stock homebrew/30-minute soak,
  must complete on the pushed commit. Do not infer those results from local
  tests. Exact pushed SHA, any short actual-process check and CI status are
  reported in the task handoff. Base-SHA process reports are historical only.

## Next physical trade trial (only on user request)

1. Ensure both previous commands have exited. Update Host and VM to this feature
   branch and verify identical SHA with `git rev-parse HEAD`. No reinstallation
   or relay redeployment is needed for these client-only changes.
2. Revalidate the exact Host USB/radio ownership through the normal gate, then
   start Host with a fresh log directory. Do not reuse any previous Pair code.
3. VM: start the supported RetroArch/gpSP game manually. In its repository,
   replace `<NEW_CODE>` below with the fresh six-digit Host code:

   ```powershell
   .\dev.ps1 doctor --emulator gpsp
   .\dev.ps1 run join <NEW_CODE> --emulator gpsp --relay https://relay.pangyostonefist.org --log-dir .qualification/physical-gpsp-07
   ```

   Connect local Netplay and choose Join Group after the prompt.
4. First verify room selection and sustained connection. Then verify actual
   trade/return-to-game/save state on both games. Finally end the room normally
   and try a second trade generation without restarting Pair or RetroArch.
5. On the first failure stop and retain both logs through cleanup. Correlate
   `switch_rfu_progress`, `gpsp_rfu_progress`, `wire_first_failure` and
   `generation_exit`, with action times and game screenshots. No automatic retry,
   raw capture or save collection is enabled. Battle testing remains separate.
