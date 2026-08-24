# Handoff — live WA proof and parent NI implementation (2026-08-24)

## Branches

- Main: `golden-capture-re`
- Emulator: `gptsolreview`, `c69e213`

Read `docs/33-parent-ni-gate-20260824.md` first.  Raw pcaps and Pia JSONL are
local under `logs/golden/pc_host_parent_wa_live_20260824_151803/` and ignored.

## Proven live

The Switch accepted PC `WA` and ACKed it.  All 79 Pia records decrypted.  The
same UI error then occurred because the Switch repeated child NI_START 17 times
while the old PC build sent only Pia ACKs.  This rules out discovery, radio RX,
CCMP, Pia, and WA as the current cause.

## Implemented

`c69e213` sends the native parent idle poll, ACKs child NI, sends `WG=0`, runs
the exact matching-ACK-driven parent `JOIN_GROUP_OK` NI sequence, then sends
`WG=1`.  Native frame bytes are locked by tests.

```text
tests.test_pia_host       8/8 PASS
ordinary emulator suite  131/131 PASS
```

The full relay integration setup fails only because this venv lacks `uvicorn`.

## Next test criterion

Run the normal two-radio health-gated one-Switch PC-host capture with
`c69e213`.  Success is `parent_ni_complete=True` followed by child UNI traffic.
The screen may still not enter the room: parent UNI/player-zero bootstrap is
the next and final known room-entry gate.

Do not release the existing `TradeEngine` in host mode.  It is a player-one
child engine.  The parent path must emit the 73-byte parent UNI slot (3-byte
LLSF plus five 14-byte rows), put PC commands in row 0, reflect the Switch in
row 1, and reproduce `SEND_PLAYER_IDS` plus LinkPlayer block exchange.

## Teardown warning

The no-peer self-DESTROY fix is valid, but a joined session still left the ldn
radio thread alive after 15 seconds.  On the next reproduction, dump the radio
thread stack before patching.  Never delete vifs concurrently while that thread
is alive; exit the process first, then let the selector remove stale interfaces
and re-run actual-RX health gates.
