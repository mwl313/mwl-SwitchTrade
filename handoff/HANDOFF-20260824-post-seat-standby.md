# Handoff — trading-room PASS, post-seat standby order fixed (2026-08-24)

Read `docs/38-live-trading-room-pass-post-seat-standby-fix-20260824.md` first. It is authoritative.

## Current truth

The real Switch accepted the PC host through discovery, Pia, parent WA/NI/UNI, both LinkPlayer blocks,
trainer cards, standby counts 0/1, room load, and sustained live movement. The queued child-reflection
FIFO in `0a8d9a0` passed: child fragments `0..16` all appeared in parent row one, with no `WD` or entry
communication error.

The chair-to-trade black screen was a deterministic RFU barrier deadlock. The child sent count 2 while
the PC parent skipped to count 3. Both radios captured the session with zero kernel drops and passed
post-test receive-health gates; do not reopen radio, beacon, CCMP, Pia, Reliable, or FIFO debugging.

## Ready build

- Emulator branch: `gptsolreview`
- Emulator commit: `ff81318` (pushed)
- Verification: parent/Pia 12/12; WSL ordinary 135/135; Windows relay 4/4; 139 total
- Evidence: `logs/golden/pc_host_parent_reflection_fifo_live_20260824_175304/` (local/ignored)

The fix makes PC-parent row zero react to child counts `0..3`, preserves only the native count-0/count-1
gaps, and prevents the child-oriented TradeEngine from leaking an ahead-of-child count.

## Next action

Run one health-gated live join on `ff81318`. Enter the room, sit, and initiate the trade. Decode only the
count-2/count-3 boundary first. A pass is child 2 -> parent 2, child 3 -> parent 3, followed by trade-menu
or party traffic. That next traffic will determine the minimum player-zero party/leader implementation.

Joined-session adapter teardown is still separately unresolved. Preserve evidence, let the selector
recover stale vifs, and do not perform concurrent cleanup while the host radio thread is alive.
