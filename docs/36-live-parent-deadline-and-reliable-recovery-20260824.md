# 36 — Live parent room-entry deadline and Reliable recovery (2026-08-24)

## Outcome

The `e2979c7` retest proved that suppressing the PC parent's premature standby was correct: row zero
remained idle after LinkPlayer, and the Switch never received an early `READY_EXIT_STANDBY`.  The Switch
still showed `Communication error`, but this was a later and more precise failure than the previous run.

The Switch sent emulator `WD` and closed the RFU link 3.557 seconds after the PC's `WG=1`.  The complete
Switch-to-Switch gold finishes both LinkPlayer blocks about 0.55 seconds after `WG=1`; the PC run took
about 3.17 seconds.  The real Switch therefore reached the same room-entry deadline with only about
0.39 seconds left after its final LinkPlayer fragment.

The child fragment bytes and parent row-one reflection were correct.  The remaining failure was Reliable
loss recovery: consecutive parent sequence holes were recovered two at a time with guest-mode jitter
settings, serializing the room bootstrap until the game closed it.

## Evidence

Local ignored capture directory:

`logs/golden/pc_host_parent_standby_live_20260824_165140/`

| File | Bytes | SHA-256 |
|---|---:|---|
| `host_ldn_mon.pcap` | 2,260,120 | `9585781af93b109848f51da640b0f1e8cb18a7cfb8d669faae3c804988e3d634` |
| `host_ldn_tap.pcap` | 58,272 | `575ce1536dff2c1f535686ba08f62f240352fc9c777062a90805db345c297d7c` |
| `observer_rtl8188_ch6.pcap` | 2,026,663 | `a30cd2fb7ef70af273ae86da521291921c30ac4aa70d3405511459e7774f0f63` |
| `pc_host_pia.jsonl` | 473,066 | `98e71f484fb1ef0e4ed6c9a07ddeb5d06b6f8fc04d98862c5c37dbe03224c31e` |

All three packet captures closed with zero kernel drops.  Both cards passed the pre-run actual-RX health
gate.  The Pia JSON decrypts through the Switch's explicit disconnect.

Timeline relative to `WG=1` (capture time 1.735 s):

```text
+0.108 s  PC SEND_BLOCK_REQ type 0
+0.809 s  first PC LinkPlayer INIT reaches the ordered stream
+1.174 s  Switch starts its LinkPlayer block
+1.909 s  PC sends its last LinkPlayer fragment
+2.684 s  Switch first sends fragment index 16
+3.175 s  Switch is still retrying fragment index 16
+3.557 s  Switch sends WD and closes the RFU link
```

The PC reflected child fragment index 16 in parent row one from capture time 4.421 s onward.  Before
disconnect, the Switch's cumulative Reliable ACK advanced beyond the first reflected frame.  This rules
out a missing rolling-tag strip or missing final-fragment reflection as the immediate cause.

The decisive parent send-window example was:

```text
1.753..1.843  parent seq 0003..0008 sent
1.842..1.894  child SACK proves 0007/0008 arrived while 0003..0006 were holes
1.912..2.525  only 0003/0004 repeatedly recovered (two-frame retransmit limit)
2.544          only after that base advanced could 0005/0006 be retried
```

This is transport delay, not a radio receive-death result: Switch-to-PC traffic remained readable, both
capture radios passed health gates, Pia authentication succeeded, and the Switch explicitly acknowledged
later parent sequence IDs selectively.

## Native comparison

The fixed CH1 gold was independently decrypted again: 18,257 CCMP data frames and 18,252 Pia datagrams,
with zero authentication failures.  Native parent traffic sends one room command about every VBlank and
finishes the bidirectional LinkPlayer exchange around 0.55 seconds after `WG=1`.  After that, both sides
remain idle for 5.083 seconds and the child initiates standby count 0.  The failed PC run never reached that
idle warp period; it closed inside the initial LinkPlayer deadline.

## Fix

Emulator branch `gptsolreview`, commit `31b29bf` (pushed), keeps the proven guest path unchanged and gives
only the PC-parent Reliable link deadline-safe recovery:

- the six-frame in-flight safety bound remains unchanged;
- parent fast-retransmit reacts to the first selective NACK;
- parent RTO is capped at 67 ms (four VBlanks) instead of the guest path's 670 ms tail cap;
- one recovery pass may resend the whole bounded six-frame window instead of only two holes;
- parent mode now honors the Switch's emulator `WD` and stops instead of retransmitting after peer exit.

Verification:

```text
focused parent/Pia tests                  11/11 PASS
Linux hardware/protocol tests           134/134 PASS
Windows relay tests                        4/4 PASS
total                                    138/138 PASS
diff whitespace check                         PASS
```

## Next live criterion

Repeat one Switch joining the CODEX room using `31b29bf` and record the same three captures plus Pia JSON.

1. LinkPlayer completes materially before the 3.56-second deadline (target: no later than `WG=1 + 1.5 s`).
2. Switch changes from fragment 16 to idle instead of sending `WD`.
3. About 5.08 seconds later the Switch sends standby count 0.
4. PC replies twice, waits two idle rows, and requests trainer cards.

If the Switch still sends `WD` despite completing LinkPlayer with ample margin, stop tuning transport and
compare the reconstructed player-zero LinkPlayer semantics and final application rows.  If it remains slow,
measure the new hole/retry cadence before changing the six-frame safety window.

