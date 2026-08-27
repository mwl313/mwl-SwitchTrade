# SwitchTrade installer engine overhaul handoff

Date: 2026-08-27

Prepared for: DeepSeek Harness / DeepSeek engineering agent

Repository: `mwl313/mwl-SwitchTrade`

Working branch: `audit`
Known-good bug-fix checkpoint: `ee6379c` (`fix(installer): preserve inline WSL shell arguments`)

## 1. Mission

Redesign the SwitchTrade installation engine so that Install, reboot continuation, Repair, Update,
Rollback, and Uninstall converge reliably from every supported and interrupted state. Do not continue
the current pattern of adding one exception for each newly observed machine state. First model the
complete lifecycle, freeze its safety requirements in executable tests, then replace the high-risk
coupling in controlled slices.

The final product must install on a supported Windows PC that has no WSL installation, preserve
unrelated user WSL distributions and configuration, install the isolated SwitchTrade runtime and
packaged custom kernel, install the native desktop application, and recover automatically after a
required reboot or interrupted process. A normal user must not need to understand WSL, PowerShell,
`usbipd-win`, kernel modules, distro registration, transaction files, or package extraction paths.

This is an installer architecture and reliability task. It is not a general application rewrite.

## 2. Supported beta boundary

- Windows 10 22H2 x64 build 19045 and supported Windows 11 x64 builds.
- Current Microsoft Store WSL2 runtime.
- The packaged SwitchTrade custom WSL kernel and module/firmware artifacts.
- Per-user native WPF application installation.
- The installer-owned isolated WSL distribution named `SwitchTrade` by default.
- RTL8192EU `0bda:818b` as the production-qualified adapter target.
- Adapter setup may be deferred; software installation must still commit coherently.
- Existing unrelated WSL distributions, user data, and non-SwitchTrade `.wslconfig` content must be
  preserved.

Out of scope for this overhaul:

- Privacy/analytics UI.
- Visual redesign of the main SwitchTrade application.
- Relay, RFU, FireRed/LeafGreen protocol, or trading behavior changes.
- A new kernel or new radio driver implementation.
- Code signing.
- Physical Switch qualification. The installer must be ready for it, but simulation must not be
  reported as physical validation.

## 3. Read these files before changing code

Primary execution and state logic:

1. `installer/SwitchTradeSetup.ps1`
2. `installer/SetupLifecycle.ps1`
3. `installer/KernelLifecycle.ps1`
4. `installer/HostCompatibility.ps1`
5. `installer/PackageIntegrity.ps1`
6. `installer/Build-Package.ps1`
7. `installer/Build-Rootfs.sh`
8. `installer/provision-wsl.sh`
9. `installer/Launch-SwitchTrade.ps1`
10. `installer/UsbAutoAttachWatcher.ps1`

Native Setup UI and elevation boundary:

1. `installer/bootstrap/Program.cs`
2. `installer/bootstrap/SetupDialog.cs`
3. `installer/bootstrap/SetupProgressDialog.cs`
4. `installer/bootstrap/app.manifest`

Existing lifecycle tests and audit evidence:

1. `installer/Test-SetupLifecycle.ps1`
2. `installer/Test-RollbackRecoveryLifecycle.ps1`
3. `installer/Test-KernelLifecycle.ps1`
4. `tests/test_installer_lifecycle.py`
5. `tests/test_package_reproducibility.py`
6. `tests/test_kernel_workflow_source.py`
7. `docs/KNOWN_ISSUES.md`
8. `docs/AUDIT_REPORT.md`
9. `docs/AUDIT_VALIDATION.md`

Do not infer behavior from comments or source-string tests alone. Trace the actual native Setup EXE,
elevation, PowerShell process, WSL process, Linux provisioning script, transaction persistence, UI
resume, and rollback paths end to end.

## 4. Immediate defect that was fixed before this handoff

The interrupted installation was at transaction phase `importing_distro`. The exact imported WSL
distribution existed at the recorded Lxss `BasePath`, but `/etc/switchtrade-distro.json` was absent.
Repair correctly recognized the narrow marker-bootstrap state and called
`Set-SwitchTradeDistroInstallId`, then failed with:

```text
DISTRO_INSTALL_ID_WRITE_FAILED
Stage: transaction_recovery
```

Root cause: inline Linux shell commands were launched as:

```text
wsl.exe ... -- sh -c <command> <arguments>
```

On the tested Store WSL runtime, the extra command-shell layer consumed Linux `$p`, `$1`, and similar
expressions before the intended `sh -c` received them. A read-only runtime probe proved:

```text
--      => p=<> arg=<>
--exec  => p=<sentinel-path> arg=<sentinel-123>
```

Commit `ee6379c` changed all five inline `sh -c`/`sh -lc` call sites to `--exec`, retained the existing
atomic marker write, and added the real subprocess error text to `DISTRO_INSTALL_ID_WRITE_FAILED`.
It also added a source regression that prevents inline shell calls from returning to the unsafe
boundary. Local validation passed:

- PowerShell parse.
- Installer pytest: 16 passed.
- PowerShell 5.1 lifecycle simulation.
- A real read-only WSL variable/positional-argument round trip.

This is a necessary blocker fix, not the requested installer overhaul. Other `wsl.exe` calls still
use scattered invocation patterns and must be reviewed individually. Do not blindly replace every
`--` token; classify each command and test its actual argument contract.

## 5. Current interrupted machine state

At handoff preparation time, the development PC retained this recoverable transaction:

```text
schema:          3
transaction_id:  0de33eb15e6e497f94aeed5fab018a64
action:          Install
release_id:      beta-5b2c414
phase:           importing_distro
install_id:      45dce0debfb0470dbb17ffb3a1a2c717
distro_name:     SwitchTrade
distro_root:     %LOCALAPPDATA%\SwitchTrade\wsl
```

The named WSL distribution is registered at the exact recorded root. Its `/etc` is writable and the
filesystem is nearly empty. Both `/etc/switchtrade-distro.json` and its temporary file were absent
when inspected. The distribution was terminated after the read-only probe. Do not unregister it or
delete the transaction to make tests pass. This state is valuable real-world recovery evidence.

The next package should first prove recovery against a disposable equivalent, then its Repair action
should safely bootstrap the exact marker and continue. A foreign distro, different BasePath,
malformed marker, mismatched install ID, or committed prior runtime must remain fail-closed.

## 6. Why architectural work is required

The current implementation has safety structure, but the orchestration boundary has become too
large and implicitly coupled:

- `installer/SwitchTradeSetup.ps1`: about 1,751 lines, 23 functions, 246 `if` statements, and 22
  `try` statements at the checkpoint preceding this handoff.
- `installer/SetupLifecycle.ps1`: about 1,218 lines and 45 functions.
- `Repair-SwitchTradeInterruptedTransaction` spans roughly lines 589-930 and combines inspection,
  ownership decisions, planning, filesystem mutation, WSL execution, and logging.
- Several functions implicitly consume script-level variables such as `$Distro`, `$DistroRoot`,
  `$StateRoot`, `$PackageRoot`, `$InstallRoot`, `$SetupLog`, `$Action`, and `$TransactionPath`.
- WSL commands are composed at many call sites. At the measured checkpoint there were 38 literal
  `--` occurrences and no common explicit-exec policy before `ee6379c`.
- Native process errors are not represented uniformly.
- Some Python tests assert that source strings exist instead of verifying lifecycle behavior.
- State simulations are valuable but did not exercise real `wsl.exe` command parsing, which allowed
  the install-ID failure to escape.

This is best described as a structured procedural monolith with high hidden coupling. It is not a
reason to discard the proven transaction and ownership rules. It is a reason to establish explicit
boundaries and make the state machine executable and observable.

## 7. Existing behavior that must be preserved

Do not regress these properties while restructuring:

1. Package integrity is validated before host mutation.
2. A global Setup mutex prevents concurrent mutation.
3. Every transaction binds a package release and manifest identity.
4. Windows application, WSL runtime, kernel selection, configuration, and rollback metadata publish
   one coherent software release or compensate coherently.
5. Hardware readiness is separate from software commit and may be deferred.
6. A WSL distribution is mutated or unregistered only when its name, exact registered BasePath,
   installer marker, and per-install ID satisfy the applicable ownership gate.
7. A same-name foreign distribution and a copied ownership marker fail closed.
8. WSL enumeration failure is unknown, never equivalent to “absent.”
9. User `.wslconfig` content outside the owned SwitchTrade block is preserved byte-for-byte where
   practical and restored on rollback/uninstall.
10. Existing unrelated WSL distributions are never reset or unregistered.
11. Existing project databases and user application data are not deleted by installer recovery.
12. Non-ASCII usernames, spaces, per-user profile paths, and elevation from a standard user retain
    the invoking user's identity and paths.
13. Reboot continuation is durable, visible, and uses the same transaction/package identity.
14. Rollback validates the retained Windows, WSL, kernel, and configuration generations before the
    first reverse mutation.
15. Logs redact credentials, tokens, authorization headers, secrets, and unrelated machine data.
16. An unsigned private-beta package is explicitly identified as such; integrity checks are not
    silently disabled.

## 8. Required target design properties

The exact file/module layout is open to review, but the resulting design must expose these distinct
responsibilities. Do not create interfaces or factories with only one consumer unless they remove a
real test or safety problem.

### 8.1 State inspector

One read-only component collects a normalized snapshot of:

- Host OS/build/architecture and pending reboot state.
- WSL command/runtime/version/capabilities.
- WSL feature state and Store runtime availability.
- SwitchTrade distro enumeration, registry identity, BasePath, marker, install ID, and runtime trees.
- Persisted transaction, committed release, previous release, kernel state, `.wslconfig`, RunOnce,
  Windows installation trees, shortcuts, and installed release configuration.
- `usbipd-win` capability and adapter inventory without mutating ownership.

It must distinguish absent, present, invalid, incompatible, foreign, inaccessible, timed out, and
unknown. It must not “repair while inspecting.”

### 8.2 Pure planner

A deterministic planner consumes requested action + verified package identity + normalized snapshot
and returns either:

- An ordered, explicit mutation plan with preconditions, checkpoints, compensation, and terminal
  state; or
- A stable structured blocker with stage, error code, recovery action, and evidence.

The planner must be testable without Windows, WSL, administrator rights, or real files. Identical
inputs must produce identical plans.

### 8.3 Transaction executor

One executor applies a previously validated plan. Each mutating step must:

1. Revalidate the identity it is about to mutate.
2. Persist intent/checkpoint before irreversible mutation where required.
3. Use bounded subprocesses with cancellation and captured stdout/stderr.
4. Record structured progress and a correlation ID.
5. Persist completion before advancing.
6. Be idempotent when replayed after process death.

Compensation must be modeled as explicit persisted work, not a best-effort catch block.

### 8.4 Platform operations

Centralize low-level operations for:

- Native process execution and quoting.
- WSL capabilities, distribution import/export/terminate/unregister, and Linux command execution.
- Windows features and Store WSL installation/update/reboot continuation.
- Windows application release staging/swap and shortcut management.
- Kernel artifact application and `.wslconfig` ownership.
- `usbipd-win` installation and optional hardware preparation.

All WSL calls must route through one audited boundary. Prefer direct executable + argument arrays
with `--exec`. Avoid `sh -c` for data-bearing commands; when a shell is genuinely required, pass
constant script text and data as positional parameters or a verified script file, never by string
concatenation. Tests must cover quotes, Unicode, spaces, JSON, `$`, backslashes, and empty arguments.

### 8.5 Native Setup UI

The native Setup EXE should select only actions valid for the inspected state, launch one engine
operation, and render its structured progress. It must not independently reimplement lifecycle
decisions. After reboot, the same GUI must reopen, identify the transaction, explain the current
stage, and continue or offer the one safe recovery action.

Long PowerShell exception dumps must stay in logs/technical details. Normal dialogs should show a
stable code, plain-language reason, current stage, and exact user action.

## 9. Required migration approach

Do not perform a blind rewrite. A new implementation that lacks parity tests is less safe than the
current monolith.

1. Freeze the current observed behavior and safety invariants in black-box fixtures before moving
   code.
2. Build a normalized install-state model and pure planner alongside the current executor.
3. Route all native/WSL subprocesses through one boundary and add real argument round-trip tests.
4. Convert one lifecycle action at a time, starting with Audit/inspection, then fresh Install,
   interrupted Install/Repair, Update, Rollback, and finally Uninstall.
5. At each slice, run old and new planning against the same state fixtures and review differences.
6. Remove old branches only after the corresponding black-box scenarios pass through the native
   Setup entry point.
7. Keep commits small enough to review, but group changes by architectural boundary rather than by
   individual symptom.

If discovery proves that a replacement engine is safer than extracting the PowerShell monolith,
document the decision and preserve the same on-disk transaction compatibility or provide a proven,
fail-closed migration. Do not strand existing interrupted installations.

## 10. Mandatory state and fault matrix

Automate at least the following. Tests that only search source text do not satisfy these scenarios.

### Host and prerequisites

- Clean Windows 10 and Windows 11 fixtures with no WSL feature/runtime.
- WSL command stub present but functional runtime absent.
- WSL feature enabled but reboot pending.
- Old Store WSL requiring update; update timeout; offline prerequisite path.
- Virtualization disabled or unsupported.
- UAC declined, standard-user launch, administrator launch, and invoking-user profile handoff.
- Non-ASCII username, spaces, long path, missing directory, readonly directory, and low disk.
- Existing malformed/comment-heavy/CRLF `.wslconfig`, and policy-blocked configuration.

### Distribution identity

- No named distro.
- Exact newly imported distro with generic marker.
- Process death immediately after import, before marker write.
- Exact markerless fresh import at the recorded BasePath.
- Malformed/unreadable marker.
- Correct marker with wrong install ID.
- Same distro name at a foreign BasePath.
- Copied marker on a foreign distribution.
- CLI/registry enumeration disagreement or timeout.
- Other user distributions present throughout all actions.

### Transaction lifecycle

- Kill the engine before and after every mutating stage and every persisted checkpoint.
- Reopen using the original action, explicit Repair, and a byte-identical re-extracted package.
- Reject an unrelated or modified package from taking over an unsafe transaction.
- Fresh Install, existing Install, Repair, Update, failed Update, forward compensation, Rollback,
  interrupted Rollback, reverse Rollback, Uninstall, interrupted Uninstall, and reinstall.
- Setup mutex contention and stale process/UI termination.
- Corrupt, truncated, schema-old, and future-schema transaction records.
- Existing `.previous`, `.candidate`, commit-swap, rollback-swap, recovery, and orphan trees.

### WSL/native command boundary

- Exact argv round trip using real `wsl.exe --exec` when WSL is available.
- JSON, Unicode, spaces, quotes, dollar signs, backslashes, empty strings, and paths ending in a
  backslash.
- Timeout, nonzero exit, stdout-only failure, stderr-only failure, cancellation, and child cleanup.
- Linux shell variables and command substitutions execute in Linux exactly once.
- Logs contain useful failure evidence but redact protected material.

### Release coherence

- Windows active/candidate/previous releases disagree with WSL and kernel axes.
- Package manifest, installed integrity manifest, WSL integrity, kernel metadata, or retained rollback
  artifacts are missing or tampered.
- Crash between each Windows/WSL/kernel/config swap and final publication.
- A completed state exposes one release ID and compatible capability set everywhere.

### Hardware separation

- Adapter absent with deferred hardware setup.
- Adapter present, unshared, shared, attached, stale bus ID, duplicate identical adapters, and
  VMware/WSL ownership conflict.
- Hardware failure cannot roll back or corrupt a coherently installed software release.
- Repair can target hardware readiness without silently replacing software generations.

## 11. Required tests and execution layers

Use multiple levels because no single test environment covers installer behavior:

1. Pure planner unit tests over serialized state fixtures.
2. Filesystem transaction simulations in isolated temporary roots.
3. Native-process and quoting tests in Windows PowerShell 5.1 and PowerShell 7.
4. Disposable WSL distro integration tests using a unique test name and root. Never point destructive
   tests at `SwitchTrade`, `Ubuntu`, the workspace root, or a user's normal distro.
5. Process-death/fault-injection tests launched through separate processes.
6. Native Setup EXE tests for action selection, elevation, progress, reboot continuation, and error
   presentation.
7. Clean Windows 10 and Windows 11 VM lifecycle qualification.
8. Deterministic package build and manifest/hash verification from a clean commit.

Every discovered P0/P1 defect requires a regression test that fails on the defect and passes on the
correction. Environment-dependent skips must state exactly which external gate owns the missing
validation.

## 12. Error and progress contract

Every failure crossing into the Setup UI must carry at least:

```text
code
message
stage
recoverable
primary_action
correlation_id
technical_detail_log_path
```

Do not infer recovery from localized WSL text or English exception strings. Localization may affect
displayed text, never control flow. Unknown capability/enumeration state must fail closed without
destructive mutation.

Progress must report meaningful phases such as prerequisite inspection, Windows feature enablement,
reboot required, WSL runtime update, distro import, runtime staging, kernel staging, validation,
commit, compensation, hardware preparation, and completion. The GUI must reopen after reboot and
continue showing this progress.

## 13. Security and destructive-action rules

- Resolve and verify exact absolute targets before recursive delete, move, unregister, or rollback.
- Never recursively target `%USERPROFILE%`, `%LOCALAPPDATA%`, `%ProgramData%`, a workspace root, `/`,
  `$HOME`, or an unresolved variable.
- Never unregister a distribution using its name alone.
- Never treat a marker copied from another installation as sufficient ownership.
- Preserve unrelated application data and user distributions.
- Verify package integrity before executing packaged scripts or importing artifacts.
- Keep relay credentials, reconnect/member tokens, key material, and authorization headers out of
  logs and support bundles.
- Do not weaken a fail-closed ownership gate merely to make a broken test state installable.

## 14. Acceptance criteria

The overhaul is complete only when all of the following are true:

- No open software-verifiable installer P0/P1 issue.
- Install, reboot/resume, Repair, Update, Rollback, Uninstall, and reinstall converge from the full
  automated state matrix.
- Fault injection at every mutating stage leaves either the prior coherent release, the new coherent
  release, or a precisely recoverable persisted transaction.
- No failure leaves mixed Windows/WSL/kernel/config revisions published as healthy.
- A clean Windows 10 and Windows 11 VM can install from no WSL, reboot, resume in the GUI, launch the
  application, Repair, Update/Rollback where applicable, Uninstall, and reinstall.
- Existing unrelated WSL distributions and user `.wslconfig` content survive byte-for-byte checks
  outside the owned block.
- The exact markerless-import state described above recovers without manual reset or unregister.
- Foreign/mismatched distro states fail closed without mutation.
- All real WSL command-boundary tests pass with Unicode and shell-sensitive arguments.
- The native Setup EXE shows concise progress and recovery; raw exception dumps remain in technical
  details/logs.
- Root pytest, PowerShell 5.1/7 lifecycle tests, .NET builds/self-tests, shell checks, dependency
  checks, and package verification pass from a clean locked environment.
- The final EXE, Setup EXE, rootfs, kernel payload, manifest, and ZIP are built from one clean commit
  and their hashes are recorded.

Hardware and two-Switch tests may remain “fix ready for physical validation,” but the installer must
not claim physical success based on simulation.

## 15. Expected deliverables from the DeepSeek pass

1. A read-only discovery report and issue register before implementation begins.
2. A concise architecture decision record explaining extraction versus replacement and transaction
   compatibility.
3. The normalized state model, planner, executor boundaries, and centralized platform operations.
4. Migration of every lifecycle action with old code removed after parity.
5. The complete automated matrix and retained failure fixtures/seeds.
6. Updated installer technical documentation, error catalog, recovery runbook, and package build
   instructions.
7. Clean, reviewable commits grouped by subsystem or lifecycle boundary.
8. Final validation report distinguishing automated, clean-VM, hardware, and physical Switch evidence.

Do not push, publish a release, unregister the live development distro, delete the existing
transaction, or modify unrelated untracked files unless the owner explicitly authorizes it.

## 16. First actions for the next agent

1. Confirm `audit` contains `ee6379c` and record the exact starting commit.
2. Keep the unrelated untracked `scripts/build-capture-evidence-bundle.py` out of installer commits.
3. Inspect the live state read-only and serialize a redacted fixture representing the current
   `importing_distro` interruption.
4. Trace all native Setup-to-PowerShell and PowerShell-to-WSL command paths.
5. Produce the discovery issue register and architecture decision before editing.
6. Freeze the destructive-action invariants and state matrix in tests.
7. Begin extraction at the subprocess/WSL boundary and state inspector, then migrate lifecycle
   actions in the order defined above.

The desired outcome is not merely “this PC installs.” It is an installer whose state transitions are
explicit, testable, restart-safe, and deterministic on every supported PC, and whose failures tell a
normal user exactly what happened without requiring manual WSL intervention.
