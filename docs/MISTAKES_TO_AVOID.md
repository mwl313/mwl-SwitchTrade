# Mistakes to Avoid

> **Authority:** This is the SwitchTrade source of truth for observed failures, disproven
> assumptions, operator/agent mistakes, and the guardrails that prevent their recurrence.
> Read this document before changing, testing, packaging, installing, deploying, recovering, or
> deleting anything in this repository or an installed SwitchTrade environment.
>
> **Last updated:** 2026-08-31
> **Current qualification branch:** `codex/m7-safe-pairing`
> **Next immutable candidate:** `v0.2.12-beta.1`; its exact source is the release tag target and its
> release ID must be `beta-<first 12 characters of that source SHA>`.

This document records what went wrong, not just what the current code intends to do. The normative
target remains the [ABC+D architecture](80-abc-connection-architecture-20260829.md), and open work
remains in the [Future TODO](FUTURE_TODO.md). If implementation, tests, a handoff, or an operator
instruction conflicts with a prevention rule here, stop and resolve the conflict before proceeding.

## 1. How this document must be used

### Before every task

1. Read this document completely, then identify the entries that can apply to the requested task.
2. Establish the exact source commit, installed release, runtime release, relay artifact, machine,
   role, adapter identity, state root, and intended evidence boundary. A filename or window title is
   not sufficient identity.
3. Separate facts into `observed`, `source-confirmed`, `reproduced`, `inferred`, and `unproven`.
   Never call an inferred cause definitive.
4. Use the smallest authoritative entry point. Do not assemble a new interpreter, environment,
   working directory, launch wrapper, or cleanup path for convenience.
5. Run all software-only and non-destructive gates close to the operator before asking anyone to
   move between PCs or touch a Switch.
6. Define the stop point, exact recovery command, recovery-state location, and clean residue
   criteria before performing the first mutation.

### When anything fails or behaves unexpectedly

1. Stop advancing both PCs and both Switches. Do not turn a failed run into a new experiment.
2. Preserve the first failure, raw bounded output, run/test/attempt identity, process identity,
   recovery state, authority state, and USB ownership. Later cleanup failures are secondary evidence.
3. Do not delete a state root, retry with the same invitation, reattach USB, close a room, or restart
   a service merely to make the screen look clean. Follow the committed recovery path.
4. Prove the lowest failing layer with a reproduction that distinguishes competing explanations.
5. Recover idempotently, then prove endpoint absence, interface/PHY absence, Linux USB state,
   Windows USB ownership, lock/recovery-state state, and room finalization.
6. Add the incident and its prevention rule here before retrying. If the cause is still unknown,
   record it as investigating rather than inventing certainty.

### Evidence and privacy rules

- Never commit room codes, member/reconnect credentials, raw packets, MAC addresses, trainer names,
  Pokémon data, private support bundles, or unredacted local paths containing personal identities.
- A unit test proves its modeled contract only. It does not prove WSL process behavior, USB timing,
  real RF, a hosted relay deployment, an installer upgrade, or a physical trade.
- An intermediate gate is never an overall pass. A successful cleanup does not convert a functional
  failure into a pass, and a functional pass is not complete until cleanup is verified.
- Absence is a factual three-state result: `present`, `absent`, or `unknown`. Timeout, parsing error,
  missing command, import failure, or permission failure is `unknown`, never `absent`.

## 2. Non-negotiable system invariants

These are distilled from repeated failures below.

1. One user action owns one coordinator, run ID, attempt ID, launch nonce, wrapper PID, endpoint PID,
   USB lease, and final USB return. Polling is read-only and cannot launch or revive work.
2. A and B must prove the same invitation/test identity and reach `coordination_paired` with
   `usb_attached=false` before either side enters P0.
3. One run attaches the exact selected adapter at most once and returns it exactly once. Endpoint
   stages may release their interfaces but may not independently cycle USB ownership.
4. The shared P0 gate owns the complete order: release/runtime integrity, `usbip-core`/`vhci-hcd`,
   exact Linux USB enumeration, `cfg80211`/`libarc4`/`mac80211`/`led-class`, profile driver/firmware,
   `ccm`, `cmac`, `tun`, `/dev/net/tun`, driver, PHY, netdev, stale-vif cleanup, and actual RX.
5. A is not ready because a room was merely seen. B is not ready because an AP call returned. C is
   not ready because the relay WebSocket connected. Each ABC+D gate needs its own evidence.
6. D cleanup is two-sided, attempt-scoped, idempotent, outcome-preserving, and part of acceptance.
   Unknown cleanup blocks a new run and blocks USB return when radio state is unproven.
7. Every WSL command supplies an explicit Linux working directory and absolute package/runtime root.
   It never inherits correctness from a translated Windows current directory.
8. Every packaged or installed test uses the exact final executable, environment, source, relay,
   and working directory. Testing components separately does not validate their composition.
9. Physical movement starts only after both PCs pass the same software pairing, release identity,
   P0 readiness, and operator checkpoint. A failed command never earns another trip between PCs.
10. Expected cancellation is a terminal outcome with a report and verified cleanup, not a traceback,
    orphaned room, or silently deleted evidence.

## 3. M7 distributed-harness incident register

### MTA-M7-001 — Relay polling exhausted the authenticated rate limit (`D-PHYS-1`)

- **Evidence:** run `fb373100-fd33-4782-a73c-db63433dccb5`, release
  `beta-0caafce68035`.
- **Observed:** P0 passed, then the run failed as `rate_limited` after approximately 30 seconds.
  Recovery initially assumed that an attempt existed even though failure occurred before one was
  created. The coordinator later terminalized the run as interrupted and verified cleanup.
- **Definitive cause:** the harness polled the relay every 250 ms. That consumed the hosted limit of
  120 authenticated requests per 60 seconds. Pre-attempt recovery then performed an invalid attempt
  lookup.
- **Correction:** commit `82e7dcc` centralized polling at one second and made the room owner close a
  pre-attempt temporary room without requiring an attempt.
- **Never repeat:** all pollers share one policy; GET is read-only; count the worst-case requests over
  the server window before a hosted run; recovery must branch on whether room, member, attempt, and
  endpoint identities actually exist.

### MTA-M7-002 — Membership expired while the operator was waiting (`D-PHYS-1-R2`)

- **Evidence:** run `14ae6551-6ce2-440f-a176-87829ec121dc`, release
  `beta-82e7dccdda08`.
- **Observed:** the last passed gate was P0. The primary failure was
  `member_credential_invalid`. Initial cleanup also failed because a
  `CONNECTION_TRANSITION_INVALID` path required closing intent. Coordinator recovery later verified
  cleanup.
- **Cause supported by runtime and the subsequent fix:** the pairing/operator wait did not sustain
  relay membership heartbeat, so a credential could expire before the next authority mutation.
- **Correction:** `d0299e1` keeps distributed members alive throughout qualification.
- **Never repeat:** every operator wait, hardware wait, and Switch checkpoint must keep the current
  membership alive below the relay timeout; cleanup must accept pre-attempt and already-closing
  states without fabricating a transition.

### MTA-M7-003 — Private-room metadata was treated as an identity contract (`D-PHYS-1-R3`)

- **Evidence:** PC B failed before P0 with `DISTRIBUTED_INVITATION_IDENTITY_MISMATCH`; PC A later
  failed `DISTRIBUTED_PEER_READY_TIMEOUT`. No valid physical result was produced.
- **Definitive cause:** the runner wrote the campaign binding into `note` while creating a private
  room and later expected `room.note` in the join response. The authority intentionally stores
  directory notes only for public rooms. A hosted probe proved the private room and both members were
  valid while no top-level note existed.
- **Additional safety defect:** PC A could acquire USB before PC B proved room identity, and an abort
  could delete distributed recovery state before local USB cleanup was verified.
- **Correction:** `distributed-invitation.v2` binds authoritative room UUID/code, source, release,
  test, action, and complementary roles; it contains no credential. Both sides must prove exact seats
  and the same identity at a pre-USB pairing barrier. Recovery state survives until local cleanup and
  authority release are both proven.
- **Never repeat:** do not use optional display/directory fields as security or test identity. Validate
  only fields guaranteed by the private-room contract. Never advance one PC beyond the shared barrier.

### MTA-M7-004 — Switch checkpoints were notifications, not barriers (`D-PHYS-1-R4`)

- **Evidence:** both PCs passed pairing, P0, attempt lock, and `C0_DATA_PLANE_PROVEN`; no Switch was
  operated. PC B reported `DISTRIBUTED_ENDPOINT_FAILED` with cleanup detail
  `d_launch_not_admitted`. Exact recovery finalized the room, detached USB, and left no residue.
- **Defect 1:** `CREATE_SWITCH_ROOM` and `JOIN_SWITCH_GROUP` were printed notifications. Endpoints
  continued immediately, so A could exhaust its scan before the operator touched the Switch.
- **Defect 2:** `StageSession` replaced the real Direct A/B failure code and last gate with generic
  `DISTRIBUTED_ENDPOINT_FAILED`.
- **Defect 3:** a 15-second relay transport expiry erased process-local launch admission even after
  D1 had put the attempt into `closing`; valid D5 evidence was then rejected as
  `d_launch_not_admitted`.
- **Correction:** `015903f` made checkpoints exact run/role-bound approval barriers, preserved the
  first stage failure through D1, and retained launch admission through D6 or a bounded D timeout.
- **Never repeat:** any human action required for a bounded scan/join must be an acknowledged state
  transition, not console prose. Cleanup may append evidence but cannot overwrite the primary cause.

### MTA-M7-005 — WSL probe depended on the Windows current directory (`D-PHYS-1-R5-NOSWITCH`)

- **Evidence:** PC A run `97f1d675-5931-444d-b114-4f6628866a0a`, release
  `beta-b92ab229870e`.
- **Observed:** pairing succeeded. P0a passed, then P0b failed
  `P0_LINUX_ENUMERATION_UNKNOWN`; cleanup reported `P0_CLEANUP_UNKNOWN` and did not detach USB because
  radio quiescence was unproven. The first official recovery repeated the failure.
- **Definitive cause:** `_wsl_linux_usb_probe` launched packaged Python without
  `wsl --cd /opt/switchtrade`. The agent had put a clean qualification worktree under Local AppData.
  WSL could not translate/chdir to that Windows path, then Python emitted
  `ModuleNotFoundError: No module named 'switchtrade'`. The probe flattened that command/import
  failure into `unknown`.
- **Disambiguating proof:** the exact probe with `--cd /opt/switchtrade` found one matching Linux USB
  device and no interface or PHY, proving that the radio was quiescent and the failure was the harness
  launch context, not USB hardware.
- **Recovery:** running the committed recovery from a clean Desktop worktree at the same source
  revision succeeded; USB returned to Windows, the room finalized, and endpoint/interface/PHY/
  recovery residue was absent.
- **Agent mistake:** the final mutating/cleanup command was never exercised from the exact AppData
  worktree before the user and PC B were told to proceed.
- **Open prevention requirement:** every WSL subprocess must set the explicit Linux runtime cwd and
  preserve command/import stderr as the factual failure. No future run may use a qualification path
  until its exact P0 and recovery probes pass there.

### MTA-M7-006 — The chosen Python launcher did not forward interactive stdin (`R6`)

- **Evidence:** PC A run `383ef5b9-24b1-4dca-8b6f-536bb29db632`.
- **Observed gates:** `P0_SIDE_READY`, `C0_AUTHENTICATED`, `C0_PEER_READY`, and
  `C0_DATA_PLANE_PROVEN` passed. The runner stopped at `CREATE_SWITCH_ROOM`. No Switch was touched.
- **Definitive cause:** `.audit-venv\Scripts\python.exe` was a forwarding/shim process which spawned
  the uv-managed base Python but did not forward interactive or piped stdin to the child. Process-tree
  inspection and a two-input test against the real interpreter proved the difference.
- **Failed operator actions:** repeated Enter writes had no effect. An exec-session ID was passed to
  the Codex terminal-opening UI, which returned a blank terminal; the user was incorrectly told to
  press Enter there. A later `AttachConsole`/`WriteConsoleInput` attempt failed with an invalid handle.
- **Recovery:** the exact harness child was stopped only after verifying PID and command. Recovery
  through the same shim reached a confirmation prompt but got EOF; a second idempotent recovery using
  the real Python accepted input and finalized authority. Final cleanup was verified and no residue
  remained.
- **Never repeat:** production qualification must not use `input()` or PTY attachment for control.
  Use explicit run-ID `continue`, `cancel`, `status`, and `recover` commands or the local control API.
  Until that exists, test two consecutive inputs on the exact executable before room creation and
  reject forwarding shims. Never tell the user a terminal is active without visible process-bound
  evidence.

### MTA-M7-007 — Fixing stdin by bypassing the venv removed dependencies (`R7`)

- **Evidence:** PC A run `109dab8a-ed83-4fcd-a1a1-7411ff6a6261`.
- **Observed:** P0 failed immediately, before USB mutation, as
  `P0_RELAY_WEBSOCKET_UNAVAILABLE`; cleanup was verified.
- **Definitive cause:** the real base Python was invoked without the virtual environment's
  site-packages. Ten exact repetitions failed in 0 ms with
  `ModuleNotFoundError: No module named 'websockets'`. This was not a relay outage.
- **Agent mistake:** one launch dimension (stdin) was repaired while the complete final environment
  was not validated.
- **Never repeat:** validate the composed command, not isolated pieces: executable, `sys.path`,
  imports, source SHA, installed release, relay TLS/WebSocket, WSL cwd, stdin/control channel, and
  recovery. Prefer one packaged entry point over hand-built `PYTHONPATH`.

### MTA-M7-008 — R8 was deliberately canceled, not a product failure

- **Evidence:** before R8, the final command environment proved two stdin inputs, `websockets`
  17.0.1, correct source/release, Linux probe, and relay WebSocket. The room was created, then the
  user requested “테스트 중지” before pairing/P0/USB.
- **Observed:** Ctrl+C stopped the runner; the room was closed and final checks showed no session,
  active run, endpoint, harness, attached USB, or running WSL distro.
- **Usability defect:** the expected cancellation surfaced a `KeyboardInterrupt` traceback instead
  of a clean terminal cancellation report.
- **Never repeat:** record this case as canceled, never failed or passed. Normalize expected cancel
  paths into a stable result and still verify cleanup.

### MTA-M7-009 — Concurrent status polling could defeat atomic state replacement on Windows

- **Observed:** on 2026-08-31, the first identity-bound control-channel test reached its checkpoint
  writer while another thread polled `distributed-control-state.json`. Windows returned
  `PermissionError: [WinError 5]` from `os.replace`, so the checkpoint remained at `created` even
  though the JSON writer used a same-directory temporary file. No relay, WSL, USB, or Switch was
  touched.
- **Definitive cause:** same-directory replacement is atomic when accepted, but the shared JSON
  writer treated a transient Windows sharing violation from a concurrent reader as permanent.
- **Disproven alternative:** the checkpoint identity and UUID were valid; the worker failed exactly
  at replacement, before command submission.
- **Correction status:** in progress. The common atomic JSON writer needs a short bounded retry for
  Windows sharing/permission races while preserving the temporary file and failing closed after the
  deadline.
- **Never repeat:** any production state file designed for concurrent read-only polling must be
  tested under concurrent readers on Windows. “Atomic replace” is not equivalent to “replace cannot
  transiently fail.”
- **Source correction (2026-08-31):** the common JSON writer now retries only bounded Windows
  `PermissionError` replacement races and still fails closed at its deadline. The control-channel
  concurrency regression and the focused harness suite pass; installed two-process evidence remains
  required.

### MTA-M7-010 — Concurrent control submissions could overwrite one another

- **Observed:** the 2026-08-31 maintainability review found a pre-qualification race; it has not been
  observed in a physical run. Two controllers could both observe no command file and then both call
  replace, allowing a later `continue` or `cancel` to overwrite the earlier accepted command.
- **Definitive cause:** the command path used atomic replacement, which protects readers from partial
  JSON but does not provide create-if-absent semantics between multiple writers.
- **Risk:** one caller could be told its cancellation was accepted while the runner consumed a
  different command. A command could also arrive after cleanup had already checked and removed the
  path.
- **Correction status:** in progress. Publish a fully written private temporary file with atomic
  no-overwrite creation, validate the current state again after publication, and remove only the
  submitter's own stale command if a terminal transition won the race.
- **Never repeat:** “atomic file” must state whether it means atomic reader visibility, exclusive
  writer ownership, or both. Control mutations require both and need a concurrent-submitter test.
- **Source correction (2026-08-31):** control commands now publish a fully fsynced temporary file by
  atomic no-overwrite link, re-read the state after publication, and remove only their own command if
  a state transition won the race. Concurrent submitter, cleanup-race, and invalid-action regressions
  pass; installed two-process qualification remains open.

### MTA-M7-011 — State-root reuse rejection happened after relay-room mutation

- **Observed:** the 2026-08-31 maintainability review found a pre-qualification ordering defect; no
  orphan was created during this review. With no active coordinator run but an old control-state file,
  `create` could open a private relay room and persist its session before `DistributedControl` rejected
  the reused root.
- **Definitive cause:** coordinator reuse was checked before `_room_session`, but control/session reuse
  was checked partly inside or after the authority mutation.
- **Risk:** a correctly rejected local launch could still leave a remote room/credential requiring
  recovery, contradicting “reject before mutation.”
- **Correction status:** in progress. Validate session, control-state, and pending-command paths before
  calling create/join, with an isolated regression proving the relay receives zero calls.
- **Never repeat:** every local idempotency/recovery guard must be evaluated before the first remote or
  hardware mutation. A later constructor check is defense in depth, not the preflight gate.
- **Source correction (2026-08-31):** `_room_session` now rejects an existing session, pending command,
  or control state before calling either relay create or join. Its regression proves zero relay
  mutations on a reused root; installed qualification remains open.

### MTA-M7-012 — Session persistence failure was outside authority rollback

- **Observed:** the 2026-08-31 maintainability review found a failure-injection gap; it has not been
  observed in a physical run. Create/join rolled authority back after identity validation failures,
  but an `atomic_json` error while persisting the private recovery session escaped that rollback.
- **Definitive cause:** the rollback `try` ended before the durable session write.
- **Risk:** a disk/permission failure could leave a live remote room member without durable local
  recovery credentials.
- **Correction status:** in progress. Put validation plus persistence in one rollback boundary, share
  the owner/member rollback function, and retain a successfully written session only if authority
  rollback itself cannot be proven.
- **Never repeat:** once a remote resource returns recovery credentials, every subsequent validation
  and persistence step remains inside an idempotent rollback boundary until durable recovery state is
  confirmed.
- **Source correction (2026-08-31):** create and join now keep identity validation, private session
  persistence, and invitation construction inside one shared authority-rollback boundary. Persistence
  failure has its own stable code, and a failure-injection regression proves the joined member is
  released without leaving a session file.

### MTA-M7-013 — Qualification kit copied dependencies into a nested false site-packages root

- **Observed:** the first `0.2.12-beta.1` package candidate from source `c5f7897a02a0` built its WSL
  appliance, MSI, and Burn bundle, but the mandatory package validator stopped at
  `DISTRIBUTED_QUALIFICATION_ENVIRONMENT_INVALID`. The candidate was not installed or published;
  WSL, USB, and the installed `0.2.11` release were untouched.
- **Definitive cause:** the kit builder selected `site.getsitepackages()[0]`. In this uv-created venv,
  that first entry is the venv root, not `Lib/site-packages`; dependency files were consequently copied
  under `python/Lib/site-packages/Lib/site-packages`, and the packaged interpreter could not resolve
  even `trio` metadata. Direct inspection of the rejected kit reproduced `PackageNotFoundError: trio`
  and showed the exact nested directory.
- **Disproven alternatives:** the portable CPython executable launched correctly from the non-ASCII
  path, the pinned requirements hash matched, and source files plus manifest identity were present.
- **Recovery/residue:** package validation used and removed only its dedicated temporary extraction
  root. The rejected build remains evidence under its source-specific artifact directory; there was no
  host installation or radio state to recover.
- **Never repeat:** never infer a venv's import directory by list position. Resolve `purelib` through
  `sysconfig`, and make the kit builder itself launch the copied interpreter from the copied source and
  verify locked imports/metadata before writing a releasable manifest.
- **Source correction (2026-08-31):** the builder now uses `sysconfig.get_path("purelib")` and performs
  the packaged import/version probe before manifest/archive creation. A fresh source identity and full
  package validation are still required; the rejected `c5f7897a02a0` artifact is not releasable.

### 2026-08-31 M7 harness prevention implementation

- Every WSL subprocess in P0 and D now uses one typed `wsl_root_command` builder with explicit
  `--cd /opt/switchtrade`. Linux USB probe failures retain a stable factual class, return code, and
  redacted stderr hash instead of collapsing cwd/import failures into generic unknown.
- Operator `input()` checkpoints are removed. `distributed-control-state.v1` exposes read-only
  status, and exact test-ID/run-ID/checkpoint-bound `continue` and `cancel` commands drive the single
  runner. A stale or duplicate command fails closed; cleanup ignores and removes raced commands.
- Cancellation is checked during pairing, P0 validation/acquisition, peer readiness, endpoint launch,
  live A/B/C work, and user waits. The worker remains the sole cleanup owner, and expected cancel is a
  canceled functional result rather than an unhandled `KeyboardInterrupt` failure.
- `scripts/windows/Invoke-M7DistributedHarness.ps1` is the only source qualification entry point. It
  fixes the repository cwd, validates its exact interpreter/import closure, rejects dirty source and
  mismatched WSL runtime identity, and uses the canonical Windows adapter-selection path before any
  room mutation. Source-level Unicode-path and mutation-free status tests pass.
- These are source corrections, not installed physical evidence. A new immutable installer/runtime
  and two-PC close-range qualification are still required before physical movement or release claims.

## 4. Legacy launcher, diagnostic, and desktop failures

### MTA-APP-001 — False-positive launch acknowledgement caused a process storm

- **Evidence:** support bundle `SwitchTrade-support-20260828T075317Z-8036dd6a.zip` recorded 128
  `session_started` events in seven bursts; late bursts launched 6 and 51 PIDs at roughly two-second
  intervals. The selected RTL8192EU was attached and visible, but the endpoint never reached scan.
- **Definitive chain:** the shell wrapper acknowledged launch before completing radio preparation;
  the controller treated that acknowledgement as endpoint success; status/room polling relaunched
  whenever the short-lived process left no endpoint state; failures before Python created neither a
  durable run nor a visible terminal cause; child output was not retained.
- **Prevention:** only an explicit mutation launches. GET/status polling is read-only. Acceptance
  requires run ID + attempt ID + nonce + wrapper PID + endpoint PID and a post-radio endpoint
  acknowledgement. Early exit is terminal until explicit Retry. Retain bounded stdout/stderr and
  cleanup the one owned process tree.

### MTA-APP-002 — Adapter shown in the UI was falsely diagnosed as absent

- **Observed:** Settings showed an authorized Realtek RTL8192EU, while diagnostic JSON returned
  `USB_NOT_FOUND`.
- **Definitive cause:** the diagnostic inspected WSL without first attaching the selected Windows
  adapter. On a later run, usbipd exposed `ClientIPAddress` before Linux enumeration completed, and an
  immediate driver/radio check failed generically.
- **Prevention:** report each gate separately: Windows detected, authorized/shared, USB/IP attached,
  Linux enumerated, driver bound, PHY/netdev ready, channel/RX healthy. Wait for bounded Linux
  re-enumeration. A Windows UI selection is not Linux presence.

### MTA-APP-003 — Diagnostic export returned a Linux-only path

- **Observed:** the desktop displayed `/root/...` for a diagnostic file, unusable to a Windows user.
- **Correction rule:** keep the private WSL copy, export a redacted copy to an explicit Windows path,
  return that path, and treat export/upload outcomes separately. Test non-ASCII usernames and UTF-8/
  UTF-16LE output.

### MTA-APP-004 — Production Diagnostics opened as a blank page

- **Cause:** the XAML view existed but its initialization/load path did not run.
- **Correction:** `ca8fd87` initialized the production diagnostics view.
- **Prevention:** a view file is not a feature. Test navigation, construction, data binding, backend
  DTO/API calls, empty/loading/error states, Back/Escape/Alt+Left, and installed-runtime launch.

### MTA-APP-005 — Local diagnostic suite became self-destructive after one pass

- **Definitive defects:**
  1. Creator diagnostics reused the owner credential for both members, so the synthetic peer never
     became ready.
  2. Each stage independently detached and reattached the adapter, creating USB sounds and a WSL/
     usbipd re-enumeration race between creator and finder roles.
  3. Cleanup checked only Windows and reported success while stale Linux USB/driver/interface/PHY
     state remained, producing `inactive port` and related driver-error storms.
- **Correction:** `90135a6` created distinct complementary credentials/roles, one run-scoped radio
  owner with one attach/detach, three-state Linux probes, worker-owned cancellation, retained cleanup
  guards, startup recovery, and structured `DIAG_*` failures.
- **Prevention:** a recommended suite is one lifecycle, not a sequence of independent hardware
  lifecycles. Endpoint stages stop between roles but the adapter remains attached until final D.

### MTA-APP-006 — Diagnostic UI presented contradictory and flickering state

- **Observed:** two “Connection needs attention” explanations alternated. Pressing End connection
  briefly returned to normal, then polling rehydrated the same failed attempt and re-enabled End.
  Close Trade Room finally returned to the menu. An intermediate hardware success could look like an
  overall pass.
- **Cause:** competing room/status projections, a terminal attempt not retired by Stop/End, and a
  later generic `relay.peer_lost` racing the specific endpoint error.
- **Prevention:** one authoritative projection; stable phase/result enums; preserve the first cause;
  terminal attempts cannot be revived; Stop/End is idempotent; “Passed” appears only after functional
  terminal success plus verified cleanup; Run Again remains disabled until cleanup is proven.

### MTA-APP-007 — Guided AP test design initially implied two Switches

- **Correction:** Guided AP association needs one Switch searching/joining the app-hosted room and a
  versioned synthetic remote app peer. If a second Switch hosts a room, the Switches can connect
  directly and bypass the app/relay, invalidating the test.
- **Prevention:** every diagnostic names which participant is real and which is synthetic, and states
  exactly which production boundary it proves. A diagnostic pass is not a full trade certificate.

### MTA-APP-008 — Error identity was inferred from prose and generic HTTP status

- **Observed audit defects:** desktop/control paths inferred meaning from English messages; Retry had
  a wrong call signature; a remote room close left stale UI/session state; desktop/control/relay
  revisions could appear compatible while required capabilities differed.
- **Correction:** error envelopes carry stable `code`, `message`, `stage`, `recoverable`,
  `primary_action`, and `correlation_id`; Retry uses the authoritative attempt contract; terminal room
  events clear or recover exact state; health advertises release and capability contracts.
- **Never repeat:** machine behavior branches on codes and contracts, never localized text. Reject
  incompatibility before room creation and test unknown envelopes rather than inventing a fallback.

### MTA-APP-009 — Polling and loopback trust boundaries were unsafe

- **Observed audit defects:** hardware polling exceptions could escape an `async void` handler and
  arbitrary loopback origins could mutate local control state.
- **Correction:** contain timeout/parse errors while preserving last good inventory, and restrict
  state-changing origins.
- **Never repeat:** loopback is still a trust boundary. GET/readiness paths do not mutate, all mutation
  endpoints authenticate/validate origin and input, and UI async exceptions become structured state.

### MTA-APP-010 — Reconnect state was hidden or consumed destructively

- **Observed audit defects:** a valid unmatched reconnect credential was hidden behind Home while
  local authority blocked new rooms. `reconnect_deadline_expired` was collapsed to
  `room_not_active`, and a readiness probe could consume state while the matching endpoint remained
  live.
- **Correction:** expose structured recovery; local-only reset requires explicit confirmation;
  Cancel preserves state; stop/adopt only the identity-matching endpoint before clearing credentials;
  readiness is non-destructive.
- **Never repeat:** reconnect credentials and endpoint ownership are first-class recovery evidence,
  never stale UI debris.

## 5. ABC+D runtime, radio, and physical-test failures

### MTA-RADIO-001 — Production wrapper omitted required LDN prerequisites

- **Observed:** a real Switch-hosted room was detected, parsed, and admitted three times, but every
  join failed at A6 `NL80211_CMD_NEW_KEY` with `ENOENT`.
- **Definitive cause:** the installed runtime contained the correct custom kernel plus `ccm`, `cmac`,
  and `tun`, but the production `run-beta-endpoint.sh` did not load/verify them or `/dev/net/tun`.
  The earlier standalone VM/WSL `run_trade.sh` path had done so.
- **Architectural consequence:** this exposed that components analogous to A/B/C existed but were not
  ordered through one readiness coordinator. It motivated the ABC+D orchestration rewrite.
- **Prevention:** all normal, diagnostic, and qualification paths call the one ordered P0 gate. A
  warm-runtime pass cannot close a cold-start requirement.

### MTA-RADIO-002 — Hot attach raced Linux driver/PHY publication

- **Observed:** usbipd reported attached and Linux showed the USB sysfs device, while the already
  loaded `rtl8xxxu` driver had not completed binding and no PHY/netdev existed. Launch raced the
  driver probe and failed. Detach while probing generated misleading inactive-port and EFuse output.
- **Prevention:** attach success is not radio readiness. Wait for exact device, driver, PHY, netdev,
  and RX with a bounded timeout. Never mutate or detach a half-probed device from another owner.

### MTA-RADIO-003 — Stale virtual interfaces and external network management blocked association

- **Observed historical failures:** stale vifs produced association status 1; NetworkManager managing
  the selected adapter produced `EBUSY`.
- **Dangerous recovery learned:** reloading NetworkManager live killed the VM network.
- **Prevention:** remove only run-owned/stale interfaces under the radio lock; configure the adapter
  unmanaged and apply that configuration by controlled reboot. Do not restart unrelated networking
  during a remote session.

### MTA-RADIO-004 — USB power/driver state could destroy receive capability

- **Observed:** USB selective suspend and `rtl8xxxu` IQK behavior caused receive death; an explicit
  USB reset restored reception.
- **Prevention:** actual RX is a mandatory gate, not driver presence. USB reset is a bounded recovery
  action before a run, never an invisible retry during a live attempt; preserve the original state and
  count it in evidence.

### MTA-RADIO-005 — Custom RTL8188EUS driver could block inside the kernel

- **Observed:** `rtl8188eus` plus `ldn.scan` could hang in a kernel operation that Trio timeout could
  not interrupt. RTL8188EU could observe traffic but failed control-port association and AP+monitor
  qualification; receive could die.
- **Decision:** abandon that custom-driver production path and quarantine RTL8188EU. The proven beta
  profile remains RTL8192EU with in-kernel `rtl8xxxu`.
- **Prevention:** the hardware matrix may expose experimental profiles but cannot bypass identical P0,
  A, B, C, and D acceptance gates.

### MTA-RADIO-006 — Fixed-channel assumptions produced false negatives

- **Observed:** valid rooms appeared on channels 1, 6, and 11. A channel-6-only capture could miss a
  legitimate session elsewhere.
- **Prevention:** a capture or scan must record its channel coverage. “The card did not hear the
  Switch” is too broad unless RX health and all expected channels were proven.

### MTA-RADIO-007 — AP existence was confused with Switch-compatible AP behavior

- **Historical failure points:** hidden SSID; missing beacon/probe/association IEs; missing privacy,
  RSN, or CCMP; zeroed D1 flags or partner info; passing a nonexistent LDN interface to hostapd;
  running an asyncio engine under Trio (`no running event loop`); missing nl80211 constants; AP with
  no monitor/TAP/control-port evidence.
- **Prevention:** B2-B10 remains ordered and factual. B does not pass until immutable fixture
  validation, exact FRLG network construction, beacon/probe response, AP+monitor+TAP, real Switch
  association, control port, data plane, hold, and cleanup are separately proven.

### MTA-RADIO-008 — Successful Direct B was overwritten by teardown timing

- **Observed:** one physical run reached B2-B10, but slow peer/context destruction rewrote the report
  as `B_HOLD_TIMEOUT`. A later run proved the LDN context could exceed a ten-second exit deadline.
- **Correction:** keep the functional timeout outside the full LDN context lifetime, bound STOP_AP/
  destroy notification, preserve B success separately, then perform authoritative interface cleanup.
- **Prevention:** teardown has its own D evidence and cannot retroactively erase a passed functional
  gate. It may still make the overall run fail cleanup.

### MTA-RADIO-009 — Transient USB bus ID was used as stable device identity

- **Observed:** replug/reboot changed the bus ID, allowing the wrong adapter to be selected or an
  unshared adapter to enter an attach/Repair loop. Reboot continuation could reuse the stale bus ID
  and leave auto-attach state.
- **Correction:** persist Windows InstanceId/profile identity, resolve the current bus immediately
  before authorization/attach, use one-time non-forced bind, and remove owned continuation state on
  rollback/uninstall.
- **Never repeat:** bus ID is location, not identity. Reject duplicate/changed identity and verify the
  selected physical device again after every re-enumeration.

### MTA-RADIO-010 — A validated nonzero PHY was later replaced with hard-coded `phy0`

- **Observed audit defect:** health could correctly select a nonzero PHY while an endpoint or
  diagnostic later operated on `phy0`.
- **Prevention:** P0 exports the exact gated PHY/interface identity; every workload consumes that
  identity and fails if it is absent or changes. Never rediscover or hard-code it downstream.

### MTA-RADIO-011 — Built-in firmware was falsely reported missing

- **Observed audit defect:** Setup looked only for an external firmware file although the custom
  kernel could embed the required firmware.
- **Prevention:** validate firmware provenance against the exact kernel/module release and accept only
  the modeled built-in or verified external form; reject absent, tampered, or mismatched identity.

### MTA-RADIO-012 — Concurrent owners and unsafe cleanup/reset corrupted radio evidence

- **Observed audit defects:** capture, diagnostics, endpoint, and Repair could race; subprocesses
  could wait indefinitely; cleanup could remove interfaces while the worker remained live; ordinary
  packetless RX triggered an automatic USB reset.
- **Correction:** one ownership lock and bounded process policy covers all mutating radio workflows;
  cleanup refuses a live worker; packetless normal launch is `RX_INCONCLUSIVE`; USB reset is an
  explicit, recorded recovery action only.
- **Never repeat:** a helper's local lock is insufficient if sibling workflows bypass it. All radio
  mutations route through the same owner and exact process identity.

## 6. Relay, authority, and transport failures

### MTA-RELAY-001 — All HTTP 409 responses were mapped to “room full/in use”

- **Observed:** with only one member, Connect correctly returned the coordination conflict “both
  trainers must press Connect,” but the desktop displayed “room full or already in use.”
- **Cause:** a generic desktop 409 fallback erased the control service's factual reason.
- **Prevention:** stable machine codes cross every layer; unknown codes retain bounded server detail;
  normal waiting is a state, not an error. Test one-member, two-member either-order, duplicate-click,
  reconnect, and stale-banner clearing.

### MTA-RELAY-002 — Retained-frame replay violated readiness order

- **Observed:** an advertisement at sequence 1 could be replayed before peer-ready sequence 0.
  `SequenceGate` accepted 1 and rejected 0 as stale, leaving an online peer waiting forever. The UI
  mislabeled the failure `DIAG_RELAY_UNREACHABLE` and B never started.
- **Correction:** v2 orders peer readiness before advertisement delivery, binds epoch/attempt, and
  rejects gaps, duplicates, stale epochs, and wrong attempts.
- **Prevention:** late-peer and reconnect tests are release gates; relay-connected does not mean
  ordered data plane proven.

### MTA-RELAY-003 — Heartbeat interval equaled the server timeout

- **Observed:** a 30-second client heartbeat against a 30-second relay timeout caused 4408 churn
  under normal jitter.
- **Prevention:** heartbeat cadence must have safe margin below timeout and be tested with latency,
  scheduling pause, reconnect, and duplicate delivery.

### MTA-RELAY-004 — Generic peer loss overwrote the specific endpoint failure

- **Observed:** local Stop or endpoint failure disconnected transport while the attempt was closing;
  the relay then projected `relay.peer_lost`, overwriting errors such as
  `radio.switch_room_not_found`. One support bundle contained 120 repeated
  `authority_phase_sync_failed` records and contradictory “relay failed” / “relay reachable” output.
- **Prevention:** D1 freezes the first A/B/C outcome; expected closing disconnects are not peer loss;
  authority sync is event-driven or rate-limited and deduplicated; a snapshot cannot report mutually
  contradictory axes.

### MTA-RELAY-005 — Deployment topology was assumed to be Docker

- **Observed:** an agent requested a Docker image ID, while the hosted relay actually ran one
  launchd-supervised native uvicorn process. Docker inspect therefore failed despite a correct
  deployment.
- **Prevention:** verify the real topology first. For this host, prove exact deployed source and
  imported-module hashes, launchd manifest, one uvicorn worker, health/storage, smoke tests, and
  private metrics. Do not substitute a Docker requirement that production does not use.

### MTA-RELAY-006 — Aggregate metrics were over-attributed

- **Observed potential issue:** the relay reported two rooms in
  `waiting_for_complementary_role` with `active_member_credentials=0`. Aggregate metrics cannot prove
  they came from D8-D10, cannot show whether reconnectable members remain, and do not prove a leak.
- **Current status:** potential issue, not a confirmed blocker. The general room TTL is six hours and
  the 30-minute waiting TTL applies to `waiting_for_partner`, not necessarily this state.
- **Prevention:** inspect ordered room/member/attempt events before cleanup. Expire only when no live
  credential, reconnectable member, live/admitted RFU attempt, or recovery claim exists. Add a
  complementary-role wait/credential-loss/reconnect/expiry regression.

### MTA-RELAY-007 — Authority audit found independent consistency and operations gaps

- **Observed audit classes (`REL-001` through `REL-016`):** unbounded retention, stale WebSockets,
  state regression, unlocked roles, retry storms, nontransactional expiry, weak idempotency,
  multi-writer risk, spoofable rate-limit identity, shallow health, offline public-directory entries,
  incomplete backup/restore, and unpinned dependency/image identity.
- **Correction:** SQLite transactions and monotonic versions; rotating credentials; WebSockets bound
  to room/attempt/direction; terminal errors stop retry; one authoritative writer; trusted-proxy
  identity; bounded limits/pruning; storage-aware readiness; backup/restore drills; locked dependencies.
- **Never repeat:** a passing happy-path smoke does not close authority durability or abuse behavior.
  Deploy and test concurrency, expiry, restart, proxy identity, backup, and stale-connection cases.

### MTA-RELAY-008 — Process identity was reduced to a numeric PID

- **Observed audit defects:** a 250 ms launch heuristic could accept a different process after restart
  or PID reuse; a control restart between wrapper acknowledgement and endpoint-state creation lost the
  session; natural exit during Stop left stale state; Windows validated a PID and killed it in a
  separate raceable step.
- **Correction:** global `flock` held through `exec`; nonce-bound acknowledgement; identity includes
  PID start ticks, argv, session, nonce, and WSL distro; pidfd is pinned before validation/signal; late
  verified state is adopted and disappearance is idempotent.
- **Never repeat:** PID alone never authorizes signal, cleanup, or adoption.

## 7. Installer, runtime, version, and Unicode failures

### MTA-INSTALL-001 — Repair split Windows and WSL across releases

- **Observed:** Repair moved/replaced WSL content before the Windows commit, then failed a later radio
  gate. Windows and WSL described different revisions and rollback was incomplete (`STB-004`).
- **Prevention:** stage and self-check both sides, persist transaction checkpoints before mutation,
  atomically publish one active release, and compensate in reverse order. Repair is a verified fresh
  replacement, not a collection of best-effort edits.

### MTA-INSTALL-002 — Package-root normalization rejected Burn cache paths

- **Observed:** Burn supplied a package-cache path ending in a separator; the provisioner appended
  another separator and falsely raised `PAYLOAD_PATH_ESCAPE` / `0x8007001e`.
- **Prevention:** canonicalize once, pass argv as data, and regression-test the exact Burn extraction
  layout.

### MTA-INSTALL-003 — Incremental WiX output embedded stale payloads

- **Observed:** candidate `beta-d0e3f825439f` had a new outer name but contained an older
  `beta-test` bundle, `beta-31d37b3b2707` manifest, and old provisioner.
- **Prevention:** force WiX Rebuild, extract the finished Setup EXE, and compare embedded release,
  manifest, provisioner, runtime, and payload hashes before publishing. A filename/version label is
  never artifact identity.

### MTA-INSTALL-004 — Custom kernel path failed under a non-ASCII username

- **Observed:** candidate `beta-9a58b1a82612` failed
  `WSL_E_CUSTOM_KERNEL_NOT_FOUND` when the kernel lived under a Korean-profile path. A disposable test
  used a fake profile, so WSL ignored that `.wslconfig` and silently booted its stock kernel, creating
  a false pass.
- **Correction:** store the verified kernel in SID-scoped, ACL-protected ASCII ProgramData storage;
  test the actual user's `.wslconfig` and restore it byte-for-byte.
- **Prevention:** every Windows/WSL path, JSON, log, subprocess, and handoff test includes non-ASCII
  and spaces. A fake profile cannot validate global WSL configuration.

### MTA-INSTALL-005 — Minimal rootfs omitted runtime tools

- **Observed:** rootfs variants lacked `depmod`, `modinfo`, or the `kmod` package, making module
  readiness impossible even when files existed.
- **Prevention:** rootfs inventory and boot self-check must prove every command used by P0, not just
  archive creation.

### MTA-INSTALL-006 — Same-release Repair tried to overwrite the running kernel

- **Observed:** content-addressed kernel file replacement hit a Windows file lock while WSL used it.
- **Prevention:** reuse an existing hash-identical immutable file; never overwrite active content.
  New content gets a new identity and atomic pointer update.

### MTA-INSTALL-007 — Provisioning depended on Setup's launch directory

- **Observed:** Explorer-launched Repair failed `ModuleNotFoundError` while repo-cwd launches passed.
  The provisioner ran a Python module without changing to its staged application root.
- **Prevention:** every process gets explicit executable, argv, cwd, environment, timeout, encoding,
  and captured output. Test Explorer/default-path launch, not just a developer shell.

### MTA-INSTALL-008 — PowerShell argument construction corrupted named parameters

- **Observed:** launch arguments passed as a positional string array rejected `-Prepare`.
- **Prevention:** use a single audited subprocess boundary and exact argv. Do not build shell command
  strings or rely on quoting across PowerShell/C#/WSL layers.

### MTA-INSTALL-009 — Readiness and process-I/O assumptions were too short or unbounded

- **Observed:** the desktop allowed 2.8 seconds while cold control startup took about 4 seconds.
  Separately, WPF waited for redirected EOF while a WSL background child retained pipe handles,
  creating an indefinite wait.
- **Prevention:** bound readiness to measured cold-start behavior and an explicit ready signal. Do not
  use EOF as service readiness or shutdown proof; close/redirect child handles deliberately.

### MTA-INSTALL-010 — Hardware preparation blocked access to recovery UI

- **Observed:** startup prepared the radio before bringing up local control, so a missing adapter
  could prevent the user from reaching Settings or diagnostics.
- **Prevention:** control and recovery UI start independently. Hardware is acquired lazily only by an
  explicit run.

### MTA-INSTALL-011 — WSL/DNS and relay failures were conflated

- **Observed:** one external incident was relay DNS `NXDOMAIN`; another involved WSL IPv6 A/AAAA and
  Tailscale DNS behavior. They were not the same failure.
- **Prevention:** report DNS resolution, TCP/TLS, HTTP health, WebSocket upgrade, authentication, and
  relay data plane separately. Use `single-request-reopen` only for the proven resolver case.

### MTA-INSTALL-012 — Lost responses and stale versions made successful terminal mutations look failed

- **Observed:** remote Leave could commit while its response was lost; a retry with stale local
  credentials was reported as relay unavailable. Heartbeats also advanced room version, causing 409
  on terminal leave/close.
- **Prevention:** terminal mutations are idempotent, tolerate already-applied state, refresh only on
  explicit version conflict, and never translate credential/semantic conflicts into reachability.

### MTA-INSTALL-013 — Transient WSL enumeration caused false cleanup success

- **Observed:** a `0.2.9 -> 0.2.10` qualification trusted one `wsl --list --quiet` snapshot. A
  transiently omitted distro name caused `PreviousName` and the cleanup journal to be cleared while
  registration and runtime storage remained.
- **Prevention:** authoritative registry + owned managed-root checks; bounded repeated absence proof;
  retain the journal on uncertainty; never touch unrelated distros or roots.

### MTA-INSTALL-014 — Missing release configuration blocked the installed local service

- **Observed:** the app showed `RELEASE_STATE_INVALID` because the installed release configuration
  was missing or incompatible. This was an install/test bootstrap defect, not proof that ABC+D radio
  code failed.
- **Prevention:** installed entry-point preflight verifies the signed/immutable release manifest and
  offers exact Repair guidance. Never ask the operator to guess or manually unregister/reset WSL.

### MTA-INSTALL-015 — Hardware selection absence was misinterpreted

- **Observed:** PC B reported that `hardware-selection.json` was absent.
- **Correct interpretation:** this can be normal before the installed app has saved an adapter. It is
  a hard preflight block for a hardware test, not by itself a broken installation.
- **Canonical Windows path:** `%LOCALAPPDATA%\SwitchTrade\runtime\hardware-selection.json` on each
  PC. A previous handoff incorrectly treated a WSL/root path as canonical.
- **Prevention:** let the app select/authorize the adapter, then validate stable InstanceId/profile;
  do not hand-create or copy another PC's selection.

### MTA-INSTALL-016 — Version strings and same-version packages were mishandled

- **Rule:** application prerelease versions may be `0.2.11-beta.1`, but Windows/MSI uses numeric
  `0.2.11`. Preserve MSI/bundle UpgradeCodes, generate a normal new ProductCode/package identity, and
  make same-version Repair behavior explicit. Never rename an old artifact to look like a new build.

### MTA-INSTALL-017 — Distro name or copied marker was mistaken for ownership

- **Observed audit defect:** a same-name distro or copied ownership marker could be adopted or
  unregistered. Purge could mutate Windows before reliable WSL enumeration and race a distro swap.
- **Correction:** every destructive operation requires the install UUID plus exact current Lxss
  BasePath; enumeration must be known; identity is rechecked immediately before unregister.
- **Never repeat:** distro name and marker content are insufficient destructive authority. Unknown
  enumeration means zero mutation.

### MTA-INSTALL-018 — Rollback identity was incomplete across process death

- **Observed audit defects:** kernel rollback could restore the wrong generation; death between WSL,
  kernel, Windows, and metadata swaps corrupted state; reverse rollback lacked a satisfiable initiating
  package identity.
- **Correction:** journal source/target releases and exact Windows/WSL/kernel/config anchors plus
  independently verified initiating package root/release/manifest hash before mutation. Fresh Repair
  classifies actual axes, compensates/finalizes, and publishes one rotated completed record.
- **Never repeat:** rollback is a forward-designed transaction, not improvised file reversal. Inject
  process death after every axis and before publish.

### MTA-INSTALL-019 — Interrupted import left a markerless owned distro

- **Observed:** death after `wsl --import` but before `/etc/switchtrade-distro.json` left the exact new
  distro markerless. Repair treated it as foreign and moved a legacy Windows tree before ownership was
  fully proven. A legacy rootfs also omitted the generic marker expected by the current builder.
- **Correction:** only a schema-3 fresh-install transaction still at `importing_distro`, with the exact
  recorded Lxss BasePath, may bootstrap a missing marker. Unreadable/malformed/foreign cases fail
  closed; orphan moves occur only after the whole recovery plan validates; packaging requires marker.
- **Never repeat:** missing, unreadable, malformed, foreign, and owned-incomplete are distinct states.

### MTA-INSTALL-020 — A candidate could self-authenticate or unknown could mean absent

- **Observed audit defects:** recovery could finalize missing/corrupt files; an unanchored WSL
  candidate could regenerate a manifest and authenticate itself; WSL enumeration failure was treated
  as distro absence.
- **Correction:** trusted complete Windows/WSL artifact manifests are anchored before exposure;
  unanchored candidates are discarded/restaged from the verified package; enumeration has an explicit
  unknown result that cannot advance or compensate.
- **Never repeat:** evidence generated by the candidate cannot establish the candidate's trust root.

### MTA-INSTALL-021 — Setup recovery behavior depended on operator guesses and extraction paths

- **Observed audit defects:** reopening after process death at import required guessing Repair; an
  unrelated `.previous` tree blocked recovery; re-extracting byte-identical setup changed path
  identity; default uninstall retained a distro the next install could not adopt coherently.
- **Correction:** original action and Repair enter the same valid recovery; verified successor package
  may compensate only an early fresh install; unrelated legacy trees move to a bounded recovery
  archive after ownership proof; manifest hash, not extraction path, binds identity; uninstall removes
  the owned distro and publishes `uninstalled`.
- **Never repeat:** UI exposes only actions valid for the inspected state. Users never choose a
  transaction algorithm by guesswork.

### MTA-INSTALL-022 — Burn passed a non-ASCII child-MSI log path and Windows Installer returned 1622

- **Observed:** the first real PC A upgrade attempt for source `0f163a22e6b8` stopped before installing
  the desktop MSI or runtime. Burn reported `0x80070656` / exit `1622`; rollback restored the existing
  `0.2.11` bundle and runtime. WSL remained stopped, the adapter remained Windows-owned, and no new
  SwitchTrade distro was registered.
- **Definitive cause:** the invoked bundle log was below the Korean user profile, so Burn derived the
  child MSI log there. Windows Installer opened a client stub log but returned 1622 before executing
  MSI actions. An administrative-install A/B probe of the exact same MSI and source path failed with
  the Unicode-profile log and completed with status 0 when only the log moved to an ASCII path. The
  portable source path, package bytes, MSI actions, reboot state, and directory ACL were thereby
  excluded.
- **Recovery/residue:** Burn completed its rollback and `0.2.11` remains the only installed product and
  WSL runtime. The failed logs and source-specific build remain evidence. The administrative probe
  installed no product; its disposable extraction directory is non-product residue pending explicit
  filesystem cleanup because this session's command policy rejected recursive deletion.
- **Never repeat:** never pass a user-profile-derived log path into Windows Installer on a non-ASCII
  profile. Burn and the provisioner retain their Unicode-safe logs; chained MSIs must omit automatic
  log-path variables unless an ASCII-safe launcher owns the path. Installed Unicode-path qualification
  must launch Setup without a custom `/log` override and inspect the bundle result plus Windows events.
- **Rejected correction:** authoring an absolute `Log/@Prefix` is invalid for this purpose; WiX split
  `C:\Windows\Temp\...` into `Prefix="C"` and a malformed extension in the compiled manifest. That
  candidate was never installed.
- **Source correction (2026-08-31):** all three chained MSIs now set empty `LogPathVariable` and
  `RollbackLogPathVariable`, the documented WiX mechanism for omitting those paths. Burn's main log
  and the provisioner's structured log remain enabled, and package validation inspects the compiled
  Burn manifest to prove no MSI receives an automatic locale-sensitive log path. A newly committed
  source identity, rebuilt bundle, default-command installation, and rollback/residue verification
  are still required.

## 8. Protocol and reverse-engineering failure lessons

These historical failures were valuable evidence, but none may be reintroduced as an “alternate”
path around ABC+D gates.

1. Station-ID direction was reversed in early native exchanges.
2. Required Net/Session message types were missing.
3. Parent/child T offsets were wrong.
4. K acknowledgement shape was wrong.
5. NI ownership/direction was wrong.
6. Rolling RFU tags were not advanced/validated correctly.
7. RFU C/A connect and selective-ACK ordering was incomplete.
8. Barrier initiation order was wrong.
9. Save-round counts were wrong.
10. LDN was ended before the avatar/scene transition completed, causing a post-room native error.
11. Movement used accumulated relative sleeps and jittered; absolute VBlank cadence was required.
12. A large “golden capture” was overinterpreted before channel and receiver-health limitations were
    understood.

Transport/protocol audit (`PRT-001` through `PRT-008`) also found peer-readiness races, reconnect
epoch confusion, lost advertisement after restart, sequence eviction/wrap errors, K-ACK backlog,
malformed-payload handling gaps, active decoder mutation risk, and unbounded shutdown/resources. The
shared prevention is attempt-bound opaque forwarding, generation-isolated queues, ordered bounded
deduplication and backpressure, deterministic replay/property/fuzz seeds, passive fail-closed decode,
and bounded shutdown. A decoder may observe but cannot mutate the tunneled payload.

Prevention: retain deterministic unit/replay tests for each protocol gate, label captured claims as
observed versus inferred, and never change a byte-level contract merely to suppress a live symptom.
Full trade, save, menu return, and graceful exit remain separate physical evidence.

## 9. Test-infrastructure failures

### MTA-QA-001 — Tests depended on ambient developer state

- **Observed audit classes (`QA-001` through `QA-006`):** no root CI; Windows-incompatible fixtures;
  dependency resolution from ambient environments; package output changed with local timestamps or
  prior build products.
- **Correction:** Windows/Linux CI, Python 3.12 locks, pinned .NET/PowerShell checks, ShellCheck and
  vulnerability audit, portable fixtures, offline wheelhouse validation, exact manifests, and
  deterministic archive metadata.
- **Never repeat:** a developer-machine pass is evidence only for that machine. Qualification records
  exact toolchain and artifact hashes; release builds begin clean and are reproducibility-checked.

### MTA-QA-002 — Harness tests were launched with an unqualified system interpreter

- **Observed:** on 2026-08-31, the first post-refactor unit run used `python -m unittest` from the
  ambient shell. Fifty-three relevant tests ran, but two pre-existing `StageSession` tests errored
  while importing `trio` because that system interpreter did not contain the repository's test
  dependencies. No WSL, USB adapter, relay room, endpoint, or Switch was touched.
- **Definitive cause:** the command did not first prove the interpreter and dependency closure even
  though `MTA-M7-007` and `MTA-QA-001` already forbade ambient-interpreter qualification.
- **Disproven alternative:** the two `ModuleNotFoundError` results are not evidence of a regression
  in `StageSession`; they occurred before either test exercised its subject.
- **Correction (2026-08-31):** the repository-qualified `.audit-venv` import probe passed and the full
  suite passed `537 passed, 3 skipped`. The canonical harness launcher performs the same dependency
  and module-origin preflight; installed immutable distribution remains open.
- **Never repeat:** before running repository tests, resolve the tracked/declared test environment
  and prove required imports. An ambient `python` result may be used only for syntax discovery and
  must never be reported as qualification evidence.

### MTA-QA-003 — New control-contract tests retained obsolete fixture assumptions

- **Observed:** in the same 2026-08-31 read-only unit run, three distributed-harness tests failed
  before hardware access: one used the non-UUID fixture `test-1` where the production control
  contract requires a UUID, one constructed a lifecycle without its `timeout`, and one still
  expected a heartbeat after a fake checkpoint returned synchronously.
- **Definitive cause:** production code and only part of the test fixture were migrated from
  blocking stdin prompts to the identity-bound control state machine.
- **Recovery/residue:** the tests used temporary files and fakes only; no relay room, WSL process,
  adapter ownership, PHY/interface, or recovery guard was created.
- **Correction (2026-08-31):** fixtures now use contract-valid identities, complete lifecycle state,
  and a real bounded wait before asserting heartbeat behavior. The focused control/P0/D suite passes.
- **Never repeat:** a contract migration is incomplete until every constructor, fake, boundary
  value, and negative test uses the new contract. Do not weaken production validation to make an
  obsolete fixture pass.

## 10. Agent and operator mistakes that caused avoidable work

### MTA-OPS-001 — Wrong or ambiguous bundle identity was analyzed

- The user once supplied the wrong package and explicitly stopped analysis. Bundle filenames and
  labels such as PC A/PC B are not authoritative.
- **Rule:** honor stop immediately; verify embedded timestamps, release/run/machine identity, and
  requested incident before drawing conclusions. If identity is absent, say so.

### MTA-OPS-002 — PC A/PC B identity appeared swapped

- A bundle uploaded from PC B appeared as PC A because persisted profile/source identity and the
  uploading computer were conflated.
- **Rule:** use an immutable machine ID plus explicit campaign role. Never derive machine identity
  from uploader, filename, display name, or “this computer.”

### MTA-OPS-003 — Absence of UI errors was treated as functional success

- A room-creation attempt produced no visible error, but the app had not detected or connected to the
  Switch.
- **Rule:** success requires positive gate evidence. Silence, timeout, a ready badge, or relay
  connectivity is not A/B/C success.

### MTA-OPS-004 — The user was sent between physically separated machines too early

- Repeated harness defects were discovered only after instructions to move between PCs, wasting time
  and trust.
- **Rule:** first place both PCs together. Prove source/release identity, exact command entry point,
  two-side pairing, no USB action before the barrier, P0, noninteractive continuation, cancellation,
  and recovery. Move devices only when the next unproven gate genuinely requires RF separation.

### MTA-OPS-005 — File deletion was attempted through computer control

- The user explicitly prohibited GUI/computer-control deletion because target selection can be
  inaccurate.
- **Rule:** list exact absolute targets first. Delete only user-authorized, resolved, bounded paths
  with one filesystem mechanism; verify targets remain under the intended directory. Never use broad
  globs, user-home roots, or cross-shell path composition. Report what was removed and recoverability.

### MTA-OPS-006 — Qualification source was made dirty by documentation work

- Local documentation edits triggered the distributed harness's source-clean gate.
- **Rule:** installed qualification uses a dedicated immutable clean worktree at the tagged source.
  Documentation and ongoing development stay in the main worktree. Do not bypass the clean-source
  check or delete legitimate user changes.

### MTA-OPS-007 — Recovery state was nearly treated as disposable test debris

- Reusing an invitation or deleting a state root would have destroyed the only exact cleanup
  authority for a failed run.
- **Rule:** never delete/bypass a state root to retry. Recover the old run, prove D/USB/authority
  terminal state, archive its redacted report, then create a new campaign root and invitation.

### MTA-OPS-008 — UI and process-control tools were assumed interchangeable

- A unified-exec session identifier was sent to a Codex terminal tab API, producing an unrelated blank
  terminal. Direct GUI executable invocation also gave an unhelpful blank exit-code result.
- **Rule:** use the tool that owns the process. To validate GUI exit, use `Start-Process -Wait
  -PassThru`; to continue a harness, use its explicit control command. Never infer control from a tab
  opening.

### MTA-OPS-009 — Private relay metrics were queried through the public path

- Public `/metrics` returned 403 because metrics are intentionally private.
- **Rule:** do not call this a relay failure. Ask the relay operator to query the private loopback
  endpoint and report exact counters without secrets.

### MTA-OPS-010 — Fix verification stopped at the changed component

- R6 fixed stdin but not dependency resolution; other earlier fixes validated source tests but not the
  installed runtime, real WSL, or physical radio.
- **Rule:** after every fix, rerun the full composed boundary and its inverse/cleanup path. The final
  command and artifact—not the edited function—is the test subject.

### MTA-OPS-011 — Early two-PC results were interpreted beyond what was exercised

- **Observed:** the first two attempts errored while no adapter was selected. A later attempt produced
  only a timeout, and neither Switch created nor searched for a room. It was tempting to call the
  system normal because no other app error appeared.
- **Correct boundary:** the first cases prove only configuration preflight behavior. A run with no
  Switch host/search does not exercise room detection, AP creation, association, RFU relay, or trade.
  A timeout is expected only when its named wait condition was deliberately left unsatisfied; it is
  not a functional pass.
- **Never repeat:** record `not tested` for every unexercised gate and require a positive event for
  every claimed stage.

### MTA-OPS-012 — Source fixes and installed bits were conflated

- **Observed:** changes could exist in the repository while the currently installed app/runtime still
  contained an older build, leading to “was the update not applied?” after the same failure recurred.
- **Rule:** before every installed test, read the installed release manifest, Windows payload hash,
  WSL runtime identity, and source commit reported by the runner. Never infer installation from a
  successful build, tag, GitHub upload, or visible version label.

### MTA-OPS-013 — A harness failure was declared isolated from production too early

- **Observed risk:** several R-series failures were in orchestration/launch context, but a generic
  endpoint failure can also hide a Direct A/B or D production defect.
- **Rule:** call a defect “harness-only” only after the same immutable low-level component passes its
  direct contract and the failure is reproduced entirely outside it. Otherwise state the affected
  boundary and uncertainty. Harness code excluded from production still matters when it is the only
  release-qualification evidence path.

### MTA-OPS-014 — A PowerShell discovery command failed because regex and shell quoting were mixed

- **Observed:** on 2026-08-30, the first read-only harness source search failed at parse time with
  `Unexpected token ')'`. No subprocess, test, hardware, or repository mutation started.
- **Definitive cause:** a large regex containing a quote alternative was embedded in a double-quoted
  PowerShell command string; `\"` was treated as a string boundary rather than a safe regex literal.
- **Rule:** pass search patterns as single-quoted PowerShell literals or separate `rg -e` arguments;
  keep shell parsing and regex parsing independent. After a parse failure, verify no command ran
  before issuing a corrected read-only query.

### MTA-OPS-015 — Repository entry-point discovery assumed a file existed

- **Observed:** on 2026-08-30, a read-only command attempted to open a root `pyproject.toml` that the
  repository does not contain. The independent searches in that command completed; no test, process,
  hardware action, or repository mutation resulted from the missing-file read.
- **Definitive cause:** packaging/entry-point layout was inferred from a conventional filename before
  the tracked file inventory was checked.
- **Rule:** use `rg --files`/`git ls-files` to resolve an exact existing path before reading a
  repository entry point. A conventional project layout is not evidence of this repository's layout.

### MTA-OPS-016 — Python module execution was assumed to imply `__main__.py`

- **Observed:** on 2026-08-30, a read-only packaging inspection attempted to open
  `switchtrade/__main__.py`, which is not present. Earlier files in the same command were read
  successfully; no test, build, hardware action, or additional mutation occurred.
- **Definitive cause:** the existence of `python -m switchtrade.connection.distributed_harness` was
  incorrectly generalized into a package-root `python -m switchtrade` entry point.
- **Rule:** distinguish a submodule entry point from a package entry point. Only advertise or inspect
  a command after the exact module/file and its packaging inclusion are confirmed by tracked-file
  inventory.

### MTA-OPS-017 — Missing-file discovery mistake recurred after its prevention rule was written

- **Observed:** on 2026-08-30, a later read-only `rg` command named
  `tests/test_p0_harness.py`, which is not in the tracked inventory, and produced an OS file-not-found
  warning. The valid search targets still completed; no test, subprocess, hardware action, or other
  mutation occurred.
- **Definitive cause:** a conventional test filename was appended from memory instead of limiting the
  command to the previously enumerated `tests/test_p0_foundation.py` or the existing directory.
- **Rule:** after a missing-path incident, do not manually type another inferred file path in the same
  task. Search the existing directory or programmatically filter the tracked inventory. Treat a
  repeated prevention-rule violation as a process defect, not harmless shell noise.

### MTA-OPS-018 — Documentation patch used an unverified context sentence

- **Observed:** on 2026-08-31, an `apply_patch` intended to add the first harness-test incidents
  failed verification because its anchor paraphrased `MTA-QA-001` instead of matching the actual
  text. The patch was atomic, so no partial change occurred.
- **Definitive cause:** the target section was not read immediately before constructing the patch.
- **Rule:** inspect the exact nearby lines before patching a long source-of-truth document. A remembered
  paraphrase is not a valid patch anchor, even when the intended meaning is equivalent.

### MTA-OPS-019 — The same unverified documentation-anchor mistake recurred

- **Observed:** on 2026-08-31, the next incident patch again failed atomically because it used a
  remembered cancellation-rule sentence instead of the exact text immediately visible in the
  source-of-truth document. No partial write occurred.
- **Definitive cause:** the `MTA-M7-008` section was not inspected before constructing the patch,
  despite the newly written `MTA-OPS-018` rule.
- **Rule:** after any patch-context failure, stop constructing anchors from memory entirely. Read the
  exact target range first and anchor only on text copied from that output.

### MTA-OPS-020 — One patch attempted both delete and add for the same document

- **Observed:** on 2026-08-31, the handoff rewrite patch was rejected before mutation because one
  `apply_patch` payload targeted the same path with both `Delete File` and `Add File` operations.
- **Definitive cause:** a whole-file rewrite was expressed using an unsupported combined patch form.
- **Rule:** for an intentional tracked-file replacement, use one verified `Update File` patch or two
  separately verified delete/add operations. Never assume a patch transport accepts two operations
  for the same path.

### MTA-OPS-021 — A multi-file patch used an unverified test anchor

- **Observed:** on 2026-08-31, a state-root preflight patch was rejected atomically because its test
  insertion anchor did not match the exact existing assertions. The production-file edit in the same
  patch was therefore also not applied.
- **Definitive cause:** the production target was inspected, but the test insertion point was inferred
  instead of copied from the just-read test range.
- **Rule:** every file in a multi-file patch needs its own verified context. If only one target has
  been inspected, patch that target alone and inspect the next target before editing it.

## 11. Required preflight checklists

### Any code or documentation change

- Read this file and the relevant ABC+D/TODO documents.
- Check `git status`; preserve unrelated/user changes.
- Identify whether the change affects a normative contract, open work, or only historical record.
- Update behavior docs and this incident register in the same commit when a new failure is learned.
- Run the smallest relevant checks, then inspect the diff for secrets, personal paths, stale version
  claims, and accidental qualification-source changes.

### Any local or two-PC qualification

- Both PCs use the same exact source SHA, installed release ID, runtime ID, relay contract, invitation
  version, test ID, action, and complementary roles.
- The exact final command proves imports, WebSocket, stdin/control mechanism, WSL cwd, P0 probe, and
  recovery before room creation.
- Previous sessions are recovered; state roots are retained; Windows owns both adapters initially.
- Both sides show `coordination_paired`, the same test ID, and `usb_attached=false` before the exact
  identity-bound Continue command.
- No Switch is touched before its explicit checkpoint; no device is moved apart before automated
  gates pass.
- Stop on the first mismatch. Do not “see what happens next.”
- End by proving report terminal state, room finalization, endpoint absence, interface/PHY absence,
  radio quiescence, USB prior-state restoration, and recovery-guard removal.

### Any installer or release

- Clean worktree/tag; coherent app/MSI/runtime/relay versions; preserved UpgradeCodes.
- Forced clean rebuild; extracted finished installer payload hash verification.
- Exact installed entry point tested from Explorer/default cwd and a non-ASCII user path.
- Install, upgrade, same-version Repair, interrupted recovery, uninstall, reinstall, and reboot resume.
- Runtime/kernel/module/firmware hashes and release manifest agree on both Windows and WSL.
- No prior broken artifacts remain published as current; deletion is explicit and independently
  verified.
- Do not publish until installed-runtime qualification passes. Source tests alone are insufficient.

### Any relay deployment

- Confirm actual supervisor/topology; deploy exact source/import closure.
- One intended worker, health ready, storage writable, smoke tests in both roles.
- Private metrics: no unexplained live/admitted RFU attempts or active credentials.
- Late-peer, reconnect, ordered-frame, restart, and terminal cleanup behavior match the client
  contract.
- Preserve evidence before cleanup; do not infer individual-room causes from aggregate counters.

## 12. Current open failure-prevention work

The following remain open even though source corrections or workarounds allowed safe recovery:

1. Qualify the explicit-Windows-cwd probes and identity-bound control/cancellation path from a new
   installed immutable build on both PCs (`MTA-M7-005`, `MTA-M7-006`, `MTA-M7-008`, `MTA-M7-009`).
2. Build and validate the new release's separate M7 qualification kit. Packaging support now emits
   one independently hashable launcher/interpreter/dependency/source closure; this item closes only
   after that exact kit passes `verify` on both PCs (`MTA-M7-007`).
3. Complete the installed two-PC/two-Switch M7 qualification only after the first two are closed.
5. Investigate credentialless `waiting_for_complementary_role` rooms by ordered event history without
   breaking reconnect grace (`MTA-RELAY-006`).
6. Continue the critical and post-release work in `FUTURE_TODO.md`; this document prevents recurrence
   but does not replace implementation or acceptance work.

## 13. Update protocol

Every new incident gets a stable `MTA-<AREA>-NNN` entry with:

- exact observed symptom and first stable failure code;
- run/release/source identity when safe to retain;
- last passed gate and whether hardware/Switches were touched;
- definitive cause or an explicit `investigating` label;
- disproven alternatives;
- recovery result and residue state;
- correction commit/status;
- a concrete “Never repeat” rule and an automated/installed/physical acceptance gate.

Never rewrite history to make a failed candidate look successful. Add a correction beneath the old
record, preserve rejected evidence as rejected, and update the open-work section. This document is
the memory of failure; the ABC+D architecture is the design authority; the TODO is the work ledger;
code and tests are the current implementation evidence.

## 14. Maintained evidence index

Use these sources to audit or extend an entry without relying on conversation memory:

- [Development History](DEVELOPMENT_HISTORY.md): early capture, protocol, VM/WSL, radio, installer,
  and product corrections.
- [Known Issues](KNOWN_ISSUES.md): field-observed STB defects and physical acceptance boundaries.
- [Full-stack Audit](AUDIT_REPORT.md) and [Audit Validation](AUDIT_VALIDATION.md): P0/P1 registers,
  cross-layer corrections, regression evidence, and unproven external gates.
- [Production Debug Menu Design](79-production-debug-menu-design-20260828.md): diagnostic intent and
  limitations.
- [ABC+D Architecture](80-abc-connection-architecture-20260829.md): normative ordered components and
  readiness/cleanup gates.
- [Rewrite Plan](81-abcd-orchestration-rewrite-plan-20260829.md) and milestone records
  [M0](82-abcd-milestone-0-baseline-20260829.md),
  [M1](83-abcd-milestone-1-coordinator-20260829.md),
  [P0](84-abcd-milestone-2-p0-source-20260829.md),
  [Direct A](86-abcd-milestone-3-direct-a-20260829.md),
  [Direct B](87-abcd-milestone-4-direct-b-20260829.md),
  [C0/C1](88-abcd-milestone-5-c0-c1-20260830.md),
  [C2](89-abcd-milestone-6-c2-20260830.md), and
  [D](90-abcd-milestone-7-authority-d-checkpoint-20260830.md).
- [M7 Physical Harness](91-abcd-milestone-7-physical-harness-20260830.md) and
  [M7 Safe Pairing/Recovery Correction](92-m7-safe-pairing-and-recovery-fix-20260830.md): distributed
  test contract, rejected runs, definitive causes, and current physical boundary.
- [Future TODO](FUTURE_TODO.md): current implementation and qualification debt.
- Installer [issue register](installer/ISSUE_REGISTER-20260827-installer-engine.md),
  [error catalog](installer/ERROR_CATALOG-20260827.md), and
  [recovery runbook](installer/RECOVERY_RUNBOOK-20260827.md): detailed setup transaction evidence.

Raw support bundles and run recovery files remain local/private. They may substantiate an entry but
must not be added to the repository.
