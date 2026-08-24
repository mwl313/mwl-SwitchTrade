# 39 — Post-seat live PASS and player-zero party-pull implementation (2026-08-24)

## Outcome

The `ff81318` real-Switch retest passed the entire chair-to-trade standby boundary. The Switch and PC
parent completed READY, count 2, and count 3 in the correct order. The prior black-screen deadlock is
fixed on hardware.

The first new boundary is exact: after count 3 the PC parent never started player-zero
`BufferTradeParties`. It continued seat held-key commands, the Switch waited at
`Communication standby... Please wait.`, and neither side exchanged a party block. This was an
expected incompleteness in the parent shim, not a new radio or transport fault.

Emulator commit `0b8a2ab` now drives the complete source-defined party exchange. It is unit- and
regression-tested but awaits its first live run.

## User-observed flow

The user performed the following sequence:

1. joined CODEX and entered the trading room;
2. walked to the chair and sat;
3. observed `Communication standby... Please wait.`, which normally precedes the trade screen;
4. made no further input while the Switch remained in that state.

No trade completed and no `received.pk3` was created.

## Wire evidence

Capture:

`logs/golden/pc_host_post_seat_standby_live_20260824_181522/`

Pia-relative event times:

| Time | Direction/event |
|---:|---|
| 27.657284 s | child/Switch READY held key `0x16` |
| 27.677095 s | parent reflects READY and emits its own READY |
| 28.474022 s | child `READY_EXIT_STANDBY count=2` |
| 28.476913 / 28.494375 s | parent row-zero count 2 replies |
| 29.092749 s | child `READY_EXIT_STANDBY count=3` |
| 29.096181 / 29.114346 s | parent row-zero count 3 replies |

This satisfies the required invariant exactly:

```text
child 2 -> parent 2 -> child 3 -> parent 3
```

Afterward:

- the child sent no new application command;
- parent row zero continued `SEND_HELD_KEYS`;
- parent emitted zero party `SEND_BLOCK_REQ` commands;
- all examined Pia datagrams authenticated (`decrypt_fail=0`);
- both monitor captures reported zero kernel drops;
- both radios passed post-test actual-RX health checks.

Therefore discovery, association, CCMP, Pia Session, Reliable, parent WA/NI/UNI, LinkPlayer,
trainer-card exchange, row-one reflection, room entry, movement, and standby counts 0..3 are all
proven below this boundary.

## Independent ROM-source audit

Reference checkout:

- repository: `pret/pokefirered`
- local commit: `c75f352304d529f6ba92d4f74b9cf8b5c3810788`

The best-fit mapping of the observed last two barriers is:

- `Task_StartWirelessTrade` in `src/cable_club.c` calls `SetLinkStandbyCallback()` before creating
  the trade menu;
- `CB2_CreateTradeMenu` state 4 in `src/trade.c` calls a second wireless standby before state 6;
- these correspond to observed counts 2 and 3 respectively;
- after count 3, `CB2_CreateTradeMenu` state 6 calls `BufferTradeParties()`.

`BufferTradeParties` makes only player zero issue the pulls. Its exact order is:

| Pull | Request selector | Bytes | Data |
|---:|---:|---:|---|
| 1 | `BLOCK_REQ_SIZE_200` (`1`) | 200 | party mons 0–1 |
| 2 | `BLOCK_REQ_SIZE_200` (`1`) | 200 | party mons 2–3 |
| 3 | `BLOCK_REQ_SIZE_200` (`1`) | 200 | party mons 4–5 |
| 4 | `BLOCK_REQ_SIZE_220` (`3`) | 220 | mail |
| 5 | `BLOCK_REQ_SIZE_40` (`4`) | 40 | gift ribbons |

Before each request state, the ROM waits until `timer > 10`. Between pulls it also waits for both
players' blocks (`GetBlockReceivedStatus() == 3`) before staging the next buffer. The Switch correctly
waited because CODEX, as player zero, had not implemented this driver.

This also reconciles a previously confusing source observation: the trade-menu creation standby is
not an extra count 4 before party exchange. It is the observed count 3. Count 4 belongs later at the
menu-to-trade-scene seam after `START_TRADE`.

## Implemented fix

Emulator branch `gptsolreview`, code commit `0b8a2ab`:

- completes parent count 3 before changing phases;
- calls the existing trade-menu-open latch so `SEND_HELD_KEYS` stops;
- drives request selectors `(1, 1, 1, 3, 4)`;
- leaves eleven idle command frames before each request, matching the ROM's `timer > 10` delay;
- reuses the existing block sender/staging implementation;
- records the child's receive-block epoch at each request;
- advances only when the PC sender is finished and a new complete child block epoch is present;
- leaves the mature guest/follower path unchanged.

This is a protocol-state fix, not speculative radio/RTO tuning.

## Verification

```text
focused parent sequence regression              1/1 PASS
parent/Pia suite                               12/12 PASS
WSL ordinary suite                           135/135 PASS
Windows relay suite (.audit-venv)               4/4 PASS
functional total                                 139 PASS
```

The Linux full-discovery command still reports the known relay `setUpClass` error because its venv
does not contain `uvicorn`. The same four relay tests pass in the Windows integration venv, so this is
not a product regression.

## Capture provenance

| File | Bytes | SHA-256 |
|---|---:|---|
| `host_console.log` | 9,288 | `37286c02bb401bc11ae0e083734202b750f8181cea79d8887b4c2df1fb05acd5` |
| `host_ldn_mon.pcap` | 6,663,606 | `9aa8c2a251f0d7fc15d700c1ec0906eb4af993977611bf7247dc24ef1360960d` |
| `host_ldn_tap.pcap` | 2,385,151 | `dda3639a1914ebeaa48527579446e530165439fdc20c70ba4f8f43a905d02406` |
| `observer_rtl8188_ch6.pcap` | 5,993,750 | `9c1b9daaf9b1e58fe44f4f25ca4eb6133549526c7a4ef2a46d104a1fe951d525` |
| `pc_host_pia.jsonl` | 5,419,097 | `0324bbdc75b3395ebf99db44ae92c59432191c95dd1ac5d6f3e69b49f366cd8f` |
| `run_host.sh` | 773 | `1edf33f36dcd732ff7553987165e868a98872a547b3b4aefd742927962d05d4f` |

Capture close statistics:

- RTL8192EU host monitor: 28,065 captured / 28,066 filter / 0 kernel drops;
- RTL8188EU observer: 30,678 captured / 30,682 filter / 0 kernel drops;
- TAP: 15,626 captured / 15,626 filter; interface removal during deliberate teardown is expected;
- post-test actual-RX gate: PASS on both cards, restored to channel 6.

The joined-session ldn radio thread again exceeded its 15-second teardown grace. Process exit,
selector stale-vif recovery, and both post-RX checks succeeded. Treat this as a separate lifecycle
defect; it did not affect the protocol result.

## Next live gate

Use emulator branch `gptsolreview` at or after `0b8a2ab`:

1. run both pre-capture actual-RX health gates;
2. capture RTL8192EU host monitor, TAP, Pia JSONL, console, and RTL8188EU observer;
3. join CODEX, enter the room, sit, and do not make extra inputs until the trade selection menu appears;
4. require five ordered parent requests with matching PC and Switch block completions;
5. if the menu opens, the party-pull gate passes; stop only at the first new leader-command boundary.

The likely next unproved layer is player-zero leadership after both users select: receiving the child
`READY_TO_TRADE`, broadcasting `SET_MONS_TO_TRADE`, validating both blocks, broadcasting
`START_TRADE`, and leading confirmation. Do not reopen lower-layer debugging unless the new capture
contains contrary wire evidence.
