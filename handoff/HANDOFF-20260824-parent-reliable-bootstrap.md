# Handoff — parent Reliable ACK/WC/WA gate (2026-08-24)

> Superseded for current work by
> `handoff/HANDOFF-20260824-parent-ni-gate.md`.  The WA gate passed live; joined
> teardown remains unresolved despite the no-peer fix recorded below.

## Current branches

- Main repository: `golden-capture-re`.
- Emulator repository (`emu/`): `gptsolreview`, commit `4478ec9`.

Read `docs/32-parent-reliable-bootstrap-20260824.md` first. Raw pcaps remain
local and ignored.

## What is fixed

The PC host now implements the native Reliable boundary that caused the last
“awaiting CODEX” failure:

```text
guest INIT fff0 -> PC ACK fff1
guest WC         -> PC WA(INIT fff0) + ACK fff2
guest ACK fff1   -> parent_link_accepted=True
```

`WA` uses the PC beacon's `rfu_session_id` and echoes the child's `WC` id. The
native sequence/window ids, message flags, payload bytes, and two-message batch
are regression-tested.

The right-seat child game engine remains gated. This commit does not yet send a
parent `T` poll or run parent NI; therefore a live Switch can still time out
after acknowledging `WA`. That later timeout is expected at this gate.

HostTransport clean shutdown is repaired by preventing ldn 0.0.17 from sending
the network-destroy control frame to its own AP participant. Connected remote
participants are still notified. Real RTL8192EU stop completed in 1.191 s and
post-stop actual RX passed.

## Verification

```text
emulator full suite  133 PASS
main suite           13 PASS
real host stop       PASS (1.191 s)
post-stop RX         PASS
```

## Immediate test

Run a health-gated one-Switch PC-host capture and stop after either the guest
ACKs `WA` or disconnects. The required milestone is `PC WA + ACK fff2` followed
by `Switch ACK fff1`. UI room entry is not the success criterion yet.

Once proven live, decode native frame 1282 onward and implement a separate
parent `T`/NI engine. Do not set `HostConnectionManager.connected=True` and do
not call the existing child `_drive_reliable()` in host mode.

## Safety

- RTL8192EU remains the host card.
- RTL8188EU remains observer/guest/relay; do not use AP+monitor host mode.
- Always run the actual-RX health gate before both host and observer captures.
- Do not commit pcaps, `prod.keys`, derived keys, or permanent console secrets.
