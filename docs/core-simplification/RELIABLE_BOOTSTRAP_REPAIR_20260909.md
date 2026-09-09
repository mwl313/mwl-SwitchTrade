# Independent Reliable receive bootstrap

Branch: `codex/gpsp-endpoint`; verified clean local/remote base
`29ca8b20e9e9d404ae55442631a6aacabc11a853`.
Scope: failed trade join in physical trial07. No battle, physical retry,
radio operation, VM installation, game/save modification or relay deployment.

## Evidence and causal limits

- Guest RFU mode verification and discovery succeeded. One connect request
  left gpSP, but no Switch RFU packet returned; the endpoint stayed connecting.
- Host LDN/Pia RX continued with zero recorded decrypt failures. Its queues
  stayed empty, while the new sequence guard rejected 3,876 received AppData
  frames and next-expected remained `0xFFF0`. These are admission attempts,
  not a count of unique messages. There was no recorded backlog overflow.
- The guard only increments that counter for a sequence mismatch, proving
  the blocking boundary. Trial07 did not log received sequence/flags/window,
  so the precise physical opener and the reason its number differed are not
  recoverable from that run. Do not claim a replay of trial07's missing bytes.
- Guest stopped cleanly later; Host then received `T_PEER_CLOSED`. That is
  secondary to the earlier join stall. Host cleanup and owned-resource absence
  were verified, and only the trial-acquired USB attachment was returned.

Two existing authenticated native fixed-channel captures both start each
direction at `0xFFF0` with Initialized set. They establish the opener shape,
not that all independent streams must share that number. Replaying these
sniffer traces in capture order stops at missing/reordered packets; an offline
sniffer cannot answer retransmission requests. This is NOT an end-to-end pass
or justification to skip a gap. A separate existing direct inbound PC-host
trace contains 5,526 unique contiguous frames and no Pia authentication errors.
All captures, keys, game bytes and device identities remain private.

The public [Pia sliding-window reference](https://github.com/kinnay/NintendoClients/wiki/Reliable-Sliding-Window)
describes independent sequence/window fields, an Initialized flag and selective
acknowledgement. The repo already documented receive-base seeding from the
opening frame, but its new strict tunnel guard still used the local send seed.

## Repair

1. Before a local receive stream is established, require its Initialized
   AppData frame. After bounded downstream admission succeeds, seed receive
   accounting from that frame's sequence. Never alter the local send window.
2. No ACK/deduplication or initialization for bytes not admitted. Before an
   opener there is no known receive base: do not send an ACK using the local
   default. Peer ACK/control processing remains independent and live.
3. Once open, retain contiguous admission, duplicate suppression, wrap-aware
   accounting and retransmission of gaps. Later Initialized flags cannot
   rebase the stream. Keep the existing queue and send-window limits.
4. Reject a Reliable frame whose declared body exceeds its available bytes
   before it can initialize the receive stream.
5. Add numeric first/last receive sequence, flags and sender-window diagnostics,
   initialization state and pre-init waiting count. No RFU payload logging.

The change is confined to the shared endpoint-local Pia/Reliable boundary.
Core/Relay wire contracts and emulator-specific RFU conversion are unchanged.
Both Switch/Switch and Switch/gpSP inherit the fix; no emulator branch is added
to Core or Relay. Legacy game-engine receive policy remains unchanged.

## Verification

Before implementation, new regression cases produced **9 failures, 2 passes**.
The matching-start cases passed, demonstrating the old tests' blind spot.
After implementation, bootstrap/backpressure/local-Pia and real endpoint-path
checks passed **23 tests**. Cases cover independent starts in both roles,
zero and 16-bit wrap, duplicate Initialized frames, missing/delayed init,
full-queue admission, false ACK prevention, continued opposite ACK handling,
truncation, ordered gap recovery, slow ACK pressure and two generations.

The actual CLI Switch/Switch and stock gpSP qualification harnesses now use
independent modeled console send seeds in successive generations. This changes
only physical console input simulation; production init, encryption, parsing,
Core/Relay, local queues and process call paths remain exercised.

Full regression, actual-process results and exact pushed SHA/CI status are
recorded in the final handoff. Unit/harness success is not a commercial trade.
The next authorized physical trial must confirm the new receive header evidence,
WA response/continued RFU, game entry, trade/save/return, and a second generation.
If Initialized is absent or the peer's first response violates the modeled
contract, preserve that new evidence instead of relaxing the gate or retrying.
