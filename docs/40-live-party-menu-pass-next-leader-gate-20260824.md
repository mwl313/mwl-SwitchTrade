# 40 — Player-zero party exchange and visible trade-menu live PASS (2026-08-24)

## Outcome

The real Switch accepted CODEX's full player-zero `BufferTradeParties` implementation and displayed
the Pokémon trade/party-selection screen. Emulator code commit `0b8a2ab` is therefore live-proven.

This retires every protocol layer from discovery through party synchronization:

```text
LDN discovery/association
-> ARP/CCMP/Pia Session
-> Reliable WA/NI/UNI
-> LinkPlayer + trainer cards
-> trading-room entry and movement
-> chair READY + standby counts 2/3
-> party pair 1/2/3 + mail + ribbons
-> visible trade selection menu (P5_IN_TRADE)
```

The next unproved layer is player-zero trade leadership after selections. It begins when the Switch
sends `READY_TO_TRADE`; CODEX must combine that with its local selection and broadcast
`SET_MONS_TO_TRADE`.

## Test procedure and visible evidence

Build:

- emulator branch/head: `gptsolreview` / `ac8b7b7`;
- code under test: `0b8a2ab`;
- main documentation branch before this report: `golden-capture-re` / `fd0c021`.

The user:

1. joined the CODEX room;
2. entered the trading room;
3. walked to the chair and sat;
4. made no further input after the pre-trade standby;
5. reported: `i see the trade screen! im leaving it idle in the trade screen`.

The host was intentionally interrupted immediately after that confirmation. No Pokémon was selected
or confirmed by the user, no trade animation ran, and no `received.pk3` was produced.

## Wire and engine timeline

Capture:

`logs/golden/pc_host_parent_party_pulls_live_20260824_183308/`

| Host time | Event |
|---:|---|
| 493.9 s | Switch READY; CODEX sits |
| 495.0 s | child count 2; parent count-2 reply path |
| 495.7 s | child count 3; parent count-3 reply completes; P4 menu phase armed |
| 496.2 s | parent request 1/5, type 1 (party mons 0–1) |
| 496.8 s | Switch party block 1/3 complete |
| 497.0 s | parent request 2/5, type 1 (party mons 2–3) |
| 498.5 s | Switch party block 2/3 complete |
| 498.8 s | parent request 3/5, type 1 (party mons 4–5) |
| 499.8 s | Switch party block 3/3 complete |
| 500.0 s | parent request 4/5, type 3 (mail) |
| 500.8 s | Switch mail block complete, count 19 |
| 501.1 s | parent request 5/5, type 4 (gift ribbons) |
| 502.2 s | Switch ribbon block complete, count 4 |
| 502.2 s | engine `P5_IN_TRADE`; visible trade menu confirmed by user |

The elapsed time from count-3 completion to visible menu was approximately 6.5 seconds. Every
request waited for completion of both the PC sender and a new complete Switch block epoch before the
next pull. The order exactly matches `pret/pokefirered` `src/trade.c:BufferTradeParties`.

## Capture integrity

Offline authentication of the preserved Pia JSONL:

```text
authenticated 4567
failed           0
out           2119
in            2448
```

Packet-capture close statistics:

| Stream | Captured | Filter | Kernel drops |
|---|---:|---:|---:|
| RTL8192EU host monitor | 29,175 | 29,191 | 0 |
| RTL8192EU TAP | 4,642 | 4,643 | 0 |
| RTL8188EU observer | 30,688 | 30,716 | 0 |

Both adapters passed the post-test actual-RX health gate. The host vifs disappeared promptly; the
selector recreated a clean monitor interface, and the joined-session 15-second teardown timeout did
not reproduce in this stop.

| File | Bytes | SHA-256 |
|---|---:|---|
| `host_console.log` | 40,209 | `d042ca080cbd264e44e595f1c5ebc9eb15408306ed3376804414502307ab1ea2` |
| `host_ldn_mon.pcap` | 8,140,311 | `d9acc528b6321ba822a18a38c322ae0d524d36930c8cd7ba100daea580041fb3` |
| `host_ldn_tap.pcap` | 707,507 | `85de2dfae539bd813fbfac155d2f96564576a509b12c63f602d310d9f2d9b0f7` |
| `observer_rtl8188_ch6.pcap` | 7,436,209 | `dce649835674b31bc96231a2f9de70306ec27cb937be5a9c8e3c7ddf9df4fc45` |
| `pc_host_pia.jsonl` | 1,601,038 | `06810861a309d969b3ee478a3e59d31b20e3e797850a66f1951b049944a8710e` |
| `run_host.sh` | 774 | `ea2470521cd1663a996dd8c3c0713becbf292dfacf04f5c4208a2b12702ac2bc` |

## Independent next-layer source audit

`pret/pokefirered` commit `c75f352304d529f6ba92d4f74b9cf8b5c3810788` assigns the next commands as
follows:

1. Each player selects a Pokémon.
2. Player one sends a 20-byte `LINKCMD_READY_TO_TRADE` block with its cursor.
3. Player zero records its own selection locally and receives player one's ready block.
4. Once both are ready, only player zero broadcasts `LINKCMD_SET_MONS_TO_TRADE` with player zero's
   cursor (`Leader_HandleCommunication`).
5. Both sides display the confirmation screen and, on YES/valid, send `LINKCMD_INIT_BLOCK`.
6. Once both confirmations are ready, only player zero broadcasts `LINKCMD_START_TRADE`.
7. After each animation, both send `LINKCMD_READY_FINISH_TRADE`.
8. Once both finish statuses are ready, only player zero sends `LINKCMD_CONFIRM_FINISH_TRADE`.

The existing `TradeEngine` is explicitly follower-oriented. It sends its own
`READY_TO_TRADE`/`INIT_BLOCK`/`READY_FINISH_TRADE` and reacts to
`SET_MONS_TO_TRADE`/`START_TRADE`/`CONFIRM_FINISH_TRADE`; it does not yet perform the player-zero
aggregation/broadcast steps. This is now the precise roadblock.

## Next implementation and live gate

Implement a contained parent/leader shim without changing the live-proven follower path:

- treat the configured CODEX slot as player zero's local ready selection;
- reassemble the Switch's `READY_TO_TRADE` block and retain its cursor;
- wait until both selections are ready and no block sender owns the row;
- send an owner-zero `SET_MONS_TO_TRADE` block using CODEX's cursor;
- preserve the Switch cursor for eventual received-Pokémon extraction;
- suppress follower-only leader-role emissions from parent row zero.

The next live success criterion is the Switch showing `Is this trade okay?` after the user selects a
Pokémon and chooses Trade. Stop there before confirmation unless the new code explicitly implements
and tests the confirmation/start stage too.

Do not retune radios, channels, CCMP, Pia, Reliable, party pacing, or standby timing. They all passed
in this capture.
