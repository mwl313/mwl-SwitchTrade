# Architecture decision: installer engine extraction (2026-08-27)

Status: accepted
Scope: installer engine overhaul per handoff/HANDOFF-20260827-installer-engine-overhaul.md
Branch: audit (starting commit 2cde52f; known-good bug-fix checkpoint ee6379c is an ancestor)

## Context

The installer engine (SwitchTradeSetup.ps1 + SetupLifecycle.ps1 + KernelLifecycle.ps1 +
PackageIntegrity.ps1 + HostCompatibility.ps1) is a structured procedural monolith with high
hidden coupling (section 6 of the handoff):

- ~1,751 + ~1,218 lines, ~68 functions, many consuming script-level variables ($Distro,
  $DistroRoot, $StateRoot, $PackageRoot, $InstallRoot, $SetupLog, $Action, $TransactionPath).
- WSL commands composed at ~38 call sites with mixed `--` / `--exec` / `sh -c` / `sh -lc`
  patterns; inline shell strings interpolated with data (kernel module extraction, module
  verification, runtime-state probes).
- Native process errors are not uniform (ProcessStartInfo wrapper in SetupLifecycle.ps1 plus
  Start-Process call sites, plus raw & calls in preflight).
- Repair-SwitchTradeInterruptedTransaction combines inspection, ownership decisions, planning,
  filesystem mutation, WSL execution, and logging in one function (~340 lines).
- Several Python tests assert source strings instead of lifecycle behavior; state simulations
  did not exercise real wsl.exe argument parsing (this allowed DISTRO_INSTALL_ID_WRITE_FAILED
  to escape, fixed by ee6379c).

## Decision

EXTRACTION, not replacement. Keep PowerShell 5.1 as the engine runtime (guaranteed on every
supported Windows 10/11 host; the native Setup EXE already launches powershell.exe -NoProfile
-NonInteractive -ExecutionPolicy Bypass -File). Build a layered engine alongside the current
executor, route every native/WSL subprocess through one audited boundary, then migrate
lifecycle actions one slice at a time, removing old branches only after black-box parity.

Rationale for extraction over replacement:

1. The proven safety logic (schema-3 transaction, ownership gates, integrity anchors,
   rollback journal, compensation planners) is already largely pure and deterministic
   (Resolve-SwitchTradeTransactionRecovery, Resolve-SwitchTradeRollbackRecovery,
   Assert-SwitchTradeDistroMutationIdentity). Rewriting it in another language (C# in the
   bootstrap, or Python) duplicates ~3,000 lines of fail-closed logic with high drift risk and
   no existing test harness; PowerShell keeps the existing Test-*.ps1 simulation and
   ParseFile CI gates.
2. On-disk compatibility is preserved: schema-3 setup-transaction.json (same phase names,
   paths, and fields), /etc/switchtrade-distro.json marker (schema 1/2), .switchtrade-release.json
   / .switchtrade-integrity.json anchors, kernel-state.json, setup-resume.json, rollback journal
   (schema 2), RunOnce continuation. The existing interrupted transaction on the development PC
   (phase importing_distro, markerless fresh import at the recorded BasePath) remains recoverable
   by the new engine; no migration of persisted state is needed.
3. The native Setup EXE boundary stays unchanged in contract: it already delegates lifecycle
   decisions to the engine (it only sniffs state for the action combobox) and consumes the
   SWITCHTRADE_SETUP_PROGRESS: / SWITCHTRADE_SETUP_FAILURE: line protocol. The engine will
   enrich the failure contract (code, message, stage, recoverable, primary_action,
   correlation_id, technical_detail_log_path) without changing the wire format.

## Target engine layout (installer/engine/)

    installer/engine/PlatformOps.ps1   - one audited boundary for every native process and WSL call:
                                          command-line quoting (exact argv), bounded subprocess with
                                          cancellation and captured stdout/stderr, wsl.exe wrappers
                                          (--exec policy; constant script text + positional args;
                                          never data in a shell string), provision-wsl.sh invocations,
                                          registry/feature/msi operations.
    installer/engine/StateInspector.ps1 - read-only normalized snapshot (absent | present | invalid |
                                          incompatible | foreign | inaccessible | timed_out | unknown)
                                          of host, WSL runtime, distro identity, transactions,
                                          releases, kernel, .wslconfig, RunOnce, usbipd inventory.
                                          Never "repairs while inspecting".
    installer/engine/Planner.ps1        - deterministic pure planner: requested action + verified
                                          package identity + snapshot -> explicit ordered mutation
                                          plan (preconditions, checkpoints, compensation, terminal
                                          state) OR stable structured blocker (stage, code, recovery
                                          action, evidence). Identical inputs -> identical plans.
                                          Testable without Windows/WSL/admin/real files.
    installer/engine/Executor.ps1       - applies a previously validated plan: revalidates identity
                                          before each mutation, persists intent/checkpoint before
                                          irreversible mutation, bounded cancellable subprocesses,
                                          structured progress + correlation id, persists completion
                                          before advancing, idempotent replay after process death.
                                          Compensation is explicit persisted work (transaction
                                          phases), never a best-effort catch block.
    installer/engine/Errors.ps1         - error catalog and the failure contract
                                          (code, message, stage, recoverable, primary_action,
                                          correlation_id, technical_detail_log_path); redaction stays
                                          centralized.

Entry point SwitchTradeSetup.ps1 keeps its public parameter surface and becomes: validate
arguments -> load engine -> (Audit: inspect and print) -> enter mutex -> inspect -> plan ->
execute -> report. The native EXE and the Resume/RunOnce contract are unchanged.

## Migration slices (order per handoff section 9)

1. Audit/inspection through StateInspector (read-only; lowest risk).
2. Platform boundary: convert every native/wsl call site to PlatformOps; add real argv
   round-trip tests (wsl.exe --exec when available) plus quoting/Unicode/space/backslash/
   empty-argument tests.
3. Fresh Install (and Update, which shares the same pipeline) through Planner + Executor.
4. Interrupted Install/Repair through the recovery planner (port of
   Resolve-SwitchTradeTransactionRecovery + marker-bootstrap + rollback recovery).
5. Rollback through the journal planner.
6. Uninstall through the destructive-action planner.
Old branches are removed only after the corresponding black-box scenarios pass through the
native Setup entry point (Test-SetupLifecycle.ps1, Test-RollbackRecoveryLifecycle.ps1,
Test-KernelLifecycle.ps1, pytest, PS5.1/7 parse, PS5.1/7 lifecycle simulation).

## Transaction compatibility contract

- setup-transaction.json schema 3 stays byte-compatible: same fields, same phase vocabulary
  (created, windows_staged, importing_distro, distro_imported, staging_wsl, wsl_staged,
  software_validated, kernel_applied, wsl_committed, completed, compensated, uninstalled,
  rollback_prepared, rollback_wsl_committed, rollback_kernel_committed,
  rollback_windows_committed, rollback_recovering_source/target, compensating_*).
- The live development-PC transaction (0de33eb1..., phase importing_distro, install_id
  45dce0de...) must be recoverable by the new engine: markerless fresh import at the recorded
  BasePath -> atomic marker write (wsl --exec, data as positional args) -> continue staging.
- Foreign/mismatched distro states, legacy (schema < 3) transactions, and modified packages
  fail closed exactly as today.

## Non-goals for this pass

- Clean Windows 10/11 VM qualification and physical Switch validation remain external gates;
  the automated + simulation layers are executed here, and the final validation report
  distinguishes evidence layers honestly.
- The native EXE visual redesign, analytics, signing, kernel/radio work are out of scope.

## Consequences

- Lower risk of behavior drift than a rewrite; every slice is test-gated.
- PowerShell keeps being the engine language (5.1), which the CI already parses and simulates.
- The monolith shrinks as slices land; dead switches and hidden script-level coupling are
  removed with the old branches (e.g. -PurgeDistro is dead plumbing and will not be carried
  into the planner surface).
- New failures surface through the structured failure contract with a stable code and a
  technical_detail_log_path so the EXE can act on recoverability and point users at the log.
