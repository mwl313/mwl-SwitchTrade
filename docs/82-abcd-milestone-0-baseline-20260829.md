# ABC+D milestone 0 baseline and reuse-admission record

> Branch: `codex/abcd-orchestration-rework`
> Status: Milestone 0 exit gate passed for the source baseline.
> Scope: characterization and reuse admission only; no ABC+D orchestration capability is claimed.

## 1. Preserved baseline

The pre-rewrite behavior and the final diagnostic-lifecycle work were preserved before new
orchestration work begins:

- `90135a6` — production diagnostic resource ownership, recovery, cleanup evidence, desktop status,
  and associated regression coverage;
- `bf4330f` — Python 3.10 relay-test portability and the supported-host installer timeout allowance;
- the architecture, definitive TODO, audited rewrite plan, and this evidence record are preserved in
  the following documentation commit.

These commits are characterization evidence. They do not close P0, A, B, C, or D gates unless a later
milestone produces the evidence required by the normative architecture.

## 2. Baseline verification

| Check | Result | Evidence |
| --- | --- | --- |
| Python source, relay, endpoint, diagnostics, and installer suite | Passed | 201 tests in 105.006 seconds; 1 intentional skip |
| Python compilation | Passed | `python -m compileall -q switchtrade relay tests` |
| Desktop Release build | Passed | 0 warnings, 0 errors |
| Desktop contract/self-test | Passed | Release executable returned exit code 0 with `--self-test` |
| Replacement provisioner contracts | Passed | `SwitchTrade provisioner contract tests passed.` |
| Radio workflow simulation | Passed | `radio workflow simulation PASS` |
| Patch whitespace validation | Passed | `git diff --check` produced no errors |

The first Python run exposed one test-only portability error: `ExceptionGroup` is unavailable under
the supported Windows Python 3.10 runner. The test verifies that an unexpected relay exception is
redacted, not exception-group semantics, so it now uses a plain `RuntimeError` carrying the same
secret marker. The complete suite then passed.

## 3. Reuse-admission ledger

No current high-level component is admitted as a whole. Each candidate remains conditional until its
listed milestone removes the conflicting ownership and behavior.

| Candidate | Decision | Reusable boundary | Required admission evidence |
| --- | --- | --- | --- |
| `LiveTransport` | Conditional; lifecycle rejected | Exact `ldn.scan/connect` mechanics and proven station compatibility patches only | M3 must remove implicit retries, communication-ID fallback, broad radio cleanup, raw identity logs, and shared mutations; then pass direct A0-A9 |
| `HostTransport` | Conditional; lifecycle rejected | Canonical `ldn.create_network()` construction and proven compatibility patches only | M4 must remove prototype selection, AP-open false readiness, broad cleanup, raw identity logs, and shared mutations; then pass direct B2-B10 |
| Hardware helpers | Conditional | Stable Windows InstanceId inventory, usbipd command construction, and three-state Linux probes | M2 must provide one owner, atomic P0 evidence, continuous Linux lock ownership, prior-state restoration, and cold-boot proof |
| `AuthorityStore` | Conditional at primitive level | SQLite transactions, credentials, membership, idempotent commands, and event/version mechanisms | M5 must use a v2 namespace and replace attempt, readiness, retention, closing, and cleanup-guard behavior |
| `TunnelClient` and v1 `Envelope` | Rejected as implementations | Tests and bounded-queue lessons only | M5 must implement an attempt-scoped, epoch-scoped, contiguous `rfu-tunnel.v2` without mixing v1 frames |
| `TunnelSim` | Conditional | Feature-neutral Pia/Reliable payload boundary only | M6 must prove no game-controller callback is reachable or extract the minimum bridge |
| `PassivePartyObserver` | Conditional | Read-only progress evidence only | M6/M8 must prove it cannot change game state and cannot expose trainer, Pokémon, MAC, or raw payload data |
| Radio scripts | Conditional | Ordered module/firmware/driver/RX mechanics | M2 must add the complete P0 atomic contract and run under the long-lived worker's lock rather than becoming a second owner |

## 4. Explicit replacement boundary

The following code is baseline evidence only and must not be extended into the new production path:

- `switchtrade/control.py` connection/session orchestration;
- `switchtrade/endpoint.py` role and lifecycle orchestration;
- `switchtrade/production_diagnostics.py` as a separate orchestration owner;
- legacy role-axis translation and overloaded `host`/`guest` state;
- current v1 tunnel connection/readiness/reconnect behavior;
- `RemoteTransport`, hostapd, direct-nl80211, and other prototype AP paths;
- legacy relay sessions and attempt/cleanup state machines.

Normal rooms and diagnostics will later call the same new coordinator. Until that cutover, the old
path remains isolated for comparison and rollback; the new path may never fall back into it.

## 5. Known failures deliberately retained

The green source baseline does not hide these confirmed blockers:

1. The production wrapper still lacks the complete `ccm`, `cmac`, `tun`, and `/dev/net/tun` P0 gate.
2. Retained relay readiness and advertisement frames can be replayed out of order.
3. There is no attempt-scoped A_READY/B_READY physical activation barrier.
4. D has no two-side `D_SIDE_QUIESCENT` and verified local-release barrier.
5. Diagnostic classifications can still be broader than the factual P0/A/B/C/D failing gate.

They remain Critical in `FUTURE_TODO.md` and are assigned to Milestones 2, 5, 6, 7, and 8. Existing
tests passing previous behavior cannot close them.

## 6. Milestone 0 exit decision

Milestone 0 passes because the baseline is reproducible, prior work is preserved in logical commits,
reuse candidates have explicit conditional boundaries, rejected orchestration is identified, and
known failures remain visible. Milestone 1 may begin only after this record and the rewrite plan are
accepted.
