# Installer state and fault matrix (2026-08-27)

Automated coverage for the mandatory matrix in the handoff section 10. Evidence layer per row:
P = pure planner unit fixtures, S = PS simulation (filesystem trees + stubbed boundary),
B = subprocess boundary with real wsl.exe, D = process-death orchestration, L = live machine
(read-only), X = external gate (clean VM / physical) still required.

## Host and prerequisites

| Scenario | Layer | Where |
|---|---|---|
| Clean Windows 10/11, no WSL | X | AUDIT_VALIDATION.md external gates; host matrix S in test_installer_lifecycle.py |
| WSL command stub without runtime | P/S | Test-EnginePlanner (launch-safe gate), StateInspector guard test |
| WSL feature enabled, reboot pending | S | WINDOWS_RESTART_PENDING gate (require_prerequisites) |
| Old Store WSL needing update | S | ensure_wsl -> --update --web-download path |
| Virtualization off | S | HOST_VIRTUALIZATION gate |
| UAC declined / standard-user handoff | L/S | EXE base64 invoking-user args; Resume user-mismatch validation |
| Non-ASCII username, spaces, long paths | B | argv round trips (unicode/space paths) live via powershell.exe + wsl.exe |
| Missing/readonly dir, low disk | S | HOST_FREE_SPACE gate; dir creation errors fail closed |
| Malformed / CRLF .wslconfig | S | kernel lifecycle config tests (Test-KernelLifecycle) |

## Distribution identity

| Scenario | Layer | Where |
|---|---|---|
| No named distro | P | absent identity -> install plan |
| Fresh import with generic marker | P | present_generic, fresh-install recovery plan |
| Death after import, before marker | P/L | live fixture: markerless importing_distro -> bootstrap + continue |
| Markerless fresh import at recorded BasePath | P/L | live fixture + planner test 7/12 |
| Malformed marker | P | present_invalid -> ownership changed fail closed |
| Correct marker, wrong install ID | P | present_foreign -> fail closed (parity test 5) |
| Same name at foreign BasePath | P | identity changed fail closed |
| Copied marker on foreign distro | P | ownership changed fail closed |
| CLI/registry disagreement or timeout | P | enumeration unknown fail closed (parity test 6) |
| Other user distros present | P/L | enumeration contains SwitchTrade; unrelated distros never touched |

## Transaction lifecycle

| Scenario | Layer | Where |
|---|---|---|
| Kill before/after every mutating stage | D/P | Test-RollbackRecoveryLifecycle 7 crash points; planner parity matrix (coherent commit, staged candidate, commit swap, wsl/windows/kernel compensation) |
| Reopen original / Repair / byte-identical package | D | rollback test replacement-package rejection + repair modes |
| Reject unrelated/modified package | D | same-release replacement rejected without mutation |
| Fresh Install / existing Install / Repair / Update / failed Update / compensation / Rollback / interrupted Rollback / reverse Rollback / Uninstall / reinstall | P/S/D | planner plan builders, recovery decisions, rollback process-death, reverse rollback |
| Mutex contention | S | SETUP_ALREADY_RUNNING |
| Corrupt / schema-old / future-schema transactions | P | dispatcher blockers (tests 10) |
| .previous / .candidate / commit-swap / rollback-swap / recovery / orphan trees | P/S/D | recovery decisions + rollback pair positions + orphan preservation in legacy sim |

## WSL/native command boundary

| Scenario | Layer | Where |
|---|---|---|
| Exact argv via real wsl.exe --exec | B | Test-EngineBoundary disposable distro (PS5.1 + PS7) |
| JSON/Unicode/spaces/quotes/$/backslash/empty args | B | live round trips through bash -c and sh -c positional args |
| Timeout / nonzero / stdout-only / stderr-only / cancellation | B | Test-EngineBoundary sections 2-3 |
| Linux shell vars/substitutions execute exactly once | B | literal $p / $(whoami) / backtick args verified verbatim |
| Logs redact protected material | S | redaction tests + failure JSON |

## Release coherence

| Scenario | Layer | Where |
|---|---|---|
| Windows/WSL/kernel axes disagree | P | recovery decision ambiguous/fail-closed cases |
| Missing/tampered manifests and anchors | P/S | integrity fail-closed (legacy sim + planner) |
| Crash between swaps and publication | D | rollback crash points + commit-swap recovery |
| Completed state exposes one release everywhere | D | convergence checks + published record assertions |

## Hardware separation

| Scenario | Layer | Where |
|---|---|---|
| Adapter absent, hardware deferred | S | DeferHardwareSetup short-circuits hardware steps |
| Adapter present/unshared/shared/attached | S | preflight + watcher lifecycle (legacy sim) |
| Hardware failure cannot corrupt software | S | hardware steps run after software commit; failures are Repair-recoverable |
| Repair targets hardware readiness | S | hardware_prepare runs on Repair path |

## Environment-dependent skips

- Real wsl.exe round trips: skipped with an explicit gate message when no WSL 2 runtime or no
  SwitchTrade rootfs is available (external host gate owns the validation).
- Clean Win10/Win11 VM lifecycle, reboot in a VM, UAC cancellation, low disk: external gates
  per AUDIT_REPORT.md:107; no simulation is represented as clean-VM or physical evidence.
