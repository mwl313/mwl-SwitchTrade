# 37 — Live batched-child reflection failure and fix (2026-08-24)

## Result

The parent Reliable recovery change did its job: the PC completed the two LinkPlayer blocks much faster.
The real Switch still closed the room, first showing FireRed's communication-error screen and then the
native Switch error `2318-0006`. Nintendo describes this code broadly as failure to start a local wireless
game, failure to complete matchmaking, or disconnection from a match. The code therefore corroborates a
local communication teardown but does not by itself identify a radio fault.

The decrypted wire identifies the actual defect. Switch AppData arrived in strict Reliable sequence order,
and every child LinkPlayer fragment reached the PC. Several child RFU `T` frames were coalesced into one Pia
datagram, however. `Sim.process_datagram()` delivered all of them before the next parent VBlank, while the
parent kept only one `_parent_child_cmd`. Each new child command overwrote the previous one. The next parent
UNI row one consequently reflected only the last command in that batch.

The Switch sent LinkPlayer fragment indexes `0..16`. The PC reflected only:

```text
3, 5, 7, 12, 13, 16
```

It never put these received fragment states in parent row one:

```text
0, 1, 2, 4, 6, 8, 9, 10, 11, 14, 15
```

The local TradeEngine still reconstructed `GIRL v0x4004` because it consumed every command immediately.
That local success hid the peer-visible failure: the Switch did not receive the full sequence of child
command reflections, repeated fragment 16, and then sent explicit `WD`.

## Capture evidence

Directory:

```text
logs/golden/pc_host_parent_fast_recovery_live_20260824_171500/
```

| File | Packets/result | SHA-256 |
|---|---:|---|
| `observer_rtl8188_ch6.pcap` | 3,454, zero kernel drops | `5911965718967FAFAAD00205AD35A61AAE817BAF1278434339F2C67459B3E229` |
| `host_ldn_mon.pcap` | 2,342, zero kernel drops | `2079835FF0C6993BA91357018F91DE5485C0DBA0BFD1048E47D08CA0A95D275B` |
| `host_ldn_tap.pcap` | 200, zero kernel drops | `F4DF9DE0553E2385373E7F1F87F7143061E7AC97E2479ACD33D2B6D44F063BC0` |
| `pc_host_pia.jsonl` | 194 records through explicit disconnect | `7C89202CDDB42B3034DC7C5F4C2C4DAB42DB3486A4BEC450A6D36ACCDC9AE75D` |

Key decrypted events, in capture-relative time:

```text
1.108 s  parent WG=1; UNI is armed
1.319 s  parent requests LinkPlayer block type 0
1.337 s  parent LinkPlayer INIT
1.957 s  parent LinkPlayer fragment 16
1.512 s  child LinkPlayer INIT repetitions begin
1.937 s  child fragments 0..3 arrive in one burst
2.133 s  child fragments 6..10 arrive in one burst
2.775 s  child fragments 14..16 arrive in one burst
2.869 s  child is still repeating fragment 16
3.045 s  child sends WD
```

Every unique incoming AppData Reliable sequence was contiguous from `fff0` through `0064`. This rules out
the proposed out-of-order-delivery cause and is strong evidence against receive death, channel drift, or a
capture blind spot in this attempt. The problem was between decrypted Pia delivery and parent RFU emission.

## Code fix

Emulator commit `0a8d9a0` on `gptsolreview` adds one parent-only FIFO at the RFU boundary:

- enqueue every changed child UNI command in arrival order;
- coalesce exact repeats after stripping the child's rolling tag because they contain no new RFU state;
- expose the oldest queued command in parent row one;
- pop it only after the parent Reliable frame was successfully queued;
- keep the mature guest path unchanged.

The focused regression injects fragment states `0, 1, 1, 2` in one batch and requires parent row one to emit
`0, 1, 2` on successive VBlanks. Verification passed:

```text
WSL/Linux non-relay suite: 135/135
Windows relay suite:         4/4
Total:                     139/139
```

## Radio state after the run

The RTL8192EU remained USB-attached and bound to `rtl8xxxu`, but host cleanup had removed its final netdev.
The existing selector recovered it without USB detach: it created `stmon0`, received real frames on channel
1, and restored channel 6. The RTL8188EU/vendor `8188eu` independently passed the same actual-RX gate and was
restored to channel 6. This was normal recoverable netdev lifecycle state, not either card's receive-death
condition.

## Current roadblock and next proof

The code defect is fixed and unit-locked, but the fix is not yet a hardware success claim. One patched live
join is required. Keep the same dual-radio health gates and full Pia capture. The pass gates are:

1. parent row one exposes child fragment indexes `0..16` in order;
2. the Switch changes from fragment 16 to idle instead of sending `WD`;
3. neither FireRed communication error nor native `2318-0006` appears;
4. child standby count 0 appears, the parent replies, and the trainer-card/room-warp gate begins.

If gate 1 passes but the Switch still disconnects, stop transport tuning and compare the child-completion
transition and first standby window byte-for-byte with the native capture. If gate 1 fails, inspect only the
new queue/emission path; the radio, CCMP, Pia ordering, WA, NI, and both LinkPlayer payloads have already
passed their evidence gates.

Nintendo reference: [Error Code 2318-0006](https://en-americas-support.nintendo.com/app/answers/detail/a_id/60532/~/error-code%3A-2318-0006).
