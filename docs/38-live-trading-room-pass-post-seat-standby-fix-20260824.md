# 38 — PC-host trading-room pass and post-seat standby fix (2026-08-24)

## Outcome

The real Switch completed every PC-host entry layer through the visible trading room. It accepted the
queued child LinkPlayer reflection fix, exchanged both trainer cards, passed standby counts 0 and 1,
loaded the room, displayed both avatars, and sustained live movement traffic. This is the first PC-host
run to prove the complete path from discovery through interactive room presence.

When the user walked to the chair and initiated the trade, the Switch faded to black and waited. The
radio link remained healthy and the child continued transmitting. Decrypted Pia data isolated one exact
application deadlock:

```text
child/Switch     READY held key 0x16
parent/CODEX     reflects READY and sends its own READY
child/Switch     READY_EXIT_STANDBY count=2, repeatedly
parent/CODEX     READY_EXIT_STANDBY count=3, repeatedly   <-- wrong
```

The parent never sent row-zero count 2. The Switch therefore could not complete its count-2 standby
callback, while CODEX waited for count 3. This is not a beacon, channel, association, CCMP, Pia,
Reliable, RFU reflection, radio receive-death, or hardware-capability failure.

## Evidence and provenance

Local ignored capture directory:

`logs/golden/pc_host_parent_reflection_fifo_live_20260824_175304/`

The directory contains `MANIFEST.md` with the exact launch command, user timeline, hashes, packet-close
statistics, and protocol boundary. Raw pcaps, decrypted Pia JSON, and keys remain local and ignored.

| File | Bytes | SHA-256 |
|---|---:|---|
| `host_console.log` | 19,398 | `a44a6e82f8b80925caa137fbb6207fe2ccc85de7dbd2240de426098269e079fe` |
| `host_ldn_mon.pcap` | 8,143,004 | `e7e831aecb0586a4c43039848046588795984c3dbba31b5263736e85967d8ada` |
| `host_ldn_tap.pcap` | 2,084,532 | `dd6ec5e8f9a1f7beee16f23f39984c7dd8b29cbf4a7b913ae03db0767db7096b` |
| `observer_rtl8188_ch6.pcap` | 6,793,251 | `b2e0871d2a5109d4b2c6012ca2a60280bc631972ff68d25f27fbbbd46c2a20e2` |
| `pc_host_pia.jsonl` | 4,730,861 | `cac2efd4db9521f8f0354fa777b98854d8bac141d6b1cf0693c6d4b3187c2ca2` |
| `run_host.sh` | 778 | `a1ba0e9898ce604cfcd3b4d3087bff092ac0a8808e1eaeb89c1db8ee8526d6a6` |

The tested emulator commit was `0a8d9a0`. RTL8192EU host monitor captured 32,833 packets with zero
kernel drops. The independent RTL8188EU observer captured 32,862 with zero kernel drops. Both radios
passed the post-test actual-RX health gate. TAP disappearance occurred only during the intentional stop.

## Milestones proved by this run

1. Switch accepted parent `WA`, NI, `WG=0`, join status, and `WG=1`.
2. All incoming parent Reliable AppData was contiguous; there were no missing child Reliable frames.
3. Child LinkPlayer fragments `0..16` all occupied parent row one in order. The new FIFO passed live.
4. No child `WD`, FireRed communication error, or native `2318-0006` occurred during room entry.
5. Child-initiated standby count 0, trainer-card exchange, and count 1 passed.
6. Both avatars entered the trading room and live held-key/movement exchange remained stable.
7. Both avatars sat; the only failed boundary was the next RFU standby count.

## Root cause

The parent-mode shim already suppressed the reused follower `TradeEngine`'s unsolicited counts 0 and 1
and answered those counts only after the child initiated them. It did not apply the same rule to post-seat
counts 2 and 3.

On child count 2, `Sim._on_gba_in()` reflected the Switch command into the follower engine's apparent
host row. That set `barrier.host_count=2`, so the child-oriented post-seat state machine immediately chose
count 3. `Sim._drive_parent_reliable()` suppressed only counts 0/1 and leaked count 3 into parent row zero.

Live Pia timing around the deadlock:

| Pia-relative time | Event |
|---:|---|
| 89.461 s | child held-key READY `0x16` |
| 89.480 s | parent reflected READY and emitted its READY |
| 90.320 s | first child `READY_EXIT_STANDBY count=2` |
| 90.393 s | first parent `READY_EXIT_STANDBY count=3` |
| 90.320 s onward | child repeated count 2; parent repeated count 3; no progress |

## Independent source audit

The current `pret/pokefirered` decompilation at commit
`c75f352304d529f6ba92d4f74b9cf8b5c3810788` agrees with the capture:

- `src/link_rfu_2.c:Rfu_LinkStandby` has different child and leader branches.
- The child sends its current `READY_EXIT_STANDBY` count.
- Player zero's leader branch waits until every child `readyExitStandby` flag is set, then emits the
  matching parent command; it cannot legally skip ahead.
- `src/cable_club.c:Task_StartWirelessTrade` sets the standby callback and waits for the RFU task to
  finish before creating the trade menu. A mismatched count therefore produces exactly the observed
  black-screen wait.

This independently validates the application-layer interpretation; the fix is not inferred from UI alone.

## Fix

Emulator branch `gptsolreview`, commit `ff81318` (pushed), now:

- treats all four room-entry standby rounds, counts `0..3`, as child-initiated in PC-parent mode;
- replies twice with the exact child count;
- preserves the measured count-0 card-request and count-1 seat idle gaps;
- adds no artificial gap after counts 2/3;
- suppresses every unsolicited follower-engine entry count from parent row zero;
- leaves the mature guest/follower path unchanged.

The focused regression recreates the live failure by making the reused engine choose count 3 immediately
after child count 2. It asserts parent row zero emits count 2 twice, idles instead of leaking count 3,
then emits count 3 only after the child initiates count 3.

Verification:

```text
focused count-2/count-3 regression                 1/1 PASS
parent/Pia suite                                  12/12 PASS
WSL ordinary suite                               135/135 PASS
Windows relay suite (.audit-venv)                   4/4 PASS
combined                                           139 PASS
```

The WSL full-discovery command still reports the known relay-fixture setup error because that Linux venv
does not contain `uvicorn`; the same four relay tests pass in the pinned Windows audit venv. A system
Python 3.10 run is not authoritative because its older `websockets` API rejects `recv(decode=False)`.

## Next live gate

Repeat the same one-Switch CODEX-host test using `ff81318`:

1. join CODEX and enter the room;
2. walk to the chair and initiate the trade;
3. verify parent row zero answers child count 2 before count 3;
4. verify the black screen clears and the trade menu/party exchange begins;
5. stop and preserve evidence at the first new boundary if it does not progress.

Do not retune the radios, Reliable window, RTO, FIFO, beacon, or NI path for this retest. They all passed
the same live run. The likely next unproved layer is player-zero party pulling and leader trade commands,
but it must be confirmed by the patched wire before implementation.

## Separate teardown defect

The joined-session host radio thread again exceeded the 15-second teardown grace, so `HostTransport`
correctly refused concurrent vif cleanup. The selector then removed the stale host vif and both cards
passed actual receive health. This remains a production-cleanup issue, not an in-session protocol fault.
