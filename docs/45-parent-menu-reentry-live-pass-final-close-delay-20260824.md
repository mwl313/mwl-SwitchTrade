# 45 — Parent menu re-entry live PASS; final close timing isolated (2026-08-24)

## Outcome

Emulator `5cb19af` passed the full post-save party reconstruction gate on a real Switch. CODEX
offered the user's captured Rattata, received and saved a valid 100-byte Pidgey, mirrored the
Switch-originated save counts 5–10, restarted the five `BufferTradeParties` pulls, and returned the
Switch to the usable Pokémon trade screen. The user directly confirmed the successful return.

The remaining failure is now only the final graceful close. `5cb19af` sent owner-zero
`BOTH_CANCEL_TRADE` on the same frame that the final ribbon block completed. The Switch did not
answer counts 11/12 because its trade-menu callback was not installed yet. Commit `823288b` adds a
source-bounded 120-frame (~2 second) menu-build delay before that final command. It is offline-test
proven and requires one hardware verification.

This run rules out the earlier high-risk alternatives: there was no RF receive death, packet loss,
Pia decrypt error, trade rollback, save deadlock, or failed party re-exchange.

## Evidence

Capture: `logs/golden/pc_host_parent_reentry_live_20260824_200611/`

Its capture-local `MANIFEST.md` records the hashes, launch scripts, and full event timeline.

```text
Pia datagrams            17,708 (8,226 out / 9,482 in)
Pia decrypt failures     0 logged
host monitor             40,805 captured / 40,818 filter / 0 kernel drops
host TAP                 17,936 captured / 17,937 filter / 0 kernel drops
RTL8188EU observer       38,741 captured / 38,750 filter / 0 kernel drops
post-test radio health   PASS / PASS, restored to channel 6
received.pk3             PIDGEY, 100 bytes, SHA-256 d12f65e6...d5a71f9
```

Decisive sequence:

```text
230.5  child/local finish complete; parent CONFIRM_FINISH_TRADE
230.5  PIDGEY committed and saved
230.9..239.6  Switch-originated save counts 5..10 mirrored successfully
239.6  count 10 stops; parent post-save party re-exchange armed
239.8..247.3  all five party/mail/ribbon pulls complete
247.3  user-visible trade-menu return succeeds
247.3  parent sends BOTH_CANCEL_TRADE too early; child does not answer 11/12
```

## Why the final cancel was early

The completion of the final party block corresponds to `CB2_CreateTradeMenu` state 6. FireRed and
LeafGreen still have to execute states 7–22: create party icons and menu sprites, draw backgrounds
and HP bars, start and finish the palette fade, and finally install `CB1_UpdateLink`. A link command
sent during that construction interval is not consumed by the normal trade-menu callback.

The fix does not restore the old 600-frame dead-host timeout. `PARENT_MENU_READY_FRAMES = 120` is a
small, one-time wait after the final block and before final cancel. The normal Switch-driven save
counts and party responses remain fully reactive.

## Implementation and verification

Emulator commit `823288b`:

- arms the 120-frame wait only after the post-save party re-exchange completes;
- emits nothing during that bounded menu-build interval;
- sends owner-zero `BOTH_CANCEL_TRADE` once after the wait;
- retains the already-proven count-11/count-12 return-field and room-exit logic;
- includes an exact regression showing no early cancel and a single cancel at expiry.

```text
focused parent final-close test       PASS
WSL ordinary tests                 136 PASS
Windows relay integration            4/4 PASS
known optional WSL relay issue        uvicorn not installed
```

## Next live gate

Offer `mons/0001_BULBASAUR_user_20260824.pk3` next, following the requested Rattata/Bulbasaur
alternation. Complete one trade and leave the session under host control. PASS requires:

1. the same successful save and return to the trade screen;
2. a short menu-ready pause rather than the old long stall;
3. the Switch accepting `BOTH_CANCEL_TRADE`;
4. completed exit counts 11/12 and clean return to the trading-room/neutral state;
5. no native communication error and both radio post-RX gates passing.

