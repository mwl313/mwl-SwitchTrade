# Phase B Implementation Prompt
## Core Foundation

You are implementing **Phase B only** of the SwitchTrade Core Simplification Program.

Prerequisite: Phase A has passed, including bounded context and `dev.ps1`.
Do not continue into Phase C.

---

# 0. Baseline and workflow

1. Work in `mwl313/mwl-SwitchTrade` on `core-simplification`.
2. Record branch, HEAD, and working-tree status.
3. Refuse to begin if Phase A tests fail.
4. Follow bounded active instructions; do not read the legacy archive in full.
5. Use sequential packets B1–B5 and one commit per packet.
6. Do not alter existing full-product behavior.
7. Do not claim hardware, WSL, RF, Switch, or production acceptance.

---

# 1. Goal

Build a hardware-independent 1:1 Core:

- six-digit Pair create/join;
- credential-bound host/guest seats;
- endpoint-neutral WebSocket;
- separate Pair and Generation lifetimes;
- epoch/sequence/probe;
- bounded queues/backpressure;
- CoreSupervisor;
- fake endpoint;
- real software-only end-to-end tests.

---

# 2. Non-goals

Do not:

- import/use `ldn`;
- touch Wi-Fi, USB, WSL, kernel, driver, firmware, or installer;
- integrate DirectA/B, TunnelSim, Pia, Reliable, or RFU;
- implement RetroArch/gpSP;
- modify/remove WPF, Control API, Room/Public Directory endpoints;
- use `relay.authority`;
- add SQLite/accounts/public lobby/profile/Ready/checkpoints;
- delete legacy code;
- perform broad package moves.

---

# 3. Required architecture

Preferred:

```text
switchtrade/core/**
switchtrade/transport/**
switchtrade/endpoints/base.py
switchtrade/endpoints/fake.py
relay/core_server.py
relay/pair_store.py
relay/core_contracts.py
tests/test_core_*.py
```

Keep code typed and small. Avoid a giant orchestrator.

---

# 4. B1 — Domain contracts and fake endpoint

## Allowed

- `switchtrade/core/**`
- `switchtrade/endpoints/{__init__,base,fake}.py`
- `tests/test_core_contracts.py`
- `tests/test_core_fake_endpoint.py`
- minimal package initializers

## Required types

Distinct types for:

- `PairSeat`
- `GenerationRole`
- `EndpointKind`
- `RuntimeKind`
- validated protocol IDs
- `PairCredentials`
- `EndpointCapabilities`
- `GenerationOffer`
- `LinkPacket`
- `CleanupReport`
- `LocalGeneration`
- `EndpointDriver`

Do not use one generic role field.

Implement a deterministic fake endpoint supporting discover, accept, opaque send/receive, close reports,
and injected failures.

## Tests

Validation, immutability, role separation, protocol mismatch, bounds, packet exchange, cancellation,
cleanup.

## Commit

```text
core: add endpoint-neutral contracts and fake endpoint
```

Stop and summarize.

---

# 5. B2 — Minimal Pair Relay

## Allowed

- `relay/core_server.py`
- `relay/pair_store.py`
- `relay/core_contracts.py`
- `tests/test_core_pair_store.py`
- `tests/test_core_relay_api.py`

## Forbidden

- `relay/server.py`
- `relay/authority.py`
- existing Room contracts/tests
- database migrations

## API

```text
POST /core/v1/pairs
POST /core/v1/pairs:join
GET  /core/v1/pairs/{pair_id}
WS   /core/v1/pairs/{pair_id}/ws
GET  /core/health
```

## Rules

- exactly 6 numeric digits
- cryptographic random code with collision handling
- opaque pair ID
- independent host/guest tokens, at least 256-bit
- store token hashes
- join consumes code
- exactly two seats
- credential determines seat
- one socket per seat
- reconnect retires old socket safely
- code/reconnect expiry
- max capacity
- create/join/guess rate limits
- bounded sweep
- no code/token logging
- no Room metadata/public directory/database

Status is read-only.

## Commit

```text
relay: add minimal credentialed pair service
```

Stop and summarize.

---

# 6. B3 — Generation-bound wire transport

## Allowed

- `switchtrade/transport/**`
- narrow additions to new Core Relay
- `tests/test_core_transport.py`
- `tests/test_core_relay_websocket.py`

## Envelope

Fields equivalent to:

- magic/version/kind/source seat/flags
- source epoch/sequence
- generation ID length/payload length
- generation ID/payload

Kinds:

- `PEER_READY`
- `PROBE_CHALLENGE`
- `PROBE_RESPONSE`
- `CAPABILITIES`
- `GENERATION_OFFER`
- `GENERATION_ACCEPT`
- `GENERATION_CLOSE`
- `DATA`
- `HEARTBEAT`
- `PEER_CLOSE`

## Behavior

- source seat bound to credential
- new epoch begins with ready sequence 0
- contiguous sequence
- duplicate/gap/stale reject
- bidirectional probe
- reconnect fresh epoch and stale-queue clear
- bounded send/receive queues
- no silent drop
- generation ordering
- DATA only for active accepted generation
- stale generation reject
- frame bounds/send timeout/cancellation/no busy loop

Relay forwards opaque payload only.

## Commit

```text
transport: add pair-bound generation wire protocol
```

Stop and summarize.

---

# 7. B4 — CoreSupervisor

## Allowed

- `switchtrade/core/**`
- narrow transport interfaces
- fake endpoint
- `tests/test_core_supervisor.py`

## Required

Host:

- create Pair and expose code
- connect/reconnect
- default origin
- local generation may precede peer
- offer after peer/probe
- activate after accept

Guest:

- join code
- connect/reconnect
- wait offer
- fake mirror accept
- activate after local ready

Pump both directions.

Observable states equivalent to:

- starting/pairing/waiting_for_peer/paired
- discovering_local/waiting_for_offer/opening_local
- generation_negotiating/active/closing_generation
- recovering_pair/stopping/stopped/failed

## Failure/cleanup

- first functional failure wins
- cancel siblings
- stop admissions
- account drain/discard
- close LocalGeneration
- verify cleanup
- exchange generation close
- clear active only after cleanup
- block next generation until cleanup
- idempotent stop

## Commit

```text
core: add pair and generation supervisor
```

Stop and summarize.

---

# 8. B5 — Software-only end-to-end

## Required

Start the real new FastAPI Core Relay and two actual clients.

Prove:

1. host creates code;
2. guest joins;
3. reuse fails;
4. WebSockets authenticate;
5. probe completes;
6. fake offer/accept;
7. bidirectional packets;
8. clean close;
9. second generation in same Pair;
10. clean supervisor stop.

Run all Phase B tests, existing Room/Relay tests, dependency-boundary tests, and full software suite when
practical.

## Commit

```text
test: qualify endpoint-neutral pair and generation core
```

---

# 9. Dependency tests

Reject:

- `ldn`/`bridge`/WSL/FastAPI imports in Core;
- endpoint/game/`relay.authority` imports in new Relay.

---

# 10. Stable errors

Provide structured errors for:

- invalid/expired/consumed code
- pair full/expired
- authentication/seat occupied
- protocol incompatible
- malformed envelope/source mismatch
- epoch/sequence errors
- probe timeout/mismatch
- generation active/stale
- DATA before accept
- queue/backpressure
- cleanup failure
- next generation blocked
- canceled

No token/code exposure in logs.

---

# 11. Final response

```markdown
## Baseline
...

## Commits
- B1:
- B2:
- B3:
- B4:
- B5:

## Final file map
...

## HTTP contract
...

## Wire contract
...

## Core state model
...

## Tests executed
| Command | Result | Scope |
...

## Existing product regression
...

## Dependency-boundary evidence
...

## Deviations
...

## Remaining risks for Phase C
...

## Phase B verdict
PASS / FAIL
```

Do not begin Switch integration.
