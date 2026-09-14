# Trial11: NI-to-UNI test candidate

Base: `codex/gpsp-endpoint` at `1c28aa23a57891fd5de254d7e7073ddf2b244a21`.
This packet changes the gpSP endpoint and its qualification, not Core/Relay,
Switch firmware, user emulator settings, games or saves. No physical trial is
performed by this packet. Status: **test candidate, not a completed trade**.

## What the physical evidence establishes

Trial11 reached discovery, native connection, both directions of NI, and native
trainer acceptance. At 02:04:51 on the VM transcript it exchanged one parent
UNI of 70 bytes and one child UNI of 14 bytes, then stopped advancing for more
than two minutes. The game screens remained on acceptance/member waiting.
The Host's preserved diagnostics showed a live lower transport and no pending
local Reliable frames. The VM's Core queue was empty. This is beyond the old
unavailable/NI_END failure, but not proof of game-room entry.

The old evidence did not record correlated WT/WK identities or the first UNI
commands. It cannot uniquely distinguish a lost completion from a clock or
game-protocol wait. **The precise physical stall cause is still unproven.**
Raw logs, screenshots, participant identities and recovery receipts stay private.
The previous Host was stopped through its bound owner; its process/VIF absence
and acquired USB lease return were recorded. VM residue was user-reported, not
independently inspected. Do not reuse the retired Pair.

## Source-backed defects and repair

1. **UNI receipts were eligible for latest-only replacement.** During NI this
   policy bounded redundant traffic, but it also applied to the clock-driven
   UNI phase. On the first qualified parent UNI, flush the older deferred WK
   and preserve every subsequent local receipt timestamp in admission order.
   Do not fabricate native NI ACKs or infer receipt of earlier timestamps.
2. **Local ACK did not prove game consumption.** Pinned stock gpSP sends its
   callback ACK before insertion into its four-packet RFU buffer; a full buffer
   can discard data after that ACK. For the qualified two-player FRLG single-UNI
   layout, allow one parent UNI locally until both its callback ACK and the
   child's UNI reply have arrived. Queue subsequent parent frames locally,
   bounded to 255 waiting plus one in flight. Saturation fails closed with
   `TRANSLATOR_QUEUE_FULL`; queued data receives no fabricated receipt.
3. **The previous actual-process oracle used polling.** Add an original
   homebrew that performs NI START/data/END/NULL, then real RFU `0x27` / `0x25`
   inverted-clock exchanges. Delay reads for 90 frames and inject twelve UNI
   frames to exercise buffer admission. A receipt alone or one UNI cannot pass.
4. **The milestone message was too easy to overread.** Keep `Bridge active.`
   for compatibility and add `RFU link established; game-room entry and trade
   are not yet confirmed.` Bounded diagnostics now record first UNI command
   IDs, fragment/tag metadata, first 24 UNI-phase wire admissions and recent
   correlated transfer/receipt timestamps. No game payloads or trainer data.

Consumption credit is specific to the source-backed FRLG child callback, which
reads parent data before sending its UNI response. It is **not** a public gpSP
consumption ACK. Only exact parent-70/child-14 single UNI, zero n/phase, and
parent receiver mask 1 qualify. Unknown/mixed layouts stay opaque. This is not
generic four-player, battle, other-emulator or arbitrary NI buffer management.
Cleanup discards pending converter data and preserves the first failure;
unconfirmed local cleanup still blocks another generation.

Primary references used for the boundary:

- [Pinned gpSP RFU callback/buffer and clock implementation](https://github.com/libretro/gpsp/blob/74db5e5/rfu.c).
- [FRLG child MSC receive/send and UNI commands](https://github.com/pret/pokefirered/blob/c75f352304d529f6ba92d4f74b9cf8b5c3810788/src/link_rfu_2.c).
- [Pinned homebrew wireless peripheral interface](https://github.com/afska/gba-link-connection/blob/c61bf351f68ad2d6e1c9d72d70e21bec19adfc0b/lib/LinkRawWireless.hpp).

## Reproduction and qualification

Reuse the actual native dev/CLI, CoreSupervisor, WebSocket relay, WireClient,
gpSP endpoint and stock RetroArch/gpSP, with actual opposite Direct A,
StageSession, LdnDataPlane, TunnelSim and CoreTunnelAdapter. Replace only the
radio/OS primitives and opposite physical game input. Test-only process/menu
control runs on a private desktop; the product remains observation-only.

`clock.cpp` sends two all-zero idle UNI frames, then native-sized command shapes
`7700/A100/8800/8900`, five parent rows, reflected child data, and wrapping child
tags. All payload counters are original homebrew data. This checks framing and
causal delivery; **it does not implement Pokémon's block/trade state machine**.

Clock fixture SHA256:
`2240ef62642e5eb8e2e2a967532b5926a09a2cd7fe19eb87cec4e175fdfa5a25`.
Two clean builds produced identical bytes; the prior polling fixture rebuilt
identically too. Compiler/dependency identities are pinned in fixture provenance.

Development evidence (dirty base, never final-SHA attestation):

- Actual stock RetroArch 1.22.2 / gpSP 74db5e5, native CPython 3.12.14:
  1,035 sustained exchanges over 60.031 seconds, then 35 over 2.031 seconds;
  twelve delayed-consumer burst exchanges in each generation; same Pair,
  same process, one retained local Netplay connection. Correlated WK and exact
  data verified. Owned sockets/handles/private desktop cleaned, test process
  exited normally, input stock tree unchanged. Private report:
  `.qualification/uni-clock-probe-03/report.json`.
- Focused converter/endpoint/oracle/attestor regressions: 101 passed. Includes
  receipt preservation, FIFO burst delivery, timestamp wrap, strict recognition,
  cancellation with pending UNI, sticky failure, stale generation rejection,
  fresh generation admission and negative clock-oracle evidence checks.
- Final full regression and exact source/process/CI identities belong to the
  final handoff. Development counts above are not a final-source or 30-minute
  soak claim. Windows CI still requires the original actual-process continuity,
  >180-second human waits and 30-minute polling soak, plus the new clock probe,
  separately for Python 3.12 and 3.14. Ubuntu runs shared regressions.

## Remaining blockers and next physical observation

The accepted native room has not progressed to completed commercial room entry.
Keep that unresolved integration observation in `GPSP_ACCEPTANCE.json`; green
homebrew/CI jobs cannot silently convert it into final product completion.
The final attestation gate intentionally remains closed until causal closure.

Next authorized trial should use the [VMware runbook](GPSP_VMWARE_RUNBOOK.md)
and the same candidate SHA on Host and VM, a fresh Pair and fresh log directory.
Do not reinstall RetroArch, change saves, or redeploy the relay for this repair.
If accepted, first require **multiple** parent and child UNI exchanges and game
room entry. If either freezes, preserve first events and both complete logs;
do not reconnect blindly. These traces distinguish callback completion,
consumption-credit wait, queued delivery and Core admission from game waiting.

Later risks, not claims of fixed defects: commercial player-ID/roster exchange,
block fragmentation/retry, multi-row reflection and tag semantics under delay,
trade confirmation/animation/save, normal room exit and a second real trade.
Do not solve a wait by inventing an ACK, replaying a save, extending queues
without bounds, or injecting a game command. Battle/RSE and other endpoints
remain separate work. RFU and frontend-specific policy stay inside the endpoint;
the opaque Core/Relay contract still permits future adapters.
