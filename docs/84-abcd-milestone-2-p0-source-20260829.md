# ABC+D Milestone 2 P0 source evidence

> Branch: `codex/abcd-orchestration-rework`
> Status: source implementation complete; PC A installed cold P0 passed; PC B and fault matrix pending.
> Scope: P0a, P0b, continuous local radio ownership, one launch canary, and local recovery only.

## 1. Implemented boundary

Milestone 2 adds a CLI-first P0 implementation below any desktop UI. The legacy normal-room and
production-diagnostic paths do not import it, so they cannot silently mix old and new ownership.

The source implementation provides:

- `p0-passive.v1`, which checks the requested RTL8192EU InstanceId without attach, detach, module
  load, room creation, or endpoint launch;
- exact `usbipd-win 5.3.0` and minimum WSL validation, current bus resolution, shared state, and proof
  that a pre-attached adapter belongs to the active SwitchTrade distribution;
- a packaged-runtime probe that verifies the release marker, full immutable payload manifest, private
  `prod.keys`, packaged Python and pinned dependencies, privileges and tools, running kernel/module
  tree, module vermagic, pinned firmware/regulatory hashes, legal target channel, idle endpoint state,
  and available radio lock;
- passive HTTPS clock/contract/capability validation plus a stateless relay WebSocket health path;
- one private recovery record for the exact InstanceId, prior attach state, current bus, and attach
  intent, written before the external attach can succeed;
- one attach only when the adapter was previously detached, stable two-sample Linux enumeration, and
  no detach of a pre-attached adapter;
- the ordered Linux gate `usbip-core -> vhci-hcd -> enumeration -> cfg80211 -> libarc4 -> mac80211 ->
  led-class -> rtl8xxxu/firmware -> ccm -> cmac -> tun -> /dev/net/tun -> PHY/netdev -> actual RX`;
- one long-lived worker under the existing radio `flock`. It emits an atomic
  `p0-side-ready.v1` report, waits on a control-owned pipe, accepts one closed and identity-bound launch
  ticket, and uses `exec` to preserve the Linux PID, process start time, and inherited radio lock;
- a package-owned endpoint canary for Milestone 2 only. It proves the launch boundary without claiming
  A, B, C, RFU, or trade behavior;
- cleanup on explicit stop and control-pipe loss, interface-down proof before detach, stable
  Windows/Linux absence after a run-owned detach, prior-state proof for a pre-attached adapter, and
  startup recovery that never kills a reused PID or detaches hardware without prior-state evidence.

The P0a and P0b reports must have identical release, kernel, runtime-integrity, module-set, and firmware
evidence. A changed value fails `P0_EVIDENCE_MISMATCH`; readiness is never inferred from a log line.

## 2. Stable failure behavior

Focused fault tests cover:

- invalid or duplicate saved adapter identity;
- an adapter attached outside the active distribution;
- unresolved prior recovery before any external command;
- delayed Linux enumeration and a driver bound without a PHY/netdev;
- an exact bus identity change during enumeration;
- `usbip: ... inactive port` as one terminal `P0_ADAPTER_ATTACH_FAILED`, not a retry storm;
- `present`, `absent`, and `unknown` Linux cleanup results;
- an interface still up before detach;
- restart recovery from attach intent even when control died before recording attach success;
- a stale or altered launch ticket, P0 report, runtime hash, firmware hash, PID, or process-start time;
- one wrapper, one launch reservation, one endpoint PID, one attach, and one conditional detach.

## 3. Source verification

The final source checks on 2026-08-29 produced:

- 230 Python control/relay/endpoint/diagnostic/installer tests passed, with one intentional skip;
- 21 focused P0/coordinator fault and lifecycle tests passed;
- the Linux radio workflow simulation passed, including cold load, delayed probe, stuck probe,
  RX failure, explicit recovery, module warning, and competing lock cases;
- replacement provisioner contract tests passed;
- desktop Release build completed with zero warnings and zero errors;
- desktop `--self-test` passed;
- Python compilation, shell syntax, JSON parsing, and `git diff --check` passed.

The repo-wide `pytest` command was also attempted in the Windows global interpreter. Its supported
source cases passed, but five Linux bridge cases could not run because that interpreter does not have
the packaged `ldn` and `zstandard` modules and has a different `websockets` API. The immutable WSL
runtime probe now verifies those exact packaged dependencies; the installed WSL qualification below
is the authoritative test for them.

## 4. Deliberate non-capabilities

This milestone does not:

- modify or depend on the existing GUI;
- route the legacy room or diagnostics API through the new coordinator;
- start `LiveTransport`, `HostTransport`, or an RFU tunnel;
- implement C0.1/C0.2 relay authority, direct A, direct B, C, or distributed D;
- build or install a public release installer;
- close the Critical missing-prerequisite TODO.

The executable source harness is `python -m switchtrade.connection.p0_harness`. It must only be run
from a qualification runtime containing the same source and immutable integrity manifest. A legacy
`0.2.6-beta.2` release runtime correctly fails release/integrity validation; the isolated
`abcd-m2-975e68b` qualification runtime is the admitted P0 candidate.

## 5. Installed PC A evidence

PC A was qualified from the non-ASCII profile `C:\Users\임민우` on 2026-08-29 using:

- source commit `975e68b` and immutable runtime `abcd-m2-975e68b`;
- runtime content ID `369f7774aad3e7a8aa6e15b6dcaf8eae512685e7d693463c0e10fe41064c6358`;
- runtime archive SHA-256 `b0116b52876bed5ef97c74d0e717961d184e90f746d3fce7f344cf419833e96e`;
- custom kernel `6.18.35.2-microsoft-standard-WSL2+` and RTL8192EU at Windows bus `4-18`;
- real relay HTTPS/WebSocket health and the packaged module, firmware, dependency, and payload gates.

The final cold run `f0a999b3-cfc7-4eda-bcfd-d18df266d72a` reached `P0_SIDE_READY`, proved actual RX,
exited its worker normally, detached exactly the adapter attached by the run, and finished with
`functional_status=passed` and `cleanup_status=verified`. Post-run inspection found the Windows device
detached, Linux USB absent, no interface or PHY, no recovery file, and a verified terminal record.

The installed exercise also exposed and fixed four boundary defects rather than bypassing them:

- redirected Windows-native UTF-16LE output was decoded as UTF-8;
- passive P0 incorrectly required live `cfg80211` regulatory state before P0b loaded the radio stack;
- post-detach Windows USB re-enumeration was misclassified immediately as an identity change;
- restart recovery inspected Windows PID/netdev/USB state instead of the selected WSL distribution.

## 6. Project entry decision and remaining Milestone 2 qualification

On 2026-08-29 the owner explicitly accepted the verified PC A cold P0 as sufficient to begin direct
A work. This is a milestone-entry decision, not evidence that PC B passed and not closure of the
cross-PC P0 qualification gate. Milestone 3 may proceed while the following debt remains:

1. Copy the exact `abcd-m2-975e68b` qualification package to PC B without rebuilding it there.
2. On PC B, cold boot with the relevant modules initially unloaded and run the P0 harness.
3. Exercise pre-attached, cancellation, app/control interruption, delayed enumeration,
   inactive-port, adapter-change, and recovery cases.
4. Confirm on both PCs that there are zero orphan worker/endpoint PIDs, active interfaces, stale
   locks, unintended detach, or unresolved recovery records.
5. Repeat the installed boundary checks under the supported English Windows locale. PC A already
   proves the non-ASCII Korean-profile path, mixed UTF-8/UTF-16LE output, and malformed-output tests.
6. After one accepted run on each PC and the fault cases, execute the agreed 30-run qualification;
   do not use the obsolete 50-run count.

Only that installed evidence can change this document to “Milestone 2 exit gate passed.”
