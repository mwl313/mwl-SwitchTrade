# Trial10: timely native NI completion, not just eventual delivery

Branch: `codex/gpsp-endpoint`. Clean local and actual remote repair base:
`f3f3627a1327f906d760052f2ca6a65aef6b2a5d`.
Scope: unattended software repair and regression. No physical retry, emulator
operation, WSL/USB operation, installation, game/save/config change or deployment.
Final commit identity is the commit containing this record; CI is not awaited.

## What the existing evidence establishes

The closed Host log and user-provided VM transcript were preserved privately,
with hashes and matching source/generation identity. Raw logs, addresses,
process identities and game data are not included here. Durations below use
the VM's own clock, not an assumed synchronized Host clock.

| Trial10 observation | Interpretation |
| --- | --- |
| Native connect acceptance and NI phase 0/1/2 acknowledgements | Discovery and the early native exchange progressed |
| First child NI_END at Core enqueue ordinal 51 | A specific completion transition, not a packet-count readiness claim |
| Actual parent NI_END_ACK 3,138 ms later; 189 END copies accumulated | Unlike trial09, END did reach the physical parent |
| Child NULL at Core enqueue ordinal 429 | The game advanced in response to its native END_ACK |
| Host final new Reliable frames 75; six in flight; pending queue 256/256 | NULL never reached local Reliable scheduling; dequeue to Core was not delivery |
| Switch WD; no parent NI transfer or UNI observed | Game join failed; trade was not reached |
| First-generation cleanup clean; later peer-close after Host Ctrl+C | Cleanup/intentional shutdown did not cause the earlier join failure |

This is a demonstrated head-of-line delivery gap. It does not reveal the
commercial game's exact internal timeout or prove all later trade stages.
The previous retirement and terminal-cleanup fixes are preserved.

## Protocol boundary and repair

[Pinned gpSP](https://github.com/libretro/gpsp/blob/74db5e5/rfu.c) emits
CLIENT_SEND immediately; its HOST_SEND callback sends CLIENT_ACK before testing
the small game-facing receive buffer. That receipt is not a native game ACK.
[Native librfu](https://github.com/pret/pokefirered/blob/c75f352304d529f6ba92d4f74b9cf8b5c3810788/src/librfu_rfu.c)
distinguishes NI state, n, phase and the native acknowledgements that advance it.

`RfuCadence`, inside the gpSP endpoint only, now controls admission of translated
repeated traffic before any Core or local Reliable sequence is allocated:

- A single recognized NI_START/NI/NI_END subframe is paced only when its exact
  bytes repeat on the same acknowledgement/direction and phase lane within
  250 ms. Changed state, n or payload is admitted immediately. The game must
  originate any later retry; no NI retry or acknowledgement is synthesized.
- NULL, UNI, mixed/padded/unknown slots and distinct data remain uncoalesced.
  NULL/opaque transitions clear the small lane cache. The maximum cache is
  eight lane entries, not a timestamp or data history.
  A native state transition also clears that direction's other phase lanes,
  so a new transaction cannot inherit a previous transaction's retry identity.
- Retain one latest-arriving **unsent** WK receipt, flushing at 250 ms cadence
  (also from the existing periodic task when local input becomes quiet).
  Number WK when admitted; keep its exact acknowledged timestamp and mid.
  This is not a cumulative acknowledgement, a timestamp array or proof of
  game consumption. Already-enqueued frames are never removed or renumbered.
- The converter now reissues WK for a byte-identical known Switch WT only
  after its local Netplay receipt completed, or for an idle WT. It does not
  re-deliver that timestamp to gpSP. Before the local receipt, duplicate WT
  remains silent. Changed timestamp contents and unknown stale timestamps
  still fail closed. This closes a latent receipt-recovery hole in the old
  timestamp deduplicator, especially important when an unsent WK is replaced.
- Close retires the pending receipt and lane state, cancels the existing
  periodic task and uses the existing sticky cleanup/barrier contract. Each
  new generation starts with a fresh cadence and converter.

The existing legacy Sim provides evidence that WK traffic must not crowd out
critical T frames and bounds K admission separately. Its comments discuss
droppable K, but its current `_queue_k_ack` actually refuses admission at its
limit and lets a repeated timestamp retry later. **This change is not a copy of
that algorithm or a claim that latest-only WK was already physically proven.**
Its corresponding retry recovery is explicitly implemented and tested here.

The 250 ms values are bounded endpoint retry policy, not human/game timeouts,
not a guarantee about every radio service rate, and not a new advertised RFU
protocol. Core/Relay remain opaque; Direct A/B, LDN, TunnelSim, the proven
six-frame Reliable window, flags and dependency versions are unchanged.

## Regressions and what they prove

1. A deterministic 59.727 Hz producer / approximately 15 frame-per-second local
   service model uses the real translator, CoreTunnelAdapter and TunnelSim
   Reliable scheduling. The old FIFO fails to deliver NULL within 4.5 seconds
   and accumulates at least 256 queued frames. Cadence delivers NULL in less
   than two seconds with fewer than 32 queued frames in this specific model.
2. The actual WebSocket relay / WireClient / CoreSupervisor / gpSP driver /
   Direct A+B / StageSession / LDN / TunnelSim path exercises native NI_START,
   NI phase data, then 60 Hz END retries against 400 ms console service. The
   physical-input model intentionally withholds the first native END reply.
   Only a second END actually delivered at that boundary permits END_ACK; only
   receipt of that native response permits the frontend input to send NULL.
   NULL must arrive within 4.5 seconds. WK retry recovery is checked separately
   without sending duplicate data into the frontend buffer.
3. Parent NI/join-status and bidirectional UNI follow. The full-path test then
   delivers 1,024 distinct packets unchanged under 100 ms radio ACK service,
   reaches real bounded backpressure, and repeats on the same Pair and local
   Netplay connection after physical-input room teardown. Owned modeled
   resources must be clean before the second generation and final return.
4. Focused checks cover state/n/phase/byte changes, timer-delayed retries,
   30-minute **simulated** scheduler pause (not a new process soak), opaque/UNI
   preservation, malformed duplicate flags, bounded receipt history, timestamp
   wrap, quiet flush, cleanup, stale input and new-generation reset.

These tests replace OS/radio and console/frontend input boundaries. They do
not use an actual Nintendo Switch, stock RetroArch process or commercial ROM.
Existing stock/homebrew CI remains required for its own qualification claims;
this packet does not relabel modeled tests as that evidence.

## Verification ledger

All results below are local Windows software tests, not actual-stock or
physical-game qualification. No local Ubuntu/WSL test was started.

| Source scope / runtime | Selection | Result |
| --- | --- | --- |
| Initial cadence revision, Python 3.12.14 | Full pytest, tests + bridge/tests | 1,085 passed, 6 skipped, 838.02 s |
| Receipt-recovery revision, Python 3.14.7 | gpSP cadence/endpoint/RFU/real path/CLI, Core lifecycle/supervisor, RFU flow | 145 passed, 91.79 s |
| Final production source, Python 3.12.14 | cadence, RFU, endpoint, actual relay/LDN timed two-generation path, agent-context and qualification contracts | 107 passed, 92.74 s |
| Final production source, Python 3.14.7 | cadence, RFU and endpoint including receipt/transaction reset | 78 passed, 4.89 s |

The full run collected modules **before** the later WK retry and NI state-reset
follow-ups. It is deliberately not labeled an exact-final-source full pass;
the final affected selections above were rerun after both changes. The six
full-suite skips require POSIX/Linux process-group, shell or nl80211 primitives;
they are not failed or completed physical checks. Existing dependency
deprecations and fixture-class collection warnings remain. Same-final-SHA
Windows/Ubuntu CI and stock/homebrew reports are not claimed or awaited.

Earlier failed development runs are not passes: an old test waited for every identical NI
copy, and a new test initially misspelled the exception class. The obsolete
expectation and typo were corrected. The hanging test's exact owned Python
process was terminated after identity checks; no physical/emulator process was
involved. Private recovery evidence records the unsuccessful first stop call
and subsequent verified test-process absence.

## Next authorized physical test

Do not reuse trial10's retired Pair. No reinstall or relay deployment is
required by this endpoint-only packet; update both checkouts and use a new
log directory/new Host Pair in a separately authorized trial. Keep the existing
supported RetroArch/gpSP binary and user-controlled game/Netplay workflow.

Observe these milestones independently: native END_ACK, NULL, parent NI
exchange, UNI, game join, party/trade selection, actual trade completion, then
clean room exit and a second generation on the same Pair. `Bridge active` alone
is not game-join or trade success. Collect both complete logs through cleanup,
including `cadence.ni_paced`, `receipts_coalesced`, pending receipt/lanes and the
Host's final Reliable counters; no default raw packet/save collection.

If unavailable recurs, stop that attempt and identify the earliest missing
milestone before changing another layer. Correlate generation and packet
ordinals with final local send position. Report the first functional failure
separately from cleanup and later intentional peer close. Do not widen the
Reliable window, manufacture native ACKs or keep blindly retrying.

Remaining physical risks include native tolerance of the retry/receipt cadence,
radio loss and scheduling tails, parent-side native receive-buffer behavior,
and commercial party/trade/save transitions not yet observed. Genuine UNI or
other distinct-data production can still exceed radio service; it retains
bounded backpressure, not a promise that every slow link meets a game deadline.
Battle, other games/languages and other emulator cores are not qualified here.
The policy is endpoint-local; a future mGBA/VBA implementation must validate its
own transport and RFU contract instead of inheriting gpSP's timing assumptions.

Verdict: software repair with scoped regression evidence; physical trade
remains unverified. No overall preflight PASS or trade-success claim.
