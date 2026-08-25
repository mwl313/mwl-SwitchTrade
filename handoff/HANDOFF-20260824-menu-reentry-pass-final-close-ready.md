# HANDOFF — menu re-entry PASS; final close delay ready (2026-08-24)

## Current truth

The real Switch now completes an entire trade with the PC host, saves it, reconstructs both parties,
and returns to the usable Pokémon trade screen. The user directly confirmed that outcome in capture
`logs/golden/pc_host_parent_reentry_live_20260824_200611/` using emulator `5cb19af`.

At 239.6 s the Switch stopped save count 10. The PC immediately restarted the exact five
`BufferTradeParties` pulls, and all completed by 247.3 s. The PC received and saved a valid Pidgey.
Pia had 17,708 authenticated datagrams and no decrypt failure; all three pcaps had zero kernel drops;
both radios passed post-run receive-health checks.

## One remaining defect

`5cb19af` sent `BOTH_CANCEL_TRADE` on the final ribbon-completion frame. The Switch was only entering
`CB2_CreateTradeMenu` state 7 and did not install `CB1_UpdateLink` until state 22, so it ignored the
early command and never originated/answered the count-11/count-12 exit chain.

Emulator `823288b` waits 120 command frames after the final party block and then sends the same
owner-zero cancel. This is a bounded menu-readiness delay, not the removed 600-frame dead-host wait.
Focused tests pass, WSL ordinary is 136 PASS, and Windows relay is 4/4 PASS. Hardware verification is
still pending; do not claim graceful completion until it passes.

## Exact next workflow

1. Run both WSL radio health gates before capture.
2. Use RTL8192EU as host and RTL8188EU as observer on the discovered room channel.
3. Offer `archive/pokemon/fixtures/0001_BULBASAUR_user_20260824.pk3` (the last run offered Rattata).
4. Let the user perform one complete trade; do not stop at menu re-entry.
5. Observe the 120-frame delay, `BOTH_CANCEL_TRADE`, counts 11/12, room exit, and close-link exchange.
6. Stop capture, record kernel-drop counters, and run both post-RX health gates.
7. Hash and manifest every artifact before changing another protocol layer.

If the Switch still ignores cancel, compare the child command stream at the end of the 120-frame
window before changing the delay. Do not modify RF, CCMP, Pia, Reliable, save barriers, or party
pulls: all of those layers passed in this capture.

Authoritative report: `docs/45-parent-menu-reentry-live-pass-final-close-delay-20260824.md`.

