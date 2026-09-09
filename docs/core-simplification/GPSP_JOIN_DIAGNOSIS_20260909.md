# Trial08: connected RFU, failed game join

Branch: `codex/gpsp-endpoint`; verified clean local/remote repair base:
`76d89638853fc7a02be7672d11b85769047e7f64`.
Scope: correlate the newly supplied Guest log with the preserved Host evidence,
repair the diagnostic/qualification blind spot, and stabilize the failing
loopback fixture. No physical retry, radio operation, VM/core/save/config change,
installation, or relay deployment. Main and other branches remain untouched.

## What is established (and what is not)

- The first generation reached native WA acceptance, child data and returned
  parent frames. The Guest counted 266 CLIENT_SEND and 267 CLIENT_ACK packets;
  271 Switch frames reached its endpoint before one **gpSP DISCONNECT**.
- The Guest's first generation closed as `local_ended`, with clean cleanup.
  The matching Host generation ended cleanly afterward. That is lifecycle
  evidence, **not a successful join or trade**. The user saw Trainer unavailable.
- The later `T_PEER_CLOSED` / `S_PEER_CLOSED` belongs to the recorded planned
  Host stop, not the original game failure. The second generation did not
  establish a new game connection. Its missing AppData is not another proven
  receive-sequence defect.
- The Host's first receive stream initialized and advanced without receive
  deferrals or decryption failures. The previous bootstrap blocker was not
  observed. Its outbound pending queue reached 256 with 43 more frames waiting
  upstream and six Reliable frames in flight. This proves pressure, **not** why
  ACK progress was slow, whether frames were NI retries, or which game condition
  caused the disconnect.
- The supplied log contains no VM `git rev-parse HEAD` result. The Host base and
  overlay identity were verified privately; identical VM SHA is not established
  by the log alone. Do not report this as a same-SHA physical qualification.

The previous logs expose RFU1 kinds but not native LLSF/NI state. They cannot
distinguish a native game rejection from an NI timeout, receiver-buffer loss,
or an unmodeled protocol detail. The commercial join's root cause remains open.

## Primary-source checks

[Pinned gpSP RFU implementation](https://github.com/libretro/gpsp/blob/74db5e5/rfu.c)
emits CLIENT_ACK before trying to admit HOST_SEND to its four-entry game-facing
buffer. Thus a CLIENT_ACK is not proof the game consumed the frame, and it is
not a native NI acknowledgement. Dropping repeated-looking data on that premise
would be unsafe. No duplicate suppression, fabricated game ACK, timeout increase,
queue/window enlargement or relaxed validation was implemented.

[Native librfu framing and NI receiver/sender](https://github.com/pret/pokefirered/blob/c75f352304d529f6ba92d4f74b9cf8b5c3810788/src/librfu_rfu.c)
defines the separate child/parent LLSF headers and NI state/n/phase/ack fields.
The endpoint observer uses those structural fields only. It never copies or
interprets a trainer, game status byte, party, save, or game command as a verdict.

## Changes

1. Generation-local, read-only LLSF observations on validated translator input:
   `ni_start`, `ni`, `ni_end`, `null`, `uni`, and their NI-ACK counterparts;
   structural state/n/phase/size, bounded first-change trace, repeated-slot counts,
   and explicit unknown/idle counts. Unknown structures remain opaque and are
   forwarded unchanged. Invalid outer framing cannot publish observations.
2. `gpsp_rfu_progress` includes these observations and `disconnected_by` (`gpsp`,
   `switch`, or null). First observed categories produce an immediate entry;
   repeated packets do not force per-frame logging. No game success is inferred
   from `Bridge active`, socket ACKs, NI headers, or successful cleanup.
3. `switch_rfu_progress` adds new-send/retransmission scheduling counts,
   send-window base and RTO (not proof of peer delivery). Together with existing queue and receive-window fields these
   distinguish local Reliable send pressure from absent native NI progress.
4. The Ubuntu-failing full-queue fixture no longer rebinds the same TCP port in
   two independent scenarios. Separate test owners get fresh ports/teardown.
   Synthetic dialing waits for actual listener readiness or the original opening
   failure, instead of treating one scheduler yield as readiness. Production
   port exclusivity, errors, listener code and timeouts are unchanged.

## Verification scope

- Tests distinguish RFU1 socket ACK from native NI ACK, preserve all repeated
  frames byte-for-byte, verify unknown/malformed handling, bounded/private
  snapshots, fresh-generation state and explicit disconnect sources.
- The existing full endpoint pressure test now first performs a modeled native
  NI identification transfer and parent join-status exchange, then UNI both
  ways. ACKs are injected at game input only after the corresponding frame
  actually completes the transport path. Both generations use the same Pair
  and local Netplay connection, then run the existing 1,024-frame pressure test.
- That path includes real WebSocket relay, WireClient, CoreSupervisor, gpSP
  driver/converter, Switch driver, Direct A/B, StageSession, LDN encryption,
  TunnelSim and CoreTunnelAdapter. OS/radio and physical game/frontend inputs
  are modeled. It is **not** the commercial game or actual stock process, and it
  does not reproduce the physical join failure. Native NI byte transport passed
  without changing wire behavior; do not describe this as a proven gameplay fix.
- Local Windows Python3.12.14 full pytest: **1,068 passed, 6 skipped** in
  780.94 seconds. Skips are existing Linux-only checks. The numeric transmit
  counter test added after this run's collection passed separately on3.12/3.14;
  it changes no production behavior. Context/index checks and final focused
  checks also passed (39 checks in the final3.12 focused batch).
- Python3.14.7 focused: **107 passed**, plus the additional counter check
  (**1 passed**). The modeled two-generation NI/pressure path passed on3.12,
  both separately (53.04 seconds) and in full pytest. No new actual-stock soak
  is claimed locally. New-SHA CI is separate and will not be waited on here.
  The base run had successful Windows jobs and the identified Ubuntu fixture
  failure; it was not overall green. No new actual-stock soak is claimed locally.

## Next evidence, only on a user-authorized trial

Update both clients, verify their SHA, use the existing supported core, and
create one new Pair through the normal Host radio gate. No relay update or
emulator reinstall is required. Keep the first failure and both complete logs
through cleanup. Do not keep retrying an unavailable trainer.

Compare, in this order:

1. Child NI_START emission and matching parent NI_START_ACK state/n/phase.
2. Child NI data phases and parent NI ACKs, then NI_END/NULL.
3. Parent NI transfer and child **NI** ACKs (not CLIENT_ACK counts), then UNI.
4. At the first stalled step, compare Host new sends, retransmissions, send-window
   advancement and RTO against bounded queue pressure.
5. Identify the RFU disconnect source; keep later transport stop/cleanup separate.

Headers localize the stalled layer; they do not expose a game rejection reason
or prove that gpSP admitted every packet to the game's four-slot buffer. If the
headers still cannot distinguish the remaining hypotheses, record that limit
before proposing any targeted additional instrumentation.

When giving VM commands, use one plain command per fenced block with **no `PS
C:\...>` prompt or copied error output**. Use relative forward-slash log paths
from the repository directory. User log-transfer errors are not protocol faults.

## Verdict and modularity

**Diagnostic/qualification repair; commercial join unresolved.** There is no
trade-success, physical-readiness, or overall preflight PASS claim in this packet.
RFU interpretation remains under `endpoints/retroarch_gpsp`; Core/Relay stay
opaque and unchanged. Switch-to-Switch only gains numeric TunnelSim diagnostics.
No mGBA/VBA capability, battle support, or process-control feature is added.
