# Trial09: NI completion stall and secondary retirement race

Follow-up: [trial10 cadence repair](GPSP_JOIN_CADENCE_REPAIR_20260910.md) uses
new correlated evidence and deadline regressions. The burst-delivery policy
and open hypotheses below describe the trial09 repair, not current acceptance.

Branch: `codex/gpsp-endpoint`; clean local/remote repair base:
`db3975058e7a76c8e1e5f4099ee55b4c89141fb9`.
Scope: unattended software diagnosis and repair. No physical retry, radio/USB
operation, VM manipulation, installation, game/save change or relay deployment.

## First failure versus secondary failure

The correlated private trial09 logs show native connection acceptance, child
NI_START, matching parent NI_START_ACK, and child NI data in phases 0/1/2 with
matching parent NI ACKs. The child then emitted NI_END 185 times without an
observed parent NI_END_ACK. No subsequent NULL, parent NI transfer or UNI was
observed. gpSP disconnected first. This is a failed game join, not a discovery
failure or proof that RFU1 socket acknowledgements mean game consumption.

One millisecond after DISCONNECT, a late Switch packet changed the translator
from closed to failed. Guest cleanup was clean but its final outcome was
S_PUMP_FAILED; the Host subsequently observed peer-close. The physical log did
not include the original translator exception stack. A deterministic software
reproduction now establishes the matching race as TRANSLATOR_NOT_ACTIVE:
`feed(DISCONNECT) -> final WD queued -> send(in-flight WT) -> failure`.

## Retirement fix

The endpoint now discards in-flight input for its already-finished generation
after checking generation/protocol ownership. It still drains the final WD
before reporting GenerationEnded. The translator remains strict, cleanup remains
fail-closed, and foreign-generation DATA is still rejected. Core/Relay and RFU
wire conversion are unchanged. This fixes the secondary Pair shutdown, **not**
the preceding native NI stall or the commercial trade.

- Red baseline: the new retirement regression failed with
  TRANSLATOR_NOT_ACTIVE before the production guard.
- Green: Windows Python 3.12.14, `tests/test_gpsp_endpoint.py`: 22 passed.
- The real WebSocket relay test deliberately holds outgoing WD, delivers an
  in-flight WT from the other Core, then releases WD. Both generations retire
  normally on the same Pair and local Netplay connection, with bidirectional
  DATA in the second generation. Its Switch and frontend inputs are modeled;
  it is not a physical Switch or actual-stock-process qualification.

## Native NI investigation

[Pinned gpSP](https://github.com/libretro/gpsp/blob/74db5e5/rfu.c) emits
CLIENT_SEND immediately and ACKs HOST_SEND before checking the four-entry
game-facing buffer. A socket ACK cannot justify dropping game retransmissions.
[Pinned native librfu](https://github.com/pret/pokefirered/blob/c75f352304d529f6ba92d4f74b9cf8b5c3810788/src/librfu_rfu.c)
requires the matching NI_END acknowledgement to advance its sender to NULL.
The observed END n=0/phase=0/size=0 is consistent with that state machine.

At first END the Guest had enqueued 131 Core packets. The preceding Host
snapshot had scheduled only 19 new local Reliable frames, six still in flight,
87 pending and RTO 109 ms. This is a concrete latency/backlog hypothesis, not
proof of which frame the Switch received before its game deadline. The last
Host periodic snapshot preceded first END; final receive counts alone cannot
close that gap. Do not fabricate an END ACK, drop repeated NI, enlarge the
Reliable window or raise a game timeout on this evidence.

## Additional terminal-completion defect

The expanded integration assertion exposed an intermittent early return from
`CoreSupervisor.wait_generation_end()`. A separate deterministic test failed
before the fix: after `close_generation()` clears its pump set, endpoint close
can still be waiting. A new waiter previously returned immediately, before
cleanup verification, final peer-close drain and clearing generation ownership.

The waiter now crosses the existing close lock after waiting for pumps. Clean
cleanup must finish before success; dirty cleanup must publish and surface its
original terminal error. No new Core state, endpoint branch or protocol message
was introduced. This protects the CLI's next-generation flow for both Switch and
gpSP. It does not explain the earlier game NI timeout.

## NI pressure and final-position evidence

The actual relay/Direct A/B/StageSession/LDN/TunnelSim test now includes 20
copies of each child NI data phase and 185 NI_END frames. All copies must reach
the modeled console boundary unchanged, in timestamp order, before its modeled
native ACK is injected. NULL, parent NI/join status and bidirectional UNI follow,
then the existing 1,024-frame slow-ACK pressure test. Repeat on the same Pair and
Netplay connection for generation two. This is burst/delivery qualification,
not a reproduction of the commercial game's VBlank cadence or timeout. It
shows no unconditional NI_END encoding/drop failure in that modeled path.

`switch_rfu_progress` now also emits `event=stopped` after its runner ends but
before simulation cleanup. This captures final new-send, in-flight, window and
receive counters even when the entire game failure falls between five-second
samples. Adapter queues are already sealed at this point: zero queue depth is
**not** proof that the prior backlog drained. A stuck runner is not read
concurrently; unavailable diagnostics are logged without masking cleanup.

On a separately authorized diagnostic trial, match generation IDs and compare
the Guest's first-NI_END `core_enqueued` ordinal with the Host's final
`reliable_tx_new` and `reliable_inflight`. If the send count never reaches that
ordinal, END never reached local Reliable transmission; if it does, distinguish
unacknowledged local transmission from acknowledged transport. Even a local
Reliable ACK is not proof that the physical game's RFU receiver consumed END.
Keep complete logs through cleanup, not just the last traceback. No relay or
emulator reinstall is needed for these source changes.

## Verification results

All runs below are local Windows software checks. Test names identify modeled
scope; none is evidence of a commercial-game trade or new stock-process soak.

| Runtime | Focused selection | Result |
| --- | --- | --- |
| Python 3.12.14 | gpSP endpoint, real NI/pressure path, Core supervisor, Switch CLI, agent-context policy | 73 passed, 75.16 s |
| Python 3.14.7 | real NI/pressure path, Core supervisor, Switch CLI | 46 passed, 60.04 s |
| Python 3.14.7 | gpSP endpoint and gpSP CLI after the Core fix | 45 passed, 8.13 s |
| Python 3.12.14 | Switch driver, RFU conversion/progress, bounded flow, receive bootstrap, agent-context policy | 95 passed, 2.36 s |

Both functional races have a failing-before/fixed-after regression. Earlier
development runs also found two unprepared diagnostic test fixtures (corrected
to use prepare before discover) and the late-waiter failure described above;
those failed runs are not reported as successful qualification. Final checks
have existing dependency deprecation/fixture collection warnings, no failures.
Full pytest and final-SHA Windows/Ubuntu CI are not claimed or waited on in this
bounded repair. No source/runtime/physical gate was bypassed.

## Recovery and remaining boundary

Before this packet, trial09 Host cleanup was verified, run-owned processes and
VIFs were absent, and only the run-acquired USB attachment was returned. The VM
reported clean endpoint cleanup; VM residue was not independently inspected.
That Pair is retired and must not be reused.

The native NI completion/root gameplay failure remains open. This record is
not an overall preflight PASS, trade-success claim or instruction to retry.
New-SHA CI is separate; per user instruction it is not a blocking wait here.
