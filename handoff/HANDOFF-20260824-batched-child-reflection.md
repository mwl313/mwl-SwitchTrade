# Handoff — batched child RFU reflection (2026-08-24)

## Current state

The fast parent Reliable build reached and reconstructed both LinkPlayer blocks, but the Switch showed the
game communication error followed by native error `2318-0006` and sent explicit Pia/RFU `WD`.

This is not an RF ordering or receive-death failure. Incoming unique Reliable AppData was contiguous
`fff0..0064`, and the Switch's fragments `0..16` all reached the PC. Several child `T` frames arrived in a
single Pia datagram. The parent stored only the last child command before its next VBlank, so row one exposed
only fragment indexes `3,5,7,12,13,16`; eleven intermediate states were overwritten.

## Fix

`frlg-ldn-trade-emu` branch `gptsolreview`, commit `0a8d9a0`:

- parent-only FIFO preserves changed child UNI commands across coalesced Pia delivery;
- exact post-tag-strip repeats are coalesced;
- FIFO advances only after successful parent Reliable queueing;
- focused batched-fragment test added;
- 135 WSL non-relay + 4 Windows relay tests pass.

Detailed evidence and hashes: `docs/37-live-batched-child-reflection-fix-20260824.md`.

## Next action

Run one health-gated PC-host live join with the user scanning. Capture observer, host monitor, host TAP, Pia
JSON, and console. Success requires row-one fragment sequence `0..16`, child `fragment16 -> idle`, no `WD` or
`2318-0006`, then child standby count 0. Do not tune Reliable or radio parameters unless this new capture
shows a failure at those layers.
