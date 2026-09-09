# Core transport burst / recovery repair

Branch: `codex/gpsp-endpoint`. Baseline: `d29759ca05364900bcf56849af13d8573a780939`.
Incident: MTA-CORE-022. Scope: software-only; no physical, VM, WSL or USB operation.

## What is established

The preceding physical trial reached room discovery, RFU acceptance and initial
bidirectional data/ACK exchange, then lost transport. Its recovery close timeout
masked the first Wire/WebSocket exception. Commercial game exchange did not pass.

Independent deterministic reproductions failed at the baseline:

- A 64-frame DATA burst exhausted the send queue before a live writer ran.
- A buffered receive burst exhausted the incoming queue before a live consumer ran.
- A recovery close timeout replaced the original transport failure's cause.

These are confirmed shared Core defects, applicable to Switch-to-Switch too.
They are not proof of the physical trial's initial trigger. A zero queue count
after cleanup cannot exclude a preceding overflow.

## Repair contract

- Queue capacity remains eight. Public send and delivered receive admission wait
  for space under the existing technical timeout; no ordered DATA is dropped to
  admit later DATA or control/close frames. Control frames cannot overtake DATA.
- Validation precedes waiting. Sequence/state mutation occurs only after capacity
  is available. Cancellation consumes no sequence. An old waiting sender cannot
  enter a replacement stream or epoch. The new epoch discards retired outbound
  frames before its probes; a retiring Generation's waiting receive tail is discarded.
- Persistent congestion fails explicitly with `T_SEND_BACKPRESSURE_TIMEOUT` or
  `T_RECEIVE_BACKPRESSURE_TIMEOUT`. Protocol/congestion failures are not retried
  as transient network failures. Human/game waits have no new timeout.
- Peer room close racing a local send is a normal Generation end, not a failed Pair.
- Recovery retains the initiating exception. Generation/socket cleanup failures
  are secondary. An unconfirmed socket close is sticky (`T_CLOSE_UNCONFIRMED`),
  retains its owner and blocks new socket admission; repeated close is not success.
- The CLI WebSocket adapter gives close handshake two seconds, then aborts only
  its owned TCP transport and waits up to one second for local close confirmation.
  This is below WireClient's normal five-second outer bound. It does not prove
  delivery of unsent traffic; a lost Generation is never replayed into the next one.
- Opt-in technical logs include `wire_first_failure` (stable code, cause type,
  numeric received/sent WebSocket close codes and queue depths),
  `websocket_close_abort`, and `wire_close_unconfirmed`. No payload, credential,
  peer-provided close reason or private process identity is added to these logs.

## Verification and acceptance impact

- `tests/test_core_backpressure.py`: bursts, concurrent senders, normal close after
  a burst, persistent stalls, cancellation, invalid flags, epoch retirement,
  sticky close, sanitized diagnostics and real localhost WebSocket close-ACK loss.
- `tests/test_core_supervisor.py`: first-cause/secondary-cleanup separation,
  fatal congestion classification, and peer-close/local-send race.
- `tests/test_switch_physical_boundary.py` adds a `burst` case: 64 ordered packets
  in each direction in each of two Generations, on the same Pair. Actual CLI,
  CoreSupervisor, WireClient, Uvicorn relay, Switch driver, Direct A/B, StageSession,
  LDN, TunnelSim and CoreTunnelAdapter execute. Only radio/kernel primitives and
  physical console input are modeled; no fake endpoint replaces this test path.
- ABC impact: I07/I08/I09/I13, T24/T29-T34/T38; gpSP G10/G13/G17/G18/G24.
  Existing acceptance is not relabeled as a physical pass. Full pytest and
  same-commit Windows/Ubuntu CI remain required for new-source qualification.
- Final-source focused regression: Python3.12 75 passed; Python3.14 93 passed
  (the latter also includes the gpSP endpoint/real relay conversion suite).
- Final-source Python3.14 full pytest: **1034 passed, 6 skipped**, 748.92s.
  Skips are existing Linux-only process-group/guardian/flock/nl80211 tests;
  Ubuntu CI must cover those owning-platform boundaries. Both Generations of
  the 64-packet bidirectional burst and the real >180-second wait passed.
- Development full runs on Python3.12/3.14 each passed1033/skipped6 before the
  final narrow probe-preservation guard/test. They are not final-source
  attestation. Python3.12 final-source focused coverage is recorded above.
- Same-commit Windows/Ubuntu CI, including actual stock RetroArch/gpSP process
  qualification, must run on the pushed commit. Local mocked-peer tests do not
  replace it. No new actual RetroArch process or commercial game test was run
  in this hands-free packet; existing process reports are historical evidence.

## Next user-assisted step

Only after this packet is pushed and the user requests a physical retry: update
both Host and VM to the same feature-branch SHA, use a fresh Pair and separate new
log directory, and test room selection. No relay redeployment, emulator/core or
Python reinstall, save editing or Netplay configuration change is required.
If it fails, retain both PCs' complete opt-in logs from before the first error
through cleanup. Correlate `wire_first_failure` before investigating further RFU
or commercial-game semantics. Do not silently retry or infer success from cleanup.

RFU translation stays inside the gpSP endpoint; Core remains payload-opaque.
No emulator-specific Core/Relay branch, launcher, new dependency or mGBA/VBA
capability is introduced. Successful commercial trade still needs physical proof.
