# Switch-to-Switch software qualification evidence

This supplements the I01–I18/T01–T44 closure. No physical device was operated.
The tracked acceptance manifest is not itself an overall PASS. The CI-produced
`ABC_SOFTWARE_PREFLIGHT_CLOSURE.final.json` binds all I01–I18/T01–T44 to a literal
SHA only after both mandatory platform jobs succeed. Do not substitute an older
green SHA, a skipped job, or this document for that attestation.

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

## Entrypoint and failure qualification

Actual Windows console Ctrl+C with the real CLI and StageSession now passes;
`CI104_STATE_READ_DIAGNOSIS.md` records the original CI reader failure and its
bounded correction. Commit 74a0c326 has successful Windows/Ubuntu CI #113.

The actual mirror driver/DirectB/StageSession remains pending for 181 real
seconds, then a real DirectA physical-boundary actor joins successfully (189.40s
test duration). No readiness deadline or clock is substituted. Actual LDN kernel
faults cover early association failure, failed VIF deletion, and cancellation
at scan/join/AP/association/control waits. See MTA-CORE-013 for cancellation-group
release evidence; true unknown/partial teardown is still fail-closed.

Actual WebSocket interruption variants now pass: OPENING_LOCAL cancels the real
DirectB nursery and both CLI owners fail cleanly; ACTIVE replaces both socket
instances in the same Pair and the second generation transfers RFU. A physical
local room end while Host awaits its Internet peer returns to discovery, then
two further generations succeed. The full-source run will also cover >5 seconds
without application data in ACTIVE before transmitting again.

`tests/test_dev_entry_route.py` invokes the original dev.ps1 and DevOverlay in a
real PowerShell process. Only the external WSL process boundary is modeled;
actual source enumeration/allowlisting/hashing, installed dependency comparisons,
immutable-release reuse, command dispatch, option validation/normalization, role
inversion and source identity propagation run unchanged. It verifies split/equal
USB/channel options, leading-zero code, an option value named `host`, malformed
input before runtime access, and Windows common-relay environment forwarding.
Real streaming/ordinary stderr/scalar exit is independently exercised with a real
child process. A real hidden Windows console CTRL_C_EVENT cancels the real
CLI/StageSession child; Linux guardian tests cover pre-CLI OS-command cancellation,
unresponsive owned process failure, and EOF into the real CLI/StageSession.
No test launches wsl.exe or touches an installed distro.

This is a **composed qualification**, not a claim that one test runs Windows,
WSL, two physical radios and the Internet simultaneously. Windows tests prove the
original dispatcher and process/control boundaries; Linux tests prove the owned
process-group guardian and actual radio shell scripts with virtual OS commands;
the main RFU test proves the complete actual Python/protocol path over real
localhost TCP/WebSockets. The substitutions join at the documented OS boundaries.

## REAL / substituted boundary map

| Component | Qualification status | Replacement/observation |
| --- | --- | --- |
| dev.ps1 / DevOverlay route, source/requirement hashes | REAL PowerShell | WSL process response/filesystem model only; actual git and source files |
| Windows console, streaming, Ctrl+C handler and pipe | REAL | New hidden test-owned console; no user's console |
| Linux parent guardian / process group / SIGINT | REAL on Ubuntu | Test-owned child; separate real CLI/StageSession child scenario |
| wsl-radio-prepare / radio-health-gate shell code | REAL in Ubuntu CI | Fake sysfs/iw/ip/tcpdump/module/USB commands; no device |
| Core CLI / composition root | REAL | OS environment and console output capture; no CLI lifetime replacement |
| Pair API/store / Core relay | REAL | Localhost address, ephemeral listening port; no FakeRelay |
| WebSocket / WireClient / WireState / CoreSupervisor | REAL | Real TCP; fault closes the captured server-side socket |
| Switch driver / DirectA / DirectB / StageSession | REAL | Default factories, real Trio threads/nurseries and readiness/lifecycle |
| LDN 0.0.17 Factory/Scanner/Station/AP/STANetwork/APNetwork | REAL installed library | Netlink/netdev/TAP/ioctl/raw/UDP socket primitives and key-file reads only |
| LdnDataPlane | REAL default A/B factories | Raw/UDP socket implementation models two isolated local radio domains |
| build_tunnelsim / TunnelSim / Pia / Reliable | REAL | Constructor observation only, no FakeSimulation or altered tick decision |
| CoreTunnelAdapter | REAL | Never called directly as the RFU success input/output |
| Physical Switch application boundary | SUBSTITUTED | Opaque synthetic GBA/RFU queues; actual local protocol encoding on each side |
| Nintendo Switch RF/driver/game behavior | NOT EXECUTED | Physical runbook; no software/CI claim proves this |

The main fixture logs only synthetic data for diagnosis. Production logging is
allowlisted gates/resource states/counters and does not enable Sim's raw logs,
captures or game payload interpretation. T13 covers real installed key-loader
failures; T16 now suspends actual AP/control/STOP_AP OS awaits and asserts bounded
technical deadlines without changing human readiness limits.

## Recorded local results and final gate

- Full local Windows Python 3.12 run collected from source `3f0a172`: **783 passed,
  6 skipped, 22 warnings, 533.67s**, exit 0. Report:
  `.qualification/full-pytest-3f0a172.xml`. Platform-only skips are paired with
  their owning CI platform; they do not stand in for core E2E qualification.
- Focused Direct/driver/CLI/input/ownership tests: 121 passed before the final
  argument/environment additions; later original dev route/overlay checks:
  24 passed. Attestation-negative + actual Direct-fault/deadline checks: 24 passed.
- Actual default-plane + real two-generation RFU regression after raw UDP
  validation: 2 passed, 54.81s. Actual 181s wait: 1 passed, 189.40s in its initial
  focused run and included in the full run.
- CI #104/#112 reader failures are diagnosed in `CI104_STATE_READ_DIAGNOSIS.md`.
  CI #114 exposed control-error/cancellation grouping (now independently proven
  leaf cleanup) and a Windows test launch budget: CLI started 11.7s after test
  start, beyond its old 10s launch allowance. The startup allowance is now 30s;
  post-ready graceful cleanup still has its separate 10s assertion.
- CI #115 (`3f0a172`, run 34100189105) passed Ubuntu. Windows had 782 passed,
  6 skipped and one legacy resource-soak failure: whole-pytest native thread
  count rose from 5 to 7 against a +1 bound. No Python thread identities were
  captured in that run, so it does not identify a product thread leak. Local
  isolated observation found 7 native threads with only MainThread before client
  startup, 9 with the two transport threads, and 7 after both stopped. The soak
  now runs its unchanged traffic and OS resource bounds in its own interpreter,
  records Python thread names alongside native counts, and requires exactly two
  owned transport threads while active and only MainThread after stop. This
  removes whole-suite measurement contamination without raising any allowance.
- These historical packet counts are not the final SHA's attestation. Final CI
  reruns all tests, shell syntax/ShellCheck/radio lifecycle/dependency audits on
  Ubuntu, and full pytest/.NET builds/self-tests/provisioning simulations/PowerShell
  parsing/lifecycle/dependency checks on Windows. Only then is the resolved
  final JSON artifact published by the dependent `software-preflight` job.

The machine-readable manifest maps every T-ID to runnable test nodes, assertions,
source and evidence, and every I-ID to its required T-IDs. Unknown/partial entries
or known software gaps prevent attestation. The final report also records a full
local run on the exact final SHA; do not conflate it with an earlier packet run.

Final source audit additionally reproduced an unbounded PairStore rate-identity
table: 2100 synthetic invalid-code clients left 4200 buckets even after expiry
and sweep. Per-key deque bounds did not bound the number of keys. Expired buckets
are now reclaimed and the total live table is capped at 4096, rejecting new
identities with the existing 429 contract without evicting live guess budgets.
T38 includes capacity, expiry and existing-budget regression coverage. See
MTA-CORE-015; no external relay or real client address was used.

Ubuntu CI #116 exposed a transient stream loss during active reconnect's resync.
The previous implementation made only one new-stream attempt. A new real relay
fault closes the second Guest WebSocket immediately after its authenticated
hello; it reproduced the terminal failure before the fix. Recovery now retries
only transport loss with bounded backoff inside the existing technical deadline
and lease. Protocol/auth failure stays terminal, old Generation data is never
reused, and the first socket exception remains in the cause chain. The stronger
`active-retry` scenario must exchange second-generation RFU after that additional
loss. T32/T38 cover it alongside bounded/permanent-failure regressions.

Full local b8eb58a also exposed cancellation arriving during the driver's
already-running no-room retry stop. The asyncio wrapper previously returned
before its StageSession stop thread, recording false unknown cleanup. A gated
actual DirectA/StageSession reproduction now verifies that repeated cancellation
waits for the owned stop result; fatal primary and real cleanup failure remain
separate and sticky. T17/T24 include all four combinations. The two other local
failures were phase/clock assertions: the 120ms recovery deadline need not fit
two attempts (separate success test does require retry), and stdout streaming is
now proven by a child waiting for the parent's acknowledgement rather than
requiring PowerShell cold startup to finish within 1.5s. Production bounds did
not change. See MTA-CORE-017 and MTA-QA-023.

## Physical handoff and modularity

See `SWITCH_TO_SWITCH_PHYSICAL_RUNBOOK.md`. No physical result has been claimed.
Real console interaction, radio timing/driver/firmware/kernel behavior, and actual
machine provisioning are outside the virtual boundary's proof.

Core carries opaque protocol-tagged payloads and 16-bit flags and owns generic
Pair/Generation lifecycle. Switch RFU flag constraints, Direct/LDN policy, Pia and
TunnelSim remain under the Switch endpoint/composition boundary. A future
`retroarch_gpsp` driver can implement the same discover/accept/receive/send/end/
cleanup contract with negotiated compatible protocol capabilities. It need not
add game commands or Switch imports to Core/Relay. No emulator implementation,
Phase D/E execution, legacy Room/Ready/Continue path or desktop redesign was added.
