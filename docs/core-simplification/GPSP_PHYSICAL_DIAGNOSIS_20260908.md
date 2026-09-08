# Switch to gpSP physical trial: pause and diagnostic handoff

## Latest update, 2026-09-09

Trial04 is stopped. A production RFU advertisement-format defect is confirmed,
but its full field mapping is not yet repaired. A separate scan-cancellation
cleanup failure was preserved; the exact USB attachment was released. See
[the current research and unresolved repair record](GPSP_COMPATIBILITY_RESEARCH_20260909.md)
before any retry. Earlier trial notes below remain historical evidence, not a
current readiness assertion. No new Pair is active.

## Scope and current verdict

Branch: `codex/gpsp-endpoint`. Physical-trial source:
`61be8530cbcee4d93fb87fc3b476e05f09d8d213` (clean).
This follow-up adds opt-in diagnostics, not a compatibility fix or physical PASS.
The user paused physical testing and authorized diagnostics, focused tests and
push only. Do not restart Host, manipulate the Switch/VM, install/reset WSL,
deploy a relay or change emulator settings without a new request.

The user operates a Switch Group Leader and Windows VM RetroArch/gpSP Guest.
The current radio/runtime source path and process identities are in the ignored
local `.qualification/PHYSICAL_HOST_FIRST_START_20260908.md`, not public logs.
Supported frontend/core identity and normal setup remain in
[the VMware runbook](GPSP_VMWARE_RUNBOOK.md).

## Measured progress (2026-09-08, Korea time)

| Trial log suffix | Evidence | Outcome |
| --- | --- | --- |
| 1523 | Direct A reached A9; Guest joined Pair | Host ended with S_PEER_CLOSED; game link not proven |
| 1538 | 15:40:07 Direct A A1-A9 passed; Host Bridge active; local Netplay/RFU mode verified | 15:41:22 local_room_ended; first generation cleanup succeeded. Next scan found a room, but 15:41:28 A5 failed with A_ASSOCIATION_FAILED |
| 1547 | 15:50:19 Direct A A1-A9 and Guest generation preparation passed; Host Bridge active | User's actual Join Group list remained empty even after re-entering; no Guest Bridge active evidenced. Host stayed connected until requested Ctrl+C at 15:55:15 |

Third-trial exit: `cleanup_ok=True`, every recorded owned resource released,
`pia_rx=1698`, `pia_rx_failed=0`. No old Core/guardian or created VIF/TAP remained;
the baseline wlan interface was not deleted. These Pia counters do **not** prove
RFU payload exchange, advertisement consumption, gameplay or trade success.
The exact test USB attachment was released afterward. Host trial is stopped.
User-owned RetroArch/game is untouched; VM final process state is user-observed.

Do not conflate the two open problems:

1. Empty gpSP game room list while the Host connection remains alive.
2. Previous local LDN session termination followed by failed reassociation.
   That failed attempt also recorded `join.factory:ExceptionGroup`, factory
   state unknown and radio_quiescent=false. Later absence of its resources does
   not retroactively make the failed cleanup report successful.

`StageSession` currently combines DisconnectEvent/LeaveEvent as local_room_ended;
the previous log lacks the event type/reason. The association report preserves
the stable gate/code but not the underlying exception leaf. Neither a deliberate
room exit nor a particular radio/driver bug has been established. The third trial
did not reproduce that termination before the user-approved stop.

## Diagnostic patch

Existing `--log-dir` / `--verbose` enables `gpsp_rfu_progress` in the gpSP driver.
No new flag, dependency, packet, timeout, handshake, emulator control, or Core/
Relay protocol change. Summaries use the existing advertisement task every five
seconds, plus activation, first advertisement write, first incoming RFU kind,
state/link-ready changes, advertiser failure and final close.

| Field | Evidence / limitation |
| --- | --- |
| state | searching, connecting, connected, closed or failed converter state |
| advertisement_writes | Completed broadcast writes to local Netplay; **not** gpSP consumption or game acceptance |
| local_writes | All completed generation action writes to local Netplay; excludes final cleanup commands |
| gpsp_packets / gpsp_kinds | Packets reaching this generation from gpSP, grouped by finite RFU command names; mode probe and retired-packet handling occur before this counter |
| switch_packets | Frames handed to the converter by Core; counts attempts including rejected input, not valid game exchanges |
| core_enqueued / core_dequeued / core_queue | Local outbound queue progress; dequeue is not remote delivery acknowledgement |
| link_ready | Existing child-transfer criterion; never inferred from broadcasts or socket liveness |

All counters reset with each Generation. There are no RFU/advertisement payloads,
trainer names, ROM/save bytes, session/header IDs or new process-path dumps in
these diagnostic records. Generation correlation ID is retained. Existing logs
may still contain private process paths; inspect/redact before sharing.

Interpretation on the next explicitly authorized trial:

- No first advertisement write: investigate activation/advertiser/local write.
- Writes increase, searching, no connect_request: gpSP/game has not requested a
  connection. Investigate broadcast encoding, game search/filter compatibility
  and frontend consumption; a write counter alone cannot distinguish them.
- connect_request received, connecting, outbound Core queue drains: inspect
  Switch response and Pia/Reliable progress, not initial room discovery.
- connected but no child_transfer/link_ready: investigate post-ACK RFU gameplay.
- Any new error/unknown cleanup: preserve first failure and stop; no blind retry.

## Resume later

1. Read this record and the local identity/evidence note; check local/remote HEAD
   and user changes. No need to reload historical archives.
2. In the VM repository, after its old SwitchTrade command has exited:

   ```powershell
   git status --short --branch
   git pull --ff-only origin codex/gpsp-endpoint
   git rev-parse HEAD
   ```

   If the checkout has unrelated edits, preserve them and resolve before updating.
   Dependencies and RetroArch/core binaries have not changed; no reinstall needed.
3. Recheck physical Host USB ownership. After detach, the old persisted adapter
   record had no bus ID: **do not assume it is still available at its old bus**.
   Verify the device is returned from VMware if needed, then apply the normal
   identity-bound attach and radio gate. No force binding or automatic capture.
4. Only on a new user request, start a fresh Host with a fresh log directory and
   give its new Pair code to the VM. All old trial codes are obsolete.
5. VM, from the repository, after manually running supported RetroArch/gpSP:

   ```powershell
   .\dev.ps1 run join <NEW_CODE> --emulator gpsp --relay https://relay.pangyostonefist.org --log-dir .qualification/physical-gpsp-04
   ```

   Replace `<NEW_CODE>` with the actual six digits; this is a template, not a live
   command. Connect Netplay manually to 127.0.0.1:55435; choose in-game Join Group
   only after its prompt. Keep the Switch Group Leader room open.
6. In a second VM PowerShell, follow the same file without stopping the client:

   ```powershell
   Get-Content .qualification/physical-gpsp-04/switchtrade-core.log -Tail 30 -Wait
   ```

   Run in the repository directory. Record game-action timestamps, current
   progress summaries, errors and a screenshot. Do not collect raw game packets
   or saves as a default diagnostic step.
7. End with owning-console Ctrl+C, collect final summaries/cleanup and check
   identity-bound residue. Do not reuse a failed Generation or automatically
   retry a terminal failure.

## Verification boundary

Focused tests exercise existing local Netplay sockets, converter and real relay
helpers, plus the added diagnostic fields, throttling, per-generation reset,
failed writes, state changes and payload redaction. They are not a new physical
or stock-process qualification. Full pytest, long stock-process soak and final
Windows/Ubuntu CI are not claimed by this diagnostic-only packet. Exact commit,
push and local test results are recorded in the local handoff and task response.

Local focused verification: **80 passed on Python 3.12 and 80 passed on 3.14**:
`test_gpsp_endpoint`, `test_gpsp_rfu`, `test_gpsp_netplay`, `test_gpsp_cli`, and
`test_agent_context_policy`. Existing upstream deprecation warnings remain.
Incident index check and Git whitespace check passed. No additional physical
trial, full suite or long-running stock-process qualification was performed.
