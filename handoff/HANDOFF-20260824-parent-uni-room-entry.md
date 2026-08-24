# Handoff — parent NI live PASS and UNI room-entry build (2026-08-24)

## Read first

Read `docs/34-live-parent-ni-pass-and-uni-bootstrap-20260824.md`, then
`docs/33-parent-ni-gate-20260824.md` for the preceding boundary.

## Branches and commits

- Main documentation/workflow: `golden-capture-re` (this handoff)
- Emulator: `gptsolreview`, `5c556ab` (pushed)

## Proven on hardware

The Switch displayed `CODEX says OK`, proving it accepted the PC's `JOIN_GROUP_OK` parent NI.  It then
displayed `Pokemon Trades! Awaiting other members!`.  All 5,456 Pia JSON records authenticated and the
capture contains no parent or child UNI frames after `WG=1`.  The tested build therefore stopped at a
precise missing parent-UNI boundary; this is not a radio, beacon, CCMP, Pia, WA, or NI failure.

Evidence is local and ignored at:

`logs/golden/pc_host_parent_ni_live_20260824_154857/`

## Ready for the next test

`5c556ab` emits the native 73-byte parent UNI layout (`460005` + five command rows), performs
`SEND_PLAYER_IDS`, requests/exchanges LinkPlayer blocks, reflects the child in row 1 with its rolling
tag removed, requests the trainer cards after standby count 0, and releases seat traffic after count
1.  The real `TradeEngine` integration reaches the trainer-card gate in tests; all 137 emulator tests
pass.

The current implementation targets visible room entry.  Do not claim a complete trade yet.  Once both
avatars enter the room, implement the parent/player-zero party pulls and leader trade commands.

## Live test

Run the usual two-radio actual-RX health-gated PC-host capture with emulator `5c556ab`.  The user starts
with one Switch scanning for rooms, joins CODEX, and reports each UI transition.  Success is both
avatars entering and holding the trading room without a communication error.

`run_trade.sh` now uses `timeout --foreground`; Ctrl-C previously targeted the waiting shell instead
of the separated timeout/Python process group.  Still verify the older joined-session radio-thread
cleanup on the next graceful stop; this run was force-terminated before that path could be judged.

