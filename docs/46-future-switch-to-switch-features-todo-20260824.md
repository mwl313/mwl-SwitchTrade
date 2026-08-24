# 46 — Future feature scope: Switch-to-Switch only (2026-08-24)

> 2026-08-25: this feature list is retained, but the authoritative ordered beta and future backlog is
> `docs/49-production-beta-priorities-20260825.md`.

## Permanent product decision

Future FRLG online features are **real Switch-to-real Switch only**. The production bridge must not
act as a battle opponent, Union Room user, or minigame player, and must not grow a separate semantic
emulator for every button, move, or battle event.

Trading's PC-host implementation remains a protocol oracle, diagnostic harness, regression fixture,
and optional automated-trade tool. It is not the architecture to copy for battles and other modes.

## Target architecture

```text
Switch A <-> local LDN/Pia terminator A <-> generic RFU slot/block tunnel
         <-> internet relay <-> generic RFU slot/block tunnel
         <-> local LDN/Pia terminator B <-> Switch B
```

The two games remain authoritative for movement, choices, battle state, animation, RNG-driven game
logic, results, and saves. The bridges transport generic RFU commands and blocks, remapping only the
session-local player/owner fields required by the two local Pia sessions.

## Future TODO, in order

1. Finish and freeze the PC-host trade/close golden baseline.
2. Fix local held-key cadence and match native Switch-to-Switch movement smoothness. Implemented as
   the absolute-VBlank scheduler in emulator `53d8878` (139/139 ordinary WSL PASS); visual hardware
   comparison is deferred until the user returns.
3. Specify a feature-neutral RFU tunnel envelope: session, direction, RFU frame/slot, sequence,
   timestamp, player mapping, and reconnect epoch.
4. Terminate LDN/Pia/Reliable locally on both ends; never send WAN latency into the local 802.11 ACK
   path.
5. Pass raw `SEND_HELD_KEYS`, block requests/fragments, standby/close commands, and `SEND_PACKET`
   payloads without interpreting gameplay meaning.
6. Build deterministic player-ID/owner remapping for two Switches; keep the original bytes available
   in captures for audit.
7. Add bounded queues, stale-frame rejection, backpressure, reconnect epochs, and per-direction health
   counters.
8. Capture one controlled native golden trace per activity to lock only its discovery/activity,
   entry, player-count, and teardown boundaries.
9. Validate in this order: Union Room presence/movement -> Union Room trade -> single battle -> double
   battle -> chat/other two-player activities.
10. Treat four-player multi battle and multiplayer minigames as separate later milestones because the
    current PC-host path and tests are two-player.
11. Require byte-level replay tests plus real two-Switch LAN and WAN tests for every advertised mode.

## Explicit non-goals

- No PC-controlled battle AI.
- No decoding and reimplementing every battle action or character input.
- No per-feature cloud game server.
- No claim that raw 802.11 frame relay is production-safe until its ACK/SIFS behavior passes real WAN
  testing. The locally terminated Pia/RFU tunnel is the default expansion path.
