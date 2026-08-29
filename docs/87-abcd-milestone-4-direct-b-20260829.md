# ABC+D Milestone 4 direct B qualification evidence

> Branch: `codex/abcd-orchestration-rework`
> Source commit: `9635a1f`
> Status: source complete; final PC A immutable runtime installed and smoke-tested; final physical rerun pending.
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

1. B2 validates the 122-byte `frlg-search-v2` fixture and SHA-256
   `c945ee4344711cc0c019356a311912437f520063ef8aa9b2f158d7a13295d863` before touching the radio.
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

The final source regression passed 414 tests with three intentional skips. The focused Direct B/P0
matrix passed 39 tests. Direct B coverage includes fixture immutability, B2-B10 order, parameter identity,
run-owned compatibility behavior without class mutation, real-peer event requirements, control-port
failure, association/hold timeout, participant loss, one launch, strict endpoint identity, one
attach/conditional detach, cleanup failure precedence, redaction, and no relay dependency. It also
opens a Trio nursery across the fake LDN context yield, proving that the stage preserves the real
library's cancel-scope nesting, and proves that a post-B10 teardown timeout cannot rewrite functional
success while still leaving cleanup unverified.

The legacy Linux-only bridge test module cannot import Windows `fcntl` and was not counted as a
Windows pass. The admitted compatibility behavior is instead covered through the new run-local Direct
B tests and remains subject to the physical installed-runtime gate.

## 5. Immutable PC A candidate

- release: `abcd-m4-9635a1f`;
- application version carried by the qualification package: `0.2.6-beta.2`;
- runtime content ID: `6e6cc8374d146faace24db0ce0d91f1b66bf17863c9694634426cc26279bebe5`;
- WSL archive SHA-256: `7c6a580311f04df057952c1d3ac8d7286343e63c77416f450e6371e9ffa053af`;
- WSL archive size: `110383498` bytes;
- custom kernel: `6.18.35.2-microsoft-standard-WSL2+`;
- active runtime: `SwitchTrade-beta-abcd-m4-9635a-e10b0acb45ae4b8aaa41208d9024f742`;
- package directory: `artifacts\qualification\m4-9635a1f\package`.

The replacement provisioner installed the candidate side by side, verified it, atomically selected
it, and retired the superseded M3 runtime. Installed smoke verified the release and payload integrity,
pinned `ldn==0.0.17`, all B2-B10 gate names, fixture hash, Direct B endpoint import, custom kernel,
zero active endpoints, no Direct B AP/monitor/TAP residue, no relay CLI option, truthful context-release
tracking, and USB bus `4-18`
detached from WSL. The checks ran from the non-ASCII Windows profile path. This proves package/runtime
readiness only and did not attach the adapter or claim physical B.

## 6. PC A physical procedure and acceptance

Use one Switch only. Do not host a room on this or another Switch. Start the harness first; when its
live evidence reaches B5/B6 and the app-hosted room is advertising, open FireRed/LeafGreen's Wireless
Club Direct Corner, enter the Trade Center, choose **Join Group**, and select the advertised room.

```powershell
$candidate = (Resolve-Path 'artifacts\qualification\m4-9635a1f').Path
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

## 7. Physical findings and historical correlation

The first PC A candidate, `abcd-m4-a96f53f`, transmitted Nintendo vendor advertisements but the real
Switch did not list a room. Comparison with prior physically successful PC-host captures proved that
the synthetic fixture had inconsistent empty Pia/RFU participant identity fields. The package-owned
`frlg-search-v2` fixture now uses one consistent synthetic `DIAG` identity and a nonzero RFU partner
word; it contains no captured trainer or Pokémon data.

Runtime `abcd-m4-d41a284` then made the room visible. Run
`fd133053-5108-499c-9ccc-0214a261a2e9` recorded a real participant transition to 2/6 and passed every
gate B2-B10, including Nintendo control activity and the bounded hold. The Switch displayed “The other
trainer appears unavailable.” Historical VM/WSL evidence in documents 26, 31, 33, and 34 records the
same UI after progressively successful LDN, Pia Session, and RFU NI stages. The message therefore does
not negate B; it marks an unimplemented higher Pia/RFU boundary that belongs after local B admission.

That run was nevertheless reported as `B_HOLD_TIMEOUT` because the single functional deadline remained
armed while `network.start()` sent its destroy notification. The notification stalled after B10 and
rewrote completed functional evidence. Commit `2154533` separated functional and cleanup outcomes, but
its first AsyncExitStack implementation closed an outer Trio timeout while LDN's nursery cancel scope
was still active. Installed run `2e0625ec-9946-435b-89e6-26b7577072e6` caught this source regression at
B5 and verified full cleanup without requiring Switch input.

Commit `99e21fe` kept one timeout scope outside the complete native LDN context lifetime, bounded the
peer destroy notification, and preserved functional success. Physical run
`d5366c2e-3e82-4592-b523-9e38bc83cc18` then passed B2-B10 and returned `B_CONTROL_READY`; the worker
exited normally and Windows/Linux USB restoration passed. The report correctly retained that functional
success but failed cleanup because the LDN context still did not exit within ten seconds.

The ldn 0.0.17 source waits without a deadline for `NL80211_CMD_STOP_AP` before its enclosing AP-interface
context performs the authoritative interface deletion. This matches the joined-session AP-context hang
recorded in documents 32 and 33. Commit `9635a1f` applies a two-second bound only to that run-owned
STOP_AP request, then continues through the ordinary interface deletion. It also records each network,
TAP, monitor, AP, interface, and factory exit checkpoint. A simulation where STOP_AP never responds
reaches `factory_released`, and the full suite passes. Immutable runtime `abcd-m4-9635a1f` is installed,
hash-verified, smoke-tested, detached, and waiting for one final real-Switch cleanup confirmation.
