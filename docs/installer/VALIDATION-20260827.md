# Installer engine overhaul: validation report (2026-08-27)

Evidence is strictly layered: automated and simulation results below were executed on the
development PC; clean-VM and physical Switch validation remain external gates and are NOT
claimed by any simulation.

## Repository state

- Branch: audit. Starting commit 2cde52f; handoff checkpoint ee6379c is an ancestor.
- Commits added by this pass:
  - e3c8b02 docs(installer): discovery issue register + architecture decision + live fixture
  - 41d1315 feat(installer): centralized native/WSL subprocess boundary
  - d9ff5b8 feat(installer): state inspector, pure planner, transaction executor
  - a3b6506 refactor(installer): all lifecycle actions routed through the engine entry point
- scripts/build-capture-evidence-bundle.py was never staged. No push, no release, no live
  distro mutation, no transaction deletion.

## Architecture decision

EXTRACTION (not replacement): PowerShell 5.1 engine modules (engine/PlatformOps.ps1,
StateInspector.ps1, Planner.ps1, Executor.ps1) with byte-compatible schema-3 transactions,
phase vocabulary, markers, journal, and RunOnce continuation. See
ARCHITECTURE-20260827-installer-engine.md.

## Automated results (executed 2026-08-27)

| Suite | Result |
|---|---|
| installer pytest (test_installer_lifecycle.py, test_package_reproducibility.py, test_kernel_workflow_source.py) | 23 passed |
| Full pytest | 307 passed, 4 skipped, 6 pre-existing environment failures (relay/bridge trio recv decode skew; reproduced on the clean base tree with changes stashed) |
| Test-EngineBoundary.ps1 (real wsl.exe argv round trips on a disposable distro) | PASS PS5.1 + PS7 |
| Test-EnginePlanner.ps1 (legacy parity + live fixture recovery) | PASS PS5.1 + PS7 |
| Test-RollbackRecoveryLifecycle.ps1 (7 process-death points through the engine) | PASS PS5.1 + PS7 |
| Test-SetupLifecycle.ps1 / Test-KernelLifecycle.ps1 (legacy libraries) | PASS PS5.1 + PS7 |
| SwitchTradeSetup.ps1 -Action Audit | PASS, read-only, full normalized state |
| Failure marker (Install with incomplete package) | PASS: SWITCHTRADE_SETUP_ERROR: PACKAGE_MANIFEST_MISSING + full failure JSON |
| PS5.1 / PS7 parse of every .ps1 (CI gate equivalent) | PASS |
| Live read-only machine state | Transaction 0de33eb1... phase importing_distro verified intact; distro registration/marker/probes confirmed; fixture serialized redacted |

## What this pass proves

- The exact markerless-import interruption (live fixture) is recognized by both the legacy and
  the engine marker-bootstrap gates; the engine recovery plan bootstraps the marker and
  continues the verified package to completion (no manual reset or unregister).
- All six lifecycle actions (Audit, Install, Repair, Update, Rollback, Uninstall) plus reboot
  continuation route through the new engine; the legacy monolith branches are removed.
- Every native/WSL subprocess runs through one audited boundary with exact argv; data never
  travels inside shell strings; real wsl.exe --exec round trips pass with Unicode, spaces,
  quotes, $, $(), backticks, backslashes, empty strings, and JSON.
- Compensation is explicit persisted work: process death at any crash point leaves the
  transaction at the checkpoint, and Repair converges deterministically (verified for rollback
  through real separate-process deaths; verified for the forward path through the planner
  parity matrix and legacy simulations).
- The failure contract carries code/message/stage/recoverable/primary_action/correlation_id/
  technical_detail_log_path.

## External gates still required (not claimed by this pass)

- Clean Windows 10 and Windows 11 VM lifecycle: Install from no WSL -> reboot -> resume in the
  GUI -> Repair -> Update -> Rollback -> Uninstall -> reinstall.
- UAC cancellation behavior, low disk, and virtualization-off on clean VMs.
- Physical Switch qualification with the RTL8192EU adapter (including cold WSL start, attach,
  and RX validation) and Windows 10 usbipd attach state.
- A signed release build with recorded artifact hashes from one clean commit (the unsigned
  private-beta path was not re-built here; package verification tests pass).

## Remaining known parity/hardening items (tracked in the issue register)

- I-09: usbipd capability deep-validation (version/help/state) is not re-run by the engine
  after install; surfaced at hardware time by the preflight script.
- I-13/I-18: WSL feature state reads require elevation (WslFeaturesEnabled false when
  unreadable); runtime launch-safety classification remains heuristic.
- I-23/I-24/I-25/I-26: launcher relay-URL argv validation, watcher PATH resolution, .wslconfig
  escaping, and duplicate hashing helpers are consolidation candidates for later slices.
- SetupLifecycle.ps1 remains as the USB watcher's dependency and the parity reference; the
  engine no longer requires it.
