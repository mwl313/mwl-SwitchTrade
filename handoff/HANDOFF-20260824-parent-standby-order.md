# Handoff — live LinkPlayer PASS, parent standby ordering fixed (2026-08-24)

Read `docs/35-live-linkplayer-pass-parent-standby-order-20260824.md` first, then
`docs/34-live-parent-ni-pass-and-uni-bootstrap-20260824.md` for the preceding gate.

## Current truth

The real Switch accepted PC discovery through parent NI and the first parent UNI bootstrap.  Both
LinkPlayer blocks completed; the PC decoded the Switch player as `GIRL v0x4004`.  The communication
error came from the PC parent emitting standby count 0 immediately after that exchange.

The native gold proves the child waits about 5.08 seconds, initiates count 0, and only then receives
the parent's reply and trainer-card request.  Parent counts 0/1 are reactive gates.

## Ready build

- Emulator branch: `gptsolreview`
- Emulator commit: `e2979c7` (pushed)
- Verification: focused 10/10, all 137/137
- Evidence: `logs/golden/pc_host_parent_uni_live_20260824_162720/` (ignored/local)

The build suppresses child-FSM standby leakage, replies twice to child counts 0/1, preserves the native
idle gaps, and delays held-key traffic after count 1.  The next live test should stop at the first
trainer-card/count-1/room-entry outcome and decode that boundary.  Do not revisit beacon, radio, Pia,
WA, NI, or LinkPlayer unless those already-proven layers actually regress.

Joined-session adapter teardown remains independently unresolved.

