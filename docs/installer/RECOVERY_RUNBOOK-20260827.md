# SwitchTrade installer recovery runbook (2026-08-27)

This runbook covers every recoverable interruption. The installer converges automatically in
almost all cases; manual action is only listed where the engine requires it. Never unregister a
distribution by name alone and never delete the transaction file - the transaction is the
recovery record.

## How recovery works

Every mutating step persists its checkpoint (setup-transaction.json phase) BEFORE mutating and
persists completion AFTER success. After a process death you may:

1. Rerun the same action from the same package, or
2. Run Repair from the package that started the transaction (a byte-identical re-extraction is
   accepted; a modified or unrelated package is rejected), or
3. Resume automatically after a required reboot (RunOnce reopens the Setup GUI).

The recovery planner (engine/Planner.ps1) computes the disposition from the persisted phase and
the normalized snapshot: finalize (already coherent), compensate (undo the partial release), or
continue (early fresh-install states compensate and then rerun the verified package). Identity
gates are revalidated before every destructive step.

## Recovery matrix

| Interrupted state | What Repair does |
|---|---|
| created / windows_staged / importing_distro / distro_imported (fresh install, no prior) | Markerless fresh import: bootstraps the ownership marker, compensates the stage/distro, then reruns the verified package to completion |
| staging_wsl / wsl_staged / software_validated / kernel_applied | Aborts the staged candidate (or compensates the kernel), removes the stage, converges |
| wsl_committed with prior | Compensates Windows/WSL/kernel back to the prior release; converged and republished |
| commit swap (crash between WSL swaps) | recover-interrupted converges the commit swap to the journaled side |
| rollback_prepared / rollback_wsl_committed / rollback_kernel_committed / rollback_windows_committed / rollback_recovering_* | Uses the rollback journal to converge all axes (Windows, WSL, kernel, config) to one journaled side, then publishes |
| compensating_* | Continues the persisted compensation |
| completed / compensated / uninstalled | Terminal: no recovery action; next action starts fresh |

## Failure codes and the exact user action

See ERROR_CATALOG-20260827.md for the full table. The primary_action field in the failure JSON
is the exact action for the user; the EXE renders it.

## Reboot continuation

- Setup enables WSL features or installs usbipd-win -> writes setup-resume.json and a per-user
  RunOnce value, exits 3010.
- After sign-in, SwitchTradeSetup.exe resume reopens the GUI, re-verifies the same package and
  user identity, and continues.
- If the resume run fails or UAC is declined at the post-reboot prompt, rerun the package and
  choose Repair (the transaction is unchanged).

## Foreign / unsafe states (fail closed, no mutation)

| State | Result |
|---|---|
| Same distro name at a foreign BasePath | Blocked: DISTRO_OWNERSHIP_CHANGED / IDENTITY_CHANGED |
| Copied marker on a foreign distribution | Blocked: DISTRO_OWNERSHIP_CHANGED |
| Malformed marker | Blocked: DISTRO_OWNERSHIP_CHANGED |
| Correct marker with wrong install ID | Blocked: DISTRO_OWNERSHIP_CHANGED |
| CLI/registry enumeration disagreement or timeout | Blocked: WSL_DISTRO_ENUMERATION_UNKNOWN (unknown is never "absent") |
| Corrupt / legacy (schema < 3) / future-schema transaction | Blocked with contact-support guidance |
| Modified or unrelated package | Blocked: SETUP_TRANSACTION_PACKAGE_MISMATCH |
| Uninstall without a completed identity transaction | Blocked: INSTALLED_DISTRO_IDENTITY_MISSING |

## Logs and support bundle

- Engine + entry-point log: %LOCALAPPDATA%\SwitchTrade\logs\setup.jsonl (JSON lines, redacted,
  correlation_id per run).
- technical_detail_log_path in every failure points at this log.
- Startup logs: %LOCALAPPDATA%\SwitchTrade\logs\startup\ (relay/control).
- State: %LOCALAPPDATA%\SwitchTrade\ (setup-transaction.json, setup-resume.json,
  kernel-state.json, usb-watcher.json, runtime\, recovery\).

## Support handoff

When contacting support, provide: the failure JSON line, the log file, the transaction
transaction_id, and the correlation_id. Do not attach credentials; the log is redacted for
bearer tokens, member/reconnect tokens, passwords, secrets, and prod keys.
