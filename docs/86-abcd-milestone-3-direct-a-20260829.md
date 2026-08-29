# ABC+D Milestone 3 direct A qualification evidence

> Branch: `codex/abcd-orchestration-rework`
> Source commit: `80c4e13`
> Status: source complete; PC A immutable-runtime one-Switch A0-A9 qualification passed; PC B pending.
> Scope: local Switch-hosted room observation, exact admission, station join, and bounded hold only.

## 1. Project entry decision

PC A's installed cold P0 run `f0a999b3-cfc7-4eda-bcfd-d18df266d72a` passed functional readiness
and verified cleanup. On 2026-08-29 the owner explicitly accepted that evidence as sufficient to
begin A. This decision does not claim that PC B passed P0 and does not remove PC B from later
cross-PC qualification.

## 2. Implemented boundary

The direct A path is independent of the legacy desktop, room orchestration, production diagnostics,
synthetic peer, and relay. It consists of:

- `switchtrade.connection.a_stage`, the one-shot A0-A9 owner;
- `switchtrade.connection.direct_a_endpoint`, the installed WSL endpoint;
- `switchtrade.connection.direct_a_harness`, the Windows qualification CLI;
- the existing P0 passive/runtime, exact USB lease, radio preparation, identity-bound launch, and
  verified cleanup boundaries;
- `direct-a-stage.v1`, the redacted stage report contract.

Direct A marks relay evidence `not_required`; it does not contact the relay. This preserves the
architectural rule that A can be admitted or rejected independently of C.

## 3. Ordered behavior

One explicit CLI action performs exactly one adapter lease, one long-lived wrapper, and one
PID-preserving endpoint launch. The endpoint then:

1. loads `prod.keys`, pins `ldn==0.0.17`, and validates fixed policy and deadlines;
2. scans only channels 1, 6, and 11 for protocol 3 advertisements;
3. admits exactly one room matching communication ID `0x01006FA0233F8000`, scene 22287, LDN
   version 4, production security, application version 88, `ACCEPT_ALL`, capacity, and six-player
   limit;
4. rejects zero compatible rooms, communication-ID fallback, and ambiguous compatible rooms;
5. validates the 122-byte Pia/RFU application data and retains only its byte count and SHA-256;
6. builds one exact station join parameter set with the 64-byte GBA passphrase;
7. verifies that the kernel-associated host identity equals the selected advertisement before A5;
8. records both CCMP key installs, Nintendo control-port authentication, and stable host/local LDN
   participant state through run-local object checkpoints;
9. resolves the live station interface by kernel index, binds UDP port 12345 and its AF_PACKET receive
   socket, and completes a bounded local hold while watching for disconnect;
10. tears down the LDN contexts, quiesces the selected base radio, restores the run's prior USB
    ownership, and terminalizes only after cleanup is verified.

The validated advertisement crosses the endpoint-to-harness pipe only in memory. Worker event logs,
stage reports, coordinator records, and final harness reports do not contain the advertisement,
BSSID, MAC addresses, credentials, trainer data, or room passcodes.

## 4. Deliberate non-reuse and non-capabilities

The stage reuses the proven low-level `ldn==0.0.17` scan, station, CCMP, control-port, and participant
mechanics. It does not reuse `LiveTransport` lifecycle orchestration, global BSSID monkey patches,
broad radio cleanup, three-attempt orchestration retry, least-participant selection, or communication-ID
fallback. Checkpoint hooks are attached only to objects owned by the current run and cannot affect a
second process or future attempt.

A successful run is `A_CONTROL_READY` local evidence after A0-A9 and the bounded hold. It is not A10,
A11, C1, `A_READY`, B readiness, RFU traffic, a trade, or distributed cleanup proof.

## 5. Automated evidence

The final source regression on 2026-08-29 passed 240 Python tests with one intentional skip. The 31
focused P0/direct-A tests cover:

- exact selection and explicit rejection of fallback and ambiguity;
- Pia header, player-name bounds, base85 alphabet, and 24-byte RFU decode;
- A0-A9 gate ordering and full low-level fake station success;
- exact associated-room identity mismatch;
- truthful A6 classification when CCMP installation fails;
- strict `direct_a` launch-ticket/endpoint matching and preserved PID/start identity;
- a single guest-role launch, one attach/conditional detach, terminal cleanup, and no raw
  advertisement in logs or reports;
- direct-A P0 validation that never invokes relay HTTPS or WebSocket callbacks;
- the existing P0, authority, relay, diagnostics, installer, and endpoint regression matrix.

## 6. Immutable PC A candidate

The installed qualification runtime is:

- source commit: `80c4e13`;
- release: `abcd-m3-80c4e13`;
- runtime content ID: `1fdc912dd49e8a70a376ea17224a547546aa7dcb68643aaead3d1a6e7feb80cf`;
- WSL archive SHA-256: `bd68607be1545851e5e99271a64b988bb326a6e75def687a076f736e008c5aef`;
- WSL archive size: `110368482` bytes;
- custom kernel: `6.18.35.2-microsoft-standard-WSL2+`;
- package directory: `artifacts\qualification\m3-80c4e13\package`.

The replacement provisioner installed it side by side, verified it, activated runtime
`SwitchTrade-beta-abcd-m3-80c4e-1e5305ea80a74e989949c853ea46343e`, and removed the superseded active
runtime. Installed smoke verified the release marker, integrity manifest, direct A modules,
`ldn==0.0.17`, all ten ordered gate names, the custom kernel, zero active endpoints, and zero attached
target USB devices. The direct A CLI was also verified to have no relay option. This smoke did not
attach the adapter or claim physical A success.

## 7. PC A physical procedure and acceptance

Use one Switch only. In FireRed/LeafGreen, enter the Wireless Club Direct Corner, open the Trade
Center, select **Become Leader**, and remain on the room-hosting screen. Do not make a room with a
second Switch.

From PowerShell at the `80c4e13` checkout:

```powershell
$candidate = (Resolve-Path 'artifacts\qualification\m3-80c4e13').Path
$active = Get-Content -Raw (Join-Path $env:LOCALAPPDATA `
  'SwitchTrade\state\active-runtime.json') | ConvertFrom-Json
wsl.exe --shutdown
python -m switchtrade.connection.direct_a_harness `
  --distro $active.active_runtime `
  --runtime-root /opt/switchtrade `
  --selection-file (Join-Path $candidate 'hardware-selection.json') `
  --state-root (Join-Path $candidate 'direct-a-state-pc-a')
```

Accept physical direct A only when the command exits 0, `functional_status=passed`,
`cleanup_status=verified`, `result_level=A_CONTROL_READY`, and the report contains every A0-A9 gate
in order. Post-run evidence must show the run-acquired adapter detached, Linux USB/interface/PHY
absent, no worker process, no recovery record, and no raw advertisement or MAC identity in the saved
files. Any functional or cleanup failure remains evidence to diagnose; it must not be retried until
cleanup is verified.

## 8. PC A physical result

PC A run `88f8e357-2e8c-4981-ad87-4cfaa1f93c31` completed on release `abcd-m3-80c4e13` with exit
code 0. One real Switch hosted a FireRed/LeafGreen Trade Center room. The run produced:

- `functional_status=passed` and `cleanup_status=verified`;
- `result_level=A_CONTROL_READY` and ordered A0-A9 completion;
- exact room detection and a 122-byte validated advertisement, persisted only as SHA-256
  `a2afffc55c865334ff0415f240a46e6e8ae3c918cecdf50b4c7ba657fc85f1fd`;
- successful station association, both CCMP operations, Nintendo control-port authentication,
  stable participant state, UDP port 12345, AF_PACKET binding, and bounded local hold;
- normal worker exit code 0 with no forced termination;
- verified LDN context release, radio quiescence, Windows detach, Linux disappearance, and prior USB
  ownership restoration.

Post-run inspection found no target USB, interface, PHY, endpoint, or worker in WSL. Windows showed
USB bus `4-18` detached from WSL. The saved run files contained no raw advertisement, MAC-address,
room-passcode, or trainer-data pattern. This passes PC A direct A only; the formal Milestone 3 exit
gate still requires the same result on PC B.
