# 34 — Live parent NI pass and UNI room bootstrap (2026-08-24)

## Outcome

The real Switch accepted the PC parent's complete RFU NI exchange for the first time.  Its UI
advanced from the old failure (`Awaiting CODEX's response` → `Trainer unavailable`) to:

```text
CODEX says OK
Pokemon Trades! Awaiting other members!
```

`CODEX says OK` is direct game-level confirmation that the five-frame parent NI status transfer
carried `JOIN_GROUP_OK=5` and was accepted.  The following waiting screen is the next protocol state,
not a retry of the old failure: the tested build stopped after `WG=1` and emitted no parent UNI
frames, so the Switch had no player-zero command stream from which to build the two-player room.

This rules out discovery, radio RX, association, CCMP, Pia, Reliable, `WC/WA`, and both NI directions
as the current room-entry fault.

## Evidence

Local ignored capture directory:

`logs/golden/pc_host_parent_ni_live_20260824_154857/`

| File | Bytes | SHA-256 |
|---|---:|---|
| `host_ldn_mon.pcap` | 7,855,267 | `b2c24fcb08c6e634da09c6f10087e0c0a09811a59472c295c7e938568987381b` |
| `host_ldn_tap.pcap` | 700,406 | `ee0ed92afa5ed11c8052447263253e096743a8399dc49971ed962a0cf796c17a` |
| `observer_rtl8188_ch6.pcap` | 6,679,315 | `3b65d2018d737700d33436c0386e916ad999e6a9055c9074b4509428f6f550ca` |
| `pc_host_pia.jsonl` | 1,609,389 | `a2302c117c8be7a0212925d1131bbf22ff8abf7ba076cc78068cf06c5b1aed2c` |

Both RF captures reported zero kernel drops: 30,582 packets on the RTL8192EU host monitor and
30,008 on the RTL8188EU observer.  The TAP captured 5,699 packets with zero drops before the host
cleanup removed that virtual interface.  Both radios passed their post-run actual-RX health gates
and were restored to channel 6.

```text
channel/BSSID        6 / a0:47:d7:b0:2b:39
Switch               98:41:5c:79:41:38
subnet               169.254.48.0/24 (PC .1, Switch .2)
PC RFU session id    0xc8d7 (wire d7c8)
Switch WC id         2f51
Pia JSON records     5,456
Pia auth failures    0
```

Offline decoding recovered all 5,456 JSON records with zero authentication failures.  Reliable
message counts were 1,996 Switch→PC and 2,980 PC→Switch.  The decisive RFU sequence was:

```text
Switch WC 2f51
PC WA d7c8/2f51
Switch ACKs WA
PC sends first parent poll
PC ACKs every child NI sub-frame
PC sends WG=0
Switch ACKs each parent JOIN_GROUP_OK NI sub-frame
PC sends WG=1
Switch UI: CODEX says OK
```

After `WG=1`, the old build continued only parent idle polls and transport acknowledgements.  The
capture contains zero parent LLSF state-4 UNI frames and zero child UNI frames.  That byte-level
absence explains `Awaiting other members!` exactly.

## Native UNI truth used for the fix

The native CH1 gold was decoded again through all 18,257 protected frames and 18,252 Pia datagrams
with zero CCMP or Pia failures.  The first room-entry UNI sequence after `WG=1` is:

| Native frame | After `WC` | Parent row 0 |
|---:|---:|---|
| 1745–1747 | 6.731–6.746 s | two empty parent UNI polls |
| 1753 | 6.768 s | `SEND_PLAYER_IDS`: `007702000100...` |
| 1761 | 6.816 s | `SEND_BLOCK_REQ` type 0 |
| 1764–1820 | 6.831–7.162 s | parent LinkPlayer block, owner 0, 17 fragments |

Every parent UNI slot is 73 bytes: three-byte LLSF `46 00 05` followed by five 14-byte command
rows.  Row 0 is the parent command.  Row 1 reflects the latest child command after clearing the
child's rolling tag; rows 2–4 are zero.  After the LinkPlayer exchange the native child emits standby
count 0, the parent requests both 100-byte trainer cards, and standby count 1 releases seat traffic.

## Implemented

Emulator branch `gptsolreview`, commit `5c556ab` (pushed), now:

- emits the exact 73-byte parent UNI window;
- sends two native empty polls, `SEND_PLAYER_IDS`, and the type-0 LinkPlayer request;
- sends the PC LinkPlayer block as owner/player zero while reflecting the Switch in row 1;
- removes child rolling tags exactly as the native parent does;
- reuses the proven entry/block receiver for the symmetric LinkPlayer and trainer-card exchange;
- requests trainer cards after the child's count-0 standby and releases held-key/seat traffic after
  count 1;
- exposes the parent connection to the live orchestrator only after NI completes.

The existing follower trade FSM is reused only for symmetric room-entry block/barrier work.  It is
not being misrepresented as a complete player-zero leader: party pulls and leader trade decisions
remain after the room-entry test passes.

Verification:

```text
py_compile relevant files                         PASS
tests.test_pia_host                               10/10 PASS
all emulator tests                               137/137 PASS
real TradeEngine LinkPlayer -> trainer-card gate PASS
```

## Shutdown finding

This run also separated two shutdown problems.  The terminal's Ctrl-C did not reach the Python
process because GNU `timeout` had placed it in a different process group; process inspection showed
the shell remained the terminal foreground group.  `run_trade.sh` now uses `timeout --foreground`,
so interactive Ctrl-C reaches the live process while the 900-second watchdog remains active.

Because this run was ultimately terminated at the timeout process group, it did not retest the older
post-association `HostTransport.stop()` thread-alive error.  The next graceful stop must still confirm
whether that separate adapter cleanup issue remains.

## Next live criterion

Use emulator commit `5c556ab`.  One Switch should join the PC room and remain connected.  Stop at the
first observed outcome:

1. both avatars enter the trading room — parent UNI/entry gate passed;
2. the screen remains at `Awaiting other members!` — inspect whether the Switch received the first
   `SEND_PLAYER_IDS`/LinkPlayer request;
3. a communication error occurs during LinkPlayer/card exchange — compare the last reflected child
   opcode and parent block fragment against the native sequence.

No additional native capture is needed before this test.  Once the room visibly opens, the next code
gate is player-zero party requests and leader-side trade selection/confirmation, not discovery or NI.

