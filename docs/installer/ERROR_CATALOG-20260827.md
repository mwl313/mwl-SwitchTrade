# SwitchTrade installer error catalog (2026-08-27)

Every failure that crosses into the Setup UI carries: code, message, stage, recoverable,
primary_action, correlation_id, technical_detail_log_path. Localized text never drives control
flow. The engine emits the failure contract from New-SwitchTradeFailure (engine/Executor.ps1)
and the entry-point trap (SwitchTradeSetup.ps1).

## Host and prerequisites

| Code | Stage | Recoverable | Recovery |
|---|---|---|---|
| HOST_UNSUPPORTED | prerequisite_inspection | no | Windows 10 22H2 x64 (build 19045) or Windows 11 x64 required |
| HOST_FREE_SPACE | prerequisite_inspection | yes | Free at least 8 GB, rerun Install |
| HOST_VIRTUALIZATION | prerequisite_inspection | no | Enable virtualization/Hyper-V in firmware or Windows |
| PAYLOAD_MISSING | prerequisite_inspection | no | Use the complete package |
| RELEASE_CONFIG_MISSING | prerequisite_inspection | no | Use the complete package |
| WINDOWS_RESTART_PENDING | prerequisite_inspection | yes | Restart Windows, then rerun (resume continues automatically) |
| DESKTOP_HASH_MISSING / DESKTOP_HASH_MISMATCH | prerequisite_inspection | no | Package is corrupt; re-download |
| PREREQUISITE_CONSENT_REQUIRED | prerequisites_enable | yes | Rerun after accepting prerequisite changes |
| SETUP_RESUME_UNAVAILABLE | prerequisites_enable | no | Use the complete native setup package |
| WSL_FEATURE_ENABLE_FAILED | prerequisites_enable | yes | Check DISM output in the log; rerun |
| VIRTUAL_MACHINE_PLATFORM_ENABLE_FAILED | prerequisites_enable | yes | Check DISM output in the log; rerun |
| WSL_UPDATE_FAILED | prerequisites_enable | yes | Install the current Microsoft Store WSL package, restart, rerun |
| USBIPD_PACKAGE_MISSING | usbipd_install | no | Use the complete package |
| USBIPD_HASH_MISMATCH | usbipd_install | no | Package is corrupt; re-download |
| USBIPD_INSTALL_FAILED | usbipd_install | yes | Check msiexec output in the log; rerun |

## Transaction and identity

| Code | Stage | Recoverable | Recovery |
|---|---|---|---|
| SETUP_TRANSACTION_CORRUPT | transaction | no | Contact SwitchTrade support (transaction file unreadable) |
| SETUP_TRANSACTION_FUTURE_SCHEMA | transaction | no | Use the newer package that wrote the transaction |
| SETUP_TRANSACTION_LEGACY_AMBIGUOUS | transaction | no | Contact SwitchTrade support (schema < 3 lacks ownership facts) |
| SETUP_TRANSACTION_INCOMPLETE | transaction_recovery | yes | Rerun the same action or Repair from the package that started it |
| SETUP_TRANSACTION_PACKAGE_MISMATCH | transaction_recovery | yes | Run Repair from the package that started the transaction |
| SETUP_TRANSACTION_INSTALL_PATH_MISMATCH / PREVIOUS_PATH_MISMATCH / DISTRO_PATH_MISMATCH / DISTRO_BASE_PATH_MISMATCH / KERNEL_PATH_MISMATCH | transaction_recovery | no | Recorded paths changed; contact support |
| SETUP_TRANSACTION_DISTRO_MISMATCH | transaction_recovery | no | Recorded distro name differs; contact support |
| SETUP_TRANSACTION_INSTALL_ID_INVALID | transaction_recovery | no | Recorded identity invalid; contact support |
| SETUP_TRANSACTION_WSL_PATH_MISMATCH | transaction_recovery | no | Runtime paths changed; contact support |
| SETUP_TRANSACTION_PATH_INVALID | transaction_recovery | no | Recorded stage is outside the installation boundary |
| WSL_DISTRO_ENUMERATION_UNKNOWN | distro_identity | yes | Enumeration timed out or registration disagrees; retry, then contact support if persistent |
| WSL_DISTRO_REGISTRATION_UNKNOWN / WSL_DISTRO_REGISTRATION_AMBIGUOUS | distro_identity | no | Lxss registration unreadable or not unique; contact support |
| DISTRO_NAME_COLLISION | distro_identity | yes | Choose another distribution name |
| SETUP_TRANSACTION_DISTRO_OWNERSHIP_CHANGED | transaction_recovery | no | Named distribution is not installer-owned; contact support |
| SETUP_TRANSACTION_DISTRO_IDENTITY_CHANGED | transaction_recovery | no | Install identity or BasePath changed; contact support |
| SETUP_TRANSACTION_WINDOWS_* / WSL_* / KERNEL_AMBIGUOUS | transaction_recovery | no | Release state cannot be compensated safely; contact support |
| INSTALLED_DISTRO_IDENTITY_MISSING | uninstall_validate | yes | Destructive actions need a completed identity transaction; contact support |
| INSTALLED_DISTRO_IDENTITY_CHANGED | uninstall_validate | no | Registered BasePath or install identity changed; contact support |
| INSTALLED_DISTRO_MISSING / INSTALLED_DISTRO_PATH_MISMATCH | uninstall_validate | no | Recorded distribution is not registered as recorded |

## Install / update stages

| Code | Stage | Recoverable | Recovery |
|---|---|---|---|
| ROOTFS_MISSING / ROOTFS_HASH_MISSING | distro_identity | no | Use a package that contains the rootfs |
| ROOTFS_HASH_MISMATCH | distro_identity | no | Package is corrupt; re-download |
| DISTRO_IMPORT_FAILED | distro_identity | yes | Import intent is persisted; rerun the same action or Repair |
| DISTRO_IMPORT_BASE_PATH_MISMATCH | distro_identity | no | Imported registration changed; contact support |
| DISTRO_INSTALL_ID_WRITE_FAILED | distro_identity | yes | Marker write failed; rerun Repair (recovery bootstraps the marker) |
| WSL_STAGE_FAILED | wsl_stage | yes | Rerun Repair (candidate cleanup + restage) |
| WSL_STAGE_INTEGRITY_MISSING | wsl_stage | no | Staged runtime has no exact integrity manifest |
| WSL_VALIDATE_FAILED | wsl_validate | yes | Rerun Repair |
| STAGED_CONTROL_NOT_READY | control_readiness | yes | Staged control did not advertise the release; rerun Repair |
| CUSTOM_KERNEL_BLOCKED_BY_POLICY | kernel_apply | yes | Managed-PC policy blocked the custom kernel; unsupported by the private beta |
| CUSTOM_KERNEL_START_FAILED | kernel_apply | yes | Kernel did not start with the expected release; rerun Repair |
| KERNEL_MODULE_INSTALL_FAILED | kernel_modules | yes | Module archive extraction failed; rerun Repair |
| KERNEL_ABI_OR_FIRMWARE_MISMATCH | kernel_verify | yes | Running kernel ABI/firmware mismatch; rerun Repair |
| WSL_COMMIT_FAILED | commit | yes | Rerun Repair (recovery converges the commit swap) |
| WINDOWS_PRIOR_RELEASE_CHANGED | commit | no | Setup state changed during commit; contact support |
| SETUP_COMPENSATION_FAILED | compensate | yes | Rerun Repair (compensation is persisted recovery work) |

## Rollback

| Code | Stage | Recoverable | Recovery |
|---|---|---|---|
| ROLLBACK_WINDOWS_MISSING | rollback_validate | yes | No retained application version; run Update first |
| ROLLBACK_DISTRO_MISSING | rollback_validate | yes | The owned distro is absent; run Repair |
| ROLLBACK_TRANSACTION_RELEASE_MISMATCH | rollback_validate | no | Release identities disagree with the transaction |
| ROLLBACK_RUNTIME_INVALID | rollback_validate | no | Retained runtime integrity failed |
| ROLLBACK_JOURNAL_INVALID / *_MISMATCH / *_ANCHOR_INVALID | rollback_* | no | Rollback journal missing or tampered; contact support |
| ROLLBACK_WSL_RECOVERY_FAILED | rollback_recovery | yes | Rerun Repair |
| ROLLBACK_RECOVERY_NOT_CONVERGED | rollback_recovery | no | Release axes did not reach one journaled side; contact support |
| ROLLBACK_WINDOWS_SWAP_STALE / ROLLBACK_WINDOWS_ACTIVE_RELEASE_MISMATCH | rollback_* | no | Swap state unexpected |

## Uninstall

| Code | Stage | Recoverable | Recovery |
|---|---|---|---|
| DISTRO_UNREGISTER_FAILED | uninstall | yes | Rerun Uninstall |
| DESTRUCTIVE_PATH_DENIED | uninstall | no | Removal target is not an installer-owned tree (safety guard) |

## Engine / boundary

| Code | Stage | Recoverable | Recovery |
|---|---|---|---|
| PROCESS_START_FAILED / PROCESS_TIMEOUT / PROCESS_CANCELLED | any | yes | Retry; check the log for the failing executable |
| PLAN_STEP_UNKNOWN | plan | no | Engine/plan mismatch; contact support |
| SETUP_ALREADY_RUNNING | mutex | yes | Wait for the other setup action to finish |
| SETUP_FAILED | any | yes | Unclassified failure; see log |

## Failure contract example

```json
{"code":"WSL_STAGE_FAILED","message":"provision stage failed: ...","stage":"wsl_stage",
 "recoverable":true,"primary_action":"Run Setup Repair","action":"Repair",
 "correlation_id":"...","technical_detail_log_path":"C:\\Users\\<user>\\AppData\\Local\\SwitchTrade\\logs\\setup.jsonl"}
```

The native Setup EXE currently renders code/message/stage/action/primary_action; the remaining
contract fields are emitted for future UI use and always present in the log.
