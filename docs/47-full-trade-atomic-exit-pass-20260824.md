# 47 — Full PC-host trade and atomic room exit PASS (2026-08-24)

## Outcome

The one-Switch PC-host FRLG path has now completed its full real-hardware golden transaction. Using
Switch A and emulator `946bc63`, the user joined CODEX, entered the trading room, traded one Pokémon,
saved, returned to the trade menu, cancelled, returned to the room, walked out, completed the escort
dialogue, and closed the RFU link. CODEX offered the captured Rattata and received a valid 100-byte
Magikarp.

The decisive fix was atomic room exit. When the Switch's child UNI row supplied `EXIT_ROOM`, the PC
armed its own one-shot before generating that same tick's parent UNI. The Switch then advanced from
the escort dialogue to `READY_CLOSE_LINK` and RFU `D`. The preceding build emitted the two players'
exit keys in consecutive parent frames and never advanced.

Immediately after the successful termination animation, Switch A displayed native error
`2318-0006`. This is downstream of the completed game transaction: the trade did not roll back, all
room-exit gates passed, and the Switch itself deauthenticated with reason `STA leaving`. The remaining
defect is the outer LDN lifetime, not FireRed/LeafGreen trade correctness.

## Authoritative evidence

Capture: `logs/golden/pc_host_atomic_exit_switcha_retry_live_20260824_212450/`

The capture-local `MANIFEST.md` contains the complete hashes, scripts, counts, and timeline.

```text
emulator under test       946bc63fb45d5d4a6de05d93fcde0f66ad666ebd
console                   Switch A / a4:c1:e8:66:73:25
offered                   Rattata
received                  Magikarp, 100 B, SHA-256 54133b53...715f3181
Pia                       6,581 in / 5,695 out; decrypt failures 0
host monitor              27,093 captured / 27,095 filter / 0 drop
host TAP                  12,429 captured / 12,429 filter / 0 drop
RTL8188EU observer        37,642 captured / 37,650 filter / 0 drop
post-run radio health     PASS / PASS
```

Decisive host timeline:

```text
145.9  Switch READY_FINISH_TRADE
186.3  parent CONFIRM_FINISH_TRADE; Magikarp committed and saved
195.3  Switch-originated save counts 5..10 complete
202.3  post-save party reconstruction complete
205.6  BOTH_CANCEL_TRADE accepted
206.9  cancel-exit standby 11 complete
207.8  return-to-field standby 12 complete
237.7  Switch EXIT_ROOM; PC EXIT_ROOM armed atomically in the receive tick
238.3  Switch READY_CLOSE_LINK; PC mirror
238.5  Switch RFU D; game link closed
```

## Why the post-exit `2318-0006` appeared

The captured build broke out of `run_live()` immediately when the Switch sent RFU `D`. That early
branch bypassed the later 1.5-second close timer and began destroying the PC-owned LDN room while the
Switch's native leave animation/network tail was still settling. In the native Switch-to-Switch gold,
the RFU disconnect is followed by a Pia Session leave roughly 1.7 seconds later before traffic ends.

Emulator `57a25c9` applies the smallest bounded correction:

- after RFU `D` in parent mode, stop producing game frames;
- keep the underlying LDN host alive until the Switch leaves the AP participant table;
- cap that wait at five seconds so teardown cannot hang forever;
- preserve immediate RFU-D exit in ordinary guest mode.

Focused parent tests are 15/15 PASS and the ordinary WSL suite excluding the optional relay-server
integration is 138/138 PASS. The user does not require another dedicated hardware trade for this
nonessential post-exit popup, so record `57a25c9` as offline-tested and hardware-unverified.

## Two preceding negative samples are not regressions

The same atomic build produced two earlier Switch B samples before Switch A's pass:

1. `pc_host_atomic_exit_live_20260824_205259`: native `2318-0013` after trainer-card standby count 1,
   before the first `SEND_HELD_KEYS`. Pia acknowledgements proved delivery, signal was strong, all
   captures had zero kernel drops, and both radios passed RX.
2. `pc_host_atomic_exit_retry_live_20260824_210720`: room entry, seating, party exchange, selection,
   `START_TRADE`, and scene standby passed. The embedded GBA stopped producing new animation frames
   about 13 seconds after START, then the Switch deliberately left; no `READY_FINISH_TRADE` arrived.

Both failed before the atomic-exit code path could run. The subsequent unchanged-build Switch A pass
rules out a deterministic regression in `946bc63` and rules out RTL8192EU/RTL8188EU receive death.

## Remaining engineering work

The PC-host trade proof is complete. Do not reopen its decoded game FSM unless a repeatable trade
regression appears. Remaining work is now:

1. joined-session `HostTransport.stop()` can still exceed its 15-second thread guard after a peer;
   cleanup is safe and both cards recover, but production shutdown should capture/fix the thread wait;
2. replace the work-plus-sleep parent cadence with an absolute VBlank deadline to reduce avatar jitter;
3. use this proven local endpoint as the baseline for the Switch-to-Switch tunnel; battles, Union Room,
   and later features remain Switch-to-Switch only per `docs/46-future-switch-to-switch-features-todo-20260824.md`.

