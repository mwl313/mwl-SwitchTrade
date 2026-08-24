# 44 — CONFIRM_FINISH live PASS; post-save count prediction removed (2026-08-24)

## Outcome

Emulator `812fb90` passed the real-Switch finish transaction. CODEX completed its own
`READY_FINISH_TRADE`, combined it with the Switch's earlier READY, transmitted owner-zero
`CONFIRM_FINISH_TRADE`, committed the trade, and saved the received Rattata as a valid 100-byte
`received.pk3`.

The Switch then completed post-trade standby counts 5 through 10. CODEX incorrectly initiated an
additional count 11, which the Switch never answered; the screen remained at
`Communication standby... Please wait.`. This is a new post-commit save/menu-return boundary, not a
regression in discovery, joining, trade data, animation, or finish confirmation.

Commit `cea2d75` fixes the boundary by following the Switch's source-timed save barriers reactively.
It is offline-test-proven and awaits hardware verification.

## Evidence

Capture: `logs/golden/pc_host_confirm_finish_live_20260824_194059/`

The capture-local `MANIFEST.md` contains the exact timeline, launch build, hashes, and runner scripts.

```text
Pia datagrams            20,421 (9,793 out / 10,628 in)
Pia decrypt failures     0 logged
host monitor             46,941 captured / 46,955 filter / 0 kernel drops
host TAP                 20,721 captured / 20,722 filter / 0 kernel drops
RTL8188EU observer       44,844 captured / 44,851 filter / 0 kernel drops
post-test radio health   PASS / PASS, channel 6
received.pk3             RATTATA, 100 bytes, SHA-256 b008f35e...112635c
```

Decisive sequence:

```text
148.5  child READY_FINISH_TRADE
182.1  parent READY_FINISH_TRADE
182.4  parent READY complete + CONFIRM_FINISH_TRADE
182.4  RATTATA committed and saved
183.0..188.7  counts 5,6,7,8,9,10 complete
188.7  CODEX invents count 11
209.0  count 11 remains unanswered; local watchdog only
```

## Why count 11 was wrong

FireRed `CB2_SaveAndEndTrade` interleaves `SetLinkStandbyCallback()` with actual save writes, fades,
and trade-menu reconstruction. Only the ROM knows when another round exists. The emulator has no
equivalent local save clock, yet `_run_save_chain()` immediately initiated another standby whenever
the previous one completed. That worked through real rounds 5–10 and then overran the ROM by one.

The source-defined solution is simpler: during the save chain, CODEX waits. A Switch-originated
`READY_EXIT_STANDBY` activates the existing reactive responder; a party request/block ends the chain
and resumes `BufferTradeParties`. CODEX no longer predicts either a count or a delay.

## Implementation and verification

`cea2d75`:

- removes proactive save-barrier initiation;
- preserves the existing reactive responder and dead-host safety net;
- removes now-unused save-pacing state;
- adds a regression assertion that an idle post-confirm tick emits zeros, leaves the barrier idle,
  and does not advance its count.

```text
focused parent finish/save test       PASS
WSL ordinary tests                 136 PASS
Windows relay integration            4/4 PASS
functional total                     140 PASS
```

The split-environment note is unchanged: WSL lacks `uvicorn` for the optional relay class, while the
four relay tests pass in Windows.

## Next live gate

With `cea2d75`, repeat one full trade. PASS requires the Switch to drive post-save barriers, return
to the trade menu, re-exchange parties, accept CODEX's Cancel, and reach neutral state without
rolling the trade back. Do not alter any lower protocol layer unless this exact flow disproves it.
