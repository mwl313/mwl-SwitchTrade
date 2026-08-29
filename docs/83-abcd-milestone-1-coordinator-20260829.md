# ABC+D milestone 1 coordinator evidence

> Branch: `codex/abcd-orchestration-rework`
> Implementation commit: `b7c5c9a`
> Status: Milestone 1 exit gate passed in source.
> Scope: state, identity, mutation serialization, and recovery only; no production cutover.

## 1. Implemented boundary

Milestone 1 adds an isolated `ConnectionCoordinator` and canonical
`contracts/abcd/connection-run.v1.schema.json`. It is not imported by the current room, endpoint,
diagnostic, desktop, or hardware paths, so characterization behavior remains unchanged.

The coordinator provides:

- one OS-locked coordinator instance per runtime directory;
- one command queue and worker thread through which every mutation is serialized;
- atomic private JSON persistence for the active pointer and per-run record;
- read-only detached snapshots that do not enter the command queue or write files;
- the lifecycle `created -> preflight -> running/awaiting_user -> closing -> cleaning -> terminal`;
- separate functional and cleanup outcomes, with bounded retained cleanup failures;
- immutable release, mode, room, seat, A/B role, attempt, adapter, wrapper, nonce, and endpoint
  bindings as those identities become authoritative;
- separate closed enums for authority seat, Switch-side role, LDN role, RFU role, and tunnel
  direction;
- distinct `wrapper_acquired`, `P0_SIDE_READY`, launch-reserved, and endpoint-started evidence;
- exactly one wrapper acquisition and endpoint launch reservation per run;
- explicit cancellation, cleanup retry, cleanup verification, and a blocking recovery guard;
- startup recovery that marks a pending run interrupted without overwriting an existing primary
  functional failure.

Only Boolean, integer, or null cleanup evidence can enter the contract record. Credentials, packet
data, MAC addresses, and arbitrary strings are not accepted as cleanup evidence.

## 2. Exit-gate verification

| Required behavior | Evidence |
| --- | --- |
| One owner and worker | A second coordinator for the same runtime is rejected by the existing OS file-lock primitive |
| Serialized mutation | Forty concurrent launch-reservation commands converge on one nonce and `launch_count == 1` |
| Read-only GET foundation | Twenty snapshots leave revision and persisted record bytes unchanged; returned objects are detached copies |
| Identity-bound launch | Duplicate matching wrapper/launch/endpoint acknowledgements are idempotent; a changed nonce, PID, adapter, room version, seat, or role fails closed |
| No false endpoint startup | Launch reservation and nonce match are required before endpoint acknowledgement; wrapper acquisition and P0 readiness are separate states |
| Functional cause preservation | Restart preserves an existing P0 failure and marks only a still-pending run as interrupted |
| Cleanup truth | Failed cleanup remains secondary evidence, sets `recovery_required`, and blocks a new run until explicit verified cleanup |
| Mutation after shutdown | Commands are rejected after the coordinator stops |
| Contract bound | The emitted top-level projection matches the required `connection-run.v1` schema fields |

Focused coordinator suite: 8 tests passed.

Full regression after the implementation commit:

- Python source/relay/endpoint/diagnostic/installer suite: 209 tests passed, 1 intentional skip;
- desktop Release build: 0 warnings, 0 errors;
- desktop `--self-test`: passed;
- replacement provisioner contracts: passed;
- radio workflow simulation: passed;
- Python compilation and `git diff --check`: passed.

## 3. Deliberate non-capabilities

Milestone 1 does not:

- attach USB hardware, load WSL modules, or start an endpoint process;
- implement the long-lived WSL worker or P0 report;
- create relay rooms or introduce `room-control.v2`/`rfu-tunnel.v2`;
- implement A, B, C, or D physical/protocol stages;
- expose new HTTP routes or desktop states;
- replace or fall back to the legacy production orchestration;
- close any Critical item in `FUTURE_TODO.md`.

These omissions are intentional. Milestone 2 will connect the coordinator to one long-lived WSL
worker and implement the complete P0a/P0b ownership and readiness gate.

## 4. Exit decision

Milestone 1 passes because one local owner now serializes mutations, snapshots are provably
read-only, launch identity cannot be rebound, interrupted state is recoverable, the primary outcome
survives cleanup failure, and unverified cleanup prevents another run. Milestone 2 may begin only
after this evidence record is accepted.
