# 42 — Player-zero selection live PASS; confirmation/START implemented (2026-08-24)

## Outcome

Emulator commit `b26b588` passed on a real Switch. CODEX received the Switch's selection and sent
player-zero `SET_MONS_TO_TRADE`; the user visibly reached `Is this trade okay?`.

The user accidentally confirmed Yes. That did not invalidate the planned gate: it supplied the next
source-defined input, the Switch's `INIT_BLOCK`, and showed exactly where CODEX still stopped.

Commit `2d66c08` now implements CODEX's confirmation plus the player-zero `START_TRADE` broadcast.
It is test-proven and awaits the next hardware run.

## Live timeline

Capture: `logs/golden/pc_host_leader_selection_live_20260824_190447/`

| Host time | Event |
|---:|---|
| 181.0 s | five parent party pulls complete; trade menu live |
| 181.0 s | CODEX local selection READY, cursor 1 |
| 189.2 s | Switch `READY_TO_TRADE`, cursor 1 |
| 189.2 s | parent `SET_MONS_TO_TRADE`, local cursor 1, child cursor 1 |
| visible | user confirms `Is this trade okay?` appeared |
| 194.2 s | Switch `INIT_BLOCK` received after accidental Yes |

The host was interrupted immediately after `INIT_BLOCK`. CODEX had no local confirmation/START
implementation in `b26b588`, so the Switch's later native communication error was the expected result
of deliberate host removal. No animation ran and no `received.pk3` was produced.

## Capture integrity

```text
Pia authenticated       5,398 / 5,398
Pia failures            0
direction               2,509 out / 2,889 in
host monitor            17,055 captured / 17,076 filter / 0 kernel drops
host TAP                 5,475 captured / 5,477 filter / 0 kernel drops
RTL8188EU observer       17,019 captured / 17,021 filter / 0 kernel drops
post-test radio health  PASS / PASS, restored to channel 6
host teardown           clean
```

| File | Bytes | SHA-256 |
|---|---:|---|
| `host_console.log` | 19,413 | `a84680215ac6872f90d7874dccaa5e57872d3710cc61158d8358045867b5e713` |
| `host_ldn_mon.pcap` | 4,394,143 | `e9300145d7e186b377082101d14fe73835170f6225c8099a6e17fde335f0a09d` |
| `host_ldn_tap.pcap` | 826,936 | `d9fe051bd169d149595c9088d3ea95775e2f2dfbdbad0a639b93053296ec5dd2` |
| `observer_rtl8188_ch6.pcap` | 3,706,486 | `c7491921945c23ebdf511b43e039ef4fb0e076089cf4f7f1bed82cf11da2d5b4` |
| `pc_host_pia.jsonl` | 1,876,063 | `4fcbd3866d5125281131d3773bfc6ab3cce500aa68be83cdd064c8dc35b94563` |

## Source-defined next transition

`pret/pokefirered` `CommunicateWhetherMonCanBeTraded`, `Leader_ReadLinkBuffer`, and
`Leader_HandleCommunication` require:

1. Both players confirm a valid offer by sending `LINKCMD_INIT_BLOCK`.
2. Player zero tracks its own confirmation separately from player one's confirmation.
3. Only when both are READY does player zero broadcast `LINKCMD_START_TRADE`.
4. Both sides fade into the wireless trade scene and run the scene-seam RFU standby before the
   animation.

## Implementation in `2d66c08`

- Parent mode reuses the existing confirm verdict, so last-living-Pokémon and invalid-partner gates
  are not bypassed.
- CODEX's queued `INIT_BLOCK` is player-zero owned and uses the proven parent Pia send adaptation.
- Switch `INIT_BLOCK` completion is latched independently from the earlier selection block.
- `START_TRADE` cannot be emitted until CODEX's INIT send is complete and the Switch's INIT is
  complete.
- Player zero then sends owner-zero `START_TRADE` and enters `S7_ANIM`; the existing barrier engine
  handles the wireless scene-seam standby.
- The parent-mode send constructor now enforces player-zero ownership for every queued leader block,
  while the follower path retains player-one ownership and behavior.

Verification:

```text
WSL ordinary emulator tests       136/136 PASS
Windows relay integration tests      4/4 PASS
Functional total                   140 PASS
```

The WSL discovery command still reports the known relay `setUpClass` environment error because that
venv lacks `uvicorn`; the four relay tests pass in `.audit-venv`.

## Next live gate

The user should join CODEX, enter/sit, select a Pokémon, choose Trade, and confirm Yes. PASS is:

```text
child READY_TO_TRADE
parent SET_MONS_TO_TRADE
parent INIT_BLOCK
child INIT_BLOCK
parent START_TRADE
visible trade animation begins
```

Stop immediately when the animation begins. Do not attempt to finish the animation until the next
leader-only gate—`READY_FINISH_TRADE` aggregation and `CONFIRM_FINISH_TRADE`—is audited and implemented.
