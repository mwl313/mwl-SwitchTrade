# Handoff — visible trade-menu live PASS; next player-zero leader gate (2026-08-24)

Read `docs/40-live-party-menu-pass-next-leader-gate-20260824.md` first. It is authoritative.

## Current truth

Emulator code `0b8a2ab` passed on a real Switch. CODEX completed all five
`BufferTradeParties` pulls—party x3, mail, ribbons—and the user visibly reached the Pokémon trade
selection screen. Pia authenticated 4,567/4,567 datagrams, every pcap had zero kernel drops, and both
radios passed post-test actual RX.

Do not regress discovery, radio, CCMP, Pia, Reliable, parent WA/NI/UNI, LinkPlayer, trainer cards,
reflection FIFO, room movement, counts 0..3, or party synchronization.

## Proven build and evidence

- Emulator branch/head at test: `gptsolreview` / `ac8b7b7`
- Live-proven code: `0b8a2ab`
- Main branch before report: `golden-capture-re` / `fd0c021`
- Evidence: `logs/golden/pc_host_parent_party_pulls_live_20260824_183308/` (local/ignored)

## Exact next boundary

The current engine is a follower. At menu-live it can offer its configured Pokémon, but player zero
must aggregate the Switch's `READY_TO_TRADE` with its own selection and broadcast
`SET_MONS_TO_TRADE`. That leader-only transition is not implemented.

Implement it as a parent shim, preserving the follower path. Require owner-zero block framing and
retain the Switch cursor. The next hardware PASS is the user's selection producing the
`Is this trade okay?` screen. The later leader-only transitions are `START_TRADE` after both
`INIT_BLOCK` confirmations and `CONFIRM_FINISH_TRADE` after both `READY_FINISH_TRADE` blocks.

The joined-session teardown timeout did not reproduce in this stop, but remains open until repeated
clean stops or a root-cause fix.
