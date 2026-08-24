# 41 — Player-zero selection broadcast implemented; hardware gate ready (2026-08-24)

## Outcome

Emulator commit `b26b588` implements the first leader-only trade-menu transition. It is regression
tested but not yet hardware-proven.

The previous live run ended at a visible Pokémon selection screen. The next run should now advance
from the Switch's selection to its `Is this trade okay?` confirmation screen. The implementation
intentionally stops at that boundary; it does not yet drive CODEX's confirmation or broadcast
`START_TRADE`.

## Source contract

The implementation follows `pret/pokefirered` commit
`c75f352304d529f6ba92d4f74b9cf8b5c3810788`:

1. `SetReadyToTrade` sends `LINKCMD_READY_TO_TRADE` only for multiplayer player one.
2. Player zero instead sets its own selection status locally.
3. `Leader_ReadLinkBuffer` receives player one's READY block and cursor.
4. `Leader_HandleCommunication` waits for both selection statuses and broadcasts
   `LINKCMD_SET_MONS_TO_TRADE` with player zero's cursor.
5. The follower receives that broadcast, records player zero's cursor, and opens the confirmation
   prompt.

No timing constant or radio behavior was guessed for this transition.

## Code changes

Branch/head: `gptsolreview` / `b26b588`.

- Parent `TradeEngine` selection records `leader_local_ready` and does not stage the follower-only
  READY block.
- Parent Pia/RFU handling detects a newly completed two-fragment child LINKCMD block, validates
  `READY_TO_TRADE`, and retains the Switch cursor.
- Once the local and child selections are ready, the five party pulls are complete, and no sender
  owns the RFU row, parent mode starts an owner-zero `SET_MONS_TO_TRADE` block.
- CODEX's configured cursor is placed in the broadcast; the Switch's cursor is stored as the partner
  cursor; the engine advances to `S6_CONFIRM`.
- The five parent party pulls now require exact child response counts `(17,17,17,19,4)`. This closes
  a latent ambiguity where a later two-fragment LINKCMD could otherwise be mistaken for completion
  of the four-fragment ribbon response.

The live-proven follower path remains unchanged.

## Verification

The new focused test exercises the actual leader selection branch rather than preloading its latch.
It proves:

- parent mode suppresses follower `READY_TO_TRADE`;
- the Switch READY block is reassembled and its cursor retained;
- the emitted block is owned by player zero;
- its exact 20-byte payload is `SET_MONS_TO_TRADE` plus CODEX cursor `1`;
- the Switch cursor `2` is retained;
- the engine reaches `S6_CONFIRM`.

Results:

```text
WSL ordinary emulator tests       136/136 PASS
Windows relay integration tests      4/4 PASS
Functional total                   140 PASS
```

The WSL discovery command continues to report the known relay `setUpClass` environment error because
that venv lacks `uvicorn`; the same four relay tests pass in the Windows `.audit-venv`.

## Next live test

1. Run the normal pre-capture health gates on both adapters.
2. Start a new CODEX host capture on RTL8192EU, with RTL8188EU observing channel 6.
3. The user joins the CODEX room, enters the trading room, sits, and waits for the selection screen.
4. The user selects one Pokémon and chooses Trade once.
5. Stop at the first visible result.

PASS requires all of the following:

```text
child READY_TO_TRADE cursor=N
parent SET_MONS_TO_TRADE local_cursor=1 child_cursor=N
owner-zero block INIT + two fragments delivered
Switch displays "Is this trade okay?"
```

Do not confirm YES in this test. If the prompt appears, preserve the capture and implement the next
source-defined layer: local `INIT_BLOCK`, child `INIT_BLOCK`, then player-zero `START_TRADE`.

If the prompt does not appear, diagnose only the READY reassembly, owner-zero block reflection, and
payload delivery. Discovery, CCMP, Pia, Reliable, room entry, standby counts, and party exchange are
already live-proven and should not be retuned.
