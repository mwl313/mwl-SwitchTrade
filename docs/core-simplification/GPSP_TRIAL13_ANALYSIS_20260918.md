# Trial13 — approval succeeds; native UNI progression remains unresolved

Status: **receipt-preservation repair implemented; selected software regressions
pass; native stall causality and trade remain unproven** (section 11).
Captured-run base: clean `codex/gpsp-endpoint` at
`f4275359722fc02bf281df11d900296038d99c03`, matching remote when checked.
Trial13 used a LeafGreen Switch leader and a FireRed gpSP guest. Do not merge
its outcome with trial12's eventual room entry/movement. Raw logs, player and
process identities, captures and screenshots remain private.

Sections 1–10 record the diagnostic-only packets without production changes.
Section 11 records the subsequently approved narrow receipt-preservation repair.
No new physical test, VM/emulator operation, WSL/USB recovery or deployment took
place in those software packets. Captured source identity is distinct from the
repair below. Section 12 records subsequent diagnostic handoff preparation;
it does not attest that the VM has received the candidate.

## 1. What the complete trace establishes

Both full files have contiguous batches/events, zero observer drops, final
flushes and matching nine-file source hashes, also matching the checkout.
The VM screenshot separately identifies the candidate commit and passing doctor.
The existing audit reports `TRACE_COMPLETE / MATCHED_CAPTURED_BOUNDARIES`,
**not** a functional pass (`NOT_ASSESSED`).

| Boundary | Observations compared |
| --- | ---: |
| Native Host admission → Guest Core receive, WT/WK | 202 / 202 |
| Guest Core enqueue → dequeue, WT/WK | 72 / 72 |
| Guest Core dequeue → Host native queue, WT/WK | 72 / 72 |
| Qualified child UNI output → Core enqueue | 1 / 1 |

These are ordered metadata comparisons, not byte-integrity or game-consumption
proof. NI retry pacing/receipt replacement is intentionally outside the first
and fourth comparisons; passing this audit does **not** validate that policy.

The actual Guest game displayed the leader's OK before its member-waiting
message. NI approval therefore reached the game. The next observed exchange
was one parent UNI (70-byte game payload) and one child UNI (14 bytes), both
with zero command headers. No subsequent player-ID or block command was seen.
About 164.66 seconds without another UNI elapsed before the requested stop.

At closing, the Guest had no pending callback ACK, UNI credit, waiting UNI or
Core queue. The Host's native Reliable send window had already drained and
its pending queue was empty, while lower traffic remained live. First-UNI
delivery was followed by a real child output; this is not the old
callback-ACK-only admission-credit deadlock.

The host's unavailable message followed the instructed Guest stop. Preserve
the earlier stall as the functional failure, not the later peer-close error.
Guest reports clean owned shutdown; its OS socket residue was not independently
queried. Host owner/process exit, owned USB return and prior service-state
restoration were separately verified and retained privately. No recovery is
repeated for this analysis.

## 2. What the games are waiting for

The pinned FRLG source gives a more precise interpretation than the screen text:

- `union_room.c`, `LG_STATE_MAIN`: receiving OK updates the displayed status;
  starting the activity requires `gReceivedRemoteLinkPlayers`.
- `link_rfu_2.c`, `Task_PlayerExchange`: ready state → player IDs (`7700`) →
  block request (`A100`) → block initialization/fragments (`8800/8900`) → all
  LinkPlayer blocks received → `gReceivedRemoteLinkPlayers = TRUE`.
- `RfuMain1_Parent` starts send-with-clock-change. `RfuMain2_Parent` waits for
  RFU completion (`parentFinished`), then checks `lman.parentAck_flag` before
  processing child commands and preparing subsequent game output. A Pia ACK
  is **not** that completion event or that game-side bitmask.
- `MscCallback_Child` receives RFU data, queues it and sends a prepared child
  reply. The main-loop command builder and the serial callback are separate:
  an immediate child reply need not contain a freshly pressed key. Waiting
  for another parent window after one idle response is not, by itself, a
  Guest fault.

Thus the narrowest proven blocker is **after approval and first idle UNI,
before sustained native RFU progression / player exchange**. The trace cannot
name the exact native wait branch. Missing `7700` is a useful milestone, not
proof that the game never prepared that command internally.

The reference includes `REVISION >= 0xA` branches and Switch-facing `svc_*`
calls. Its ordinary RFU serial protocol is not the implementation of the
closed Switch emulator's WT/WK completion/clock handling. Neither cartridge
revision incompatibility nor complete equivalence of these environments follows
from source similarity. Exact commercial binaries were not independently
identified by this analysis.

## 3. New native-gold comparison

The existing authenticated native Switch↔Switch capture was decoded offline:
18,258 Wi-Fi / 18,252 Pia records, zero recorded authentication/decode failures.
Capture SHA256:
`e6df7e03b2d33c11aaec112306f4605706a11afd9fd35fc9dd97ad768257d0b5`.
Repeated Reliable identities had no changed payloads. The capture has known
sequence gaps; first observed time is not necessarily first actual send time.

Relative to its first observed parent UNI:

| Observed normal-capture event | Relative time |
| --- | ---: |
| First parent idle UNI | 0 ms |
| Second parent idle UNI | 15.000 ms |
| First observed WK + child idle UNI, same captured datagram | 19.311 ms |
| Parent player-ID command `7700` | 37.101 ms |
| Parent block request `A100` | 85.316 ms |
| Parent block initialization `8800` | 100.447 ms |

This is evidence that normal progression need not take minutes, **not** a
universal 37-ms deadline or permission to fabricate a second parent frame.

Trial13 Host-local trace instead shows:

- First parent UNI admission → its WK transmit attempt: **167.036 ms**.
- First parent UNI admission → child WT transmit attempt: **200.920 ms**.
- WK and child WT were attempted in separate batches, **33.884 ms** apart.
- Child WT queue → native Reliable window release: **317.648 ms**, with four
  scheduled attempts. This is not a measured packet-loss rate.

All trial intervals use one Host clock. Gold timings use one capture clock.
No Host/VM clock subtraction is used. Native receive observation and local
transmit intent are different measurement boundaries: the comparison identifies
timing/grouping questions, not exact end-to-end latency or a proven cause.

There is also one concrete structural discrepancy: of 97 scheduled WK attempts
(55 unique receipts), one new WK encoded `message_index=1` while occupying
AppData position 2 after a retransmitted WK. Prior gold analysis found all
8,101 unique observed WK indices equal to their outgoing AppData position.
The discrepant attempt was about 1.289 seconds **before** first UNI; the final
UNI WK had index/position 1/1 and drained. It is a candidate compatibility gap,
not proof that it caused the stall or permission to rewrite retransmissions.

Finally, NI-phase cadence admitted 55 receipts for 202 observed parent WT
identities, replacing 147 deferred receipts. The current unit tests explicitly
validate this implementation policy. They do not independently establish that
the closed native wrapper treats skipped receipts and the renumbered receipt
counter as equivalent. The gold's capture gaps cannot prove a missing receipt
was intentionally omitted. Keep this question separate from the established
NI-retry flood/backpressure repair; blindly disabling all pacing could revive it.

## 4. Ranked investigation and repair gates

| Priority | Candidate / requirement | What closes it |
| --- | --- | --- |
| P0 | Native completion/clock semantics after first UNI | Receiver-backed evidence distinguishing receipt delivery, child-slot admission, RFU clock completion and next parent WT. Empty transport queues alone cannot do this. |
| P0 | WT/WK identity, receipt replacement and grouping | Check native completion behavior under retained vs replaced NI receipts, batched vs separated WK/WT and retransmission regrouping. Require one-variable evidence; never change payloads in Core/Relay or invent acknowledgments. |
| P1 | Delay sensitivity of the native completion path | Measure native-shaped tests at controlled local delays/loss/order. Establish a working fast-path control before attributing the failure to Internet/VM delay. Do not extend game timeouts to hide the failure. |
| P1 | gpSP callback ACK before its four-slot FIFO admission | Separate actual stock-core NI-tail + delayed-read reproduction; current source model demonstrates possibility, not trial13 causality. The observed first child UNI lowers its priority for this particular stall. |
| P1 after entry | Later in-room error from trial12 | Continuous child-tag/native-receive evidence and game-side error/queue/clock status. Host movement success and Guest movement/error timing do not uniquely identify the cause. |

The existing polling/clock homebrew and full-stack tests remain valuable, but
their opposite console is a fixture that calls `game.press(parent_frame(...))`.
It supplies the next frame after its own expected receipt/data checks. It does
not execute the native parent wrapper's decision to advance. Its receipt check
also assumes index 1, and UNI pacing tests model the expected causal consumer.
These tests can validate the converter and actual gpSP while the native parent
still stalls. Another longer run of the same oracle cannot close this gap.

The next software work item is a **native-envelope completion conformance
reproducer**, with independently grounded acceptance conditions for receipt
identity/order/grouping and next-parent progress. Reuse the existing relay/
endpoint/stock harness. Do not label a model based on a guessed native rule as
root-cause reproduction. A modeled failure can show sensitivity only.

Existing logs and gold allow offline comparison and candidate preparation.
They do not expose the closed receiver's internal clock state. If a receiver
implementation or independent evidence cannot resolve it, a separately
authorized native-controlled comparison is required; it cannot truthfully be
replaced by another synthetic PASS. That test should capture the first transition
and actual packet grouping, with one changed condition and a known control,
not repeat the same join/movement sequence hoping the wait clears.

## 5. Requirements for full communication

| Gate | Present evidence / next pass condition |
| --- | --- |
| Discovery, Netplay RFU and reciprocal approval | Demonstrated on real hardware in trial13. |
| Prompt, repeatable room entry | Not passed. Continuous UNI, player-ID and complete LinkPlayer blocks must progress without the unexplained long stall. |
| Stable two-way in-room operation | Trial12 partial only. Verify idle, Host-only movement, Guest-only movement and interaction separately under bounded load/delay; no communication error or tag/block loss. |
| Complete trade | Unproven: both party displays, selection/confirmation, all blocks, animation and bilateral save/return. A displayed animation or one-sided save is insufficient. Never interrupt a save. |
| Normal close and reuse | Require actual clean room exit and a second Generation/trade with retained healthy Pair/frontend and fresh RFU state. Software lifecycle tests alone do not attest this. |
| Release qualification | Existing exact-source stock continuity/soak, full regressions and Windows/Ubuntu final-SHA gates remain; acceptance stays `BLOCKED_NATIVE_UNI_VALIDATION` / `NOT_ATTESTED`. |

Prioritize trade. Battles, multiple children, RSE and new emulator adapters are
not part of closing this failure. Preserve the opaque shared Core and isolate
native-wrapper vs frontend/RFU adaptation; a proven gpSP-specific fix must not
silently alter the working Switch↔Switch path.

## 6. Reproducibility and source references

Reused `tools/audit_rfu_trace.py` for the complete two-log comparison and the
existing authenticated offline gold reader for the transition comparison.
The private follow-up script and pinned-source hashes are retained beside
qualification evidence; no new third-party dependency or raw-data publication.

- [FRLG link/MSC/player-exchange reference](https://github.com/pret/pokefirered/blob/c75f352304d529f6ba92d4f74b9cf8b5c3810788/src/link_rfu_2.c)
- [Group leader/member UI states](https://github.com/pret/pokefirered/blob/c75f352304d529f6ba92d4f74b9cf8b5c3810788/src/union_room.c)
- [RFU send/receive library](https://github.com/pret/pokefirered/blob/c75f352304d529f6ba92d4f74b9cf8b5c3810788/src/librfu_rfu.c)
- [Stock gpSP callback/FIFO/clock reference](https://github.com/libretro/gpsp/blob/74db5e5/rfu.c)

The ESP32 reference's `host/core/Rfu.cs` at
`1f8ae46c6a1c25cc127b02f85d37659cfc40a856` corroborates the wrapper field
layout, but its packet builders are not the closed native receiver and do not
resolve this completion question. No unrelated functionality is imported.

## 7. Verification of this analysis packet

- Complete two-log audit rerun: `TRACE_COMPLETE`,
  `MATCHED_CAPTURED_BOUNDARIES`, `issues=[]`, functional `NOT_ASSESSED`.
- Focused trace, boundary, cadence, UNI-transition and repository-context tests:
  **52 passed**. They verify the existing analysis/implementation contracts;
  they do not resolve the native receiver blind spot described above.
- Private transition comparison completed with unchanged repeated Reliable
  payloads and complete physical Host trace assertions.
- Original evidence hashes unchanged; pinned reference hashes retained privately.
- `git diff --check` clean. No stock emulator, full-suite, CI or physical test
  was run as part of this documentation/analysis packet.

## 8. Follow-up packet: executable envelope observations

User approved moving to the next software work item. Base remains `f427535` on
`codex/gpsp-endpoint`; the preceding analysis and incident notes were already
uncommitted and are preserved. Scope: `tools/audit_rfu_trace.py`, its tests, a
new `tests/test_gpsp_native_envelope.py`, and this/current-incident record only.
Production endpoints, Core/Relay, native wire/timers, emulator state and physical
resources are unchanged. No dependency, error code, migration or deployment.

The new in-memory wire tests run actual converter/cadence, CoreTunnelAdapter,
TunnelSim, Reliable scheduling, Pia serialization and encryption/decryption.
RFU1 input and lower-layer peer acknowledgments are scripted; this is NOT a
native RFU receiver or stock-emulator qualification. Tests do not supply a next
parent frame merely because a transport ACK arrived.

Covered cases:

- Callback receipt and child response serviced together or on separate ticks,
  including a retransmitted receipt accompanying a later first child response.
- Lost ACK followed by a new WK: the old WK **or WT** precedes it, reproducing
  index 1 at actual AppData position 2 through the real serializer. Reliable
  retransmission preserves original payload bytes; no rewriting is introduced.
- Selective ACK of a later frame retains the earlier gap; retransmitting and
  cumulatively acknowledging that gap drains correctly, including `FFFF → 0000`.
- NI receipt replacement, last-deferred receipt flushed at UNI, and recovery
  only on an actual repeated parent WT. Passage of time generates no receipt
  for an already replaced timestamp.
- Datagram chunk boundaries and trailing control frames agree with the existing
  attempt observer's AppData positions; production window size is unchanged.

The existing offline audit now reports these observations automatically:
position comparisons/unknowns, up to eight discrepancy samples, observed parent
timestamps without a queued WK, and first-UNI receipt/child transmit timing,
first-attempt grouping, subsequent window release and next observed parent UNI.
It uses the Host clock only and refuses this summary for incomplete/mismatched
two-sided evidence. It never promotes these observations to receiver compliance.
Existing CLI exit codes still concern trace/boundary verification only.

Applied to the unchanged trial13 evidence: 97 WK attempts, one position
discrepancy, 202 parent timestamps and 55 queued receipt timestamps (147 without
a queued receipt). First WK and child attempts are in different datagrams,
33.884ms apart; child queue to Reliable window release is 317.648ms. No next
parent UNI is present through 164,832.442ms from first Host UNI admission to
final Host trace flush. This differs slightly from the earlier Guest closing
snapshot's age because the observation boundaries are different, not a PC-clock
subtraction. Missing receipts here describe policy output, not proven radio loss.

Verification command (existing Python environment):

```text
python -B -m pytest -q tests/test_gpsp_native_envelope.py tests/test_rfu_trace.py tests/test_rfu_boundary_progress.py tests/test_gpsp_rfu.py tests/test_gpsp_cadence.py tests/test_gpsp_uni_transition.py tests/test_rfu_flow_control.py tests/test_gpsp_flow_control_path.py tests/test_agent_context_policy.py tests/test_reliable_bootstrap.py bridge/tests/test_tunnel_pia_liveness.py
```

Final code on Windows CPython 3.12.14: **131 checks passed in 136.88s**, including
actual local relay/virtual-radio two-Generation pressure, Reliable bootstrap and
Pia liveness regressions; six existing dependency deprecation warnings.
This supersedes the first 118-check run before final diagnostic hardening.
The tests remain scoped software evidence, not a full suite, CI, native receiver,
stock-process or physical-game pass. No production-code fix is asserted.

### Next closure decision

This closes the deterministic envelope-reproduction and reporting substep,
**not** receiver-backed completion conformance. Changing the closed receiver's
assumed acceptance rule inside a fixture would not supply the missing evidence.
Do not rewrite opaque WK bytes or relax qualification to make a model pass.

The next useful physical experiment is a separately scheduled low-latency-path
control using the same endpoint source, supported core and game pair, changing
only relay routing to a host-local relay reachable from the VM. First verify
VM reachability and the narrowly scoped listener; no firewall widening or relay
launch is performed here. Existing native-gold behavior is the independent
normal reference, not a claim that this proposed control will pass.

Record actual first-UNI timing/grouping, receipt coverage and next-parent/player
exchange before movement. Progress only on the low-latency path would support
timing sensitivity; a repeat stall would leave native completion/receipt semantics
open. Neither outcome alone assigns causality to the WK position discrepancy.
If byte/receipt-policy changes are then needed, test one evidence-backed endpoint
change at a time and retain Switch↔Switch opaque forwarding and NI flood guards.
No new Pair, physical test, radio acquisition or user input is required for this
completed software substep. Full entry/trade acceptance remains blocked.

## 9. Trial14 host-local control result (2026-09-18)

The user subsequently authorized the proposed physical control. Both endpoints
used `f4275359722fc02bf281df11d900296038d99c03`, with the same LeafGreen Switch
leader / FireRed gpSP guest pair. Host overlay was dirty only for preserved
analysis/tests/docs; all nine logged runtime-file hashes match trial13 and
the Guest. The existing relay implementation ran temporarily on the Host's
VM-only virtual interface, reachable by WSL and VM without Internet routing
or firewall changes. Local Windows versus prior remote Linux relay runtime
is an environmental limitation, not an isolated proof of a timing mechanism.

### Observed result and complete evidence

Room list, request and native approval succeeded; both games then remained on
the approval/member-wait screens. No entry, movement, trade or save attempted.
User-requested normal VM-first stop caused the later unavailable/peer-close
messages; those are secondary to the preceding stall.

Both complete logs passed the existing audit with `TRACE_COMPLETE`,
`MATCHED_CAPTURED_BOUNDARIES`, no issues, 449 Host / 1,658 Guest events and no
observer drops. Native admitted WT/WK -> Guest Core matched 116/116; Guest
enqueue -> dequeue -> Host native queue matched 41/41 on each boundary;
qualified child UNI -> Core admission matched 1/1. These are metadata/order
checks, not raw-payload integrity or native game-consumption attestation.

| Host-local observation | Trial13 Internet path | Trial14 local path |
| --- | ---: | ---: |
| First parent UNI -> WK attempt | 167.036ms | 16.548ms |
| First parent UNI -> child WT attempt | 200.920ms | 16.566ms |
| WK and child in same first scheduled datagram | no | yes |
| Child queue -> lower Reliable window release | 317.648ms | 201.000ms |
| Subsequent parent UNI | not observed | not observed |

Trial14 had one idle UNI each direction and no next parent for 90.873 seconds
through final Host flush. The final first-UNI WK has index/position 1/1 and the
child WT follows at position 2. WK and child subsequently retransmitted, so
the first-attempt times/grouping are **not proof of first over-air reception**.
The drained lower window still does not prove RFU completion.

Guest pre-cleanup queues/UNI credit/receipt backlog were empty; all 79 observed
parent-delivery/callback pairs matched. Both games stayed stalled despite the
faster first response and its co-packing. Internet routing delay or separated
first-UNI packets alone are insufficient explanations for this reproduction.
Do not generalize that into a proof that every timing effect is irrelevant.

### Remaining software focus, not another blind physical retry

Two pre-UNI encoded-WK-index versus actual-position differences remain. NI
cadence coalesced 88 receipts (116 parent timestamps, 28 queued timestamps).
Those are observed policy effects, not proven RF loss or native rule violations.
The next bounded software task is independent native-gold/source comparison
of receipt identity, retransmission positioning and completion semantics,
retaining opaque forwarding and NI flood protection. The closed receiver's
internal completion state remains unobserved; no production fix is claimed.

Host-owned endpoint/keeper/local-relay processes and relay listener were absent,
WSL stopped, the acquired USB returned automatically and VMware USB arbitration
was restored to its prior state. No detach/reset was needed. Guest whole log
reports stopped/clean and user confirmed returned prompt; independent VM socket
verification remains pending. The Pair is retired and no retry was started.

## 10. Post-trial14 receipt/recovery audit (2026-09-18)

Approved unattended packet: branch/base still `codex/gpsp-endpoint` / `f427535`;
preserve the preceding dirty analysis, audit and tests. Scope is the existing
offline audit, trace/envelope/cadence-model tests and this/current-incident
record. No production policy, wire format, Core/Relay, timer, window, dependency,
emulator/save, deployment or hardware change. No new physical test is ready
merely because these software checks pass.

### Independent gold checks

Reused authenticated capture reader and private `trial14_receipt_audit.py`.
Same gold hash as section 3; 18,258 Wi-Fi and 18,252 Pia records decoded, zero
authentication/decode failures and one observed network. Only sanitized field
counts are reported; raw capture/decoded application data stays private.

- 8,181 observed unique parent WT timestamps and 8,101 unique child WKs.
  Observed WK numbers span 1..8,455 with 354 numbers unobserved. There are
  344 parent timestamps without a captured WK and 264 WKs without a captured
  parent. These gaps are **not evidence of intentional receipt suppression**.
- In 7,314 adjacent WK-number intervals with both corresponding parent WTs
  observed, no other observed parent WT intervenes in Reliable order. This
  includes 38 pre-UNI intervals. Thus observed native behavior supplies no
  support for treating latest-only NI receipts as cumulative acknowledgments.
- WK index equals its outgoing AppData position in all 8,101 cases, including
  976 at position 2. In 952 matched cases that index is 2 while the incoming
  parent WT position is 1: the field must not be repaired by copying the
  incoming parent's position. This remains correlation, not receiver code.
- Eighteen repeated parent WTs keep the same Reliable identity and bytes.
  No observed parent timestamp is reissued under a different Reliable identity.
  Eighteen repeated WKs also keep bytes and positions. Absence in this capture
  is not a universal prohibition on other native behavior.

### Confirmed recovery-test blind spot

The previous direct-translator repeat test bypassed local Reliable admission.
After Host admission, Reliable correctly deduplicates retransmission of the
same sequence **before** the translator can see it. Consequently, a WK removed
later by cadence is not restored by ordinary retransmission of that WT.
The translator's recovery branch requires another application delivery, such
as the same timestamp carried under a **new** Reliable sequence. The captured
native repeats do not exercise that condition.

New regression uses actual encrypted Pia input, TunnelSim receive/dedup,
CoreTunnelAdapter, translator, cadence and outgoing serialization. Receipts
for timestamps 10 and 12 are emitted; 11 is replaced. A same-sequence retry
does not reach the translator; 240 seconds of virtual time does not restore
it. A deliberately new Reliable sequence does reach the recovery branch.
This confirms a limitation of the old recovery claim, **not that the native
first-UNI stall has been causally explained**. Do not disable dedup or fabricate
new timestamps/game input to make that test pass.

### Both complete logs locate the omission before Core

The offline audit now pairs receipt eligibility (idle WT, actual gpSP callback,
or non-waiting known repeat) with later Core WK admission, not merely Host and
Guest transport boundaries. Missing callbacks are not counted as receipts;
unknown fields/unpaired WKs are inconclusive. Incomplete/source-mismatched
traces cannot receive a complete accounting verdict. No private fields or
cross-machine clock subtraction are added. CLI exit status remains a boundary
audit, not native completion or functional qualification.

| Count | Trial13 | Trial14 |
| --- | ---: | ---: |
| Eligible receipts: idle + callback | 61 + 141 | 37 + 79 |
| WK admitted to Core | 55 | 28 |
| Eligible but never admitted | 147 | 88 |
| Of those, eligible before first UNI | 147 | 88 |
| Unpaired WK / unknown records / receipt-number gaps | 0 / 0 / 0 | 0 / 0 / 0 |

Thus continuous outgoing receipt numbers and `MATCHED_CAPTURED_BOUNDARIES`
can coexist with policy omissions. All 88 trial14 omissions occur before
Core admission; 72 already had actual frontend callbacks and 16 were idle.
They are not evidence that Core/Relay or the radio lost those WKs. No repeat
eligibility events were observed in either Guest trace.

### Rejected shortcut and next closure criteria

A test-only counterfactual preserves **all** receipts while retaining identical
NI retry protection. In the existing 59.727Hz producer / six-frame window /
400ms scripted service model, production cadence delivers NULL at 1.205s with
peak pending backlog 3. Preserving receipts alone misses the 4.5s observation
bound and reaches backlog 212. At 50ms scripted service the lossless candidate
delivers NULL below 2s with backlog below 32. This demonstrates service-budget
sensitivity, not measured radio throughput or a native timeout.

Therefore do not ship a one-line removal of receipt replacement, enlarge the
window, change WK bytes on retransmit, or restore the old NI flood. A candidate
must simultaneously preserve eligible receipt identity, bound admission under
slow service, and deliver NI state changes/NULL promptly. It must retain ordered
opaque Core/Relay forwarding and same-generation cleanup. If this requires a
new cross-endpoint credit/priority contract, design that explicit contract first;
do not hide RFU-aware scheduling inside Core or alter Switch-to-Switch behavior.

WK grouping remains a separate candidate. Native receiver completion after
the initial idle UNI, sustained tagged UNI/player blocks, two-way movement,
trade and bilateral save remain unverified. A separately controlled native
comparison is still necessary to establish causality after a candidate passes
the software gates. This packet neither changes the supported VM build nor
asks the user to reconnect. Prior cleanup identities and pending independent
VM socket verification remain unchanged.

### Packet verification

Same section-8 regression selection on Windows CPython 3.12.14: **139 passed
in 136.74s**, six existing dependency deprecation warnings. The selection
includes the two new real-wire/counterfactual checks and six new accounting
cases, plus actual local relay/virtual-radio two-Generation pressure/lifecycle,
UNI, Reliable bootstrap and Pia liveness checks. First focused selection:
49 passed. Both original two-log audits remain `TRACE_COMPLETE`,
`MATCHED_CAPTURED_BOUNDARIES`, `issues=[]`; receipt omissions are now reported
separately, functional status remains `NOT_ASSESSED`.

The four original trial13/14 log hashes and native-gold hash were rechecked
unchanged. `git diff --check` clean. No full-suite, CI, stock emulator or
physical-game result is claimed; no production change, commit or push made.

## 11. Lossless receipt repair and service-bound checks (2026-09-18)

Approved next unattended step. Branch/base remain `codex/gpsp-endpoint` /
`f4275359722fc02bf281df11d900296038d99c03`; preserve section-10 working changes.
First isolate a test-only lossless-receipt candidate through the existing full
two-endpoint/local-relay/native-Reliable test. The earlier direct-input deficit
model bypasses parent ingress Reliable pacing; it remains an overload bound,
not proof that the full path necessarily behaves identically.

Allowed: cadence/envelope/full-path tests, existing offline audit, this record
and the matching current incident. Initially no production changes. Acceptance:
every eligible receipt retained in order, bounded existing queues, real delayed
END retry and NULL delivery inside the unchanged 4.5-second model bound, 337
tagged UNI exchanges and two-generation cleanup. Preserve the unthrottled
overload counterexample. A test failure must remain visible, not be resolved by
loosening deadlines. No new Core/Relay contract, RFU-aware central scheduling,
wire mutation, enlarged window/timer, synthetic game ACK, dependency, hardware,
VM, release, commit or push. A modeled pass is not native room entry or trade.

The first full-path candidate check passes both generations: all 201 NI-phase
receipts per generation delivered, NULL at 3.141s in each, and 337 sustained
UNI exchanges per generation; trace receipt accounting complete. Together
with the retained overload check: 2 passed in 61.38s. Therefore extend this
same packet narrowly to production `retroarch_gpsp/cadence.py` and related
endpoint/UNI regressions: remove NI receipt replacement/renumbering, retain
identical-NI pacing and existing bounded FIFO admission. No other runtime
policy, Core/Relay or native scheduler change is authorized by this decision.
Finish with receipt-specific saturation/resume/cancellation checks and the
broader regression selection. The direct-input overload risk remains open;
this measured model result does not imply universal throughput/deadline bounds.

Local test-development first failure: initial focused selection had 66 passes
and two new callback saturation setup timeouts. Instrumented repeat reached
240/256 entries, lock free, producer still running at the unchanged 5s setup
bound: it had not reached the intended full-queue condition. Like the existing
full-path pressure fixture, disable asyncio debug stack capture in this isolated
test loop; do not extend the setup, cancellation or NI deadlines. Teardown
completed and the test process exited; no physical/runtime recovery applies.

### Implemented boundary and preserved limits

`RfuCadence` now forwards every translator-authorized WK unchanged, immediately
into the existing bounded driver FIFO. It no longer replaces an unsent NI
receipt with a newer timestamp or renumbers receipts to conceal the omissions.
Idle receipts still originate from validated idle WTs; non-idle receipts still
require the actual frontend callback. No timer creates receipt/game completion.
Identical recognized NI retries retain the same 250ms per-lane pacing. Distinct
NI bytes/states, NULL, UNI, unknown/mixed slots remain opaque and ordered.

The old diagnostic keys remain compatible: `receipts_coalesced=0` and
`receipt_pending=0` now mean cadence has no lossy/deferred side queue, NOT that
the downstream transport has drained. `ordered_receipts` remains the first-UNI
marker used by existing first-UNI diagnostics, not a switch in delivery policy.
`receipt_sequence` observes the translator's original number; actual Core
admission is still established by sequenced `core_enqueued` trace events.

Only `switchtrade/endpoints/retroarch_gpsp/cadence.py` changed in production.
No shared Core/Relay, native Reliable window, wire serializer, RFU1 translator,
NI retry interval, UNI-consumption gate or disconnect/lifetime policy changed.
Ponytail's reuse rule kept the existing FIFO/backpressure and real-path test
infrastructure; no new scheduler, dependency or protocol option was added.

### Validation, including failures retained as counterexamples

- Four new endpoint checks fill all **256** receipt FIFO slots using either
  idle WTs or actual modeled Netplay callbacks. Each source tests ordered
  resume and cancellation while blocked; clean next generation retains the
  same Netplay connection with no stale receipt and fresh numbering. All four
  pass in 0.57s after the setup correction, unchanged deadlines/capacities.
- Existing full-path tests now require **every** NI receipt, contiguous numbers
  and full trace accounting, rather than asserting receipt coalescing. Native
  END must reach the modeled peer twice before its END_ACK is emitted; NULL
  must still arrive within 4.5s under the 400ms peer-service schedule.
- Sustained tests deliver 337 qualified UNI frames each way in each of two
  generations, with eight-frame parent bursts, causal consumption, tag checks,
  exact ordered byte comparisons, complete metadata and virtual-OS cleanup.
  The separate 1,024-frame pressure scenario still exercises bounded native
  and adapter queues and actual waiting admission.
- An additional asymmetric test gives ONLY the synthetic peer a 128-frame
  send window, leaving the product's window unchanged. It passes the same
  lossless receipt/NI deadline/UNI/two-generation requirements. This prevents
  relying solely on a peer copy of our six-frame sender; it does not assert
  the actual closed console has that window or model every radio schedule.
- Preserve `LegacyReceiptCadence` only in tests to reproduce the old omission
  and demonstrate that an ordinary same-Reliable-identity retry cannot repair
  it. The repaired path retains all three original timestamp receipts under
  the same encrypted receive/dedup test; native retry dedup remains intact.
- The unthrottled direct-input counterexample still fails the 400ms-service
  4.5s NULL bound with a lossless FIFO. This bypasses parent native admission;
  it is deliberately retained as a service-capacity limit, not hidden by a
  longer timeout. Sustained input above service capacity cannot have both
  losslessness and a universal latency bound. Finite queue backpressure is
  not evidence that every real native timing requirement is satisfied.

Final selected regression: **171 passed in 157.96s**, eight existing dependency
deprecation warnings; separately the added wide-peer-window full-path check:
**1 passed in 55.84s**, four of the same warnings. Total **172 distinct tests**.
The selection is section 10's 139-check command plus `test_gpsp_endpoint.py`,
the new receipt/dedup cases and wide-peer-window check. No full-suite, CI,
stock-process or physical qualification is claimed. All trial13/14 original
log hashes and native-gold hash remain unchanged. No commit or push.

### What the next controlled trial must distinguish

Do not rerun the unchanged `f427535` VM build. First qualify and identify the
new candidate on both endpoints and close the previously pending independent
VM socket/residue check. Then use one existing empty English Direct Trade
room, record both complete source-matched logs and stop at the first failure.

1. Verify eligible WKs reach Core and native send boundaries without omissions;
   a transport boundary match alone is insufficient.
2. Check that NI END/NULL and approval remain prompt, with no growing queues.
3. After the first idle UNI, look for another parent UNI and player exchange
   (`7700`, then block commands), not merely an empty Reliable window.
4. Only after actual room entry check Host movement, then Guest movement
   separately. Do not combine an entry test with trade/save before entry and
   bidirectional progress are established.

If lossless receipts are verified but the native parent still stalls, that
falsifies this repair as a sufficient explanation. WK outgoing index/grouping,
native completion/clock semantics and later sustained tag/queue behavior remain
separate candidates. Do not synthesize the next parent, rewrite retransmitted
bytes or treat modeled echo traffic as native completion. No more user input
was required for this software packet; physical validation remains outstanding.

## 12. Integrity review and next-test handoff (2026-09-18)

The user clarified product direction: the pre-simplification desktop is legacy;
the Simplified Architecture under development becomes the new application.
Preservation does not require new Core/Pair compatibility with the old GUI/Room
workflow. Switch-to-Switch and driver/endpoint modularity remain regression gates.

The preceding read-only integrity review compared the simplified baseline
`5f27ea95c7d39fa8537df4ee7606244e94bae471` with `f427535` plus this repair.
Windows CPython3.12.14 selected regressions: **604 passed, 3 skipped**. The skips
were one POSIX lock test and two Linux-native cleanup tests, not physical passes.
No forbidden endpoint import was found in the inspected boundaries. Earlier gpSP
work did change shared supervisor/transport/diagnostics; these were tested, not
assumed untouched. The current receipt repair changes only endpoint cadence in
production. Hardware profile/driver policy and legacy desktop remain preserved.

Fresh pre-handoff verification after the testing request: **170 passed** on the
same interpreter, in two non-overlapping selections:

- 107 passed in222.06s: cadence, endpoint, native-envelope, UNI transition,
  RFU trace, real-stack pressure/two-generation and dev-overlay contract tests.
  Ten dependency deprecation warnings; no failures or skips.
- 63 passed in4.46s: repository context policy, gpSP qualification contracts
  and gpSP CLI. These qualification tests are not actual stock-process trials.

The normal Host doctor verifies the existing registered runtime and dependency
hashes. Commit/remote revision, immutable Host overlay and VM update evidence are
per-run facts recorded privately. Do not infer them from passing unit tests.
Prepare trial15 on the trial14 host-local relay route, with fresh log directories
and a new Pair only after independent VM socket cleanup/source/doctor checks.
No CI wait is required for this explicitly requested diagnostic comparison;
qualified use/release still requires the existing exact-SHA acceptance gates.
No room entry, movement, trade, save or native-root-cause resolution is claimed.
