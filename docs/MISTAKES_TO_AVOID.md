# Mistakes to Avoid

> **Authority:** This is the SwitchTrade source of truth for observed failures, disproven
> assumptions, operator/agent mistakes, and the guardrails that prevent their recurrence.
> Read this document before changing, testing, packaging, installing, deploying, recovering, or
> deleting anything in this repository or an installed SwitchTrade environment.
>
> **Last updated:** 2026-09-01
> **Current integration target:** `main`; the completed feature line is being fast-forwarded from
> `codex/m7-safe-pairing` and obsolete audit/feature branches are intentionally retired.
> **Current published immutable release:** `v0.2.14-beta.1`; its exact source is the tag target.
> **Current installed validation candidate:** `0.2.19-beta.1`, release ID `beta-f49938017c36`, exact
> source `f49938017c364966ee91d989263cb7fb2df66a47`. This is not yet M10 physical acceptance.

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

### MTA-M7-014 — Qualification verification mutated its own immutable kit

- **Observed:** PC A successfully upgraded the unreleased `0.2.12-beta.1` candidate from source
  `1096263ba19a`; installed software health, release/runtime identity, kernel, hardware selection, and
  Windows USB ownership all passed. The extracted qualification kit then passed its first `verify`
  command but the immediately following `preflight` stopped at
  `DISTRIBUTED_QUALIFICATION_INTEGRITY_FAILED`. No distributed room was created, USB was not attached,
  and no Switch was touched.
- **Definitive cause:** the packaged launcher invoked CPython without `-B`. Its environment probe
  imported standard-library, dependency, and SwitchTrade modules and wrote unmanifested
  `__pycache__/*.pyc` files inside the supposedly immutable kit. The next launcher invocation correctly
  rejected those extra files. The package validator had executed `verify` only once in a disposable
  extraction, so it never tested repeated use of the same kit.
- **Disproven alternatives:** every manifest hash was valid before the first invocation; packaged
  source, interpreter, dependency versions, installed release ID, WSL marker, and adapter selection
  matched. Installed runtime verification passed independently. This was not an ABC+D engine, relay,
  radio, Unicode-path, or Switch failure.
- **Recovery/residue:** the rejected kit created only bytecode beneath its own qualification directory.
  There is no runner state, relay room, endpoint, PHY/interface, USB lease, or recovery guard to clean.
  The healthy but unreleased `0.2.12` installation remains a predecessor for the corrected installer
  upgrade; it must not be published or sent to PC B.
- **Never repeat:** an immutable qualification executable must be operationally read-only, not merely
  hash-valid at extraction. Run packaged Python with bytecode writes disabled, exclude all cache files
  at build time, and run package verification repeatedly in the same extracted directory before any
  installation or release.
- **Source correction (2026-08-31):** the launcher now passes `-B` to every Python process, the kit
  builder removes and rejects Python cache artifacts, and package validation executes two consecutive
  `verify` calls and proves no cache appeared. The corrected candidate advances to `0.2.13-beta.1` so
  Windows performs an unambiguous versioned upgrade from the rejected local `0.2.12` installation.

### MTA-M7-015 — A line break split the WSL command from its Linux marker probe

- **Observed:** the unreleased PC A `0.2.13-beta.1` installation passed software health and two
  consecutive immutable-kit `verify` calls. Its first read-only `preflight` then emitted a PowerShell
  `Get-Content` error for `C:\opt\switchtrade\.switchtrade-release.json` before returning a stable
  harness code. No room, runner state, endpoint, USB attachment, radio resource, or Switch action had
  started.
- **Definitive cause:** runtime auto-discovery invoked `wsl.exe ... --` at the end of one PowerShell
  line and placed `cat ...` on the following line. PowerShell ended the native command at the newline
  and resolved `cat` as its own `Get-Content` alias, so the Linux path was reinterpreted as a Windows
  path. The subsequent explicit-distro probe already used a correctly typed argument array, proving
  the split inline invocation was the only failing path.
- **Disproven alternatives:** source, release, manifest, interpreter, dependency, installed runtime,
  kernel, adapter selection, and USB ownership identities all matched. WSL was installed and its
  release marker existed; the probe never asked WSL to read it. This was not an ABC+D runtime or radio
  failure.
- **Recovery/residue:** the failed operation was read-only and stopped during runtime discovery. The
  `0.2.13` local installation remains healthy but rejected for release; it must not be published or
  copied to PC B.
- **Never repeat:** never express a native subprocess protocol as parser-dependent inline tokens.
  Inventory and every per-distro command must go through one captured executable-plus-argument-array
  boundary, and raw `@(& wsl.exe ...)` forms are forbidden in the canonical launcher.
- **Source correction (2026-08-31):** WSL inventory and marker reads now use `Invoke-Captured` with
  explicit arrays, failures map to stable inventory/identity codes, and regression rejects raw WSL
  invocations. Disposable package validation now imports the candidate runtime and runs the packaged
  launcher's auto-discovery `preflight` before uninstalling it. The successor advances to
  `0.2.14-beta.1`; installed acceptance still requires repeated `verify` followed by `preflight`
  before publication.

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

### MTA-RADIO-013 — Exact sysfs validation rejected the canonical USB device path

- **Observed (Q3 run `q3-radio-20260831-01`):** Windows attached only the selected second
  RTL8192EU and the attach delta bound `/sys/devices/platform/vhci_hcd.0/usb1/1-1`, but the new
  exact probe reported `absent`. The run failed `P0_LINUX_ENUMERATION_TIMEOUT`; cleanup then
  correctly refused detach with `P0_RADIO_NOT_QUIESCENT` because the same false probe could not
  prove device ownership. No worker, C stage, or Switch operation started.
- **Definitive cause:** `/sys/bus/usb/devices/1-1` is a symlink. `Path.resolve()` correctly returns
  the canonical `/sys/devices/...` target, while the first Q3 implementation incorrectly required
  that canonical path to remain textually under `/sys/bus/usb/devices`.
- **Recurrence (Q3 run `q3-radio-20260831-02`):** the Python probe had been corrected, but the
  shell selector still imposed the obsolete raw `/sys/bus/usb/devices/*` prefix before comparing
  canonical identities. Both exact leases passed, then the first worker exited with
  `invalid exact USB device path`. Radio cleanup still completed B then A with both prior states
  verified. The worker-cleanup projection also falsely said cleanup failed because closing an
  already-dead worker's stdin raised `BrokenPipeError`.
- **Disproven alternatives:** usbipd attach succeeded for the exact Windows InstanceId; WSL listed
  exactly one matching identity; there was no second attach, driver worker, relay, or hardware
  failure. The defect was solely the new Q3 canonical-path membership test.
- **Recovery:** the private exact identity was preserved. After membership was changed to compare
  against the canonicalized USB inventory, the exact probe returned `present/matches=1/up=0`; the
  one selected adapter was detached through `UsbLease.from_recovery`, Windows and Linux absence were
  both verified, and both cards ended Windows-owned with no recovery file.
- **Never repeat:** validate a canonical sysfs identity by membership in the canonicalized inventory,
  not by its textual parent prefix. A symlink-to-`/sys/devices` fixture is a mandatory regression
  before any real attach. Audit every consumer (Python probe, shell selector, worker attestation,
  and recovery), and treat an already-closed control pipe as idempotent cleanup. Unknown exact
  evidence must continue to block broad or guessed detach.

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

### MTA-INSTALL-023 — One transient Lxss lookup falsely declared a healthy runtime corrupt

- **Observed:** on 2026-08-31, PC A's installed `0.2.14-beta.1` desktop stopped before launching the
  local control service and displayed `SOFTWARE_NOT_READY · Installed runtime state is corrupt.` No
  new control startup log was created and no USB, endpoint, PHY, or temporary interface was acquired.
- **Definitive cause:** `ProvisioningEngine.InspectAsync` successfully enumerated WSL names but ignored
  that result for an active runtime. It classified the runtime solely through one direct Lxss registry
  lookup. That lookup returned no registration in the failing snapshot, which is the only code path
  capable of producing the observed `corrupt` state. The desktop then presented Repair as if durable
  damage had been proved.
- **Disproven alternatives:** the installed release manifest, active-runtime pointer, release ID,
  control contract, kernel file and hash, WSL distro identity, Python/control payload, and relay URL
  all agreed. Repeated read-only `status`, installed `verify-software`, real WSL boot, and the
  `app-readiness.v1` endpoint passed without Repair. The adapter remained shared but Windows-owned.
- **Correction:** read-only status now reconciles the exact active name across the WSL CLI inventory
  and Lxss registry projection. Either positive view prevents a false corruption result; if both are
  absent, one bounded second observation is required before `corrupt` is returned. Executable health
  remains a separate real control-process readiness check. Contract tests cover a transient omission
  from either view, a simultaneous one-snapshot omission, and durable absence from both.
- **Never repeat:** a single transient discovery snapshot never authorizes Repair guidance or a
  corruption label. Distinguish discovery disagreement, durable absence, and executable health, and
  run the installed desktop entry point—not only provisioner `verify`—before publishing a release.
- **Status:** source correction and focused provisioner regression pass; a new immutable package,
  installed desktop cold-launch/relaunch test, non-ASCII-profile check, and two-PC upgrade remain the
  release acceptance gate.

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
- **Recurrence (2026-09-01, `0.2.15-beta.1` packaging preflight):** the first full-suite command again
  used ambient `python`; collection stopped on `test_direct_a_stage.py` and
  `test_direct_b_stage.py` with `ModuleNotFoundError: trio`. Desktop and Provisioner checks passed in
  parallel, and no installer, WSL, relay, USB, endpoint, or Switch mutation occurred. The exact
  `.audit-venv` interpreter then proved `trio 0.33.0` and `pytest 8.3.5` before the retry. Release
  preflights must print this import probe before invoking pytest, not merely rely on shell PATH.

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

### MTA-QA-004 — A manually typed Base64 fixture had the wrong decoded length

- **Observed:** the first Q2 focused test stopped before relay, WSL, USB, worker subprocess, or Switch
  activity because the new worker-config fixture failed its required 32-byte payload check.
- **Definitive cause:** the literal Base64 string decoded to 29 bytes. The expected assertion said 32
  bytes, but the fixture had been typed manually instead of being generated from the asserted source
  bytes.
- **Correction:** construct encoded fixtures with `base64.b64encode(b"x" * 32)` so the source and
  expected length have one authority. Keep the production length validation unchanged.
- **Never repeat:** do not hand-author encoded binary test vectors unless their encoded form is the
  contract under test. Generate them from explicit source bytes and separately retain malformed and
  wrong-length negative fixtures.

### MTA-QA-005 — A module worker relaunched `__main__` instead of its canonical module

- **Observed:** Q2 run `q2-normal-20260831-01` created and admitted a private relay attempt, then both
  workers exited before writing status. Their bounded logs contained `Error while finding module
  specification for '__main__'`; the parent reported `CD_WORKER_EXITED` at `Q2_WORKER`.
- **Definitive cause:** the coordinator was itself invoked with `python -m`, so its runtime
  `__name__` was `__main__`. It reused that dynamic value in the child `-m` argument instead of the
  canonical `switchtrade.connection.dual_adapter_cd_harness` module name.
- **Recovery/residue:** the coordinator closed the private room, removed credential/config recovery
  files, and both Python workers were absent. Both RTL8192EU devices remained Windows-owned and
  unattached. No Switch was touched. The pre-existing SwitchTrade WSL distro was running, but Q2
  launched no WSL command and made no radio mutation.
- **Additional report defect:** although resource cleanup was proved, the failed-run report left
  `cleanup_status=pending`; every terminal functional outcome must receive a separate terminal cleanup
  result.
- **Correction gate:** child launch uses one constant canonical module identity; an automated launch-
  argv test rejects `-m __main__`; terminal report finalization independently sets cleanup to verified
  or failed. Repeat Q2 only after the focused suite passes.
- **Never repeat:** never derive a subprocess entry point from runtime `__name__`. Package and validate
  one canonical module/executable identity, and test the exact parent-as-`-m` composition before a
  hosted run.

### MTA-QA-006 — Q2 generated a second run ID after relay admission

- **Observed:** Q2 run `q2-normal-20260831-02` launched both canonical worker modules, but both failed
  `C_AUTHENTICATION_FAILED` at `C0_AUTHENTICATED` with the same bounded detail hash. Neither worker
  passed a C gate.
- **Definitive cause:** the coordinator generated one UUID per P0 attestation and then `_side_config`
  generated a different UUID for each WebSocket launch. The relay correctly requires the launch
  header's run ID to equal the member's admitted P0 run ID and rejected both connections with 4403.
- **Disproven alternatives:** hosted HTTPS and WebSocket health were ready, `rfu-tunnel.v2` was
  advertised, the attempt was admitted, the canonical child module launched, and both failures were
  symmetric before peer readiness.
- **Recovery/residue:** cleanup was verified: the private room closed, credential/config recovery was
  removed, both worker PIDs were absent, no USB or WSL command ran, both radios remained Windows-owned
  and unattached, and no Switch was touched.
- **Correction gate:** create each immutable side identity once, derive its P0 attestation and worker
  config from that same record, and add a unit assertion that P0 run/stage identity equals the exact
  child launch identity before another hosted run.
- **Never repeat:** identities are values, not labels to regenerate in each layer. Construct one side
  identity record and project every attestation, config, launch, status, C2, and D payload from it.

### MTA-QA-007 — Synthetic qualification incorrectly requested a completed trade outcome

- **Observed:** Q2 run `q2-normal-20260831-03` passed ordered C0/C1, mutation-free status reads,
  one-sided activation blocking, the current-generation C2 barrier, and bidirectional synthetic RFU.
  D1 then returned `state_conflict`; the parent retained `C_SYNTHETIC_RFU_PROVEN` as the last gate.
- **Definitive cause:** the harness requested D outcome `completed`. The normative relay contract
  permits `completed` only when `last_passed_gate` is the physical `C_TRADE_COMPLETE`. Existing relay
  smoke correctly uses `canceled` for a successful synthetic diagnostic, but the new harness did not
  reuse that established rule.
- **Disproven alternatives:** both workers had already proved the real hosted tunnel and byte-exact
  synthetic payloads; the rejection occurred synchronously in `begin_d_closing` before worker close.
- **Recovery/residue:** cleanup was verified, the room and credentials were retired, both worker PIDs
  were absent, and no WSL, USB, radio, or Switch action occurred.
- **Correction gate:** a successful Switchless diagnostic freezes functional success locally but
  requests authoritative D outcome `canceled` with `C_SYNTHETIC_RFU_PROVEN`; tests assert that the
  relay attempt terminalizes canceled while the diagnostic report passes only after verified cleanup.
- **Never repeat:** authority outcomes retain their normative meaning. Synthetic evidence never
  impersonates `C_TRADE_COMPLETE`, and an application-level diagnostic pass is distinct from the
  authority's no-trade canceled outcome.

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
- **Recurrence (2026-08-31, Q2 discovery):** a source search named an assumed root
  `rfu_tunnel_v2` directory even though the preceding tracked inventory did not contain that path.
  `rg` reported only the missing path while valid `switchtrade/connection` and `relay` searches
  completed. No worker, relay mutation, WSL process, USB action, or Switch interaction started.
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

### MTA-OPS-022 — The verified-anchor rule was violated again during the qualification correction

- **Observed:** on 2026-08-31, the first attempted correction for `MTA-M7-014` combined code, tests,
  version, and documentation in one patch and named an exact `0.2.12-beta.1` line that was not present
  in the handoff document. `apply_patch` rejected the complete patch atomically; no code or document
  received a partial edit.
- **Definitive cause:** a repository-wide search result was treated as if every listed target contained
  the same version literal, despite the prior `MTA-OPS-021` rule requiring per-file verified context.
- **Rule:** after any repeated context failure, do not use a multi-file patch for that correction.
  Patch only the exact file and range just displayed, verify it immediately, then inspect the next
  target. An atomic rejection prevents corruption but does not excuse the process failure.

### MTA-OPS-023 — Read-only shell expressions were not made PowerShell-safe

- **Observed:** on 2026-08-31, one diagnostic `Select-String` call used an invalid hand-escaped regular
  expression, and a later annotated-tag verification passed Git's `^{}` peel syntax through
  PowerShell without quoting it. Both commands failed before returning their intended read-only
  result. The searches were repeated with `rg`, and the tag target was independently confirmed with
  `git rev-list -n 1 refs/tags/v0.2.14-beta.1` as
  `f57038e7e38ffdd0f79c24e0c06cc213890a9303`.
- **Definitive cause:** shell-specific parsing rules were ignored while constructing ad hoc read-only
  commands, despite simpler literal-safe commands being available.
- **Rule:** use `rg -F` for literal text whenever regex is unnecessary. In PowerShell, verify an
  annotated tag with the full `refs/tags/<tag>` form and `git rev-list -n 1`; do not pass unquoted Git
  peel expressions. A read-only failure cannot corrupt state, but it still consumes time and must not
  be normalized as harmless noise.

#### Recurrence (2026-09-01, WSL manifest diagnosis)

- **Observed:** an ad hoc PowerShell-to-`bash -lc` diagnostic over-escaped an `awk` expression and
  failed with `unexpected character '\\'`. It was read-only and changed no repository, package,
  WSL, USB, relay, or installed state.
- **Correction:** the manifest bytes and line endings were inspected directly from PowerShell, then
  the production consumer was corrected without relying on the failed compound diagnostic.
- **Permanent guard:** do not embed a quoted `awk` program through two shell parsers for a fact that
  either shell can inspect directly. Prefer a literal-safe single-shell command, and split
  cross-shell diagnostics at the process boundary.

### MTA-OPS-024 — A combined desktop stop/relaunch command was rejected before execution

- **Observed:** during the 2026-08-31 `SOFTWARE_NOT_READY` investigation, one compound PowerShell
  command combined graceful window close, a forced-process fallback, application relaunch, readiness
  polling, log reads, and USB inspection. The execution boundary rejected it before any mutation.
- **Definitive cause:** too many lifecycle actions and a forced fallback were bundled into one opaque
  command when the normal application close path was both safer and independently verifiable.
- **Rule:** application lifecycle qualification uses one observable transition per step: normal UI
  close, process/listener absence proof, launch, then readiness proof. Never combine a forced kill
  fallback with launch and validation in one command.

### MTA-OPS-025 — An accessibility close click was attempted without usable geometry

- **Observed:** the first normal-close attempt selected the correct SwitchTrade accessibility element,
  but the input helper returned `coordinate input geometry is unavailable`; the window remained open.
  A fresh screenshot-backed observation followed by `Alt+F4` closed it normally, and process, listener,
  WSL, and USB cleanup were then verified.
- **Definitive cause:** the accessibility tree exposed a close-button index without actionable input
  geometry. The selection was valid, but that observation type could not support the requested click.
- **Recurrence (2026-09-01):** the standalone UI walkthrough selected the accessibility index for
  **Create a Trade Room**, but the same helper returned `coordinate input geometry is unavailable`.
  The result was treated as unknown and no second index click was attempted; a fresh screenshot-backed
  observation was required before any coordinate action. No backend, WSL, relay, USB, or production
  process was involved.
- **Rule:** after any UI input failure, assume the outcome is unknown, re-observe, and do not reuse the
  index. For a standard window close, prefer a freshly targeted `Alt+F4` when accessibility geometry is
  unavailable; never escalate directly to forced termination.

### MTA-OPS-026 — The one-transition lifecycle rule was violated again during adapter discovery

- **Observed:** on 2026-08-31, a second-adapter discovery attempt again combined application launch,
  readiness polling, and hardware inventory in one PowerShell command. The execution boundary rejected
  the command before SwitchTrade, WSL, USB/IP, or the repository changed state.
- **Definitive cause:** the already-recorded `MTA-OPS-024` rule was read too late and a convenient
  compound command was treated as harmless because the intended final operation was read-only.
- **Correction:** the installed application was launched as one explicit transition; readiness and
  inventory were then queried separately. Both adapters remained Windows-owned and unattached.
- **Never repeat:** read this document before constructing any lifecycle command. Launch, readiness,
  and inventory are separate operations even when the final objective is discovery. A policy rejection
  is evidence that no mutation occurred, not permission to repeat the same command shape.

### MTA-OPS-027 — Windows wildcard paths were passed directly to `rg`

- **Observed:** during the same read-only source inspection, path arguments containing wildcard
  filenames were passed to `rg` under PowerShell and produced invalid-filename errors. No test,
  subprocess, hardware action, or repository mutation started from that command.
- **Recurrence (2026-08-31, Q0/Q1):** while checking whether JSON Schema validation was already a
  dependency, `requirements*.txt` was again supplied as an `rg` path. The command failed read-only
  before returning search results; the qualified test suite, USB ownership, WSL, and source files were
  unchanged. This recurrence proves that merely documenting the shell rule is insufficient unless
  every search command is constructed from an existing directory plus explicit `--glob` filters.
- **Recurrence (2026-09-01, M8/M9 audit):** the same `requirements*` wildcard was again placed in an
  `rg` path list while auditing schema dependencies. PowerShell returned an invalid-filename error;
  the remaining explicit paths were still searched and no source, process, WSL, USB, relay, or test
  state changed. The recurrence happened despite this document having been read, so the command-shape
  prevention must be applied mechanically rather than recalled after construction.
- **Definitive cause:** shell wildcard expansion was assumed instead of using ripgrep's own file
  filtering contract, repeating the shell-safety class documented by `MTA-OPS-023`.
- **Correction:** searches now name an existing directory and use `rg --glob` for file selection.
- **Never repeat:** on Windows, never pass an inferred or wildcard filename as an `rg` path. Resolve
  paths from `rg --files`, or search an existing directory with one or more explicit `--glob` filters.

### MTA-OPS-028 — A read-only control API route and projection were guessed

- **Observed:** a final adapter-inventory recheck queried an assumed `/api/v1/hardware` route and
  received 404. The corrected route was then projected through an assumed `adapters` property even
  though its contract uses `devices`, yielding null display fields. Neither request launches work or
  changes hardware selection, sharing, attachment, or repository state.
- **Definitive cause:** an earlier successful response was recalled semantically instead of resolving
  the exact route and response model from source before use.
- **Correction:** source inspection identified `GET /api/v1/hardware/devices`; its unmodified JSON
  response then proved two distinct supported adapters, both Windows-owned and unattached.
- **Never repeat:** discover the exact registered route and DTO before calling a local API. Inspect the
  raw response once before projecting fields, and never interpret a projection error as product or
  device failure.

### MTA-OPS-029 — Failure evidence inventory was read and then ignored

- **Observed:** after Q2 worker launch failed, one combined read-only command first enumerated the run
  directory and proved it contained only the parent report and two worker logs, but then attempted to
  read two nonexistent `status.json` paths. PowerShell returned file-not-found errors; no cleanup,
  process, relay, WSL, USB, or source mutation resulted.
- **Definitive cause:** expected artifacts from the design were appended to the command before the
  actual enumerated inventory was evaluated, repeating the path-assumption class in `MTA-OPS-017`.
- **Never repeat:** evidence inspection is two commands: enumerate exact existing paths, evaluate that
  result, then read only returned paths. Never combine discovery with reads of expected outputs after a
  failure precisely because missing outputs are part of the evidence.

### MTA-OPS-030 — Test module filenames were inferred instead of enumerated

- **Observed:** during the Q3 source audit, read-only `Get-Content` calls targeted
  `tests/test_radio_worker.py` and `tests/test_wsl_radio_prepare.py`; neither file exists because
  those tests live in `test_p0_foundation.py` and `test_product_foundation.py`. No test, hardware,
  process, or source mutation resulted from the failed reads.
- **Definitive cause:** component names were converted into plausible test filenames without first
  using `rg --files`, repeating the path-assumption class in `MTA-OPS-017` and `MTA-OPS-029`.
- **Correction:** the test inventory was enumerated and the exact existing files were read.
- **Never repeat:** resolve every unfamiliar test/document path with `rg --files` before reading it;
  semantic component names are not filesystem evidence.

### MTA-OPS-031 — A long campaign loop was interrupted after its next child had already started

- **Observed (Q6 campaign `q6-30-cycle-20260831-01`):** the user reduced the requested repetition
  count from 30 to 10 after six cycles. The parent PowerShell loop was sent Ctrl+C immediately after
  cycle 6 reported, but cycle 7 had already attached both radios. The console process ended before
  the child harness could publish terminal cleanup, leaving both exact radios WSL-owned. Cycles 1-6
  remained valid; cycle 7 was rejected and never counted.
- **Definitive cause:** repetition policy lived in an external shell loop with no between-cycle stop
  checkpoint. Printed completion was incorrectly treated as proof that the parent had not already
  launched the next child.
- **Recovery:** both private exact recovery records were preserved. No radio worker remained; exact
  `wlan1` and `wlan0` were quiesced, then side 2 and side 1 were restored in reverse order through
  `UsbLease.from_recovery`. Windows and Linux state were verified and both recovery files cleared.
- **Never repeat:** do not interrupt a parent repetition loop based on console output. A campaign
  runner must own `max_cycles`, check cancellation only between terminal-clean cycles, and publish a
  campaign checkpoint before launching the next child. If policy changes mid-campaign, let the
  current bounded child clean up and request stop through that checkpoint.

### MTA-OPS-032 — A PowerShell statement was used where a parenthesized expression was expected

- **Observed:** the replacement Q6 loop attempted `Join-Path $campaign (if (...) {...})`.
  PowerShell treated `if` as a command in that position, leaving `--state-root` without a value; the
  Python parser exited before the harness, WSL, USB, relay, or repository state changed.
- **Definitive cause:** statement syntax was assumed to be an inline expression without first
  validating the small loop command.
- **Correction:** resolve the conditional name in its own `$runName = if (...)` statement, then pass
  the resulting string to `Join-Path`.
- **Never repeat:** compute and validate conditional PowerShell values in a separate statement before
  placing them in lifecycle command arguments. An argument-parser exit is not a test attempt.

### MTA-OPS-033 — Ripgrep's default regex engine was given unsupported look-around

- **Observed (2026-09-01):** a read-only display-string audit for the standalone
  `SwitchTradeNoBackend` project used a negative look-ahead in `rg` without selecting PCRE2. Ripgrep
  rejected the pattern before searching. No source, process, backend, WSL, relay, USB, or installed
  state changed.
- **Definitive cause:** a PCRE feature was assumed to be available in ripgrep's default regex engine
  even though the same audit could be expressed as two literal searches.
- **Correction:** use `rg -F` for the required literal inventories and compare their results without
  advanced regex syntax.
- **Never repeat:** default every repository string audit to literal `rg -F`; select `--pcre2` only
  when look-around is genuinely necessary and independently justified.

### MTA-OPS-034 — Ripgrep file filters were placed after the end-of-options marker

- **Observed (2026-09-01):** the final standalone-GUI string audit put `-g` filters after `--`.
  Ripgrep correctly treated them as file paths, emitted Windows path errors, and did not perform the
  intended searches. No source, process, backend, WSL, relay, USB, or installed state changed.
- **Definitive cause:** the command used `--` before all options had been supplied.
- **Correction:** place every `-g` filter before `--`, then pass the literal pattern and search root.
  Discard the failed command's apparent `clear` results and rerun the full inventory.
- **Never repeat:** construct ripgrep commands as `rg [options and globs] -- [pattern] [paths]`; any
  ripgrep diagnostic makes the entire audit unknown rather than partially successful.

### MTA-APP-011 — A WPF self-test synchronously waited on an async export bound to the UI context

- **Observed (2026-09-01, M9):** the first Desktop application-session self-test opened no window and
  produced no final exit because `ExportAsync(...).GetAwaiter().GetResult()` blocked the WPF startup
  thread while the async continuation tried to resume on that same synchronization context. No
  backend, WSL, USB, relay, endpoint, or installed state was touched; only disposable self-test
  directories were created.
- **Definitive cause:** a library-style async method was invoked synchronously from WPF startup without
  moving the entire async operation off the UI synchronization context.
- **Correction:** the self-test runs the export through `Task.Run` and then waits for that independent
  task. Both `--session-self-test` and the complete `--self-test` now exit 0, including a Korean path.
- **Never repeat:** any native startup/self-test path that must remain synchronous may wait only on an
  operation proven not to capture the UI context, or must execute the complete async call on a worker
  task. Every release build runs the executable self-test with a bounded process timeout; a successful
  compile is not evidence against a synchronization deadlock.

### MTA-APP-012 — New Desktop projections initially reused occupied versioned contract names

- **Observed (2026-09-01, M8/M9):** the wrapper plan called the Desktop readiness and product-run
  projections `app-readiness.v2` and `connection-run.v1`, but those exact names already identify the
  relay P0 readiness payload and the internal coordinator record. Reusing either name would let two
  incompatible shapes claim the same immutable contract identity.
- **Definitive cause:** the prose plan named contracts semantically without first checking the
  repository-wide schema registry and current producers/consumers.
- **Correction:** existing schemas remain unchanged. The Desktop-facing contracts are explicitly
  `local-app-readiness.v2` and `production-connection-run.v1`; Python routes, C# DTOs, launcher,
  provisioner, installer manifests, schemas, and tests agree on those names.
- **Never repeat:** before naming or versioning a contract, search schemas, producers, consumers,
  package manifests, and documentation. A versioned name is immutable; a new incompatible projection
  receives a new unambiguous name and a cross-language contract regression.

### MTA-QA-008 — A pure-GET test observed legitimate background progress and blamed polling

- **Observed (2026-09-01, M8):** the first `ConnectionRunService` pure-polling regression captured its
  `before` snapshot during `preflight` and its `after` snapshot after the worker had independently
  reached `running`, producing one failed assertion. The GET calls launched nothing; one runner was
  active and no hardware, WSL, relay, or endpoint was involved in the fake-runner test.
- **Definitive cause:** the test did not establish a stable asynchronous checkpoint before comparing
  immutable projections.
- **Correction:** the fake runner publishes `running`, signals a barrier, and then waits. The test
  compares repeated GET results only inside that stable interval and separately asserts one launch.
- **Related recurrence:** a stale-revision test later sampled the initial `created` projection while
  the service-owned `preflight` publication was already queued, then attempted Stop with that old
  revision. The same test-shape error briefly recurred in the new shutdown-identity case. Both tests
  now wait for the explicit preflight barrier before taking the actionable snapshot; these were
  legitimate asynchronous progress, not command or GET mutation.
- **2026-09-01 dry-run recurrence:** the heartbeat revision test signaled immediately after the fake
  runner queued `running`, not after the service-owned event queue published it. It therefore compared
  a factual `preflight` snapshot with the later factual `running` snapshot and again mislabeled normal
  progress as heartbeat mutation. The regression now waits for the authoritative projection itself to
  reach `running` before freezing the no-writer interval.
- **Never repeat:** a read-purity test must control all legitimate background writers. Establish an
  explicit barrier, record launch/mutation counters, poll within the quiescent interval, and assert
  both identical projection and unchanged counters.

### MTA-QA-009 — New production API tests exposed guessed helper fields and incomplete imports

- **Observed (2026-09-01, M9):** the first production-control route test failed before exercising a
  run because the readiness helper referenced a nonexistent nested `readiness_axis`; a subsequent
  request-identity path lacked the `uuid` import. These were source-only failures in a temporary
  `TestClient`; no local service, WSL, USB, relay, endpoint, or installed application changed state.
- **Definitive cause:** new route code reused the semantic idea of legacy readiness and command
  identity without resolving the exact local helper scope and import closure.
- **Correction:** readiness uses the route-local `axis` constructor and `uuid` is an explicit module
  import. Production API tests now cover readiness, missing identity, one start, pure GET, typed run
  projection, support checkpoint, legacy/debug 404s, Stop, and verified terminal cleanup.
- **Never repeat:** exercise the packaged route table through its actual application factory before
  calling an API cutover complete. Tests must import a fresh module, enter lifespan, call every new
  helper path, and prove retired routes are absent; static inspection cannot prove closure.

### MTA-QA-010 — Cleanup uncertainty was initially hidden by a successful context-manager expectation

- **Observed (2026-09-01, M8):** restart-recovery tests intentionally created an unresolved cleanup
  guard, but their initial context-manager structure implicitly expected `close()` to succeed. The
  corrected service properly raised `SERVICE_CLEANUP_TIMEOUT`, so the test shape—not cleanup—was
  wrong. The tests use temporary state and fake runners; no real process, WSL, USB, relay, or endpoint
  was touched.
- **Definitive cause:** convenience teardown semantics conflicted with the fail-closed service
  contract that shutdown cannot report success while cleanup remains unproven.
- **Correction:** uncertainty tests own the service explicitly and assert the stable shutdown error.
  Verified-cleanup tests continue to use the normal context-manager path.
- **Never repeat:** tests for cleanup uncertainty must assert the expected teardown failure and retain
  recovery state. Never weaken production `close()` merely to make generic test cleanup silent.

### MTA-APP-013 — Application shutdown bypassed caller command identity

- **Observed (2026-09-01, M8/M9 audit):** Stop, End, Leave, Close, Retry, and checkpoint continuation
  required UUID command identity plus exact run revision, but `/api/v1/app/shutdown` directly called
  service cleanup without validating the caller's run/revision. It still used the correct cleanup
  owner, so no duplicate process or USB owner was observed; the defect was found by source audit
  before installed or hardware execution.
- **Definitive cause:** shutdown was treated as process-lifetime plumbing rather than a state mutation
  in the same command contract.
- **Correction:** `ConnectionRunService.shutdown` is serialized and identity-bound. The Desktop reads
  the current readiness run/revision and sends command, revision, and optional run headers before the
  backend performs bounded service-owned cleanup. Stale shutdown identity has an automated rejection
  test; a verified shutdown closes the runner once.
- **Never repeat:** every path that can cancel work, advance a gate, release authority, stop a process,
  or change hardware ownership is a mutation. It must enter the one command queue with idempotency and
  revision identity, including app/window/OS shutdown.

### MTA-APP-014 — Endpoint heartbeat churned public revision without changing state

- **Observed (2026-09-01, M8 audit):** each two-second endpoint heartbeat updated the watchdog clock
  correctly but was also queued as a generic public event. The generic handler incremented and
  persisted the run revision even though no projected field changed. No physical run was performed;
  source inspection and fake-runner tests found the issue.
- **Risk:** an otherwise valid UI command could become stale between its status read and submission,
  and the state file would receive unnecessary writes for the lifetime of every connection.
- **Definitive cause:** liveness evidence and authoritative state transition publication shared one
  callback even though they have different revision semantics.
- **Correction:** heartbeat now updates only the identity-bound monotonic watchdog timestamp. Endpoint
  event evidence remains in the bounded worker stream. A regression sends ten heartbeats inside a
  stable run and proves the complete public snapshot and revision remain unchanged.
- **Never repeat:** revisions represent user-visible authoritative state transitions, not telemetry.
  Heartbeats, counters, and packet-free diagnostic events use bounded evidence sinks and monotonic
  supervision without invalidating commands.

### MTA-APP-015 — Production state did not receive passed A/B/C/D gates

- **Observed (2026-09-01, M8 audit):** the shared endpoint and distributed lifecycle advanced their
  gates correctly, but only qualification console status received those events. The production
  projection could therefore remain at an older preflight/checkpoint gate, weakening UI progress and
  the service-level failure summary even when the executor report was accurate.
- **Definitive cause:** the neutral lifecycle adapter implemented commands and checkpoints but omitted
  the one-way passed-gate event sink needed by the product projection.
- **Correction:** the shared lifecycle emits only already-passed P0/A/B/C/D gates through an optional
  `gate_passed` sink. The production adapter maps them to `current_gate` and `last_passed_gate`; legacy
  qualification controls ignore the optional sink. No gate order or low-level A/B/C/D implementation
  changed. Focused shared-lifecycle regressions and a production projection test pass.
- **Never repeat:** a new adapter must have an explicit matrix for commands, checkpoints, passed gates,
  failures, heartbeats, and cleanup—not just start/stop. Product UI and summaries consume factual
  state transitions, never parse qualification console text.

### MTA-APP-016 — Support export omitted bounded endpoint and D-stage evidence files

- **Observed (2026-09-01, M9 audit):** the Desktop export included JSONL component logs, stderr, final
  reports, and WSL snapshots, but its strict allowlist omitted the bounded endpoint control stream
  `worker-events.ndjson` plus `*-stage.json` and local D release/control reports. Export still
  succeeded, which could have hidden the evidence gap until a field failure.
- **Definitive cause:** the allowlist was designed from desired categories rather than checked against
  the exact filenames produced by the admitted executor and D owners.
- **Correction:** the allowlist now explicitly includes the bounded/sanitized worker event stream,
  stage reports, D5 control report, and D local-release report. Private endpoint config, credentials,
  recovery secrets, raw captures, and non-allowlisted files remain excluded. The non-ASCII Desktop
  self-test creates nested representative files, confirms their ZIP presence, and proves nested
  credentials are redacted.
- **Never repeat:** derive an export allowlist from an enumerated producer-to-file ledger and test one
  representative from every P0/A/B/C/D and startup category. “ZIP created” is not evidence that the
  diagnostic set is complete.

### MTA-APP-017 — The GUI labeled every cancellation as End and disabled Stop during preparation

- **Observed (2026-09-01, M9 audit):** the Trade Room button always displayed “End connection” and
  always called `/session/stop`. Because `Starting` was also classified as a pending UI mutation, the
  button was disabled precisely while the user needed to cancel preparation. The backend already had
  separate Stop and End commands; no physical run was used to find this projection defect.
- **Definitive cause:** legacy GUI state names were reused without an explicit action matrix for the
  new production phases. The first correction also changed state to `Ending` before remembering
  whether it had been active; the Desktop self-test caught that active End still selected Stop.
- **Correction:** passed `C_RFU_ACTIVE` or `C_TRADE_COMPLETE` makes the GUI factually active. Preparing,
  checkpoint, and recoverable-failure states expose Stop; active state exposes End. The coordinator
  captures the pre-transition state before displaying `Ending`. Active Leave/Close goes directly
  through service-owned D and authority finalization; preparation first Stops, then releases retained
  room authority. Verified `room_closed`/`member_left` evidence clears the service projection only
  after distributed cleanup.
- **Never repeat:** define and test the complete UI-action matrix from authoritative phase and gate:
  created/preflight/awaiting-user -> Stop, RFU-active -> End, active owner/member -> Close/Leave,
  cleaning -> no mutation, terminal verified -> Retry plus retained-authority action. Button text,
  enablement, route, and cleanup wait must be asserted together.

### MTA-APP-018 — Readiness GET performed a blocking relay probe

- **Observed (2026-09-01, M9 audit):** the first local readiness request synchronously called a relay
  client with a five-second timeout, while Desktop startup allowed one second for the entire local
  response. A slow relay could therefore make a healthy installed service appear not to have started;
  repeated GETs also initiated external work.
- **Definitive cause:** relay reachability caching was placed inside the HTTP handler rather than owned
  by application lifespan.
- **Correction:** one lifespan-owned `RelayReadinessMonitor` probes with a bounded client and keeps an
  in-memory `unknown/ready/failed` snapshot. GET only reads that snapshot, returning `checking` until
  the first result. A regression reads the snapshot twenty times and proves no additional probe.
- **Never repeat:** local startup readiness must be fast and factual even when every external service
  is slow or down. External probes run under a separately supervised lifecycle; GET handlers never
  create rooms, launch processes, acquire USB, retry, recover, heartbeat, or initiate health work.

### MTA-APP-019 — Desktop compatibility and About text retained `0.2.x` assumptions

- **Observed (2026-09-01, M9 audit):** `ControlApiClient` still rejected any product version outside
  the hard-coded `0.2.` prefix, the recovery detail said `0.2.x`, and Settings displayed the stale
  literal `0.2.2 beta.1`. This would break the planned `0.3.0-beta.1` cutover despite exact release ID
  and contract identity matching.
- **Definitive cause:** historical UI compatibility scaffolding survived the release-identity rewrite.
- **Correction:** compatibility now requires the exact installed release ID, exact local contract,
  backend compatible flag, and a nonempty product version—no product-series prefix. About reads the
  assembly version and mismatch text describes exact release identity.
- **Never repeat:** never use display or semver prefix strings as installed runtime authority. Package
  manifest, active runtime, backend, and Desktop must compare immutable release/contract identities;
  version text is derived from build metadata.

### MTA-QA-011 — WPF's required instance binding triggered the warning-as-error analyzer

- **Observed (2026-09-01, M9):** after replacing the stale About literal with an assembly-derived
  view-model property, Release build failed only with CA1822 because the property did not otherwise
  access instance data. Python tests had already passed; no app, WSL, USB, relay, or installer state
  changed.
- **Definitive cause:** the binding requirement and the repository's warning-as-error analyzer policy
  were not handled together in the first edit.
- **Correction:** the property remains an instance member for WPF binding and carries a narrow
  justification-specific suppression. Release build then passed with zero warnings and errors, and
  both Desktop self-tests exited 0.
- **Never repeat:** when a framework requires an instance member that a performance analyzer wants
  static, add the smallest documented suppression at the member and verify the actual Release build;
  do not weaken analyzer policy globally.

### MTA-QA-012 — The checkpoint-Stop endpoint regression used an incomplete config fixture

- **Observed (2026-09-01, M8 dry-run):** the first new endpoint-level Stop regression failed before
  reaching its checkpoint because its mocked configuration omitted `relay_url`, `room_code`, and
  `member_token`. No hosted relay request, WSL process, USB action, endpoint process, or Switch action
  occurred.
- **Definitive cause:** the test replaced config-file validation but supplied only the fields directly
  relevant to D, while the unmodified endpoint constructor correctly consumed the complete validated
  configuration.
- **Correction:** the fixture now supplies the full endpoint construction boundary while mocking only
  external transport and stage behavior. Production validation was not weakened.
- **Never repeat:** a test that bypasses one contract parser must still use a complete value already
  accepted by that parser. Build fixtures from the contract-required field set, then vary only the
  field under test.

### MTA-APP-020 — Stop at a physical checkpoint was parsed only as Continue

- **Observed (2026-09-01, M8 dry-run preflight):** source inspection before any relay room, USB
  attachment, endpoint launch, or Switch action found that `CREATE_SWITCH_ROOM` and
  `JOIN_SWITCH_GROUP` waits accepted only `continue_checkpoint`. The service correctly sends an
  identity-bound `closing_intent` when Stop is requested, but the endpoint would reject that valid D
  command as a stale Continue command, enter its generic failure path, and then wait for a second
  closing intent that the single-send parent correctly never emits.
- **Definitive cause:** the endpoint had two command parsers—one for physical checkpoints and one for
  the active bridge—and the checkpoint parser did not share the normal D transition.
- **Correction:** a checkpoint now validates `closing_intent` through the existing D command validator
  and carries it directly to the one endpoint `finally` owner. It emits no synthetic functional
  failure and proceeds through the same `EndpointDStage` used after an active connection. Continue
  remains exactly run/checkpoint-bound.
- **Never repeat:** every blocking user checkpoint must accept both its exact Continue transition and
  the one identity-bound terminal transition. Test Stop at each checkpoint and require one D intent,
  one endpoint report, preserved functional outcome, and verified cleanup before installed dry-run or
  physical qualification.

### MTA-APP-021 — Production adapter classified checkpoint Stop as a functional failure

- **Observed (2026-09-01, M8 dry-run audit):** after correcting the endpoint command boundary, the
  composed service trace showed that `RunControl.await_user` raises the stable
  `CONNECTION_CANCELED` result for Stop, but `ProductionControlAdapter` forwarded that service error
  into `DistributedLifecycle.drive`. Its generic error branch would begin D with outcome `failed`
  instead of the requested `canceled`. No relay room, WSL process, USB action, endpoint, or Switch was
  started while finding this source defect.
- **Definitive cause:** role-wait cancellation already translated the service error into
  `DistributedCanceled`, but the later physical-checkpoint adapter omitted the same semantic mapping.
- **Correction:** the production checkpoint adapter translates only the exact
  `CONNECTION_CANCELED` code into `DistributedCanceled`; timeout, stale identity, and other failures
  remain failures. The endpoint then receives one canceled D intent through the corrected path.
- **Never repeat:** every adapter between state machines needs an explicit outcome matrix, not merely
  matching method names. Test success, user cancellation, timeout, stale identity, and cleanup
  separately at each blocking boundary.

### MTA-APP-022 — An implicit base Window style did not theme the standalone WPF window

- **Observed (2026-09-01):** the first visible `SwitchTradeNoBackend` render had the intended dark
  header but a white main canvas and low-contrast body copy. Build and construction self-tests had
  passed; no backend, WSL, relay, USB, or installed-product action occurred.
- **Definitive cause:** the standalone app relied on an implicit `Style TargetType="Window"`, but
  the generated `MainWindow` is a derived type and did not inherit that implicit style as assumed.
- **Correction:** set the root window's background, foreground, font family, and font size explicitly,
  then require one screenshot-backed render check in addition to construction self-tests.
- **Never repeat:** a WPF compile or hidden construction test does not prove theme application. Every
  new root window needs explicit shell colors and one visible render inspection at release scale.

### MTA-APP-023 — The longer standalone app name clipped inherited home copy

- **Observed (2026-09-01):** after the dark shell correction, screenshot inspection showed the home
  subtitle ending mid-word and both navigation-card descriptions colliding with their action labels.
  No input beyond normal launch/close occurred and no backend, WSL, relay, USB, or production process
  was touched.
- **Definitive cause:** current-GUI copy was adapted from `SwitchTrade` to the longer
  `SwitchTradeNoBackend` name without adding wrapping, while navigation cards retained a fixed height
  sized for the shorter original copy.
- **Correction:** enable bounded text wrapping and give the two fixed navigation cards enough height
  for the supported copy at the minimum window size.
- **Never repeat:** any product-name or localization-length change requires visible checks at both the
  default and minimum window widths; fixed-height cards must either wrap within their bound or grow.

### MTA-APP-024 — Native ComboBox chrome erased the selected-value contrast

- **Observed (2026-09-01):** the standalone create-room screen rendered its closed game and language
  ComboBoxes with Windows' light native chrome while the app-level style forced a light foreground.
  The selected values were present but nearly invisible. No backend, WSL, relay, USB, or production
  process was involved.
- **Definitive cause:** a foreground-only dark-theme style assumed the native ComboBox template would
  honor the requested dark background; the active Windows template retained its light field surface.
- **Correction:** use an explicit high-contrast dark text color for the native closed field and its
  items instead of partially overriding the template.
- **Never repeat:** do not theme only one axis of a native control. If its full template is not owned,
  visually verify text/background contrast in closed, open, selected, disabled, and focused states.

### MTA-QA-013 — The standalone UI build targeted an executable that was still running

- **Observed (2026-09-01):** the first Release build after the owner-led GUI simplification stopped
  with `MSB3027`/`MSB3021`; the existing `SwitchTradeNoBackend` process held the destination
  executable open. No production Desktop, backend, WSL, relay, USB, or Switch state was touched.
- **Definitive cause:** the app had intentionally been relaunched for playtesting, but the build
  preflight did not check for a running standalone instance before targeting the same output path.
- **Correction:** close only the exact standalone window before rebuilding, then relaunch the newly
  verified executable. Source changes remain independent from the production Desktop project.
- **Never repeat:** before an in-place WPF build, check whether its exact output executable is
  running. Close and relaunch that exact standalone app, or use an isolated output directory when it
  must remain open; do not spend the SDK retry window on a known file lock.

### MTA-APP-025 — Adapter selection fired before later XAML fields were initialized

- **Observed (2026-09-01):** the simplified standalone GUI built cleanly, but its first construction
  self-test exited with a `NullReferenceException` in `AdapterChanged`. No window became usable and
  no production Desktop, backend, WSL, relay, USB, or Switch state was touched.
- **Definitive cause:** `SelectedIndex="0"` raised `SelectionChanged` while XAML was still loading;
  the handler tried to update `AdapterStatus`, which appears later in the same XAML object graph and
  had not yet been assigned.
- **Correction:** attach the event after `InitializeComponent()` returns, then call one shared state
  updater explicitly for the initial selection.
- **Never repeat:** an event that reads sibling named controls must not be attached declaratively when
  initialization order can fire it during XAML construction. Wire it after initialization and keep a
  construction self-test that instantiates the exact window.

### MTA-APP-026 — The global TextBlock style overrode the ComboBox contrast correction

- **Observed (2026-09-01):** screenshot QA of the simplified home screen showed the selected adapter
  as pale text on the native light ComboBox field. Build and construction tests passed; no production
  Desktop, backend, WSL, relay, USB, or Switch state was touched.
- **Definitive cause:** the earlier ComboBox and ComboBoxItem foreground correction relied on normal
  property inheritance, while the app also applied an explicit implicit `TextBlock` foreground style.
  The generated selection presenter used a TextBlock, so that more local style setter won.
- **Correction:** remove the redundant global TextBlock foreground setter. Normal body text inherits
  the explicitly themed root window; text hosted by native controls inherits that control's verified
  foreground.
- **Never repeat:** inspect the effective child element produced by native WPF templates. A parent
  foreground setter is not sufficient when an implicit child style sets the same property; verify the
  exact closed selected field after every global typography change.

### MTA-APP-027 — Left-aligned shared content width compressed the trade status layout

- **Observed (2026-09-01):** visible navigation from Create Room to the simplified trade screen
  rendered the participant strip and status panel at their minimum desired width. `You`/`Partner`
  and `Online` overlapped even though the window had ample free space. No production Desktop,
  backend, WSL, relay, USB, or Switch state was touched.
- **Definitive cause:** the shared screen host used `HorizontalAlignment="Left"`; home and form
  screens looked acceptable at desired width, but the trade grid never received the available width.
- **Correction:** let the bounded shared host stretch to its `MaxWidth`, while individual home and
  join stacks retain their own intentional widths.
- **Never repeat:** verify every screen hosted by a shared WPF grid. A layout that fits one child's
  desired width does not prove sibling screens receive the available width; inspect the narrowest
  multi-column state at both default and minimum window sizes.

### MTA-QA-014 — A bare Desktop build was treated as an installed backend-connected artifact

- **Observed (2026-09-01):** visible QA launched the Release output directly and expected the local
  service to start. The new production shell rendered correctly, but startup factually stopped at
  `PROVISIONER_MISSING`; no relay room, USB mutation, endpoint, or Switch action occurred.
- **Definitive cause:** `dotnet build` emits the WPF executable but not the package-owned adjacent
  `SwitchTradeProvisioner.exe`. The installed provisioner/runtime on this PC also exposes the older
  `app-readiness.v1` contract, so copying that one sidecar beside a newer source build would not make
  a valid immutable release.
- **Correction:** use Desktop/self-test and typed contract tests for source validation. Prove the live
  local-service path only through one complete replacement package whose Desktop, provisioner,
  runtime, release ID, and contracts were produced together.
- **Never repeat:** distinguish a bare UI build from an installed product artifact before visible QA.
  Never assemble a hybrid installation by copying individual sidecars or relaxing release checks just
  to make a source window reach Home.

### MTA-APP-028 — Home displayed an adapter that the backend had not selected

- **Observed (2026-09-01, rejected installed candidate `0.2.15-beta.1`, release
  `beta-0540ac862ae8`):** the installed Home screen displayed the first compatible USB adapter in the
  closed ComboBox even though the authoritative inventory reported every adapter with
  `selected=false`. The status described supported hardware and Create/Join remained enabled. No
  relay room, connection run, USB attach, endpoint, or Switch action occurred; both adapters remained
  Windows-owned and residue-free.
- **Definitive cause:** `HomeScreenViewModel.LoadAdaptersAsync()` projected the first inventory item
  as `SelectedDevice` whenever the backend had no selection. That UI-only fallback could not be
  distinguished from an authoritative selection and, because it was already the ComboBox value,
  choosing the same first item did not reliably emit a selection change.
- **Correction:** project only the item marked `IsSelected` by the backend, show `Select an adapter`
  when none exists, and disable connection entry actions until the selected adapter is selectable and
  Windows-authorized. Provide an explicit authorization action for the valid selected-but-unshared
  state, then reload the authoritative inventory after every mutation.
- **Never repeat:** candidate availability is not selection. A UI must never invent persisted or
  hardware authority state from list order, a previous local value, or a visual default. Installed QA
  must cover no selection, selected/unshared, selected/shared, cancellation, and first-item selection.

### MTA-APP-029 — Dynamic adapter text changed the apparent size of main actions

- **Observed (2026-09-01, installed `0.2.17-beta.1`):** with no authoritative adapter selection,
  Home's action group contracted to its shortest child content; after a long adapter label appeared,
  the same group expanded. Create also used a taller primary style than the other two actions, so the
  selected and unselected states appeared to change both action size and color even though command
  availability was the only intended state change. No connection run, relay room, WSL, USB, endpoint,
  or Switch state was touched.
- **Definitive cause:** the left-aligned Home stack had only `MaxWidth`, so WPF derived its desired
  width from dynamic and localized child text. The three peer actions also did not share one visual
  style and height.
- **Correction:** give the supported Home action column one fixed 620-pixel layout width and use the
  same secondary style, height, and font size for all three actions. Retain the standard muted disabled
  treatment so unavailable commands are not falsely presented as clickable.
- **Never repeat:** action geometry must not depend on empty, long, localized, or device-specific
  labels. Visual QA must compare no-selection and longest-label states at the minimum supported window
  size, while preserving a truthful disabled-state cue.

### MTA-OPS-035 — A theme resource filename was inferred instead of enumerated

- **Observed (2026-09-01):** a read-only inspection successfully opened the verified button-theme
  file and then attempted to read an assumed `Themes/Colors.xaml` path that does not exist. PowerShell
  returned file-not-found; no build, app, WSL, relay, USB, endpoint, Switch, or source mutation resulted.
- **Definitive cause:** a conventional theme filename was appended without first enumerating the
  tracked theme directory, repeating the inferred-path class already prohibited by `MTA-OPS-017`.
- **Correction:** the missing color file was unnecessary; the verified button template already showed
  the enabled and disabled resource behavior needed for the decision.
- **Never repeat:** use `rg --files <existing-directory>` before naming any adjacent resource. Never
  extend one verified path into a guessed sibling path, even for a read-only command.

### MTA-QA-015 — The full regression suite was started with an unqualified ambient Python

- **Observed (2026-09-01):** after the Home layout correction, `python -m pytest -q` used the ambient
  Windows interpreter and stopped during collection because `trio` was not installed. The Desktop
  build and both Desktop self-tests had already passed; no test body, application, WSL, relay, USB,
  endpoint, or Switch action started from the failed Python command.
- **Definitive cause:** the command reused the shell's generic `python` instead of first resolving and
  proving the repository's dependency-complete validation interpreter.
- **Correction:** enumerate existing virtual-environment markers, select the repository-owned
  interpreter that imports the locked test dependencies, and rerun the unchanged suite there.
- **Never repeat:** a green suite count from an earlier turn does not qualify the current shell's
  interpreter. Before every full Python run, resolve the exact executable and prove its required test
  imports; never use an ambient `python` by convenience.

### MTA-OPS-036 — Post-install verification reused an obsolete manifest path

- **Observed (2026-09-01):** the `0.2.18-beta.1` upgrade returned exit code 0 and the installed EXE
  reported the correct product/file versions, but the same read-only verification command then tried
  an assumed `%LOCALAPPDATA%\SwitchTrade\current\release-manifest.json` path that was absent. The app
  had not yet been relaunched; no WSL, relay, USB, endpoint, or Switch action occurred.
- **Definitive cause:** a path from an earlier installation layout was recalled instead of enumerating
  the current package-owned state or asking the installed service's versioned readiness projection.
- **Correction:** enumerate the exact installed state tree, launch the installed entry point normally,
  and use `app-readiness.v2` plus the EXE version as authoritative installed identity evidence.
- **Never repeat:** package build paths, staging paths, and installed state paths are distinct. Never
  verify a release by a remembered filesystem location; resolve the current layout or use its typed
  public readiness contract first.

### MTA-APP-030 — The first `0.2.18-beta.1` launch did not expose local readiness

- **Observed (2026-09-01, release `beta-98183bdd9370`):** the verified installer returned exit code 0,
  the installed EXE reported `0.2.18-beta.1`, and a normal launch started the Desktop process, but
  `GET /api/v1/app/readiness` did not become available within the bounded 45-second observation. No
  connection run, relay room, USB attach, endpoint, or Switch action was requested.
- **Status:** **investigating**. An installer success code and correct Desktop file version prove
  neither provisioner completion nor local-service readiness.
- **Immediate rule:** do not click Retry, relaunch, Repair, reinstall, unregister WSL, or mutate runtime
  state until the exact current process tree and newest package-owned launcher/provisioner evidence are
  inspected. Preserve the first failure and distinguish Desktop, provisioner, WSL appliance, and
  control-service identity before choosing recovery.
- **Definitive correction:** this was a verifier false negative, not an application failure. The
  launcher recorded `BACKEND_READY` 4.8 seconds after session start, Uvicorn was healthy on the
  package-owned port `8787`, and its log contained repeated 200 responses for the readiness route.
  The external check had queried an obsolete port `8765` for 45 seconds.
- **Never repeat:** resolve the installed local-service endpoint from the current launcher/source or
  observed child command before polling it. Never carry a port across release architectures from
  memory, and never label a timeout as product failure until package-owned evidence is reconciled.

### MTA-OPS-037 — A stale JavaScript binding shadowed the Windows automation client

- **Observed (2026-09-01):** the first read-only installed-window inspection returned
  `sky.list_apps is not a function`. No window input, navigation, connection command, WSL, relay, USB,
  endpoint, or Switch action occurred.
- **Definitive cause:** the persistent JavaScript session already contained a top-level `sky` binding;
  initializing `globalThis.sky` did not replace what the bare identifier resolved to. Direct inspection
  proved `globalThis.sky.list_apps` was the expected function on the Windows target.
- **Correction:** use the explicitly validated `globalThis.sky` object for every remaining operation
  and keep selected windows on `globalThis` as required by the tool workflow.
- **Never repeat:** persistent automation sessions are shared state. Never assume a bare top-level name
  refers to the object just assigned on `globalThis`; inspect and call the qualified binding before the
  first app query, and perform no input after a binding mismatch until selection is refreshed.

### MTA-APP-031 — The first Home correction retained a color difference the user asked to remove

- **Observed (2026-09-01, installed `0.2.18-beta.1`):** installed visual QA proved all three main
  actions had equal width and height and the new adapter instruction was present, but the shared base
  template still painted disabled Create/Join with `DisabledSurfaceBrush` and disabled text while the
  enabled Browse action used the normal surface and text colors. No connection run, relay room, USB,
  endpoint, or Switch action occurred.
- **Definitive cause:** the implementation deliberately retained a conventional muted disabled cue,
  overriding the user's explicit request that enabled and adapter-blocked main actions have the same
  color. Source compilation could not reveal that requirement mismatch; the installed screenshot did.
- **Correction:** use a Home-only action template with identical normal and disabled surface, border,
  and text rendering. Command `CanExecute` still blocks unavailable actions; an arrow cursor identifies
  disabled mouse interaction and the standard focus ring preserves keyboard navigation feedback.
- **Never repeat:** do not silently substitute a general UX preference for a specific visual direction.
  When a user asks for equality across states, compare the installed states visually before calling the
  change complete and keep any necessary state signal orthogonal to the requested color/geometry.

### MTA-OPS-038 — A PowerShell inventory pipeline was syntactically invalid

- **Observed (2026-09-01, housekeeping preflight):** the first read-only branch/worktree inventory
  command failed with `An empty pipe element is not allowed`. No deletion, Git mutation, process,
  WSL, USB, relay, installed-app, or hardware action occurred.
- **Definitive cause:** a statement-form `foreach` block was piped directly to `Format-List` instead
  of first being evaluated or assigned as a pipeline expression.
- **Correction:** collect the loop results into a variable, then pipe that variable to the formatter;
  the exact inventory subsequently completed.
- **Never repeat:** for destructive-operation preflight, keep enumeration syntactically simple and
  execute it read-only first. Do not combine a statement-form loop with a trailing pipeline, and do
  not begin deletion until the corrected inventory has completed and its targets are bounded.

#### Recurrence (2026-09-01, repository cleanup)

- **Observed:** the preflight for removing three PC-specific handoff files from Git tracking again
  piped a statement-form `foreach` block directly to `Format-List`. PowerShell rejected the command at
  parse time with `An empty pipe element is not allowed`; no Git index or working-tree state changed.
- **Cause:** the already documented correction was not applied when composing a new read-only
  destructive-operation preflight.
- **Permanent guard:** every PowerShell loop used for inventory first assigns its results to a named
  task-specific variable. Only that completed variable may be piped to formatting. A parser failure
  invalidates the complete inventory and no mutation follows it.

### MTA-OPS-039 — Ignored historical documents were mistaken for published documentation

- **Observed (2026-09-01, housekeeping documentation):** `docs/STATUS.md` and
  `docs/67-hardware-support-expansion-20260826.md` were edited before verifying that the current
  distribution branch tracks them. `git status` correctly omitted both because `/docs/**` is ignored
  except for an explicit public allowlist. No commit, push, build, runtime, WSL, USB, relay, installed
  app, or hardware state was affected.
- **Definitive cause:** filesystem presence and historical Git log entries were incorrectly treated as
  proof that a path was tracked at `HEAD`.
- **Correction:** restore the local historical files and place the current status/hardware-expansion
  decision only in tracked `README.md`, `FUTURE_TODO.md`, and the tracked M8/M9 decision document.
- **Never repeat:** before editing documentation that must ship, verify the exact path with both
  `git ls-files --error-unmatch` and `git check-ignore -v`. Filesystem presence, old history, and a
  plausible filename are not current publication authority.

### MTA-OPS-040 — Artifact verification and recursive deletion were combined at one execution boundary

- **Observed (2026-09-01, housekeeping cleanup):** an intended PowerShell command both resolved and
  validated the artifact root and then recursively deleted the computed variable. The execution
  safety boundary rejected the command before PowerShell started. No artifact, source, process, WSL,
  USB, relay, installed-app, or hardware state changed.
- **Definitive cause:** the read-only target proof and destructive operation were composed into one
  invocation, so the deletion target was still computed at the point of mutation even though the
  script contained an internal prefix check.
- **Correction:** finish target/path/tracked-file/size verification in a separate read-only call, then
  issue deletion against that already verified absolute literal path and independently confirm absence.
  The execution boundary also rejected a direct literal `Remove-Item -Recurse` before launch. Because
  `artifacts/` is an ignored repository path with zero tracked files, the accepted fallback is an
  exact-path `git clean -ndX -- artifacts/` preview followed by the matching `git clean -fdX` action;
  do not switch shells or broaden the path.
- **Never repeat:** a recursive filesystem mutation uses an exact literal target established by a
  completed earlier read-only check. Do not ask an execution boundary to trust validation and deletion
  of a computed path inside the same command.

### MTA-OPS-041 — Ignored-artifact cleanup was partial because of Windows long paths

- **Observed (2026-09-01, housekeeping cleanup):** the exact-path `git clean -ffdX -- artifacts/`
  removed the ordinary generated artifacts but exited 1 after several deeply duplicated UI-evidence
  paths exceeded Git for Windows' default path-length handling. The command clearly reported every
  retained path; source and installed-product state were not targeted.
- **Definitive cause:** the generated DRAFT evidence tree recursively contained copies of its own long
  path, while the cleanup invocation did not enable Git's long-path support for that one operation.
- **Correction:** inventory the remaining exact artifact root, preview with
  `git -c core.longPaths=true clean -nffdX -- artifacts/`, then apply the identical command without
  `-n` and verify the root is absent. Do not change global Git configuration.
- **Never repeat:** before deleting a large Windows artifact tree, include maximum path length in the
  read-only inventory and use a one-command long-path setting when needed. A nonzero cleanup exit is a
  partial result, never success; enumerate and remove the residue before continuing to Git integration.

### MTA-OPS-042 — A filtered repository inventory named unverified top-level paths

- **Observed (2026-09-01, hardware-profile expansion):** the first read-only file inventory passed
  assumed `schemas` and `Desktop` paths to `rg`; neither exists at the repository root, so ripgrep
  emitted two missing-path diagnostics. The valid named directories were still enumerated. No test,
  build, application, WSL, relay, USB, endpoint, Switch, or source mutation occurred.
- **Definitive cause:** likely component names were converted into top-level paths instead of first
  enumerating the repository, repeating the exact path-assumption class prohibited by
  `MTA-OPS-017`, `MTA-OPS-029`, and `MTA-OPS-030`.
- **Correction:** enumerate tracked files from the repository root and filter that returned inventory;
  do not append semantic directory names to an `rg --files` command.
- **Never repeat:** a repository-wide inventory starts with an existing root only. Every narrower path
  must come from that result or an immediately preceding existence proof; any path diagnostic makes
  the attempted inventory incomplete and it must not be used as evidence.

#### Recurrence (same turn)

- **Observed:** a later source search again named an unverified `desktop` directory and also passed a
  shell-style `tests/test_*` path through PowerShell. Ripgrep reported both targets as invalid. The
  valid `switchtrade/control.py` read completed, but the failed search output was discarded and no
  conclusion was based on it. No source, installed-product, WSL, relay, USB, or Switch state changed.
- **Cause:** the correction above was applied only to the first inventory command, not to every later
  filtered search in the task.
- **Permanent guard:** every subsequent search in this hardware-profile task must start at `.` (or at
  a path copied from `rg --files .`) and express filename filtering with ripgrep's `-g` option. A
  literal subdirectory may be supplied only after `Test-Path -LiteralPath` succeeds in the immediately
  preceding command.

#### Second recurrence (same turn)

- **Observed:** after reading the tracked `p0-side-ready.v1.schema.json`, the next command assumed a
  sibling `p0-passive.v1.schema.json` existed. It does not, so `Get-Content` emitted a missing-path
  error. The existing schema read was valid; the nonexistent-file read was discarded. No source or
  runtime state changed.
- **Cause:** an inferred sibling filename was treated as repository evidence instead of selecting the
  name from the tracked-file inventory.
- **Permanent guard amendment:** do not pass any newly inferred literal path to a filesystem command
  in this task. Copy the exact path from `rg --files .`; if no matching path is returned, record that
  the artifact is absent without probing a guessed name.

### MTA-OPS-043 — A multi-site patch was built from reconstructed rather than exact context

- **Observed (2026-09-01, hardware-profile expansion):** a broad `apply_patch` covering control DTOs
  and several function signatures failed verification at `endpoint_command`. The patch engine applied
  nothing, so source and runtime state remained unchanged.
- **Definitive cause:** signature context was reconstructed from truncated/filtered search output
  instead of copied from a direct bounded read of every edit site.
- **Correction:** read the exact bounded source around each site, then patch one coherent function or
  DTO group at a time and verify the removed identifier with `rg` after every patch.
- **Never repeat:** a multi-site patch may include only exact context already visible in complete
  bounded reads. If a file has many dispersed call sites, use multiple small verified patches rather
  than one speculative patch.

### MTA-OPS-044 — A firmware hash loop continued after HTTP failure with stale data

- **Observed (2026-09-01, hardware-profile expansion):** an in-memory PowerShell hash loop fetched
  five pinned linux-firmware paths. Two MT7662 paths returned `NOT_FOUND`, but the non-terminating
  web errors let the loop reuse the previous iteration's `$encoded` value and print two false hashes.
  Those two values were discarded immediately and were never written to a manifest or source file.
- **Definitive cause:** the evidence command did not set terminating error behavior, did not clear the
  per-item buffer, and did not validate decoded length before hashing.
- **Correction:** fetch every binary with `-ErrorAction Stop` inside an isolated per-item scope, require
  nonempty decoded bytes, and abort the entire command on the first missing object. Record source path,
  byte length, and SHA-256 together; never accept output from a command that emitted an error.
- **Never repeat:** cryptographic manifest evidence is all-or-nothing. Any transport, decode, or path
  failure invalidates the full batch, and no value from that batch may be copied into release metadata.

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

1. Complete the remaining deterministic M8/M9 installed cases after PC A's `0.2.19-beta.1` normal
   entry/readiness/UI pass: explicit WSL cwd, identity-bound control, cancellation, one launch,
   interruption, startup recovery, and verified cleanup must pass without invoking the qualification
   harness as product runtime (`MTA-M7-005` through `MTA-M7-015`).
2. Qualify the application-session logging and Desktop exporter in an installed
   backend-dead/startup-failure scenario. The exporter remains read-only and cannot launch, retry,
   recover, or clean a connection.
3. Complete the installed two-PC/two-Switch M10 qualification through the normal packaged GUI and
   production wrapper, not a repository CLI or retired Debug menu.
4. Investigate credentialless `waiting_for_complementary_role` rooms by ordered event history without
   breaking reconnect grace (`MTA-RELAY-006`).
5. Continue the critical and post-release work in `FUTURE_TODO.md`; this document prevents recurrence
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

### MTA-OPS-045 — Do not combine remote evidence retrieval with local cleanup in one shell call

- **Observed:** A PowerShell command that combined two firmware downloads, hash calculation, and
  temporary-file deletion was rejected by execution policy before it ran.
- **Impact:** No repository or temporary file changed, but the validation round trip was wasted and
  produced no usable evidence.
- **Cause:** Network retrieval and filesystem cleanup were unnecessarily coupled in one complex
  command, increasing quoting and policy surface.
- **Correction:** Retrieve authoritative remote evidence with the web client, then make local
  repository changes separately. If a local temporary file is unavoidable, use one verified target
  and a separate bounded cleanup step.
- **Never repeat:** Do not combine remote download, derived-path construction, and deletion in one
  shell invocation. A failed evidence command must never be treated as evidence or copied into a
  manifest.

### MTA-OPS-046 — A PowerShell web error must terminate before any digest is computed

- **Observed:** A missing firmware URL emitted `NOT_FOUND`, but the one-line PowerShell probe still
  reached the digest calculation and printed the SHA-256 of an empty byte array.
- **Impact:** The printed digest was false evidence. It was discarded immediately and was never
  written to the firmware manifest.
- **Cause:** The probe assumed `-ErrorAction Stop` alone made every `Invoke-WebRequest` failure
  terminating, and did not separately assert response bytes before constructing the digest.
- **Correction:** Resolve the exact firmware filename from the authoritative driver source first.
  Every later retrieval must run in a script scope with `$ErrorActionPreference = 'Stop'`, assert a
  non-empty response, and emit a digest only from the validated bytes.
- **Never repeat:** Never accept a digest from a command that printed any transport error, and never
  hash before checking that the retrieved byte count is positive.

### MTA-OPS-047 — Never concatenate a byte array into PowerShell diagnostic output

- **Observed:** A firmware digest probe used ambiguous `+` concatenation, so PowerShell enumerated
  the decoded byte array instead of printing only its length. The command returned the correct
  digest but also produced a very large, useless output.
- **Impact:** No file or secret changed or leaked—the firmware is a public upstream binary—but tool
  output was needlessly noisy and validation became harder to audit.
- **Cause:** The output expression relied on operator precedence instead of constructing one bounded
  formatted string.
- **Correction:** Preserve only the validated digest values and use `-f` formatting (or explicit
  scalar variables) for every later binary-evidence probe.
- **Never repeat:** Never interpolate or concatenate raw byte arrays. Binary validation output is
  limited to filename, lowercase SHA-256, and integer byte count.

### MTA-DEV-016 — DTO field removal must update every constructor before compiling

- **Observed:** Removing user-visible hardware maturity fields changed
  `HardwareDeviceViewData` from ten constructor arguments to eight, while five Desktop self-test
  fixtures still passed the old argument list. The Release build failed with `CS1729`.
- **Impact:** The compiler blocked the candidate; no installer or production binary was produced.
- **Cause:** The edit updated API mapping and some fixtures but did not enumerate every constructor
  call before the first build.
- **Correction:** Search the exact type name repository-wide, update every construction site, then
  run the Desktop Release build and self-test.
- **Never repeat:** A DTO/schema field change is incomplete until all producers, consumers,
  serialization contracts, fixtures, and constructors have been enumerated and compiled.

### MTA-OPS-048 — Verify test filenames before combining reads

- **Mistake:** A combined inspection command referenced `tests/test_replacement_installer_source.py`
  without first confirming that the file exists. The read failed even though the preceding files
  were inspected successfully.
- **Impact:** No repository state changed, but the command produced avoidable noise and repeated the
  unverified-path class already covered by MTA-OPS-042.
- **Prevention:** Discover candidate tests with `rg --files tests` first, then read only exact returned
  paths. Do not infer a test filename from a component name.

#### Recurrence (2026-09-01, focused CI regression command)

- **Observed:** a focused pytest node used the invented class name `DistributedHarnessTests`; the
  actual class is `DistributedContractTests`. Pytest rejected collection before running any test.
- **Impact:** no test or product action ran and no state changed; the command only wasted one local
  invocation.
- **Permanent guard:** discover both the exact file and enclosing class with `rg` before composing
  pytest node IDs. An uncollected command is not validation evidence.

### MTA-DEV-017 — Do not compare cross-platform text contracts by raw file hash

- **Observed:** The production firmware manifests contained the same ordered hash/path records, but
  the Windows checkout used CRLF while the Linux kernel workflow used LF. A raw SHA-256 comparison
  would reject a valid matching kernel artifact.
- **Impact:** A correct multi-driver kernel could be blocked during replacement-package creation
  solely because of line-ending normalization.
- **Root cause:** The packaging gate treated the byte representation of a text contract as its
  semantic identity.
- **Prevention:** Parse and validate every manifest record, normalize it to
  `<lowercase sha256>  <forward-slash path>`, reject duplicates or malformed paths, and compare the
  resulting records. Keep artifact integrity hashes for each artifact separately; do not use them
  as a cross-platform semantic comparison.

#### Recurrence (2026-09-01, kernel mirror verification)

- **Observed:** after the correct source subtree was loaded into a temporary kernel-repository clone,
  verification compared raw working-tree SHA-256 values. `firmware-manifest.sha256` differed because
  checkout line-ending filters produced different byte representations of the same tracked text. No
  kernel commit, push, workflow, or artifact was created.
- **Cause:** the existing semantic-text rule was not applied to repository mirroring; raw worktree
  bytes were mistaken for tracked content identity.
- **Permanent guard:** exact repository mirrors compare Git tree/blob object IDs from the source tree
  and target index. Cross-platform text contracts additionally pass their semantic parser. Raw
  working-tree hashes are reserved for binary artifacts whose byte identity is the contract.

#### Recurrence (2026-09-01, immutable appliance manifest handoff)

- **Observed:** Windows verified the wheelhouse's 25 filenames and hashes, but the disposable Linux
  appliance rejected the file set. Git stored the manifest with LF while the Windows checkout used
  CRLF; WSL's `awk` retained the trailing carriage return in every expected filename. The same issue
  would later have affected firmware paths. No appliance or installer was produced.
- **Correction:** track every `*.sha256` contract with `eol=lf`, and defensively strip only a terminal
  carriage return before Linux filename/hash processing. The normalized firmware contract is also
  the one stored in the appliance.
- **Permanent guard:** text contracts crossing Windows/WSL boundaries require both repository EOL
  policy and consumer-side semantic normalization. A Windows-side successful parse does not prove
  the mounted byte representation is safe for Linux line tools.

### MTA-OPS-049 — Do not assume validated recursive temp cleanup is permitted

- **Mistake:** After a successful firmware fetch validation, a separate PowerShell command verified
  that the exact cleanup target was a `SwitchTrade-FirmwareValidation-*` directory under the system
  temp root and then attempted `Remove-Item -Recurse`. The execution policy still rejected it.
- **Impact:** No deletion occurred and no source file changed, but one explicitly identified
  validation directory remained in the user's temp directory.
- **Prevention:** Treat recursive cleanup as independently policy-sensitive even after exact path
  validation. Prefer a test API that owns and cleans its temporary directory internally, or leave
  the exact disposable path for the user instead of retrying blocked deletion commands.

### MTA-OPS-050 — Preflight the declared test environment before a full suite

- **Mistake:** The full Python suite was started with the ambient interpreter without first checking
  the repository's declared test dependencies. Collection stopped because `trio` was absent.
- **Impact:** No product test failed and no state changed, but the full-suite result was inconclusive
  and had to be rerun in the correct environment.
- **Prevention:** Before a broad suite, identify the repository test requirements and preferred
  virtual environment, then run a dependency import preflight. Keep focused standard-library tests
  separate from suites that require the full test environment.

### MTA-DEV-018 — An emitted release field is not a contract until the installer validates it

- **Observed:** The replacement builder began emitting the matrix-derived `driver_modules` list,
  but the Provisioner DTO and release-manifest schema did not consume or validate it.
- **Impact:** The kernel artifact gate still checked modules, so no false package had been produced,
  but installed release metadata could not independently prove the complete hardware contract.
- **Correction:** `driver_modules` is now required and validated alongside unique `VID:PID`
  profiles; an explicitly reused runtime must also match the current source content ID.
- **Never repeat:** For every release-manifest field, update producer, schema, consumer, negative
  tests, and package validator together. Additive JSON output alone is not an accepted contract.

### MTA-OPS-051 — Do not delete and add the same path in one patch

- **Observed (2026-09-01, repository cleanup):** the first README simplification patch described the
  same tracked path as both `Delete File` and `Add File`. The patch engine rejected the complete patch
  before applying any operation; no source or documentation changed.
- **Definitive cause:** a whole-file replacement was expressed as two conflicting operations in one
  atomic patch instead of two individually valid patches.
- **Correction:** delete the exact file in one patch, recreate it in a second patch, and then inspect
  the resulting diff before touching any other path.
- **Never repeat:** one patch may contain only one operation for a given path. Whole-file replacement
  uses separate delete and add patches, with the failed patch treated as producing no evidence.

### MTA-OPS-052 — A local Git fetch needs a real ref and explicit native exit checks

- **Observed (2026-09-01, kernel-repository synchronization):** a temporary clean clone attempted to
  fetch abbreviated commit `a5410f3` from the local product repository as though it were a remote ref.
  Git rejected the fetch. PowerShell's `ErrorActionPreference` did not stop the later native Git
  commands, so the subsequent read-tree and inventory check also failed. The temporary clone remained
  on the unmodified kernel-repository main tree and no remote commit or artifact was created.
- **Definitive cause:** an abbreviated object name was used where fetch requires an advertised ref or
  full refspec, and native process exit codes were assumed to behave like PowerShell terminating errors.
- **Correction:** fetch the exact advertised feature branch, immediately require `$LASTEXITCODE -eq 0`,
  then read its `FETCH_HEAD` subtree. Check every native Git command before using its output.
- **Never repeat:** cross-repository synchronization fetches only a verified branch/tag/full refspec.
  `ErrorActionPreference` is not a native exit-code guard; no dependent command runs until the prior
  native command's exit code is explicitly accepted.

### MTA-OPS-053 — Never poll a process with an unreturned session identifier

- **Observed (2026-09-01, CI wait):** a bounded command returned no session identifier, but a later
  poll used an unrelated numeric value. The process tool rejected it as an unknown process ID.
- **Impact:** no external or repository state changed; one status poll failed and was repeated as a
  fresh read-only GitHub query.
- **Definitive cause:** the absence of a returned session ID was not treated as terminal evidence for
  that tool call.
- **Correction:** poll only an identifier copied verbatim from the immediately preceding command
  result. If none is returned, issue a new bounded read-only status command.
- **Never repeat:** never infer, reuse, or invent process/session identifiers.

### MTA-OPS-054 — Release preflight must prove every retained immutable input

- **Observed (2026-09-01, 0.2.20 release build):** the replacement builder passed kernel
  verification, then stopped because `artifacts/audit-wheelhouse-linux-cp312` was absent. Repository
  cleanup had correctly classified that directory as a retained immutable input, but the release
  preflight did not check it before starting. A generic cross-platform `pip download` could not
  recreate it because `ldn 0.0.17` and `python-netlink 0.0.15` publish only source archives; the
  manifest pins internally built wheels. A first PyPI catalog pass also omitted those transitive
  source-built artifacts. An exact generated-wheel removal command was rejected by the execution
  policy and was not retried.
- **Impact:** no incomplete installer was produced and no installed runtime changed. The first build
  left only an empty release directory and already verified downloaded prerequisites. Recovery used
  the two locally retained wheels whose hashes exactly matched the manifest, while every published
  wheel was retrieved only after its PyPI filename and digest matched the same manifest.
- **Definitive cause:** release readiness was inferred from a clean Git tree and kernel artifact,
  while one required artifact class lived outside Git and had no automatic reconstruction path.
- **Correction:** enumerate all builder inputs before invocation. A wheelhouse is ready only when its
  file set exactly equals `wheelhouse-manifest.sha256` and every digest matches. Source-only pinned
  packages must come from a previously verified retained wheel or a separately versioned,
  reproducible build recipe; never silently replace the manifest with a freshly built wheel hash.
- **Never repeat:** artifact cleanup preserves every input named by the release builder. Run the
  complete input preflight—including kernel, firmware, base rootfs, prerequisites, and wheelhouse—
  before creating a release output directory.

### MTA-QA-016 — Local green is not cross-platform evidence when a fixture observes ambient state

- **Observed (2026-09-01, hardware-matrix candidate):** the complete Windows suite passed locally,
  while GitHub's Ubuntu and Windows jobs exposed six fixture assumptions: a command snapshot was
  taken before its final gate publication, a Windows-only adoption test ran on Linux, a P0 recovery
  fixture touched the runner's real network namespace, a launcher status read required a
  development-only virtual environment, Unicode was compared through an unspecified console
  encoding, and a soak limit counted the clients' fixed startup resources as growth. A bounded
  multi-case rollback simulation also exceeded an outer 90-second CI timeout despite each internal
  operation remaining bounded.
- **Impact:** no product runtime, installer, USB device, or published release changed. CI correctly
  rejected the candidate, but the release was delayed and the local result had overstated portable
  confidence.
- **Definitive cause:** tests mixed the contract under test with scheduler timing, host platform,
  ambient network inventory, console code page, and pre-activation resource baselines.
- **Correction:** wait for the named stable gate before issuing revision-bound commands; skip a
  platform-specific test outside its platform; mock every external recovery probe not under test;
  make status a dependency-free read; compare UTF-8 argument digests through ASCII output; measure
  steady-state growth from an active baseline and final cleanup from the pre-client baseline; size
  only the outer orchestration timeout for the number of already-bounded cases.
- **Never repeat:** a cross-platform release requires both CI operating systems to pass. A test may
  observe only the state named by its contract, and every environment-sensitive dependency must be
  gated, mocked, encoded, or explicitly incorporated into the baseline.

#### Recurrence (2026-09-01, final soak cleanup measurement)

- **Observed:** the exact release candidate transferred all 8,192 RFU frames, bounded its queues,
  released the relay session, and proved both owned `TunnelClient` threads stopped. Windows CI still
  failed because the containing pytest process had six threads at the final sample versus five at
  startup; descriptor use had dropped and no product-owned worker remained alive.
- **Definitive cause:** the test used total threads in the shared pytest process as a second cleanup
  oracle after already checking the exact product-owned thread objects. A runner/plugin thread may
  start independently at any point, so total-process parity cannot identify an owned leak.
- **Correction:** retain the exact `host._thread` and `guest._thread` termination assertions, relay
  live-session zero gate, queue bounds, and descriptor/socket cleanup bounds. Remove only the
  ambient pytest-process thread-count equality assertion.
- **Permanent guard:** resource cleanup tests identify and assert owned resources directly. Shared
  process totals may provide bounded soak telemetry, but they must not be used as an ownership-proof
  terminal gate when the exact owned object is available.

### MTA-QA-017 — A CI stage hidden behind an earlier failure is still unvalidated

- **Observed (2026-09-01, second hardware-matrix CI):** both operating systems passed their full
  functional tests, but Ubuntu then failed ShellCheck on pre-existing code. Earlier CI runs had
  stopped during pytest, so the later lint stage had never supplied green evidence. The findings
  were intentional inner-shell/dpkg expansions, functions invoked indirectly by `EXIT` traps, and
  one combined `export`/`readlink` assignment that masked the command result.
- **Impact:** no runtime or release was published. CI correctly blocked the candidate after its
  functional tests passed.
- **Definitive cause:** successful completion of later CI stages had been inferred from the pipeline
  definition rather than observed on the exact commit.
- **Correction:** add narrow ShellCheck annotations where indirect expansion is the contract, and
  split the `readlink` assignment from `export` so resolution failure is checked. Rerun the complete
  pipeline rather than only the formerly failing test stage.
- **Never repeat:** a release gate is green only when every ordered stage completes on the exact
  candidate SHA. A skipped stage is unknown, not passed.

### MTA-QA-018 — Runtime shell entry points must retain executable mode in Git

- **Observed (2026-09-01, third hardware-matrix CI):** functional tests, shell syntax, and ShellCheck
  passed, but the radio lifecycle simulation exited 126 when it invoked
  `wsl-radio-prepare.sh`. Git tracked that script and its delegated `radio-health-gate.sh` as 0644.
- **Impact:** CI stopped before dependency audit and no release was published. Because the immutable
  appliance copies these files from `git archive`, the same mode would also make the production
  endpoint fail when executing either gate directly.
- **Definitive cause:** executable permission was assumed from the shebang and local Windows
  behavior, while Git's tracked mode—the mode preserved by the Linux release archive—was never
  included in the runtime contract.
- **Correction:** track both direct runtime gate entry points as 0755. Keep the lifecycle simulation
  invoking them exactly as production does, and verify archive/runtime modes during packaging.
- **Never repeat:** every packaged script executed by path must be 100755 in `git ls-files --stage`.
  A shebang without an executable Git mode is not a runnable entry point.

### MTA-DEV-019 — Selecting a leaf kernel driver does not enable hidden Kconfig parents

- **Observed (2026-09-01, first multi-driver kernel run):** `olddefconfig` retained `rtl8xxxu` but
  dropped `mt76x0u`, `mt76x2u`, `rt2800usb`, `RT2800USB_RT35XX`, and `rtw88_8821cu`. The workflow's
  required-option gate stopped before compilation and uploaded no artifact.
- **Impact:** no invalid kernel or installer was produced, and the existing public releases were
  untouched. One remote build run was consumed.
- **Definitive cause:** Microsoft's WSL config disabled the MediaTek, Ralink, and Realtek vendor
  menus. Ralink and rtw88 also have `RT2X00` and `RTW88` menu parents. Writing only the leaf symbols
  cannot satisfy hidden Kconfig dependencies, so `olddefconfig` correctly removed them.
- **Correction:** enable `WLAN` and all three vendor menus, select the `RT2X00` and `RTW88` parents,
  then select the leaf modules. Verify both parents and leaves after `olddefconfig`, and still verify
  the exact built `.ko` artifacts after compilation.
- **Never repeat:** derive every required leaf's full dependency chain from the exact pinned kernel
  Kconfig before dispatching. A config request is not evidence; post-`olddefconfig` symbols and built
  modules are the acceptance gates.

#### Recurrence (2026-09-01, second multi-driver kernel run)

- **Observed:** after the vendor/menu parents were fixed, every Ralink and Realtek symbol survived,
  but `MT76x0U` and `MT76x2U` were still dropped. The workflow again stopped before compilation and
  uploaded no artifact.
- **Definitive cause:** the pinned kernel's `scripts/config` uppercases symbols by default. It wrote
  the nonexistent `MT76X0U`/`MT76X2U` names even though Kconfig defines lowercase `x`. The exact
  source tool documents `--keep-case`; the workflow had not enabled it.
- **Permanent guard:** pass `--keep-case` before every case-sensitive Kconfig symbol and keep the
  exact-case post-`olddefconfig` assertions. Dependency-chain review includes the configuration
  tool's name-normalization behavior, not just Kconfig expressions.

### MTA-DEV-020 — An immutable builder must not inherit its TLS roots from the host distro

- **Observed (2026-09-01, replacement appliance build):** after all pinned inputs passed, the
  disposable Ubuntu Base builder stopped at `cp: cannot stat
  '/etc/ssl/certs/ca-certificates.crt'`. Ubuntu Base intentionally has APT and the Ubuntu archive
  keyring but no generated CA bundle; prior builds had masked the assumption by using an older
  pre-provisioned runtime as the builder rootfs.
- **Impact:** no appliance, installer, installed runtime, USB, relay, or public release changed.
- **Definitive cause:** the appliance script copied a security input from the ambient builder even
  though the builder contract allowed the pinned minimal base rootfs.
- **Correction:** bootstrap only the signed `ca-certificates` package with TLS peer verification
  disabled, relying on APT's pinned Ubuntu archive signing key and signed package hashes for
  authenticity. Confirm the generated bundle, then repeat `apt-get update` and install every runtime
  package with normal TLS verification. No host certificate enters the artifact.
- **Never repeat:** an immutable build consumes only declared pinned inputs. Minimal-rootfs support
  must be exercised directly; ambient host certificates, tools, and provisioned runtime state are
  not valid hidden inputs.

## 14. Maintained evidence index

Use these sources to audit or extend an entry without relying on conversation memory:

- [Development History](DEVELOPMENT_HISTORY.md): early capture, protocol, VM/WSL, radio, installer,
  and product corrections.
- [Known Issues](KNOWN_ISSUES.md): field-observed STB defects and physical acceptance boundaries.
- [Full-stack Audit](AUDIT_REPORT.md) and [Audit Validation](AUDIT_VALIDATION.md): P0/P1 registers,
  cross-layer corrections, regression evidence, and unproven external gates.
- [Production Debug Menu Design](79-production-debug-menu-design-20260828.md): superseded historical
  diagnostic intent and limitations; it is not a current product requirement.
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
- [Single-PC Dual-Adapter Switchless C+D Suite](93-single-pc-dual-adapter-switchless-cd-suite-20260831.md):
  focused remaining C+D qualification scope, exact dual-radio ownership, exclusions, fault matrix,
  and claim boundary.
- [Production Wrapper and Beta Cutover](94-production-wrapper-beta-cutover-20260831.md): current
  one-radio, no-AI runtime decision; M8-M10 mini plan; support-log export and beta acceptance boundary.
- [Future TODO](FUTURE_TODO.md): current implementation and qualification debt.
- Installer [issue register](installer/ISSUE_REGISTER-20260827-installer-engine.md),
  [error catalog](installer/ERROR_CATALOG-20260827.md), and
  [recovery runbook](installer/RECOVERY_RUNBOOK-20260827.md): detailed setup transaction evidence.

Raw support bundles and run recovery files remain local/private. They may substantiate an entry but
must not be added to the repository.
