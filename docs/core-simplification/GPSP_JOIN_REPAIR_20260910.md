# Trial09: NI completion stall and secondary retirement race

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

## Recovery and remaining boundary

Before this packet, trial09 Host cleanup was verified, run-owned processes and
VIFs were absent, and only the run-acquired USB attachment was returned. The VM
reported clean endpoint cleanup; VM residue was not independently inspected.
That Pair is retired and must not be reused.

The native NI completion/root gameplay failure remains open. This record is
not an overall preflight PASS, trade-success claim or instruction to retry.
New-SHA CI is separate; per user instruction it is not a blocking wait here.
