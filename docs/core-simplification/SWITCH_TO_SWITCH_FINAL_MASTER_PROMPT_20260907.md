# SwitchTrade Astra Final Master Prompt — Switch↔Switch Production-Preflight Closure

You are the final implementation, audit, and qualification owner for the current SwitchTrade Switch↔Switch milestone.

## 0. Repository and operating constraints

Repository:
- https://github.com/mwl313/mwl-SwitchTrade

Branch:
- `Simple-Architecture`

Current verified HEAD at handoff:
- `207537e28a66207fd7aad970e34b6487dfef1608`

Do not assume the handoff SHA is still current. At the start:
1. fetch the branch;
2. confirm exact HEAD, parent history, worktree state, and remote;
3. inspect all changes after `207537e28a66207fd7aad970e34b6487dfef1608` if any;
4. preserve unrelated/user-owned work.

Do NOT modify `main`, published tags/releases, or begin emulator implementation in this task.

This is a one-shot completion task. Do not stop after one packet, one bug, one focused suite, or one green CI run if known software gaps remain. Continue until either:
- all software preflight requirements below are closed and the next meaningful unknowns are physical Nintendo Switch / Wi-Fi behavior only; or
- a genuine external blocker exists that cannot be resolved without physical hardware, external credentials, or user-only infrastructure.

If you encounter a genuine blocker, finish every other resolvable item first and report the blocker precisely. Partial progress must never be labeled as overall completion.

---

# 1. Product mission

SwitchTrade exists to restore Internet communication for the Nintendo Switch re-release of Pokémon FireRed / LeafGreen while keeping the consoles stock.

The current product milestone is:

> **Two stock Nintendo Switch consoles running the supported FireRed / LeafGreen release must be able to communicate through the Internet via SwitchTrade, using two nearby PCs and a common relay, with no custom firmware required on either Switch and no manual timing/checkpoint coordination between users.**

The immediate deliverable is not merely “the architecture compiles.” It is:

> **Switch↔Switch over the relay is software-complete, modular, fail-closed, repeatable, and immediately ready for a two-PC / two-Switch physical test.**

The physical test should be testing actual radio/Switch behavior, not discovering another avoidable software integration gap.

---

# 2. Next product milestone — preserve this future direction

After Switch↔Switch is fully established and the protocol/lifecycle boundaries are stable, the next milestone will add emulator endpoints, initially centered on a GBA emulator path such as RetroArch/gpSP.

Future target combinations:
- Switch ↔ Switch
- Switch ↔ Emulator
- Emulator ↔ Emulator

Therefore the current Switch↔Switch implementation must leave the architecture reusable for emulator endpoints.

The following separations are architectural invariants and must be preserved:

- Pair seat: `host / guest`
- Generation role: `origin / mirror` (or leader-side / mirror-side internally)
- Endpoint kind: `switch_ldn` now, emulator endpoint later
- Runtime kind: managed WSL for Switch; native runtime may be used later for emulator
- Protocol ID: explicit, negotiated, endpoint-facing protocol identity
- Relay: authenticated opaque forwarding only
- Core: endpoint-neutral Pair / Generation / Supervisor orchestration

The relay and generic Core must NOT learn Pokémon commands, RFU game opcodes, Direct A/B implementation details, or emulator-specific semantics.

Do not prematurely implement Switch↔Emulator in this task. Instead make sure the Switch↔Switch result does not create Switch-only coupling in Core or Relay that will force another architecture rewrite later.

---

# 3. Intended final user flow

The final development flow must conceptually behave as follows.

## Host PC

Command:

```powershell
.\dev.ps1 run host [--relay <common-relay-url>] [--usb-id <vid:pid>] [--channel <1|6|11>]
```

Expected behavior:

1. development source/runtime is prepared without reinstalling the product;
2. selected USB radio is identity-checked and passed through the radio health gate;
3. SwitchTrade starts and immediately prints a six-digit Pair code;
4. the host user may take as long as needed to create the FireRed/LeafGreen Group Leader room on the Switch;
5. SwitchTrade continuously/reliably discovers the exact supported Switch LDN room;
6. no-room or scan-timeout states that leave no owned residue are normal retry states, not fatal errors;
7. the host PC joins the real Switch-created LDN room through Direct A;
8. the resulting dynamic advertisement/setup payload is forwarded through the real Core relay to the guest;
9. the host may wait as long as needed for the remote user within explicit Pair/lease policy;
10. when the guest mirror is ready, the generation activates automatically;
11. `Bridge active.` is shown;
12. actual Pia/Reliable/RFU-compatible traffic flows bidirectionally through TunnelSim → Core → relay → Core → TunnelSim;
13. when the physical Switch room ends, the Generation cleans up completely but the Pair remains alive;
14. the host returns automatically to local room discovery for the next Generation without requiring a new Pair code;
15. Ctrl+C at any phase performs bounded, ownership-verified cleanup and exits without traceback.

## Guest PC

Command:

```powershell
.\dev.ps1 run join <6-digit-code> [--relay <common-relay-url>] [--usb-id <vid:pid>] [--channel <1|6|11>]
```

Expected behavior:

1. runtime/radio preparation occurs automatically;
2. the Pair code is joined;
3. the guest may arrive before or after the host creates the Switch room;
4. waiting for the host room is a normal lifecycle state, not a short transport timeout;
5. once the real host advertisement arrives, Direct B automatically creates the mirrored LDN AP/monitor/TAP using only owned resources;
6. the mirrored AP may exist before the Joining Switch associates;
7. the UI/CLI tells the user to select Join Group when the mirror appears;
8. the user may take human-scale time to choose Join Group; this must not be terminated by an arbitrary 5s/120s/180s readiness timeout;
9. cancellation, actual transport loss, Pair expiry, and unrecoverable local failures must still terminate the wait safely;
10. after physical Switch association/control readiness, the generation activates automatically;
11. `Bridge active.` is shown;
12. actual RFU-compatible traffic flows bidirectionally;
13. when the generation ends, the guest cleans up all owned local resources and stays in the same Pair waiting for the next host generation;
14. Ctrl+C cleans up completely and exits cleanly.

There must be NO:
- app Room browser;
- public/private room selection;
- trainer metadata pairing flow;
- Ready button;
- Continue button;
- timing checkpoint;
- countdown requiring synchronized user action;
- manual origin/mirror role selection;
- legacy Room/Attempt authority in the new Core flow.

The user should only need to choose Host or Join, share/enter a six-digit code, and operate the Pokémon game's native Group Leader / Join Group UI.

---

# 4. Architecture that must be preserved

The existing simplified architecture is fundamentally correct and must not be replaced unless you prove a specific invariant is impossible.

## Pair

A Pair is the Internet relationship between the two PCs for the CLI session.

It owns:
- pair_id
- host/guest credentials
- six-digit code / code expiry
- peer presence
- reconnect lease
- protocol capabilities

## Generation

A Generation is one actual local-link lifecycle:

```text
real Host Switch room
→ Direct A local session
→ opaque advertisement/setup payload
→ Core generation negotiation
→ Direct B mirrored AP
→ Joining Switch association
→ TunnelSim/Core data plane
→ local/remote close
→ verified cleanup
```

One Pair must support multiple sequential Generations.

## Direct A

Leader-side PC near the Group Leader Switch:
- exact supported room scan;
- strict FRLG room validation;
- association identity validation;
- Nintendo control and participant validation;
- local Pia data plane;
- sustained StageSession;
- setup advertisement exported to Core;
- retry only when the failure is explicitly retryable AND cleanup is verified.

## Direct B

Mirror-side PC near the Joining Switch:
- validate remote advertisement;
- identity-bound radio reset;
- create mirrored LDN network only after real remote offer exists;
- AP/monitor/TAP are run-owned resources;
- AP may wait before peer association;
- wait for physical Switch association/control;
- sustained StageSession;
- cleanup must quiesce/remove only resources owned by this run.

## TunnelSim

TunnelSim remains the feature-neutral Pia/Reliable terminator:
- local Switch-side Pia/Reliable protocol terminates locally;
- Core transports opaque RFU/application bytes plus required flags;
- Core and Relay do not understand game commands;
- leader Direct A uses the existing child/joiner-side Pia role;
- mirror Direct B uses the existing parent/host-side Pia role.

Do not rewrite mature Pia/Reliable/RFU behavior merely to satisfy a new test.

---

# 5. Current state already achieved — preserve and reverify

Do not regress the following work that has already been implemented or substantially corrected:

1. endpoint-neutral Core / Pair / Generation foundation exists;
2. real Core relay and WireClient exist;
3. six-digit Pair creation/join exists;
4. Core no longer requires Room/Ready/Continue checkpoints for the new flow;
5. Direct A/B are wrapped as a Switch LDN endpoint driver;
6. `CoreTunnelAdapter` exists as the opaque RFU bridge boundary;
7. TunnelSim runner is delayed until Core activates the Generation, preventing normal pre-peer waits from filling the data queue;
8. proven radio interface identity is separated from the run-owned Direct A station VIF name;
9. CLI USB/channel options are bound to radio-gate evidence and RX proof;
10. Guest data-plane peer binding is deferred until the real Joining Switch exists;
11. Host Direct A performs peer binding before readiness;
12. PowerShell child output and integer exit code were separated;
13. Python is executed unbuffered for immediate Pair/status output;
14. PairStore code-reuse ownership bug was corrected;
15. generic 5-second `receive()` timeout is no longer used as human waiting policy;
16. Direct B association default was changed away from the old fixed 120-second user timeout;
17. StageSession readiness default was changed away from the old 180-second outer timeout;
18. unowned `ldn-tap` fallback deletion was removed/restricted;
19. no-room/scan-timeout retry reporting was improved;
20. several actual Direct A/B + StageSession cancellation tests were added;
21. first functional failure versus cleanup failure handling has partial coverage;
22. CI run #108 for `207537e...` was green on Windows and Ubuntu.

These are not blanket guarantees. Reverify them in the final integrated path and keep the fixes unless a stronger implementation is required.

---

# 6. Known unresolved or insufficiently proven issues

Treat the list below as the minimum known issue set. You are also responsible for finding additional integration defects while auditing the full call graph.

## A. Direct A early-resource cleanup gap

A known unresolved cleanup boundary exists around early Direct A VIF ownership.

The current code distinguishes LDN context state such as `not_acquired / acquiring / acquired / released / unknown`, but a VIF can already have been created before the LDN session is considered acquired.

Required behavior:
- if no owned OS/radio resource was acquired, clean no-room/scan timeout may retry;
- if a run-owned station VIF was created, its release must be proven independently of higher-level LDN readiness;
- if VIF deletion/teardown fails or is unknown, cleanup must be unverified and next admission blocked;
- `not_acquired` must never falsely imply “no owned resource existed.”

Add fault-injection coverage for:
- association/connect failure + VIF deletion succeeds;
- association/connect failure + VIF deletion fails;
- startup/cancellation races around VIF creation;
- no unrelated PHY/interface deletion.

## B. Cancellation and error identity

Cancellation and failure classification must be consistent through Direct A/B → StageSession → driver → CoreSupervisor → CLI.

Audit at least:
- Direct A scan cancellation;
- Direct A join/association cancellation;
- immediate StageSession start/stop race;
- Direct B AP creation cancellation;
- Direct B association waiting cancellation;
- Direct B control-port waiting cancellation;
- cancellation before readiness signal;
- cancellation concurrently with failure;
- cleanup failure after cancellation.

Preserve the first functional failure identity. Cleanup failure is additional evidence and should only become primary if no prior functional failure exists.

Also correct exception ordering/classification issues such as runtime dependency errors being swallowed or bypassed by broader `BaseException` handlers. `ImportError` / missing LDN runtime must still map to stable explicit runtime-dependency failures rather than escaping as an unclassified exception.

## C. Cleanup evidence must reflect real ownership

Cleanup success is a product safety invariant.

The system must separately reason about every resource type that can be owned before readiness:
- selected/proven PHY identity;
- health-gate monitor interface (proven identity, not casually deleted);
- Direct A run-owned station VIF;
- Direct B AP VIF;
- Direct B monitor VIF;
- Direct B TAP;
- LDN network/context;
- data-plane sockets;
- TunnelSim runner/thread;
- StageSession thread;
- transport generation queues.

Rules:
- unknown cleanup == failure;
- cleanup cannot be inferred from “stage never became ready”;
- cleanup verification must be idempotent;
- repeated stop must preserve the first stop/cleanup error;
- next Generation is forbidden after unverified cleanup;
- cleanup may only affect resources proven to be owned by this run/selected adapter.

## D. Local Switch room/end lifecycle is not yet proven end-to-end

A real Generation must end when the local Switch-side LDN lifecycle ends, not only when tests directly call `close_generation()`.

Audit and implement the endpoint lifecycle signal from actual Direct A/B/StageSession/TunnelSim boundaries to CoreSupervisor.

Required behavior:
- Host Switch leaving/destroying its local room ends the generation cleanly;
- Joining Switch leaving/disconnecting ends/propagates generation close appropriately;
- local room-end cleanup completes;
- peer receives generation close;
- both supervisors return to PAIRED/waiting state;
- the same Pair can create a second Generation automatically;
- no new six-digit code is needed.

Do not teach generic Core Pokémon commands. This must remain a local endpoint lifecycle signal.

## E. Human waiting must stay interruptible

Removing arbitrary wall-clock timeouts is correct only if waits still terminate for real reasons.

Audit every long wait, including:
- host waiting for local Group Leader room;
- host waiting for peer;
- guest waiting for generation offer;
- guest waiting for physical Join Group association;
- guest waiting for Nintendo control readiness.

Each wait must respond correctly to:
- Ctrl+C / cancellation;
- transport/socket death;
- authenticated peer closure;
- Pair/reconnect lease expiry;
- endpoint/radio failure;
- cleanup failure.

Do not replace this with one large arbitrary timeout.

## F. Transport loss during pre-active states

A connection failure must be handled not only in ACTIVE pumps but during:
- WAITING_FOR_PEER;
- DISCOVERING_LOCAL where applicable;
- WAITING_FOR_OFFER;
- OPENING_LOCAL / Direct B association wait;
- GENERATION_NEGOTIATING.

Do not leave Direct B AP/StageSession running indefinitely after the Internet Pair is unrecoverably lost.

Reconnect behavior must either:
- recover the Pair safely and return to a valid waiting state; or
- close the active/pending Generation, verify cleanup, and fail cleanly.

Never continue a stale Generation across an unproven transport epoch.

## G. Pair code / reconnect lease lifecycle

The six-digit code and Pair reconnect lease already have server-side lifetimes, but the CLI lifecycle must use them meaningfully.

Required behavior:
- Host sees code expiry information;
- invalid/expired/consumed code produces clear user-facing failure;
- once Guest joins, the Pair continues independently of the consumed invite code;
- reconnect lease expiry terminates unrecoverable waiting/recovery cleanly;
- Pair expiry cannot leave radio/AP/threads running;
- same Pair supports multiple valid Generations until Pair lifecycle ends.

Do not confuse invite-code expiry with an already-established Pair lifetime.

## H. Common relay must be explicit and physically usable

`127.0.0.1:8788` is a development default, not an Internet rendezvous solution for two different PCs.

For physical qualification, make the common relay requirement explicit and operational:
- both PCs must point at the same reachable Core relay;
- relay URL handling must support the intended `http/https/ws/wss` conversion safely;
- provide an exact way to launch/configure the Core relay for testing;
- provide an exact way for both clients to select that relay;
- fail with useful diagnostics if it is unreachable or authentication/pairing fails.

Do not hard-code a private deployment URL unless one is explicitly provided.

## I. Actual CLI / PowerShell / WSL entrypoint qualification

The final test cannot stop at Python unit calls.

Verify the real development entrypoint behavior:
- `dev.ps1 run host`
- `dev.ps1 run join <code>`
- options after command are normalized correctly;
- `--relay`, `--usb-id`, `--channel` propagate correctly;
- radio role inversion remains correct;
- radio gate proves the exact USB/channel/RX evidence used by the CLI;
- stdout is streamed immediately;
- stderr does not accidentally become PowerShell control-flow failure when it is ordinary child stderr;
- actual integer exit code is preserved;
- Ctrl+C/termination propagates into Python/WSL cleanup;
- generic `dev.ps1 run -- <other python args>` remains valid.

Use actual PowerShell process invocation on Windows CI or an equivalent high-fidelity test. Source-string assertions are insufficient as the final proof.

## J. Real TunnelSim path is still insufficiently qualified

The old C5 composition test is useful but bypasses important production behavior by using `FakeSession`, `FakeSimulation`, and direct `CoreTunnelAdapter.send_rfu()/poll()` calls.

The final software qualification must keep real:
- real FastAPI/Uvicorn Core relay;
- Pair create/join APIs;
- WebSockets;
- WireClient;
- CoreSupervisor;
- SwitchLdnEndpointDriver;
- real StageSession thread model;
- real CoreTunnelAdapter;
- real TunnelSim;
- real Pia/Reliable processing path as far as software can exercise it;
- real CLI lifecycle orchestration where practical.

Only replace hardware/OS-dependent primitives:
- actual nl80211 operations;
- actual Wi-Fi adapter;
- raw socket binding if unavailable in CI;
- physical Switch events.

Do NOT claim end-to-end RFU qualification by directly placing a frame in `CoreTunnelAdapter.send_rfu()` and reading `poll()` on the other side.

Drive data through the TunnelSim-facing Reliable/app path so production semantics are exercised.

Use valid RFU/AppData flags. Do not rely on a test-only flags value that real TunnelSim rejects (for example an AppData bit that is not set).

## K. Two-generation same-Pair qualification

Prove with real Core/driver/StageSession/TunnelSim software boundaries that:

Generation 1:
- local room appears;
- advertisement crosses relay;
- mirror opens;
- guest associates;
- data becomes ACTIVE;
- bidirectional RFU-compatible traffic works;
- room ends;
- both sides cleanly return to Pair waiting.

Then without creating a new Pair:

Generation 2:
- a new Host local room is discovered;
- a fresh generation ID is negotiated;
- no stale DATA/offer/accept frame from generation 1 is admitted;
- the guest mirrors the second advertisement;
- the second generation activates and transports data;
- cleanup succeeds again.

## L. First-failure preservation and cleanup failure

Test combined fault cases:
- local TunnelSim tick failure + simulation.close failure + StageSession.stop failure;
- transport failure + cleanup failure;
- generation close send/drain failure + local cleanup failure;
- cancellation + cleanup failure.

The original functional failure should remain diagnosable as primary unless no functional failure preceded cleanup.

## M. Startup and readiness races

Race-test:
- stop immediately after StageSession.start();
- cancel before Trio token/scope is fully published;
- cancel at readiness transition;
- peer disconnect at offer/accept transition;
- local stage becomes ready while cancellation is being signaled;
- repeated start/stop loops leave no `switchtrade-direct-stage` or TunnelSim runner thread behind.

## N. Dependency/runtime qualification

Preserve the actual Switch runtime contract:
- managed Linux/WSL runtime;
- `ldn==0.0.17` compatibility contract unless deliberately and fully requalified;
- required crypto/netlink dependencies;
- required production LDN keys path;
- supported hardware profile selection;
- radio health gate and RX proof;
- no package installation drift on the end user's machine outside the managed runtime design.

Failure must be explicit if required runtime dependencies or keys are missing.

## O. Protocol/module boundary audit for the next emulator phase

Before final closure, audit imports and interfaces to ensure:
- Relay does not import Switch endpoint/game modules;
- Core does not import concrete Switch driver internals;
- Switch LDN driver implements generic endpoint contracts;
- `GenerationOffer` contains opaque setup payload and explicit protocol ID;
- Core DATA remains opaque payload + flags bound to a generation;
- no current fix hard-codes assumptions that make a future `retroarch_gpsp` endpoint impossible without Core rewrite;
- Switch-specific Pia/RFU transformation remains within endpoint/protocol adapter boundaries.

Do not add emulator code now. Produce a short architecture note describing what interface a future emulator endpoint will implement after Switch↔Switch is proven.

---

# 7. Existing preflight tracker is not complete — finish it, do not work around it

The repository contains:

- `docs/core-simplification/ABC_SOFTWARE_PREFLIGHT_CLOSURE.json`
- `docs/core-simplification/ABC_SOFTWARE_PREFLIGHT_RESUME.md`

At the current handoff they are stale/incomplete and explicitly indicate an unfinished preflight.

Use them as a checklist, but verify every claim against current code and tests.

Requirements:
- reconcile tracker HEAD/source_revision fields to the actual final commit;
- finish every still-relevant issue I01–I18;
- finish/re-map every still-relevant acceptance item T01–T44;
- do not mark PASS for a test that was not actually run at the final source revision;
- if a prior T-ID is obsolete because the implementation changed, document the replacement test and why it is equivalent/stronger;
- update the resume file to the final state instead of leaving stale “worktree after…” references;
- `task_state` may become COMPLETE and `verdict` may become PASS only after the final acceptance conditions below are true.

The tracker is evidence, not authority: if it misses a software defect you discover, fix and add it rather than ignoring it because no I-ID existed.

---

# 8. Mandatory final software qualification

Build a final pre-physical qualification suite whose purpose is to answer:

> “If this still fails on two real Switches, is the remaining unknown genuinely physical radio/Switch behavior rather than an obvious software integration gap?”

At minimum prove all of the following.

### Entry/runtime
1. real `dev.ps1 run host` route construction;
2. real `dev.ps1 run join <code>` route construction;
3. option forwarding;
4. unbuffered streaming;
5. exit-code correctness;
6. cancellation propagation;
7. radio identity/channel/RX binding;
8. run-owned interface naming and cleanup ownership.

### Pair lifecycle
9. Host creates a six-digit code;
10. Guest can join after a human-scale delay;
11. Guest can already be paired while Host room does not yet exist;
12. code expiry/invalid/consumed states are distinguished;
13. established Pair survives invite-code consumption;
14. reconnect lease behavior is deterministic;
15. common relay configuration is explicit.

### Direct A
16. clean no-room retry;
17. clean scan-timeout retry;
18. ambiguous/incompatible room fails closed;
19. Host peer identity is bound before TunnelSim creation;
20. early station/VIF cleanup success;
21. early VIF cleanup failure blocks next admission;
22. scan cancellation;
23. join/association cancellation;
24. local room end generates lifecycle close.

### Direct B
25. mirror is never created before a real remote offer;
26. AP/data-plane can exist with no Joining Switch yet;
27. user association may wait beyond historical 5/120/180-second limits;
28. cancellation during AP creation;
29. cancellation during association wait;
30. cancellation during control wait;
31. peer identity binds only after association;
32. owned AP/monitor/TAP cleanup is verified;
33. unrelated interfaces are untouched.

### Core / data plane
34. advertisement crosses the actual relay;
35. Generation offer/accept ordering is correct;
36. actual TunnelSim-facing bidirectional RFU-compatible traffic crosses Core/relay;
37. payload and valid flags are preserved;
38. inactivity alone does not become transport failure;
39. transport loss during pre-active states cleans/recover safely;
40. transport loss during ACTIVE recovers or fails closed without stale generation reuse;
41. generation close is drained before transport shutdown;
42. first failure identity is preserved if cleanup also fails;
43. unknown cleanup blocks the next Generation.

### Pair reuse
44. first generation ends from a realistic local lifecycle event;
45. both sides return to Pair waiting;
46. second generation starts with the same Pair;
47. fresh generation ID/state is used;
48. no stale old DATA is admitted;
49. second generation activates and transports data;
50. second cleanup is complete.

### Legacy separation / future modularity
51. no legacy Room/Attempt/Ready/Continue/checkpoint API is called by the new path;
52. Core/Relay concrete Switch import boundaries remain clean;
53. protocol/endpoint contracts remain reusable for the later emulator endpoint.

### Regression
54. all Phase A radio/runtime tests pass;
55. all Phase B Core tests pass;
56. all Switch endpoint tests pass;
57. existing Direct A/B tests pass;
58. StageSession tests pass;
59. TunnelSim/Reliable/Pia tests pass;
60. legacy production regressions remain green unless intentionally retired with documented reason;
61. full repository pytest passes;
62. Windows CI passes every required job/step;
63. Ubuntu CI passes every required job/step;
64. final CI HEAD exactly equals the final reported commit SHA.

Do not reduce the test quality merely to get green CI. Fix flaky/racy tests if they are real test defects, but preserve their intended invariant.

---

# 9. Physical-test readiness deliverables

When software preflight is complete, add/update a concise physical Switch↔Switch test runbook.

It must tell the user exactly:

## Relay
- how to start/use a relay reachable from both PCs;
- what URL each PC should use;
- how to confirm relay reachability before touching Switches.

## Host PC
- exact `dev.ps1` command;
- how supported USB adapter selection works;
- expected radio-gate output;
- expected Pair code output;
- when to open the native Pokémon Group Leader room;
- expected status sequence until Bridge active.

## Guest PC
- exact `dev.ps1` command with code and relay;
- expected waiting messages;
- when the native Join Group room should appear;
- when to select it;
- expected status sequence until Bridge active.

## Functional test
- a minimal real Switch↔Switch interaction that confirms the link is carrying the expected GBA/RFU session;
- what success looks like;
- what logs/evidence to collect on failure.

## Repeated-generation test
- leave/end the first game link;
- prove both PCs remain paired;
- create/join a second native room;
- prove a second generation activates without new Pair code.

## Shutdown
- Ctrl+C on either side;
- expected cleanup;
- commands/diagnostics to prove no SwitchTrade-owned interface/TAP/thread/process residue remains if necessary.

Do not call the physical hardware test “already passed.” The deliverable is that it is **ready to run immediately**.

---

# 10. Scope constraints

Do NOT:
- redesign the whole Core;
- restore old room browser / Room authority;
- restore Ready/Continue checkpoints;
- add synchronized user timing requirements;
- move game semantics into Relay/Core;
- rewrite working Pia/Reliable/RFU code without a demonstrated defect;
- implement the emulator endpoint yet;
- modify `main` or published tags/releases;
- perform destructive machine-wide WSL/reset/install operations without explicit user authorization;
- touch unrelated desktop UX;
- claim physical qualification without physical devices.

You MAY make narrow architectural corrections when necessary to satisfy the lifecycle and modularity invariants above.

---

# 11. Working method for this one-shot Astra task

This task intentionally asks you to finish the full software milestone in one run.

Work autonomously through all resolvable stages:

1. establish exact repository/branch state;
2. read the current Core simplification design and current preflight tracker;
3. audit the actual current call graph, not just historical audit prose;
4. reconcile known issues with current code;
5. implement fixes in coherent commits;
6. add high-fidelity tests at the real abstraction boundaries;
7. run focused tests after each risky change;
8. continue to lifecycle/lease/room-end work;
9. build the final real-software integration qualification;
10. validate actual PowerShell/dev entrypoint behavior;
11. run full repository tests;
12. push the completed branch;
13. wait for/check the CI associated with the exact final HEAD if your environment permits synchronous CI inspection;
14. resolve CI failures that are software/test defects;
15. update closure/resume documents with the final evidence;
16. produce the physical test runbook;
17. stop before actual physical Switch testing.

Do not ask for permission between ordinary coding packets. Do not stop because one commit is complete. Do not declare PASS because a focused suite is green.

If CI is asynchronous and you genuinely cannot obtain its result in this execution environment, do not falsify it. Mark final software state as `FUNCTIONALLY COMPLETE / CI PENDING` and report the exact run URL/HEAD if available. However, if CI results are accessible, inspect and resolve them before finalizing.

---

# 12. Final acceptance / verdict

You may report:

`ABC SOFTWARE PREFLIGHT: PASS`

ONLY when all of these statements are true:

- the Switch↔Switch software path is complete from development entrypoint to relay to Switch endpoint boundaries;
- normal user waiting is timing-independent but interruptible;
- a real local room end leads to generation cleanup and same-Pair re-wait;
- two sequential generations on one Pair are proven;
- actual TunnelSim-facing RFU-compatible data is exercised through the real Core relay path;
- cleanup ownership is fail-closed for all acquired resources, including early pre-ready resources;
- cancellation and transport loss do not leave unverified state;
- Pair/code/reconnect lifecycle is explicit and tested;
- no legacy Room/Ready/Continue authority is used;
- future emulator endpoint modularity is preserved;
- final full tests pass;
- Windows and Ubuntu CI for the exact final HEAD are green (or, only if CI result is truly inaccessible, the report explicitly says CI PENDING instead of PASS);
- the physical test runbook is ready.

At PASS, the next meaningful step must genuinely be:

> **Run two PCs + two supported USB Wi-Fi adapters + two stock Nintendo Switch consoles and perform the first real Switch↔Switch relay test.**

After that physical Switch↔Switch protocol is stabilized, the next development phase will be:

> **Implement a modular emulator endpoint (initially RetroArch/gpSP-oriented) so the same Core/Pair/Generation infrastructure supports Switch↔Emulator and later Emulator↔Emulator without redesigning Relay/Core.**

---

# 13. Required final report

At the end, report all of the following:

1. final branch and exact final SHA;
2. commits created and purpose of each;
3. files changed;
4. every known issue above and its resolution status;
5. additional defects discovered and fixed;
6. actual tests added/changed;
7. focused test results;
8. full pytest result;
9. Windows CI run ID/result;
10. Ubuntu CI run ID/result;
11. final state of I01–I18 and T01–T44 (or documented stronger replacements);
12. exact final Host/Guest/relay test commands;
13. remaining risks that genuinely require physical Switch/Wi-Fi hardware;
14. modularity note for the future emulator endpoint;
15. one explicit final verdict:

- `ABC SOFTWARE PREFLIGHT: PASS`
- `ABC SOFTWARE PREFLIGHT: FAIL`
- or, only when appropriate, `FUNCTIONALLY COMPLETE / CI PENDING`

Never use PASS if a known software integration gap remains.
