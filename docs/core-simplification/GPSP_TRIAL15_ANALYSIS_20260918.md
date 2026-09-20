# Trial15: room entry, then idle communication error

## Scope and verdict

Diagnostic source: `codex/gpsp-endpoint` at
`f7e9126c67338ba00cdca67a58a790d7f5bee5b3`. Host used its verified immutable
overlay; Guest trace identifies the same nine instrumented source files.
Host Python 3.12.3, Guest Python 3.14.7. This is not a release qualification.
Both endpoints used the temporary host-local relay, not the Internet relay.

The user recreated the native room several times. On the final attempt, both
games entered, then both displayed Communication error within several seconds
without either player moving or pressing a button. Approval-to-entry was
reported as not very long, but exact screen/action timestamps were not captured.
Movement is therefore not a necessary trigger for this occurrence. Neither
room recreation nor a particular game timer is established as its cause.

**Progress:** the receipt omission repair is verified at the recorded boundaries,
and the final generation passed the old first-UNI plateau into player/block and
in-room command traffic. **Still failing:** repeatable prompt entry and stable
idle communication. No trade, save, battle or full interoperability pass.

## Evidence and generation separation

Original logs remain private; byte-preserving copies were hashed:

- Host: 1,560,375 bytes; SHA256
  `a65156f6b8de3860d3c7292956b8908e61008a320633b4c39d0a15cde8d7acc9`.
- Guest: 2,071,503 bytes; SHA256
  `96dfa669a169d7c03633d7dd28227f3e62206a9c65c0969ceae1ea164bae8310`.

Run the existing `tools/audit_rfu_trace.py` separately with each common
generation ID from these private logs. All four have complete metadata coverage
and final flushes; complete coverage alone is not a forwarding or game pass.

| Generation, chronological | Audit result | Interpretation |
| --- | --- | --- |
| 1 | 313 inbound matched; 322 Guest RFU dequeued, 59 Host native admissions | Retired with 256 pending native frames and 7 pre-clear Core frames. Their total 263 accounts for the admission-count difference. Six already-admitted frames were still in flight. This is an interrupted/backlogged generation, not a lossless end-to-end pass. |
| 2 | Insufficient RFU evidence | Room lifecycle/metadata only; no qualified RFU exchange. |
| 3 | Insufficient RFU evidence | Same limitation; do not combine with another room. |
| 4 | Matched captured boundaries | 623/623 Host-to-Guest; 922/922 Guest enqueue/dequeue/Host native admission; 274/274 qualified child UNI. This is the progressed generation, not a completed trade. |

The count accounting in generation 1 does not establish what triggered its
retirement. It prevents incorrectly interpreting a post-close boundary mismatch
as unexplained packet corruption, or hiding that mismatch behind generation 4.

## What the receipt repair actually achieved

For generation 4, all 623 eligible WK receipts (591 callback, 32 idle) reached
Core enqueue with matching timestamps, original receipt numbers and order.
There were zero omitted or unpaired receipts and zero receipt-number
discontinuities. This directly closes the specific omission seen in trial14.

Parent and child each reached 274 UNI frames. The recorded child non-idle tag
checks report zero discontinuities. Host Pia decrypt failures are zero. These
observations do not prove payload integrity, native game consumption, no RF
loss, or that every game's internal queue accepted every frame.

## Remaining delay: receipt preservation is not timely service

The first parent UNI-to-next-parent interval is still **16,106.498ms** on the
Host clock. The Host's first-parent-admission-to-matching-WK-send-attempt
interval is **16,123.245ms**. Neither is an inferred game timeout or a
cross-computer one-way latency measurement.

On the Guest's own clock, that parent receipt takes **8.140ms** from Core receive
to local callback, followed by **1.038ms** from callback to Core dequeue.
Across the complete final generation, Guest enqueue-to-dequeue max is 2.139ms,
local socket-write max 3.437ms, parent-transfer-to-local-delivery max 124.315ms,
and delivery-to-callback max 50.032ms. Callback ACK still does not prove game
consumption.

Meanwhile Host periodic snapshots show `pending_remote` rising to **201** with
**six** Reliable frames in flight. It drains through 125 and 48 before initial
UNI progression resumes. Later snapshots still contain 22–32 pending frames.
This directly exposes a native-send backlog that Guest `core_queue=0` hides.
The maximum observed periodic value is not a continuously measured peak.

Within Host only, once a frame is admitted to Reliable, its first scheduled send
attempt follows within 0.154ms across all 924 admissions. The long backlog is
therefore before that admission boundary, not an idle scheduler after it.
Recorded held-key-command admissions then take 16.642–1,791.614ms to release
the cumulative Reliable window. This includes recovery/earlier-hole effects;
window release is not a native game-consumption timestamp or pure radio RTT.
There are 924 new frames and 768 retransmission attempts in this generation.
Retransmission counts do not by themselves distinguish loss from delayed ACKs.

The current tunnel drains a bounded FIFO, shares a six-frame native send window,
and admits new frames only as that window frees. The six-frame policy is inherited
from an earlier physically constrained path in `bridge/frlgsim/sim.py`; its
comments record failures with larger windows. Do not increase it speculatively,
drop preserved receipts, reorder opaque RFU messages, or extend game timers.

**Conclusion:** a substantial native-send service/backlog problem is observed.
Its relationship to the final game's fatal-error branch remains a hypothesis.
Additional Host Core-admission/pending-FIFO age observations would separate the
remaining transport-versus-native-queue residence precisely; do not subtract
the two PCs' monotonic clocks to invent that measurement.

## In-room error and remaining uncertainty

The final generation reaches `7700`, block/standby traffic and `BE00` headers,
consistent with the user's room-entry report. A held-key header does not prove
a person pressed a direction: the value/arguments are intentionally not logged.
The supplied source reference and trial12 analysis identify multiple possible
game errors (internal queues, command continuity and particular keepalive
callbacks); none is directly observed by these metadata logs.

After the last UNI, Guest remains at 274/274 for about 19 seconds before its
generation-closing snapshot. Pending callback ACKs, UNI credit and waiting
frames are then empty. Host eventually reports `local_room_ended`. The later
requested whole-client Ctrl+C and Host `S_PEER_CLOSED` happen after the original
in-game failure and are not its cause. Drained end-state queues do not erase
the earlier backlog or prove adequate real-time delivery.

WK message-index/datagram-position differences are still observed (551 of
1,170 scheduled receipt attempts). As in trials13/14, this is a wire-layout
question, not a proven receiver violation. The new progression also means
such differences are not sufficient to predict permanent first-UNI failure.

## Next software packet, before another physical trial

1. Extend the existing closed-loop native-envelope/service reproduction with
   this trial's asymmetric input, six-frame window and cumulative-ACK/retry
   scheduling characteristics. Preserve first-generation saturation and the
   final-generation NI backlog into UNI; do not test only a drained NI tail.
2. Measure pending-FIFO residence, oldest-frame age, admission rate and
   cumulative/ selective ACK advancement on the same Host clock. Keep bounded
   metadata and first-failure/pre-clear state; no game arguments or raw payloads.
3. Compare native packet grouping and ACK/window recovery with existing gold
   and primary implementations. Determine why service remains slow while
   preserving every authorized receipt; a generic larger buffer is not a fix.
4. Validate any resulting narrow change against receipt identity, wrap/loss/
   reordering, causal UNI pacing, two generations and Switch-to-Switch/shared
   endpoint regressions. The prior 400ms scripted-service and 337-UNI tests
   cover their model, not this newly observed native scheduling profile.
5. Then run one controlled physical generation: stationary entry/idle first,
   Host movement next, Guest movement next. Trade/save comes only after stable
   idle and both directions. Stop at the first failure; do not recreate rooms
   during that evidence run.

Steps 1–4 can proceed without the user, VM or Switch. A later physical test is
still required to prove the repaired native behavior. This analysis changes
no production policy and introduces no new physical retry.

## Shutdown evidence and limits

User confirms normal VM Ctrl+C and preserved RetroArch. Host and local relay
owning sessions exited; independent Host process and active-port checks found
no owned survivors. A former helper PID was reused by an unrelated process
and was left untouched. WSL running inventory is empty; final stage reports
all owned resources released, quiescent radio and no cleanup errors.
No fresh live netdev listing was taken after the distro stopped.

The trial-acquired adapter returned automatically. A fresh identity guard
prevented a now-unnecessary detach; no detach/reset was executed. The VMware
USB service was restored to its prior Running/Auto state, and the restoration
helper exited. Independent post-stop VM socket verification was requested and
is pending; do not declare that separate gate passed from the UI overlay.

## Software follow-up: service reproduction and timing boundaries

This packet starts from the same `f7e9126` base and preserves the preceding
analysis/incident worktree edits. It changes diagnostic observation and test
coverage, **not the native transmission policy**. Allowed production scope is
the Switch endpoint adapter, opaque TunnelSim/progress observer, a delegating
Sim ACK hook, and source identity. Core/Relay contracts, gpSP conversion and
cadence, Reliable algorithms, six-frame window, retry timers, queue capacities,
game/save data, driver ownership and legacy desktop behavior are unchanged.
No hardware, VM, WSL, USB or existing application session is operated.

### A reproduced blind spot, not a reconstructed native receiver

The encrypted-envelope test now supplies 360 parent NI transfers at 30Hz,
through actual native receive/dedup, adapter, translator, cadence, native
Reliable, Pia encryption and outgoing decode. The first parent UNI and its
actual modeled callback/child response arrive **before** the NI FIFO drains.
ACK service is explicitly scripted, independent of application replies. No
fixture emits a next parent simply because a receipt/child was sent.

| Scripted six-frame service | Peak native pending | First UNI response waits | Messages preserved |
| --- | ---: | ---: | ---: |
| Cumulative ACK every 50ms | 2 | 0ms in this zero-local-delay fixture | 362/362 |
| Cumulative ACK every 400ms, selective ACKs behind the oldest hole | 182 | 12,000ms | 362/362 |

Both cases use the same production window and preserve payload/receipt bytes
and order. In the slow case 298 selective ACK observations release no slots;
the cumulative window eventually drains. A queue-size/loss-only assertion
passes while real-time service is inadequate. This demonstrates the backlog
mechanism and the old drained-NI-tail coverage gap. It does **not** establish
that physical trial15 used this ACK pattern or that 12s is a game timeout.
The existing full Core/relay/two-generation tests remain separate coverage.

### Independent native-gold service comparison

Reused the authenticated offline reader; sockets explicitly forbidden, no raw
capture rewrite or new decoded-payload export. Gold SHA256 remains
`e6df7e03b2d33c11aaec112306f4605706a11afd9fd35fc9dd97ad768257d0b5`.
18,258 Wi-Fi / 18,252 Pia records decode with zero authentication/decode
failures and one network. Direction below describes the original sender.

| First observed application to first observed ACK | Pairs | Median | P95 | Maximum |
| --- | ---: | ---: | ---: | ---: |
| Native parent frames | 8,185 | 20.001ms | 25.595ms | 74.414ms |
| Native child frames | 16,178 | 12.556ms | 17.380ms | 277.047ms |

Parent emits 7,175 observed bulk ACKs, child 6,941; neither observed mask has
selective bits. Parent/child AppData repeats are 18/37. Parent ACK interval
median/P95 is 18.483/30.289ms, child 15.556/35.561ms. Capture gaps and repeated
frames mean these are **sniffer-observed intervals, not live pure RTT**. They
show no support for treating multi-second steady backlog as normal. They also
do not prove that local radio loss, ACK delay, or a native receiver constraint
caused the trial15 error. In particular the slow test's selective pattern is
a counterexample, not a gold replay.

### What the new diagnostics separate

- `native_pending`: generation-local ordinal, depth, Core-call-to-admission
  wait, then Core-queue-to-tunnel-poll residence. Timestamps stay local and are
  never serialized into the Core protocol or game wire.
- `native_tx_queued`: same ordinal plus pending-FIFO residence before Reliable
  admission. Together these give exact local Core-call-to-Reliable residence,
  excluding upstream network time and native game consumption.
- `native_ack`: actual authenticated parsed bulk ACK id, selective-bit count,
  send-window and in-flight counts before/after, and number of released slots.
  The hook delegates to the unchanged Reliable implementation before observing.
- `native_backlog`: current/peak depth, oldest age, maximum admitted residence,
  and sticky pre-clear snapshot. Disconnect/final evidence keeps queued work
  visible even after cleanup; generation reset starts fresh measurements.
- Offline audit reports these independently of forwarding and functional
  verdicts. Old logs say `NO_NATIVE_SERVICE_EVIDENCE`, never zero delay. It
  accepts the exact historical nine-file source set and the new eleven-file
  set (adding Sim and Reliable), not an arbitrary equal-length hash map.

All observations remain bounded metadata with no game arguments, raw payloads,
keys or device identifiers. New tests distinguish 2s Core admission blocking,
3s Core queue residence and 5s pending residence; preserve the 256-frame
pending plus 256-frame upstream pre-close evidence; release blocked producers;
check fresh generations and both native roles through selective ACK/sequence
wrap against an uninstrumented Reliable state. Private original Host/Guest
hashes still match and the previous final-generation audit still reports
complete/matched boundaries, with the new measurements explicitly unavailable.

### Remaining decision and next physical gate

There is no justified transmission-policy fix yet. The next single-generation
trial must distinguish these cases on the **same Host clock**:

1. Core admission/poll is already late: investigate local pumping/backpressure.
2. Frames arrive promptly but pending residence grows and bulk ACKs are sparse:
   investigate the native transmit/ACK path, not VM callback latency.
3. ACKs arrive frequently but release no space: inspect cumulative sequence,
   selective holes and retry scheduling, without enlarging the window blindly.
4. Queues and ACK service are prompt but the game fails: return to native RFU
   consumption/game continuity; transport success is not a game verdict.

Retain the same local-relay route and ROM/player pairing, use fresh source-bound
logs, allow no room recreation within the measured generation, and time approval,
entry and first error. Stationary entry/idle is the first functional gate; do
not move or trade during it. The independent VM socket-cleanup check remains
pending. This software packet does not itself authorize or launch that trial.
Changes are local until separately committed/distributed; do not tell the VM
to pull an uncreated revision or reuse an expired Pair code.

### Verification log

An initial broad selection was interrupted after approximately seven minutes
without a pytest failure summary. Inspection found that its early virtual-OS
boundary suite deliberately runs seven lifecycle cases and a real 181-second
readiness wait. Slowness alone was not a product failure; the interrupted run
is **not counted as a pass**. The identified test launcher/runtime processes
and runtime's direct children were independently absent afterward. No product
timeout was changed and no hardware cleanup/retry was performed. Subsequent
verification separates the long boundary suite from the affected fast and
full gpSP flow suites. Ordinary audit-command import-path/patch-context errors
were corrected locally and did not change the evidence or production policy.

Completed on Windows CPython3.12.14 using the existing audit environment:

- **554 passed** in260.09s: all selected gpSP, RFU, Reliable bootstrap,
  Switch endpoint/Core composition, shared Core/relay/transport, Direct A/B,
  Pia host/liveness and agent-context tests. No failures or skips; 22 warnings
  concern existing helper-class collection and dependency deprecations.
  The three full gpSP pressure/UNI/wider-peer two-generation cases passed in
  82.71s,60.77s,55.31s respectively; no test deadline was enlarged.
- **1 passed** separately in46.91s:
  `test_actual_cli_relay_ldn_tunnelsim_two_generations[None]`, using real CLI,
  local relay and LDN/TunnelSim with virtual OS primitives, not physical radios.
- Final focused rerun **46 passed** in1.25s after the audit malformed-record
  guard and production-equivalent five-second trace-flush test refinement.
  This overlaps the554 selection and is not added to its count. Both service
  profiles have zero observer drops at that flush interval.
- Earlier focused85 and39 selections also passed and overlap the above.
  No native game/stock emulator, CI, release, commit, push or deployment pass
  is implied. `git diff --check` is clean. The deliberate long-readiness test
  and other interruption variants in the aborted boundary suite are not
  claimed as newly passed here.

The minimal-change approach reused the existing envelope fixture/auditor,
kept observation inside the endpoint and preserved the native ACK algorithm.
The actual remaining ACK-service cause still requires one source-bound
physical observation; a broader speculative timing rewrite is not justified.
