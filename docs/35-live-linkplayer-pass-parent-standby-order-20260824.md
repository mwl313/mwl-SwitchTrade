# 35 — Live LinkPlayer pass and parent standby ordering (2026-08-24)

## Outcome

The real Switch again accepted the complete PC-parent NI exchange and displayed `CODEX says OK`.
Unlike the previous build, it then accepted `SEND_PLAYER_IDS`, the type-0 LinkPlayer request, and the
PC's complete player-zero LinkPlayer block.  The PC simultaneously reassembled the Switch's player-one
LinkPlayer as `GIRL v0x4004`.  This proves the first parent UNI window and the symmetric LinkPlayer block
exchange on real hardware.

The Switch then showed `Communication error`.  The failure is one gate later and has a byte-specific
cause: the reused child TradeEngine made the PC parent initiate `READY_EXIT_STANDBY count=0` immediately
after LinkPlayer completion.  A native parent does not initiate this gate.

## Evidence

Local ignored capture directory:

`logs/golden/pc_host_parent_uni_live_20260824_162720/`

| File | Bytes | SHA-256 |
|---|---:|---|
| `host_ldn_mon.pcap` | 882,304 | `75317d1c928a8dbd9d117d15a431a5dcdc04ca2e4b21c6ef0fc7bc2548dfcbfa` |
| `host_ldn_tap.pcap` | 53,184 | `cde33aa15be51b287c5f49ce7bfbc76111a73a62189298395245cda9e6cbbfe8` |
| `observer_rtl8188_ch6.pcap` | 1,140,750 | `c1ff3b736d23b03feea4f83d386f9b96ab9ab683808d44502f2d8bdd3f24e694` |
| `pc_host_pia.jsonl` | 240,839 | `dd968727b71c0d737a11b71f572ab28b92ffe03a5b4b22caf2e25452a2f94e8f` |

Capture quality was clean: RTL8192EU host monitor 3,104 packets, RTL8188EU observer 4,540 packets,
and TAP 368 packets, all with zero kernel drops.  Both radios passed actual-RX health gates before the
run.  The Pia JSON decrypts through the decisive exchange.

Live timeline relative to the first post-NI parent UNI:

```text
+0.000 s  parent idle UNI
+0.036 s  SEND_PLAYER_IDS
+0.328 s  parent SEND_BLOCK_REQ type 0
+0.345 s  parent LinkPlayer INIT (owner 0, 17 fragments)
+2.319 s  parent last LinkPlayer fragment
+2.805 s  child last LinkPlayer fragment received; GIRL v0x4004 reconstructed
+2.805 s  WRONG: parent immediately starts READY_EXIT_STANDBY count 0
+2.805..2.893 s  six premature parent count-0 frames
```

The Switch never emitted its own count-0 standby, so the PC never reached the trainer-card request.
It tore down the LDN participant shortly afterward.  Discovery, CCMP, Pia, Reliable, WA, NI, parent
UNI layout, player IDs, and LinkPlayer blocks are therefore no longer candidates for this failure.

## Native comparison

The fixed-channel two-Switch gold was independently decoded again: 18,257 protected 802.11 frames,
18,252 authenticated Pia datagrams, zero failures.  Native timing relative to child `WC` is:

| Time | Native action |
|---:|---|
| +6.816 s | parent requests LinkPlayer block |
| +7.162 s | parent sends its last LinkPlayer fragment |
| +7.269 s | child sends its last LinkPlayer fragment |
| +7.269..12.352 s | **both sides idle for 5.083 s** while the room warp runs |
| +12.352 s | child initiates `READY_EXIT_STANDBY count=0` |
| +12.398 s | parent reflects the child count in row 1 |
| +12.413, +12.433 s | parent replies with count 0 twice |
| +12.448, +12.463 s | parent sends two idle rows |
| +12.478 s | parent requests trainer cards (`SEND_BLOCK_REQ type=2`) |
| +13.296 s | parent reflects child count 1 |
| +13.316, +13.331 s | parent replies with count 1 twice |
| +13.747 s | parent held-key/room traffic starts after about 24 idle command frames |

This is direct evidence that the parent must react to, not initiate, counts 0 and 1.

## Fix

Emulator branch `gptsolreview`, commit `e2979c7` (pushed), now:

- suppresses the child TradeEngine's unsolicited count-0/count-1 warp bursts in parent row zero;
- waits indefinitely and safely in idle UNI until the real Switch initiates each standby;
- echoes a newly observed child count exactly twice;
- leaves two idle parent command frames before the type-2 trainer-card request;
- leaves 24 idle parent command frames after the count-1 reply before arming held-key/seat traffic;
- deduplicates repeated child standby commands so a retry cannot restart the phase.

Verification:

```text
focused parent/Pia tests  10/10 PASS
all emulator tests        137/137 PASS
diff whitespace check     PASS
```

## Next live criterion

Repeat one one-Switch join using `e2979c7`.  The first decisive outcomes are:

1. Switch sends standby count 0 after the native room-warp delay and PC issues type-2 card request:
   premature-parent gate fixed;
2. Switch sends standby count 1 and held-key traffic begins: trainer-card/second warp gate passed;
3. both avatars appear in the room: implement/audit the player-zero seat and leader party/trade flow;
4. an earlier communication error: compare the last parent row 0 and reflected child row 1 against
   the native table above before changing any radio or discovery code.

## Separate shutdown issue

`timeout --foreground` now delivered Ctrl-C to Python, but joined-session `HostTransport.stop()` still
did not finish before the second interrupt.  The wrapper then mislabeled its resulting return code as a
watchdog timeout.  This cleanup defect is independent of the successful wire capture and remains a
production blocker; capture a thread stack before changing the adapter teardown.

