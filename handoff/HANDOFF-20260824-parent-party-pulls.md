# Handoff — post-seat live PASS; parent party pulls ready (2026-08-24)

Read `docs/39-post-seat-live-pass-parent-party-pulls-20260824.md` first. It is authoritative.

## Current truth

The `ff81318` hardware retest passed child 2 -> parent 2 -> child 3 -> parent 3 exactly. The Switch's
`Communication standby... Please wait.` screen was the normal pre-trade transition. It remained there
because CODEX sent no player-zero party requests and continued seat held keys.

Do not regress discovery, channel, cards, CCMP, Pia, Reliable, WA/NI/UNI, LinkPlayer, trainer card,
row-one FIFO, room entry, movement, or standby counts 0..3. Every one of those layers passed in the
same zero-kernel-drop capture, and both radios passed post-test actual RX.

## Ready build

- Emulator branch: `gptsolreview`
- Code commit: `0b8a2ab`
- Handoff head: `ac8b7b7`
- Verification: 12 parent/Pia + 135 WSL ordinary + 4 Windows relay = 139 functional passes
- Evidence: `logs/golden/pc_host_post_seat_standby_live_20260824_181522/` (local/ignored)

The parent now stops held keys after count 3 and runs the ROM order `1,1,1,3,4`: party pair x3,
mail, ribbons. It waits eleven frames and requires both directions to complete each block before the
next request.

## Next action

Run one health-gated live join on `0b8a2ab` or later. The user should join, enter, sit, and make no
additional input until the trade party menu appears. Decode the five requests and both block streams.

A pass means the visible menu opens. The next likely unimplemented layer is player-zero leader logic:
`READY_TO_TRADE` reception -> `SET_MONS_TO_TRADE` -> `START_TRADE` -> confirmation. Preserve and stop
at the first new boundary rather than changing lower layers.

Joined-session radio-thread teardown remains separately unresolved.
