# Phase C Implementation Prompt
## Switch LDN Core Integration

You are implementing **Phase C only** of the SwitchTrade Core Simplification Program.

Prerequisites:

- Phase A passed.
- Phase B passed.
- Branch is `core-simplification`.
- Endpoint-neutral fake end-to-end is green.

Do not begin Phase D or E.

---

# 0. Baseline

Record:

- branch;
- exact HEAD;
- working-tree status;
- Phase A result;
- Phase B result;
- installed WSL/runtime identity if available.

Do not read the full legacy archive. Search the bounded index only for matching Direct A/B, WSL cwd,
cleanup, or radio errors encountered here.

Use sequential commits C1–C5.

---

# 1. Goal

Connect the proven Switch LDN/Pia/Reliable/RFU path to the endpoint-neutral Core and expose:

```text
host
join <six-digit-code>
```

Automatically:

- pair two PCs;
- scan the Host-side Group Leader Switch room;
- deliver its advertisement;
- create the Guest-side mirror AP;
- wait for the Joining Switch;
- activate TunnelSim;
- clean up on cancellation/failure.

No Ready, Continue, Start, Lobby, or room-management step.

---

# 2. Fixed role mapping

| User | Pair seat | Generation role | Switch action | Stage |
|---|---|---|---|---|
| Host / leader side | host | origin | Group Leader | DirectAStage |
| Guest / mirror side | guest | mirror | Join Group | DirectBStage |

Do not call the leader-side PC an AP host.
Do not merge Pair seat and radio role.

---

# 3. Non-goals

Do not:

- delete/rewrite existing WPF/full product;
- modify/remove Room/Public Directory APIs;
- use old Room/Attempt authority in the new path;
- add profile metadata, Ready, role selection, or checkpoints;
- make WSL portable;
- rewrite installer/Provisioner;
- change dependency locks/kernel/driver/firmware;
- replace `ldn.create_network()` with hostapd/direct nl80211;
- implement RetroArch/gpSP;
- claim physical stability/production readiness;
- broadly refactor `bridge/frlgsim`;
- change proven algorithms without isolated regression proof.

---

# 4. Preferred files

```text
bridge/__init__.py

switchtrade/endpoints/switch_ldn/__init__.py
switchtrade/endpoints/switch_ldn/driver.py
switchtrade/endpoints/switch_ldn/generation.py
switchtrade/endpoints/switch_ldn/connection.py
switchtrade/endpoints/switch_ldn/tunnel_adapter.py
switchtrade/endpoints/switch_ldn/cleanup.py
switchtrade/endpoints/switch_ldn/errors.py

switchtrade/composition.py
switchtrade/core_cli.py

tests/test_switch_ldn_driver.py
tests/test_switch_ldn_tunnel_adapter.py
tests/test_switch_core_composition.py
tests/test_switch_core_cli.py
```

Small justified variations are allowed. No giant endpoint module.

---

# 5. C1 — Switch endpoint boundary

## Allowed

- package initializers
- `switchtrade/endpoints/switch_ldn/**`
- `switchtrade/composition.py`
- boundary tests
- narrowly justified shared FRLG contract extraction

## Required

1. Implement `SwitchLdnEndpointDriver` for Phase B `EndpointDriver`.
2. Capabilities:
   - `switch_ldn`;
   - `managed_wsl`;
   - `switchtrade.gba-frame.v1`;
   - origin/mirror.
3. Keep `ldn`, PHY, AP/TAP, Pia, Reliable, and FRLG imports inside this boundary.
4. Core/Relay do not import the concrete driver.
5. Composition root may select it.
6. Prefer normal package imports; minimal `bridge/__init__.py` allowed.
7. Do not move the entire bridge tree.
8. Shared constant extraction:
   - isolated commit if needed;
   - no value changes;
   - preserve tests;
   - no behavior changes.

## Commit

```text
endpoint: add Switch LDN driver boundary
```

Stop and summarize.

---

# 6. C2 — Leader-side Direct A generation

## Allowed

- Switch endpoint files
- narrow Phase B interfaces
- leader tests
- existing Direct A only for a minimal injection seam

## Required

1. validate policy/installed paths;
2. create fresh DirectAStage;
3. wrap in StageSession;
4. start/wait ready;
5. on no-room/scan-timeout:
   - stop or verify terminal stage;
   - cleanup;
   - cancellation-aware bounded backoff;
   - fresh stage;
6. on fatal error:
   - preserve exact code/gate;
   - stop;
7. on success:
   - retain StageSession;
   - obtain resources/advertisement;
   - create `GenerationOffer` with `switchtrade.gba-frame.v1`;
   - return leader LocalGeneration.

No user confirmation.
No arbitrary room selection.

## Tests

- retry/fresh object
- cleanup before retry
- cancellation
- fatal/ambiguous preservation
- advertisement offer
- retained StageSession
- no busy loop

## Commit

```text
endpoint: adapt Direct A as leader-side generation
```

Stop and summarize.

---

# 7. C3 — Mirror-side Direct B and TunnelSim adapter

## Allowed

- Switch endpoint files
- narrow Core transport interfaces
- tests
- existing Direct B/TunnelSim only for a minimal seam

## Mirror

1. accept only `switchtrade.gba-frame.v1`;
2. pass opaque setup payload as DirectB `application_data`;
3. fresh DirectB + StageSession;
4. existing LDN AP/monitor/TAP path;
5. wait readiness/association;
6. retain StageSession;
7. return mirror LocalGeneration;
8. no checkpoint;
9. no AP before offer.

## CoreTunnelAdapter

Expose:

```text
connected
connection_generation
send_rfu(payload, flags)
poll()
```

Map Core DATA to RFU payload/flags without game interpretation.

Require:

- generation identity validation
- payload/flags bounds
- bounded queue
- backpressure error
- reset on reconnect/generation change
- no stale replay
- thread safety for TunnelSim

## Composition

Leader:

- `pia_connect.ConnectionManager`
- `TunnelSim(parent=False)`

Mirror:

- `pia_connect.HostConnectionManager`
- `TunnelSim(parent=True)`

Use current crypto/VBlank.
Party observer disabled by default.

## Tests

- no AP before offer
- protocol mismatch
- DirectB error preservation
- send/poll/flags
- stale/reconnect/overflow
- parent mapping
- no game interpretation

## Commit

```text
endpoint: adapt Direct B and TunnelSim to Core transport
```

Stop and summarize.

---

# 8. C4 — CLI and automatic lifecycle

## Allowed

- `switchtrade/core_cli.py`
- `switchtrade/composition.py`
- Switch endpoint files
- narrow CoreSupervisor changes
- tests
- minimal Phase A `dev.ps1` routing

## Commands

```console
python -m switchtrade.core_cli host
python -m switchtrade.core_cli join 381742
```

Development:

```console
.\dev.ps1 run host
.\dev.ps1 run join 381742
```

Options:

- `--relay`
- `--usb-id`
- proven `--channel`
- `--verbose`
- `--log-dir`

No Room metadata/role selection.

## Lifecycle

Host:

- create Pair/print code;
- cancellation-aware discovery;
- discovery may precede peer;
- after peer/probe send offer;
- wait mirror;
- bridge.

Guest:

- join Pair;
- wait offer;
- auto open mirror;
- wait Joining Switch;
- accept;
- bridge.

Both:

- human-readable events;
- technical logs separate;
- Ctrl+C no traceback;
- cleanup before exit;
- nonzero on unexpected/cleanup failure.

## Commit

```text
cli: add automatic host and join Switch Core flow
```

Stop and summarize.

---

# 9. C5 — Software qualification

Run:

1. Phase A tests.
2. Phase B tests.
3. new Switch endpoint tests.
4. existing Direct A/B tests.
5. StageSession tests.
6. TunnelSim/Reliable/Pia tests.
7. Room/production regression.
8. full software suite when practical.

Using injected fake Direct A/B resources prove:

- Host local-before-Guest;
- Guest-before-Host;
- advertisement over real Core transport;
- automatic mirror open;
- both local ready;
- TunnelSim-compatible activation;
- bidirectional payload/flags;
- cancellation cleanup;
- first failure preservation;
- no checkpoint API call.

Real two-Switch run is optional and must not be called stabilized acceptance.

## Commit

```text
test: qualify Switch LDN Core composition
```

---

# 10. Cleanup

Test this exact order:

1. mark closing;
2. stop local admission;
3. stop remote DATA;
4. drain/discard accounting;
5. close TunnelSim;
6. stop StageSession;
7. verify Direct context release;
8. verify owned AP/monitor/TAP/interface;
9. close Core generation transport;
10. publish CleanupReport;
11. clear generation.

Do not detach USB without exact lease ownership.
Do not remove unrelated interfaces/PHY.
Unknown cleanup blocks next generation.

---

# 11. Error preservation

Preserve exact `A_*`, `B_*`, transport, generation, and cleanup errors.

New equivalents:

- `SWITCH_ENDPOINT_POLICY_INVALID`
- `SWITCH_ENDPOINT_BUSY`
- `SWITCH_ENDPOINT_PROTOCOL_MISMATCH`
- `SWITCH_ENDPOINT_TUNNEL_FAILED`
- `SWITCH_ENDPOINT_TICK_FAILED`
- `SWITCH_ENDPOINT_CLEANUP_FAILED`
- `SWITCH_GENERATION_CANCELED`

Expected cancellation is not a traceback/failure.

---

# 12. Final response

```markdown
## Baseline
...

## Commits
- C1:
- C2:
- C3:
- C4:
- C5:

## Final role mapping
...

## Reused existing modules
...

## Existing modules changed
| File | Reason | Behavior change |
...

## CLI
...

## Automatic lifecycle
...

## Cleanup order
...

## Tests executed
| Command | Result | Scope |
...

## Existing product regression
...

## Physical work executed
- None / exact smoke details

## Unproven items deferred to D
...

## Deviations
...

## Phase C verdict
PASS / FAIL
```

Do not begin physical stabilization or gpSP work.
