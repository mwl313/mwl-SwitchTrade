# Handoff — player-zero selection gate implemented; live test pending (2026-08-24)

Read `docs/40-live-party-menu-pass-next-leader-gate-20260824.md` for the live evidence, then
`docs/41-player-zero-selection-implemented-20260824.md` for the implementation.

## Current truth

- `0b8a2ab` is live-proven through the visible Pokémon selection screen.
- `b26b588` adds the source-defined player-zero selection broadcast and is test-proven, not yet
  hardware-proven.
- WSL ordinary tests pass 136/136; Windows relay integration passes 4/4 (140 functional total).
- Radios, CCMP, Pia, Reliable, room entry, movement, counts 0–3, and all five party pulls are behind
  the active boundary.

## Exact next gate

Have the user join the CODEX room, reach the Pokémon selection screen, select one Pokémon, and choose
Trade once. CODEX should log the child `READY_TO_TRADE`, send owner-zero `SET_MONS_TO_TRADE`, and the
Switch should show `Is this trade okay?`.

Stop there. This commit deliberately does not perform the next player-zero duties. After a live PASS,
implement both `INIT_BLOCK` confirmations and the owner-zero `START_TRADE` broadcast from
`pret/pokefirered`, preserving the capture before changing code.

Do not retune lower layers unless the new capture directly disproves their prior live passes.
