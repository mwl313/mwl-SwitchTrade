# Handoff — parent Reliable room-entry deadline (2026-08-24)

Read `docs/36-live-parent-deadline-and-reliable-recovery-20260824.md` first.

The `e2979c7` live retest removed the premature parent standby, but the Switch sent explicit emulator `WD`
at `WG=1 + 3.557 s`.  Native completes LinkPlayer at about `WG=1 + 0.55 s`; the PC took about 3.17 s.
Parent row one did reflect the child's final fragment and the Switch acknowledged that Reliable range, so
the failure is the room-entry deadline consumed by serialized Reliable holes, not a bad fragment tag or
radio receive death.

Use emulator `gptsolreview` commit `31b29bf`.  It changes parent mode only: first-NACK fast recovery,
67 ms RTO cap, full bounded six-frame recovery, and explicit child `WD` handling.  All 138 tests pass.

Next live success sequence:

```text
LinkPlayer <= WG=1 + 1.5s
child changes fragment 16 -> idle
~5.08s warp idle
child standby count 0
parent replies twice + two idle rows + card request
```

Do not enlarge the six-frame window until a new capture proves the faster recovery is still insufficient.
Do not revisit discovery, CCMP, Pia Session, WA, NI, UNI layout, rolling-tag stripping, or the standby order
without contrary wire evidence; all are already proven through this gate.

