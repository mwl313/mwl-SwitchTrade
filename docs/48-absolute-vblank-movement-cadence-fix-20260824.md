# 48 — Absolute-VBlank movement cadence fix (2026-08-24)

## Outcome

Emulator `53d8878` removes the scheduler defect that made the PC-host avatar movement visibly
jitterier than native Switch-to-Switch movement. The live loop now targets absolute 59.727 Hz
VBlank deadlines rather than performing one tick and then sleeping a full VBlank.

This is offline-regression tested and intentionally not hardware-tested yet because the user will
perform the visual Switch test later.

## Root cause

The old loop was effectively:

```text
receive/decrypt/process/build/send work + sleep(16.74 ms)
```

Processing time was therefore added to every frame period. During the busy room phase, decrypting
Pia, processing Reliable traffic, building RFU rows, and sending the parent batch could consume a
material fraction of a VBlank. A 12–16 ms work interval plus the unconditional 16.74 ms sleep yields
roughly 30–35 updates per second, matching the user's laggy/jittery movement observation. The final
Switch A proof capture carried 5,695 outgoing Pia datagrams over 168.27 seconds (~33.85/s); not every
tick must emit a datagram, but this is consistent with the busy-path cadence loss.

## Fix

`frlgtrade.py` now:

1. uses the existing shared `Sim.MS_PER_VBLANK` timing constant;
2. records one monotonic absolute deadline before entering the live loop;
3. subtracts work time and sleeps only for the remainder of the VBlank;
4. advances from the prior deadline while on time, preventing accumulated drift;
5. resynchronizes to the current monotonic time after an overrun, preventing rapid catch-up bursts.

The same pacer is used on all three loop paths: connection bootstrap, normal active gameplay, and
the bounded post-disconnect LDN tail. No RFU command, Pia packet, timeout constant, or trade FSM state
was changed.

## Verification

The deterministic clock regression proves:

- 5 ms of work in a 20 ms test period sleeps 15 ms, not 20 ms;
- consecutive on-time frames remain on absolute 20/40 ms deadlines;
- a late frame resynchronizes without sleeping or emitting multiple catch-up ticks;
- the next frame after resynchronization returns to the normal absolute period.

```text
focused parent/Pia suite                     16/16 PASS
ordinary WSL suite excluding optional relay 139/139 PASS
py_compile                                   PASS
diff --check                                 PASS
hardware movement comparison                 DEFERRED BY USER
```

## Deferred acceptance check

When the user returns, a short room-entry movement check is sufficient; a full trade is not required
to judge cadence. PASS is substantially smoother remote-avatar motion with no room-entry, Reliable,
or keepalive regression. A capture should then measure parent command intervals near the native
VBlank cadence and preserve any scheduler overruns for later production instrumentation.

