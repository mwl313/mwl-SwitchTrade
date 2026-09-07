# Switch-to-Switch software evidence (work in progress)

This supplements the I01–I18/T01–T44 closure. No physical device was operated.
No overall PASS is claimed here.

## Production path

`tests/test_switch_physical_boundary.py::test_actual_cli_relay_ldn_tunnelsim_two_generations`
runs actual CLI host/join loops, Pair HTTP API, Uvicorn/FastAPI Core relay, real
localhost WebSockets, WireClient, CoreSupervisor, default Switch driver, default
Direct A/B, real StageSession threads, installed LDN 0.0.17, default LdnDataPlane,
build_tunnelsim, TunnelSim, Pia crypto/connection/Reliable and CoreTunnelAdapter.
An observation-only constructor wrapper records real TunnelSim instances.

`tests/virtual_ldn_os.py` replaces Linux netlink, netdev inventory, raw/UDP
sockets, TAP file/ioctl, radio reset and OS configuration/key-file reads. All
keys are synthetic. Actual LDN Factory, Scanner, Station, AccessPoint,
STANetwork/APNetwork encode/decode advertisements, authenticate and forward
encrypted frames through the real monitor/TAP code. Two isolated radio domains
can exchange RFU only through Core.

Physical console actors reuse actual LDN/TunnelSim with synthetic opaque game
input/output queues. The test never invokes the production adapter's
send_rfu/poll directly. It does not claim synthetic game input is a physical
FRLG gameplay capture. AP and monitor share a synthetic radio MAC in this fixture.

Verified:

- Local room first, Internet Guest over five seconds later; local Pia/RTT remains live.
- Guest waiting first, second local room over five seconds later.
- Opaque bytes and valid Reliable AppData flags in both directions.
- Physical leader leaves its LDN context; actual CLI loops retain Pair and
  automatically admit a second generation, which transfers real datagrams too.
- One Pair/code; no manual supervisor lifecycle/admission invocation.
- Empty owned netdev/TAP/raw-socket inventory and SwitchTrade threads at final close.

A separate default-data-plane test proves A/B local/peer identity binding and
station raw packet -> actual APNetwork -> TAP -> LdnDataPlane delivery.

## Newly exposed defects

1. CLI printed Bridge active but child Pia stayed at FINALIZE: Sim consumed valid
   Reliable before the connection FSM could observe its completion signal.
2. Automatic mirror had no RTT maintenance while remote RFU was pending. Automatic
   endpoints now enable bounded RTT/echo and Session accept retransmission;
   legacy capture-replay cadence stays unchanged.
3. Local simulation was stopped while awaiting the Internet peer. Driver now
   starts maintenance at LDN readiness; Core DATA pumps still require admission.
   Early RFU is bounded, overflow fails explicitly, and no game command is fabricated.

`bridge/tests/test_tunnel_pia_liveness.py` covers Reliable completion, Session
response retransmission, RTT fields/echo/measurement and bounded probes. Existing
native parent bootstrap gold tests remain in the focused regression suite.

## Remaining before final closure

Actual dev/PowerShell interruption and WSL boundary qualification; real-library
failure/cancellation/reconnect matrix and historical 120/180-second equivalent
waiting; complete I/T evidence; CI #104 diagnosis; physical runbook; full pytest
and exact-final-SHA Windows/Ubuntu CI.
