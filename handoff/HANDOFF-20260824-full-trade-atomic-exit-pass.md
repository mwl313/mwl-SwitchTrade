# HANDOFF — full PC-host trade + atomic room exit PASS (2026-08-24)

## Current truth

The PC-host FireRed/LeafGreen one-trade golden path is complete on real hardware. Capture
`logs/golden/pc_host_atomic_exit_switcha_retry_live_20260824_212450/`, Switch A, and emulator
`946bc63` passed join, room entry, selection, animation, commit, save, menu rebuild, final cancel,
return-field standbys 11/12, room exit, `READY_CLOSE_LINK`, and RFU `D`. CODEX offered Rattata and
saved a valid Magikarp.

The atomic exit invariant is hardware-proven: after receiving the child's `EXIT_ROOM`, arm the PC
one-shot before building the same parent UNI frame. The Switch's immediate progression to
`READY_CLOSE_LINK` is the proof. Do not revert `946bc63` or move `linkstate.exit()` back into the
outer loop.

## Post-exit popup

The user confirmed termination succeeded, then saw native `2318-0006`. The captured build stopped
its host loop immediately on RFU `D`, too early for the surrounding native Pia/LDN leave tail.
`57a25c9` now stops game output after `D` but holds the AP until the peer leaves or five seconds
elapse. Focused parent tests are 15/15 and ordinary WSL tests are 138/138. Per user direction, no
dedicated repeat trade is required; this final tail change remains hardware-unverified.

## Do not misclassify the earlier failures

- `pc_host_atomic_exit_live_20260824_205259`: Switch B failed with `2318-0013` before first held keys.
- `pc_host_atomic_exit_retry_live_20260824_210720`: Switch B reached animation, then its GBA stream
  stopped before `READY_FINISH_TRADE`.
- Both were pre-exit failures with strong RF, zero kernel drops/decrypt failures, and post-RX PASS.
- The unchanged `946bc63` Switch A success proves they were not deterministic atomic-exit or radio
  receive-death regressions.

## Next work, in order

1. Fix the independent joined-session `HostTransport.stop()` 15-second thread timeout using a captured
   thread stack; the selector already recovers stale vifs safely.
2. Correct parent cadence to an absolute VBlank deadline and measure room-movement jitter.
3. Preserve the one-Switch PC-host path as the golden regression oracle.
4. Build the generic Switch-to-Switch Pia/RFU tunnel for future trade/battle/Union Room features.

Authoritative report: `docs/47-full-trade-atomic-exit-pass-20260824.md`.

