# Trial12: delayed room entry and in-room communication error

Status: **native integration unresolved; diagnostic candidate only**.
Source baseline: `codex/gpsp-endpoint` at
`560535874f681c7194d3425bcd6ae51dff63dcf0` (local and remote checked).
The VM's exact source SHA was not independently recorded in its supplied log.
No physical trial, emulator/game manipulation, radio recovery or deployment is
performed in this packet. Raw logs, process/player identities and captures stay
private. This supersedes the earlier private analysis's missing-VM-log premise.

## Correlated evidence

The complete VM transcript and preserved Host log refer to the same Generation.
Their clocks were not independently synchronized: compare packet/counter
identities, not sub-second differences between the machines' wall clocks.

| Observation | What it establishes / does not establish |
| --- | --- |
| VM 01:31:07: first parent UNI, callback receipt, then child idle UNI | An exchange was observed, and the converter released its consumption credit. This is not a direct observation of the Switch game reading the response. |
| VM 01:31:12 through 01:34:59: parent/child UNI counts both 1; Core enqueued/dequeued both 46; ACK/inflight/waiting queues empty | Roughly four minutes without further application progress, not a converter waiting forever for its first child reply. Host Reliable also drained while Pia RX continued. |
| By VM 01:35:04: parent/child counts 11/10, then continuous progress | The initial wait was not a permanent deadlock. Player-ID (`7700`), block request (`A100`), block initialization (`8800`) and fragment (`8900`) commands appeared. |
| By VM 01:36:00: parent/child UNI counts both 337; Core enqueued/dequeued both 718 | Hundreds of bidirectional UNI exchanges. Final command metadata includes held-keys (`BE00`), consistent with the user's report of entering the room. Counts do not prove all game commands were accepted. |
| Final pre-close VM samples: ACK/inflight/waiting queues empty; Host pending/inflight also empty | No visible queue jam or overflow at this boundary. Earlier transient pressure and game-side loss are not excluded. |
| Host 01:36:15: local room ended; VM closes this Generation | The game communication error preceded intentional test shutdown. Cleanup success is not functional success. |
| VM 01:37:37: `T_PEER_CLOSED` after Host shutdown | Secondary shutdown evidence, not the cause of the earlier room error. |

The pre-change log retains only the first twelve and last UNI command headers.
Five-second samples cannot reconstruct all intervening commands or their tags.
Early observed non-idle child tags wrap normally; the last tag alone cannot
prove continuity across the entire session. The complete *log file* is therefore
not a complete *game-command trace*.

### Conclusions that must not be claimed

- Do not diagnose this as failure to find the Switch, disabled RFU, or failure
  to connect Netplay. Those stages were passed in this run.
- Do not diagnose a stuck first-UNI admission credit: the transcript shows it
  cleared. The earlier source-modeled NI-tail/four-slot-buffer counterexample
  remains a separate latent risk, not an established cause of this run.
- Do not equate callback ACK, Core dequeue, or Reliable acknowledgment with
  successful processing by either game's state machine.
- Do not derive packet loss percentage from 685 retransmissions / 718 new Host
  sends. Retransmissions can also reflect delayed ACKs and timer behavior.
- Do not claim movement itself caused the error: the user's input and error
  are temporally associated, not a proven causal chain.

## Software packet: preserve evidence beyond startup

The existing endpoint observer is extended, not a new emulator manager:

1. Keep the last 24 qualified UNI command-header records per direction, with
   observation ordinal, native transfer timestamp and local monotonic elapsed
   time. Keep first twelve and last fields for compatibility.
2. Count command opcodes and track gaps/last activity age. These are observations,
   never deadlines, automatic retries, inferred game state, or success criteria.
3. Inspect adjacent non-idle child tags modulo eight for the entire Generation.
   Idle does not advance a tag. Preserve the first discontinuity even after
   recent records roll out. Non-UNI/unknown intervals explicitly break coverage.
   This diagnoses the gpSP output boundary only: eight lost commands can alias
   the tag, and a valid output sequence cannot prove downstream game receipt.
4. Include command headers alongside the recent Core-enqueue transfer identity
   to distinguish generation from queue admission. No command arguments,
   player information, game blocks, saves, raw packets or fingerprints are logged.
5. Emit `closing` diagnostics **before** retirement clears pending state. Keep
   `closed` as a separate cleanup result. The old final snapshot could erase
   precisely the pending state needed to investigate a failure.

These changes do **not** change RFU bytes, receipts, pacing, transport ordering,
Core/Relay contracts, or user waiting behavior. They fix diagnosability gaps;
they are not represented as a fix for the native game communication failure.
All storage is bounded and Generation-local. New kinds/opcodes and the first
tag discontinuity may force a log; repeating traffic keeps the existing cadence.

The tag rule is checked against
[FRLG ChildBuildSendCmd / RfuMain2_Parent](https://github.com/pret/pokefirered/blob/c75f352304d529f6ba92d4f74b9cf8b5c3810788/src/link_rfu_2.c).
The separate callback/admission uncertainty follows the
[pinned gpSP RFU implementation](https://github.com/libretro/gpsp/blob/74db5e5/rfu.c).
These are source-based contracts, not proof of closed Nintendo wrapper behavior.

## Remaining blockers and shortest closure path

| Priority | Open question | Required evidence before a protocol fix |
| --- | --- | --- |
| 1 | Why does the native parent pause after an idle UNI despite drained transport? | Reproduce native RFU receipt/clock completion requirements separately from the homebrew echo oracle. Verify NI-phase receipt replacement and the first transition against native evidence; do not invent a clock pulse/ACK to force progress. |
| 1 | Why does in-room traffic end after sustained UNI? | Complete local tag-continuity counters and timestamp-correlated recent commands, compared with native delivery/game error evidence. Valid gpSP tags exclude only an upstream discontinuity, not native receive/consume loss. |
| 2 | Is local Reliable delay aggravating game timing? | Measure ACK/retransmit/backlog behavior under a native-shaped completion schedule. The existing empty final queues and actual-process echo pass are insufficient. Do not simply enlarge queues or extend game timeouts. |
| 2 | Can NI-tail traffic fill gpSP before first UNI? | Existing source-model counterexample needs an actual stock-core reproduction before choosing a safe consumption policy. It is not the observed first-UNI credit stall in trial12. |
| 3 | Do full trade and reuse work? | After stable entry/movement: interaction, party blocks, confirmation, animation, save, normal exit, and another Generation on the same Pair/process. None is attested yet. |

Use unattended, synthetic reproduction first. If it does not uniquely expose
the native failure, one separately authorized diagnostic trial with the new
observer is needed; this packet does not start it. Use both complete opt-in logs,
exact Host/VM SHAs and the first visible error/action time. Do not repeatedly
reselect/reconnect after failure or treat a new Pair as a repair.

For that trial, require prompt room entry first, then one controlled movement,
then interaction only if stable. Never interrupt a save. Host cleanup remains
identity-bound; no process-name kills, WSL reset, unrelated USB operations or
user-emulator termination. Prior Host process/VIF absence and owned USB return
were recorded privately; this packet does not repeat recovery. VM resource
cleanup was not independently inspected.

Core and Relay remain endpoint-neutral. No mGBA/VBA/RSE/battle capability is
added or claimed. A new emulator still requires its own verified frontend/link
adapter, not changes to opaque Pair/Generation forwarding.

## Verification boundary

Focused results belong to this diagnostic packet, including a synthetic
337-command sequence with a deliberately missing middle tag, idle/tag wrap,
long wait observation, unknown coverage, bounded/private detached snapshots,
and pre-retirement pending-UNI preservation. Existing actual relay/Direct A/
StageSession/LDN/TunnelSim tests remain required for the touched endpoint path.

Local CPython 3.12.14 development checks passed:

- Converter/progress/UNI/cadence/endpoint/full-path pressure/CLI/qualification:
  163 passed, 6 dependency deprecation warnings, 94.27 seconds.
- Agent-context policy and clock/full-process **oracle unit tests**:
  34 passed, 1.53 seconds (not execution of a stock process).
- Final Core-admission correlation and pre-retirement diagnostics:
  2 passed, 0.98 seconds; one overlaps the first run. A repeated non-idle tag
  remains byte-for-byte forwarded and does not turn diagnostics into policy.
- Total: 198 distinct focused tests, including seven new test cases.
  `git diff --check` clean. These runs used the working candidate, not a new
  final-SHA CI attestation. An initial synthetic privacy test used a 15-byte
  command by mistake; its fixture was corrected to the required 14 bytes.

Neither the full pytest suite nor a new actual-process/30-minute soak or final-SHA
CI is implied by these focused checks. The previous baseline's green platform
jobs and stock clock probe do not close its failed final acceptance gate.
`GPSP_ACCEPTANCE.json` intentionally remains blocked, not CI-pending complete.
