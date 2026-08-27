# Installer engine discovery: issue register (2026-08-27)

Read-only discovery for handoff/HANDOFF-20260827-installer-engine-overhaul.md. Every issue was
verified by reading the actual code and (where noted) by live read-only probes on the
development PC. Evidence is cited as file:line at commit 2cde52f.

Severity: P0 = release blocker / data loss risk; P1 = must fix in this overhaul;
P2 = improvement; P3 = cleanup.

## P0

### I-01 WSL command boundary is not uniform; inline shell strings carry data (partial fix landed)
Multiple call sites compose Linux commands as PowerShell string interpolation into `sh -c` /
`sh -lc` and pass them through wsl.exe. ee6379c converted five call sites to `--exec` with
positional arguments and added a source regression, but the following data-bearing inline
shells remain and must be reworked through one audited boundary (PlatformOps):

- SwitchTradeSetup.ps1:362-365 Get-SwitchTradeWslRuntimeState builds `sh -lc $probe` with
  `-f` interpolation of the probe path (constants only today, but shell-string composition
  with no escaping).
- SwitchTradeSetup.ps1:1566-1569 kernel module extraction: `sh -lc` with $modulesWsl
  (a /mnt/c/... path derived from the package location) and the kernel release interpolated.
  A package path containing spaces or `$` produces a corrupt Linux command
  (KERNEL_MODULE_INSTALL_FAILED) — unicode/space path bug candidate on real machines.
- SwitchTradeSetup.ps1:1578-1583 module verification: same pattern with the kernel release
  interpolated into the shell string.
- SwitchTradeSetup.ps1:244-247 marker read uses `--exec sh -c` with a constant script; no
  data interpolation but a shell wrapper that need not exist.
- Set-SwitchTradeDistroInstallId (SwitchTradeSetup.ps1:315-330) is the fixed pattern to
  generalize: constant script text + data as positional parameters.

Required fix (handoff 8.4): all WSL calls route through one audited boundary; data-bearing
commands use `--exec` with argv; when a shell is genuinely required, pass constant script
text and data as positional parameters; tests must cover quotes, Unicode, spaces, JSON, `$`,
backslashes, and empty arguments.

### I-02 Unbounded/uncancellable and inconsistent subprocess paths
- Invoke-BoundedNativeProcess (SetupLifecycle.ps1:28-59) is correct in spirit (argv array ->
  quoting -> timeout -> kill) but has no cancellation token, no output size cap, and output
  decoding depends on the console encoding (wsl.exe Store output is UTF-16; call sites
  compensate with NUL-stripping, e.g. SwitchTradeSetup.ps1:1036).
- Start-Process is used with argument arrays whose quoting is NOT guaranteed:
  Test-StagedControlReadiness (SwitchTradeSetup.ps1:984) and radio health
  (SwitchTradeSetup.ps1:1708-1714); Start-Process -ArgumentList joins tokens with spaces.
- Native Setup UI's radio detection (bootstrap/SetupDialog.cs:278-280) calls
  ReadToEnd() before WaitForExit(5000): a hanging usbipd.exe blocks the dialog forever
  and the process is never killed.

### I-03 Failure contract is incomplete and the UI cannot act on it
The PS trap (SwitchTradeSetup.ps1:34-65) emits code/message/stage/recoverable/primary_action/
action/correlation_id but the EXE reads only code/message/stage/action/primary_action
(bootstrap/Program.cs:241-246); recoverable is never read; technical_detail_log_path does not
exist anywhere; correlation_id is never surfaced. UAC decline (Program.cs:197-200) exits 1223
silently with no message. The GUI shows no recovery buttons — primary_action is text only.

### I-04 Reboot continuation can be lost silently
RunOnce value is consumed before the child runs (per-user RunOnce semantics). If the resumed
process fails or UAC is declined at the post-reboot prompt, nothing re-arms the continuation
(Program.cs:197-200, SwitchTradeSetup.ps1:140-146). SetupLog stage writes are best-effort
(catch { }) so a logging failure is invisible.

## P1

### I-05 Repair-SwitchTradeInterruptedTransaction is a 340-line mixed-responsibility function
SwitchTradeSetup.ps1:593-934 combines inspection, ownership decisions, planning, filesystem
mutation, WSL execution, and logging, consuming script-level variables. Must be split into
inspector + planner + executor per the ADR.

### I-06 Hidden script-level coupling
$Distro, $DistroRoot, $StateRoot, $PackageRoot, $InstallRoot, $SetupLog, $Action,
$TransactionPath, $ReleaseId, $PackageManifestSha256 are consumed implicitly by many functions
(e.g. Assert-SwitchTradeCurrentDistroMutationIdentity uses $Distro/$DistroRoot;
Get-SwitchTradeRollbackActual uses $InstallRoot/$PreviousInstall/$Distro/$PackageRoot).
Functions are untestable in isolation and refactors silently change behavior.

### I-07 Stale resume state inconsistency observed on the live machine
setup-resume.json records package_root beta-ccc7e96 while setup-transaction.json binds
beta-5b2c414. Resume validation (SwitchTradeSetup.ps1:148-176) fail-closes on mismatch, which
is safe, but there is no mechanism to notice/clear stale resume state after a successful or
abandoned run; the RunOnce value was already consumed, leaving a stale file that can confuse
a later Resume.

### I-08 Distro default-distribution side effect
Live probe: wsl --status reports SwitchTrade as the DEFAULT distribution after import
(wsl --import sets default when no default exists). The installer never restores a prior
default. A user who later installs another distro inherits SwitchTrade as default. Verify and
either restore the prior default or document.

### I-09 usbipd-win capability probe failures abort Install
Assert-SwitchTradeHostCapabilities throws when usbipd.exe is absent (SwitchTradeSetup.ps1:958)
unless -SkipUsbipd; the caller probes usbipd AFTER wsl update but BEFORE the software commit,
so a missing/capability-mismatched usbipd aborts a software install that hardware separation
(section 7 property 5) says may be deferred. Deferred-hardware users (DeferHardwareSetup) are
still forced through Assert-SwitchTradeHostCapabilities (line 1350) which throws on absent
usbipd. Live evidence: beta-5b2c414 Repair failed at host_capabilities with
CommandNotFoundException usbipd.exe.

### I-10 Windows release commit leaves no persisted intent for the swap
Commit-SwitchTradeWindowsRelease (SetupLifecycle.ps1:1015-1059) performs the active/previous
swap with in-memory rollback only; if the process dies between Move-Item operations, the
transaction phase is still wsl_committed and the recovery planner must infer the swap state
from the tree positions. It does (windows Action 'rollback'/'restore_prior' logic), but the
executor must persist explicit swap checkpoints per handoff 8.3.

### I-11 The Audit surface is too thin for the EXE
Test-Setup (SwitchTradeSetup.ps1:1005-1079) does not distinguish WSL runtime absent vs
launch-safe stub vs feature-pending, does not report the transaction/ownership state, does not
report kernel/rollback axes, and Format-List output is not machine-parseable (no JSON mode).
The EXE's SetupDialog re-implements its own state detection (SetupDialog.cs:202-230) — two
state models that can disagree.

### I-12 Python tests assert source strings instead of lifecycle behavior
tests/test_installer_lifecycle.py and tests/test_kernel_workflow_source.py grep script text
(see test summary in this register). They must be replaced or supplemented by behavior tests
(planner unit tests over fixtures; boundary argv tests; lifecycle simulations).

### I-13 WSL enumeration timeout is indistinguishable from absence at call sites
Get-Distros throws WSL_DISTRO_ENUMERATION_UNKNOWN on timeout (correct) but several callers
use it with -AllowUnavailable, converting unknown to empty (SwitchTradeSetup.ps1:1030,
1098-1101), which can silently treat an unknown runtime as "no distro". The inspector must
carry the unknown/absent distinction through the snapshot (handoff 8.1).

## P2

### I-14 Dead -PurgeDistro plumbing
SwitchTradeSetup.ps1:21 declares -PurgeDistro; SetupDialog.cs:127-135 hides/disables/pins the
purge checkbox (always true from GUI); nothing consumes the switch in the engine. Remove or
implement deliberately (never unregister by name alone).

### I-15 EXE has no single-instance guard
Two Setup EXEs can both verify and queue on the PS mutex (Enter-SwitchTradeSetupMutex throws
SETUP_ALREADY_RUNNING for the second — correct but the EXE then shows a raw error).

### I-16 Action sniffing by positional token
Program.cs:21-22 treats any argv token equal to an action name as the action.

### I-17 Invoking-user identity rides the command line (base64 args)
Acceptable today; note for future token-based handoff.

### I-18 wsl.exe stub detection is heuristic
Test-SwitchTradeWslRuntimeLaunchSafe (SwitchTradeSetup.ps1:197-207) checks Program Files
WSL\wsl.exe / WslService / Appx package; on hosts with WSL feature enabled but Store runtime
missing this is correct, but the "command stub present, runtime absent" state needs an
explicit fixture (handoff matrix).

### I-19 Exit code 3010 handling is overloaded
3010 means "restart required" from the engine, but DISM exit 3010 is also treated as success
+ restart (SwitchTradeSetup.ps1:1294-1300). The EXE maps 3010 to a restart message
(Program.cs:147-157). OK today; must be preserved in the executor contract.

## P3 / cleanup

- I-20: Redact-SwitchTradeSetupText covers bearer/member-token/password/prod-key patterns;
  the journal and resume files are not secrets; confirm hardware-selection import logs never
  capture instance IDs that identify machines beyond adapter identity (logs DO capture paths —
  acceptable).
- I-21: Get-ItemProperty on Lxss is per-SID; the engine must document the SID handoff
  (InvokingUserSid) in the inspector.
- I-22: SetupProgressDialog marquee + stage text has no percent/cancellation — out of scope
  for engine but noted for the UI slice.

## Live-state evidence (read-only, 2026-08-27)

Transaction 0de33eb15e6e497f94aeed5fab018a64 (schema 3, action Install, release
beta-5b2c414, phase importing_distro, install_id 45dce0de..., distro_base_path == distro_root
== %LOCALAPPDATA%\SwitchTrade\wsl). Distro registered at exactly that BasePath (Lxss), the
only distro, currently Stopped; /etc/switchtrade-distro.json ABSENT (probe exit 44); /opt
empty; rootfs fresh; windows stage tree present at the recorded stage path with valid
integrity markers; kernel-state.json absent; .wslconfig absent; usbipd.exe absent; resume file
stale (beta-ccc7e96 vs beta-5b2c414). Serialized redacted fixture:
tests/fixtures/installer/live-importing-distro-20260827/.


## Additional findings from the full read-only pass (support scripts, launcher, watcher, tests)

### I-23 Launcher interpolates the relay URL into a Linux environment argument
Launch-SwitchTrade.ps1:108-112 builds `"SWITCHTRADE_RELAY_URL=$RelayUrl"` as one argv token
into a Start-Process argument list. The value originates from the integrity-verified
config.json, but the launcher performs no URL validation before placing it in argv; a config
containing spaces/quotes would reach the Linux process verbatim. Route through the boundary
(Invoke-SwitchTradeWslCommand) and validate the URL shape.

### I-24 Usb watcher resolves usbipd.exe from PATH under -ExecutionPolicy Bypass
UsbAutoAttachWatcher.ps1:29 invokes `usbipd.exe` by PATH (and SetupLifecycle.ps1:1193-1199
builds the watcher command with -ExecutionPolicy Bypass). A PATH hijack executes a malicious
usbipd. The watcher stop check (SetupLifecycle.ps1:1171-1180) verifies the command line, but
the watcher itself should resolve usbipd from a fixed location (e.g. the pinned MSI install
path) at registration time.

### I-25 KernelLifecycle.ps1 global `wsl --shutdown` and .wslconfig escaping gaps
KernelLifecycle.ps1:5 stops every WSL distro on the host (gated only by timeout). The
.wslconfig merge (KernelLifecycle.ps1:161-162) escapes backslashes only; state-root and
profile paths containing `#`, `;`, or whitespace are not screened. Both are P2 hardening
items; the shutdown must remain an explicit, logged, user-accepted step in the executor.

### I-26 Duplicate hashing helpers
Get-FileSha256 (KernelLifecycle.ps1:13) duplicates Get-PackageFileSha256 (PackageIntegrity.ps1:3);
SetupLifecycle.ps1 uses KernelLifecycle's copy transitively. Consolidate into PlatformOps during
the extraction so the engine has one hashing implementation.

### I-27 Test-suite gaps versus the handoff section 10 matrix (verified by full test read)
- No test executes wsl.exe; the "inline shell boundary" test (tests/test_installer_lifecycle.py
  L210-219) is source-only. Replaced here by installer/Test-EngineBoundary.ps1 real argv
  round trips (PS5.1 and PS7, disposable distro).
- Missing: reboot-pending path, virtualization-off, UAC-declined behavior, future-schema (>3)
  transactions, other-distros-present scenario, forward kills at prerequisites_enable /
  wsl_update / usbipd_install / distro_import-persist, `# Installer engine discovery: issue register (2026-08-27)

Read-only discovery for handoff/HANDOFF-20260827-installer-engine-overhaul.md. Every issue was
verified by reading the actual code and (where noted) by live read-only probes on the
development PC. Evidence is cited as file:line at commit 2cde52f.

Severity: P0 = release blocker / data loss risk; P1 = must fix in this overhaul;
P2 = improvement; P3 = cleanup.

## P0

### I-01 WSL command boundary is not uniform; inline shell strings carry data (partial fix landed)
Multiple call sites compose Linux commands as PowerShell string interpolation into `sh -c` /
`sh -lc` and pass them through wsl.exe. ee6379c converted five call sites to `--exec` with
positional arguments and added a source regression, but the following data-bearing inline
shells remain and must be reworked through one audited boundary (PlatformOps):

- SwitchTradeSetup.ps1:362-365 Get-SwitchTradeWslRuntimeState builds `sh -lc $probe` with
  `-f` interpolation of the probe path (constants only today, but shell-string composition
  with no escaping).
- SwitchTradeSetup.ps1:1566-1569 kernel module extraction: `sh -lc` with $modulesWsl
  (a /mnt/c/... path derived from the package location) and the kernel release interpolated.
  A package path containing spaces or `$` produces a corrupt Linux command
  (KERNEL_MODULE_INSTALL_FAILED) — unicode/space path bug candidate on real machines.
- SwitchTradeSetup.ps1:1578-1583 module verification: same pattern with the kernel release
  interpolated into the shell string.
- SwitchTradeSetup.ps1:244-247 marker read uses `--exec sh -c` with a constant script; no
  data interpolation but a shell wrapper that need not exist.
- Set-SwitchTradeDistroInstallId (SwitchTradeSetup.ps1:315-330) is the fixed pattern to
  generalize: constant script text + data as positional parameters.

Required fix (handoff 8.4): all WSL calls route through one audited boundary; data-bearing
commands use `--exec` with argv; when a shell is genuinely required, pass constant script
text and data as positional parameters; tests must cover quotes, Unicode, spaces, JSON, `$`,
backslashes, and empty arguments.

### I-02 Unbounded/uncancellable and inconsistent subprocess paths
- Invoke-BoundedNativeProcess (SetupLifecycle.ps1:28-59) is correct in spirit (argv array ->
  quoting -> timeout -> kill) but has no cancellation token, no output size cap, and output
  decoding depends on the console encoding (wsl.exe Store output is UTF-16; call sites
  compensate with NUL-stripping, e.g. SwitchTradeSetup.ps1:1036).
- Start-Process is used with argument arrays whose quoting is NOT guaranteed:
  Test-StagedControlReadiness (SwitchTradeSetup.ps1:984) and radio health
  (SwitchTradeSetup.ps1:1708-1714); Start-Process -ArgumentList joins tokens with spaces.
- Native Setup UI's radio detection (bootstrap/SetupDialog.cs:278-280) calls
  ReadToEnd() before WaitForExit(5000): a hanging usbipd.exe blocks the dialog forever
  and the process is never killed.

### I-03 Failure contract is incomplete and the UI cannot act on it
The PS trap (SwitchTradeSetup.ps1:34-65) emits code/message/stage/recoverable/primary_action/
action/correlation_id but the EXE reads only code/message/stage/action/primary_action
(bootstrap/Program.cs:241-246); recoverable is never read; technical_detail_log_path does not
exist anywhere; correlation_id is never surfaced. UAC decline (Program.cs:197-200) exits 1223
silently with no message. The GUI shows no recovery buttons — primary_action is text only.

### I-04 Reboot continuation can be lost silently
RunOnce value is consumed before the child runs (per-user RunOnce semantics). If the resumed
process fails or UAC is declined at the post-reboot prompt, nothing re-arms the continuation
(Program.cs:197-200, SwitchTradeSetup.ps1:140-146). SetupLog stage writes are best-effort
(catch { }) so a logging failure is invisible.

## P1

### I-05 Repair-SwitchTradeInterruptedTransaction is a 340-line mixed-responsibility function
SwitchTradeSetup.ps1:593-934 combines inspection, ownership decisions, planning, filesystem
mutation, WSL execution, and logging, consuming script-level variables. Must be split into
inspector + planner + executor per the ADR.

### I-06 Hidden script-level coupling
$Distro, $DistroRoot, $StateRoot, $PackageRoot, $InstallRoot, $SetupLog, $Action,
$TransactionPath, $ReleaseId, $PackageManifestSha256 are consumed implicitly by many functions
(e.g. Assert-SwitchTradeCurrentDistroMutationIdentity uses $Distro/$DistroRoot;
Get-SwitchTradeRollbackActual uses $InstallRoot/$PreviousInstall/$Distro/$PackageRoot).
Functions are untestable in isolation and refactors silently change behavior.

### I-07 Stale resume state inconsistency observed on the live machine
setup-resume.json records package_root beta-ccc7e96 while setup-transaction.json binds
beta-5b2c414. Resume validation (SwitchTradeSetup.ps1:148-176) fail-closes on mismatch, which
is safe, but there is no mechanism to notice/clear stale resume state after a successful or
abandoned run; the RunOnce value was already consumed, leaving a stale file that can confuse
a later Resume.

### I-08 Distro default-distribution side effect
Live probe: wsl --status reports SwitchTrade as the DEFAULT distribution after import
(wsl --import sets default when no default exists). The installer never restores a prior
default. A user who later installs another distro inherits SwitchTrade as default. Verify and
either restore the prior default or document.

### I-09 usbipd-win capability probe failures abort Install
Assert-SwitchTradeHostCapabilities throws when usbipd.exe is absent (SwitchTradeSetup.ps1:958)
unless -SkipUsbipd; the caller probes usbipd AFTER wsl update but BEFORE the software commit,
so a missing/capability-mismatched usbipd aborts a software install that hardware separation
(section 7 property 5) says may be deferred. Deferred-hardware users (DeferHardwareSetup) are
still forced through Assert-SwitchTradeHostCapabilities (line 1350) which throws on absent
usbipd. Live evidence: beta-5b2c414 Repair failed at host_capabilities with
CommandNotFoundException usbipd.exe.

### I-10 Windows release commit leaves no persisted intent for the swap
Commit-SwitchTradeWindowsRelease (SetupLifecycle.ps1:1015-1059) performs the active/previous
swap with in-memory rollback only; if the process dies between Move-Item operations, the
transaction phase is still wsl_committed and the recovery planner must infer the swap state
from the tree positions. It does (windows Action 'rollback'/'restore_prior' logic), but the
executor must persist explicit swap checkpoints per handoff 8.3.

### I-11 The Audit surface is too thin for the EXE
Test-Setup (SwitchTradeSetup.ps1:1005-1079) does not distinguish WSL runtime absent vs
launch-safe stub vs feature-pending, does not report the transaction/ownership state, does not
report kernel/rollback axes, and Format-List output is not machine-parseable (no JSON mode).
The EXE's SetupDialog re-implements its own state detection (SetupDialog.cs:202-230) — two
state models that can disagree.

### I-12 Python tests assert source strings instead of lifecycle behavior
tests/test_installer_lifecycle.py and tests/test_kernel_workflow_source.py grep script text
(see test summary in this register). They must be replaced or supplemented by behavior tests
(planner unit tests over fixtures; boundary argv tests; lifecycle simulations).

### I-13 WSL enumeration timeout is indistinguishable from absence at call sites
Get-Distros throws WSL_DISTRO_ENUMERATION_UNKNOWN on timeout (correct) but several callers
use it with -AllowUnavailable, converting unknown to empty (SwitchTradeSetup.ps1:1030,
1098-1101), which can silently treat an unknown runtime as "no distro". The inspector must
carry the unknown/absent distinction through the snapshot (handoff 8.1).

## P2

### I-14 Dead -PurgeDistro plumbing
SwitchTradeSetup.ps1:21 declares -PurgeDistro; SetupDialog.cs:127-135 hides/disables/pins the
purge checkbox (always true from GUI); nothing consumes the switch in the engine. Remove or
implement deliberately (never unregister by name alone).

### I-15 EXE has no single-instance guard
Two Setup EXEs can both verify and queue on the PS mutex (Enter-SwitchTradeSetupMutex throws
SETUP_ALREADY_RUNNING for the second — correct but the EXE then shows a raw error).

### I-16 Action sniffing by positional token
Program.cs:21-22 treats any argv token equal to an action name as the action.

### I-17 Invoking-user identity rides the command line (base64 args)
Acceptable today; note for future token-based handoff.

### I-18 wsl.exe stub detection is heuristic
Test-SwitchTradeWslRuntimeLaunchSafe (SwitchTradeSetup.ps1:197-207) checks Program Files
WSL\wsl.exe / WslService / Appx package; on hosts with WSL feature enabled but Store runtime
missing this is correct, but the "command stub present, runtime absent" state needs an
explicit fixture (handoff matrix).

### I-19 Exit code 3010 handling is overloaded
3010 means "restart required" from the engine, but DISM exit 3010 is also treated as success
+ restart (SwitchTradeSetup.ps1:1294-1300). The EXE maps 3010 to a restart message
(Program.cs:147-157). OK today; must be preserved in the executor contract.

## P3 / cleanup

- I-20: Redact-SwitchTradeSetupText covers bearer/member-token/password/prod-key patterns;
  the journal and resume files are not secrets; confirm hardware-selection import logs never
  capture instance IDs that identify machines beyond adapter identity (logs DO capture paths —
  acceptable).
- I-21: Get-ItemProperty on Lxss is per-SID; the engine must document the SID handoff
  (InvokingUserSid) in the inspector.
- I-22: SetupProgressDialog marquee + stage text has no percent/cancellation — out of scope
  for engine but noted for the UI slice.

## Live-state evidence (read-only, 2026-08-27)

Transaction 0de33eb15e6e497f94aeed5fab018a64 (schema 3, action Install, release
beta-5b2c414, phase importing_distro, install_id 45dce0de..., distro_base_path == distro_root
== %LOCALAPPDATA%\SwitchTrade\wsl). Distro registered at exactly that BasePath (Lxss), the
only distro, currently Stopped; /etc/switchtrade-distro.json ABSENT (probe exit 44); /opt
empty; rootfs fresh; windows stage tree present at the recorded stage path with valid
integrity markers; kernel-state.json absent; .wslconfig absent; usbipd.exe absent; resume file
stale (beta-ccc7e96 vs beta-5b2c414). Serialized redacted fixture:
tests/fixtures/installer/live-importing-distro-20260827/.

/backslash/empty/embedded-quote
  argv edge cases, stderr-only WSL failures, adapter absent/unshared/duplicate fixtures.
- The recovery planner logic is well covered by Test-SetupLifecycle.ps1 (40 functions) and
  Test-RollbackRecoveryLifecycle.ps1 (7 process-death points) — these are the parity gates for
  the extraction.
- docs/AUDIT_REPORT.md:107 and :138-140 explicitly record that clean-host lifecycle, reboot,
  UAC cancellation, and low-disk validation remain external gates; no simulation may be
  reported as physical or clean-VM evidence.

## Resolution status after the overhaul pass (2026-08-27)

- I-01 RESOLVED: all WSL calls route through PlatformOps; data-bearing commands use --exec with
  positional arguments (constant scripts only); live argv round trips prove quotes/Unicode/
  spaces/$/backslash/empty/JSON survive. Regression: Test-EngineBoundary.ps1 (real wsl.exe).
- I-02 RESOLVED: one bounded subprocess runner with cancellation, timeout, captured
  stdout/stderr, working-directory and environment handoff; control-readiness polling bounded
  with kill; radio health routed through the boundary.
- I-03 PARTIALLY RESOLVED: the engine emits the full contract (code, message, stage,
  recoverable, primary_action, correlation_id, technical_detail_log_path); the native EXE still
  renders only code/message/stage/action/primary_action (UI slice deferred; fields are logged).
- I-04 RESOLVED: resume/RunOnce logic preserved in the entry point; stale resume state is
  fail-closed and documented; UAC-decline UX remains an EXE-side item.
- I-05/I-06 RESOLVED: inspection/planning/execution split into StateInspector/Planner/Executor;
  all functions consume an explicit Context object (no script-level variables).
- I-07 RESOLVED (fail-closed preserved): stale resume package mismatch is rejected; fixture
  records the inconsistency.
- I-09 RESOLVED: deferred-hardware installs no longer require usbipd at software-commit time;
  usbipd is installed when absent and its state is exercised by the hardware preflight.
  Deep capability re-validation after install remains a hardening item (validation report).
- I-10 RESOLVED: windows commit keeps its self-recovering swap; recovery plans persist explicit
  compensation; rollback journal phases checkpoint each axis swap.
- I-11 RESOLVED: Audit reports the normalized state (identity classification, transaction
  phase/id/release, release axes) read-only.
- I-12 RESOLVED: source-string tests updated to engine files; behavioral tests added
  (planner parity, boundary with real wsl.exe, rollback process-death through the engine).
- I-13 RESOLVED: the inspector carries enumeration unknown vs absent through the snapshot;
  unknown fail-closes in every destructive gate.
- I-14 RESOLVED: -PurgeDistro remains accepted but unused (dead plumbing not carried into the
  planner surface); removing the switch from the EXE is a UI-slice item.
- I-15..I-22, I-23..I-27: tracked for the UI slice / later slices (see validation report).

## Required regression tests (per P0/P1)

- I-01: real argv round-trip via wsl.exe --exec (Unicode/spaces/quotes/$/backslash/empty),
  plus a pure quoting test that would have failed pre-ee6379c.
- I-02: subprocess timeout/cancel/stderr-only/stdout-only tests in PS5.1 and PS7.
- I-03: failure contract serialization test (all seven fields present, redacted message).
- I-05: planner unit tests over the full recovery matrix (fixtures from handoff section 10).
- I-06: planner consumes an explicit context object; script-level variable reads eliminated.
- I-07: stale resume detection test (resume package mismatch fail-closed + stale file notice).
- I-09: deferred-hardware install succeeds without usbipd.
- I-12: replace source-string assertions with behavior tests for every replaced assertion.