# ABC+D Milestone 4 direct B qualification evidence

> Branch: `codex/abcd-orchestration-rework`
> Source commit: `a96f53f`
> Status: source complete; PC A immutable runtime installed and smoke-tested; physical B2-B10 pending.
> Scope: local app-hosted room advertisement, one real searching Switch, control port, and bounded hold.

## 1. Entry decision and boundary

PC A direct A run `88f8e357-2e8c-4981-ad87-4cfaa1f93c31` passed A0-A9 with verified cleanup. The
owner then explicitly directed the project to proceed with Milestone 4. PC B P0/direct A remain
qualification debt and are not represented as passed.

Direct B is independent of the legacy desktop, normal-room orchestration, production diagnostics,
synthetic peer, and relay. It starts at B2 with one immutable release-owned advertisement fixture.
B1 is deliberately absent because live A-to-B delivery belongs to Milestone 5.

## 2. Implemented components

- `switchtrade.connection.b_stage`: one-shot B2-B10 stage owner.
- `switchtrade.connection.direct_b_endpoint`: identity-bound installed WSL endpoint.
- `switchtrade.connection.direct_b_harness`: Windows qualification CLI.
- `direct-b-stage.v1`: redacted stage report contract.
- Existing P0 passive/runtime checks, exact USB lease, long-lived worker, selected-radio lock, and
  verified Windows/Linux cleanup boundaries.

The stage reuses only the canonical low-level `ldn.create_network()` construction mechanics and the
required beacon, retained-CCMP, AP-destroy, and control-port compatibility behavior. Compatibility is
bound to objects created by the current run. It does not mutate shared classes, reuse
`HostTransport` lifecycle orchestration, expose an AP-engine selector, perform broad machine cleanup,
contact a relay, or retry implicitly.

## 3. Ordered behavior

One CLI action acquires exactly one adapter lease and one long-lived worker. The endpoint then:

1. B2 validates the 122-byte `frlg-search-v1` fixture and SHA-256
   `998a8087aa9011dc7b0bc3200b99702c03eeefb3e9c3259349f3b540e6425ce2` before touching the radio.
2. B3 inventories the selected PHY and removes only its stale virtual interfaces and the exact
   run-reserved TAP.
3. B4 loads production keys and constructs protocol 3, scene 22287, communication ID
   `0x01006FA0233F8000`, application version 88, six-participant `ACCEPT_ALL`, 64-byte passphrase,
   legal-channel network parameters.
4. B5 creates and retains the AP, monitor, TAP, and LDN context with run-unique resource names.
5. B6 verifies the Pia UDP/raw data-plane sockets while the AP context remains alive.
6. B7 requires over-air room evidence; a successful real Switch association is the external
   observation that advances B7. Interface-up alone cannot pass it.
7. B8 validates the joining participant and the 1/6 to 2/6 participant transition.
8. B9 sends through the Nintendo control port to the registered real peer and confirms connected
   participant state.
9. B10 holds the AP, participant, TAP, sockets, and endpoint for a bounded interval and fails if the
   Switch leaves.
10. Cleanup closes the run-owned LDN contexts, verifies the exact selected PHY is quiescent, removes
    the exact TAP, exits the endpoint, restores prior USB ownership, and records cleanup separately
    from functional outcome.

Reports contain fixture identity/length/hash, ordered Boolean/count evidence, timing, stable errors,
and cleanup proof. They do not persist the raw advertisement, credentials, passphrase, BSSID/MAC,
packet capture, trainer data, or Pokémon data.

## 4. Automated evidence

The final source regression passed 251 tests with one intentional skip. The focused P0/A/B matrix
passed 42 tests. Direct B coverage includes fixture immutability, B2-B10 order, parameter identity,
run-owned compatibility behavior without class mutation, real-peer event requirements, control-port
failure, association/hold timeout, participant loss, one launch, strict endpoint identity, one
attach/conditional detach, cleanup failure precedence, redaction, and no relay dependency.

The legacy Linux-only bridge test module cannot import Windows `fcntl` and was not counted as a
Windows pass. The admitted compatibility behavior is instead covered through the new run-local Direct
B tests and remains subject to the physical installed-runtime gate.

## 5. Immutable PC A candidate

- release: `abcd-m4-a96f53f`;
- application version carried by the qualification package: `0.2.6-beta.2`;
- runtime content ID: `5696cbc80cdf45cbc8933cafe761fff06ffb348b907d58ef7cde129769a35197`;
- WSL archive SHA-256: `6f8e614ed4d110ccae5d98df37c3db3db68abffced5ed36f125b742395b86877`;
- WSL archive size: `110364608` bytes;
- custom kernel: `6.18.35.2-microsoft-standard-WSL2+`;
- active runtime: `SwitchTrade-beta-abcd-m4-a96f5-329e3033102d4eeaa2aac60336c59c15`;
- package directory: `artifacts\qualification\m4-a96f53f\package`.

The replacement provisioner installed the candidate side by side, verified it, atomically selected
it, and retired the superseded M3 runtime. Installed smoke verified the release and payload integrity,
pinned `ldn==0.0.17`, all B2-B10 gate names, fixture hash, Direct B endpoint import, custom kernel,
zero active endpoints, no Direct B AP/monitor/TAP residue, no relay CLI option, and USB bus `4-18`
detached from WSL. The checks ran from the non-ASCII Windows profile path. This proves package/runtime
readiness only and did not attach the adapter or claim physical B.

## 6. PC A physical procedure and acceptance

Use one Switch only. Do not host a room on this or another Switch. Start the harness first; when its
live evidence reaches B5/B6 and the app-hosted room is advertising, open FireRed/LeafGreen's Wireless
Club Direct Corner, enter the Trade Center, choose **Join Group**, and select the advertised room.

```powershell
$candidate = (Resolve-Path 'artifacts\qualification\m4-a96f53f').Path
$active = Get-Content -Raw (Join-Path $env:LOCALAPPDATA `
  'SwitchTrade\state\active-runtime.json') | ConvertFrom-Json
wsl.exe --shutdown
python -m switchtrade.connection.direct_b_harness `
  --distro $active.active_runtime `
  --runtime-root /opt/switchtrade `
  --selection-file (Join-Path $candidate 'hardware-selection.json') `
  --state-root (Join-Path $candidate 'direct-b-state-pc-a')
```

Accept PC A Direct B only when the command exits 0 with `functional_status=passed`,
`cleanup_status=verified`, `result_level=B_CONTROL_READY`, and B2-B10 in order. Post-run evidence must
show normal endpoint exit, no recovery record, the run-acquired adapter returned to Windows, and no
Linux USB/interface/PHY/process residue. This is local B evidence only; it cannot claim B1,
`B_READY`, C, relay transport, RFU, a trade, or formal Milestone 4 completion while PC B remains open.
