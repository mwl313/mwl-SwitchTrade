# Live-state fixture: interrupted Install at importing_distro (2026-08-27)

Source: the real development PC state captured read-only at handoff time (branch audit,
commit 2cde52f). Values are the exact recorded values from the live machine; no credentials
or secrets are present in transaction state. This fixture feeds the installer-engine planner
and recovery tests. NEVER point destructive tests at the live machine — use this fixture.

## Recorded transaction (setup-transaction.json, schema 3)
- action: Install, release_id: beta-5b2c414 (the checkpoint package that failed the marker write)
- phase: importing_distro (process died right after `wsl --import` completed, before the
  distro marker write was confirmed; marker bootstrap has not run)
- install_id: 45dce0debfb0470dbb17ffb3a1a2c717
- distro_name: SwitchTrade; distro_root == distro_base_path == %LOCALAPPDATA%\SwitchTrade\wsl
- windows_stage: a fully staged and integrity-anchored Windows release tree at
  %LOCALAPPDATA%\Programs\SwitchTrade.stage.<guid> (windows_integrity_sha256 set)
- prior_release_id: "" (fresh install), distro_existed_before: false
- package_root: <dev machine>\Desktop\SwitchTrade-unsigned-private-beta-5b2c414

## Verified live facts (read-only probes, 2026-08-27)
- Distro "SwitchTrade" IS registered in HKEY_USERS\<sid>\...\Lxss at BasePath exactly
  %LOCALAPPDATA%\SwitchTrade\wsl, Version 2; it is the only WSL distribution.
- /etc/switchtrade-distro.json is ABSENT (marker probe exits 44).
- /etc is a fresh, nearly empty rootfs; /opt exists and is empty (no runtime trees).
- Distro state at probe time: Stopped (terminated after the read-only probe).
- WSL: Store runtime 2.7.12.0, WslService Running; wsl --status names SwitchTrade the
  default distribution; wsl.exe resolves to System32\wsl.exe (Store shim).
- Host: Windows 11 Education build 26200, x64; non-ASCII user profile C:\Users\<user>
  (real username is non-ASCII, exercising the unicode-path path).
- %LOCALAPPDATA%\SwitchTrade\recovery\ contains one orphaned Windows tree
  (windows-orphan-20260827T074523Z-...) preserved by an earlier Repair from package
  beta-6c6f409; the recorded stage path itself still exists with valid integrity markers.
- setup-resume.json exists but records package_root beta-ccc7e96 (a STALE/older package
  than the transaction's beta-5b2c414) — a state inconsistency to handle fail-closed.
- usbipd.exe is NOT installed (log evidence); .wslconfig absent; kernel-state.json absent;
  usb-watcher.json absent; InstallRoot/Previous absent.

## Failure genealogy (logs\setup.jsonl, redacted to codes)
1. beta-e3fbe02 Install -> WSL_DISTRO_ENUMERATION_UNKNOWN (PROCESS_TIMEOUT, pre-WSL stub scan)
2. beta-ccc7e96 Install -> WSL_CAPABILITY_PROBE_FAILED (host_capabilities)
3. beta-5b2c414 Repair -> CommandNotFoundException usbipd.exe (host_capabilities)
4. beta-5b2c414 Install -> SETUP_COMPENSATION_FAILED: DISTRO_INSTALL_ID_WRITE_FAILED;
   compensation: DISTRO_NAME_COLLISION  (the pre-ee6379c inline sh -c argument bug)
5. beta-5b2c414 Uninstall / Install -> SETUP_TRANSACTION_INCOMPLETE (fail-closed, correct)
6. beta-6c6f409 Repair -> preserved orphan tree, then SETUP_TRANSACTION_DISTRO_OWNERSHIP_CHANGED
   (marker absent => ownership gate failed closed, correct at that commit)

## Expected recovery semantics (see docs/installer/ARCHITECTURE-20260827-installer-engine.md)
- Repair from the exact package beta-5b2c414 (byte-identical manifest) must:
  recognize Test-SwitchTradeFreshImportMarkerBootstrap, write the marker atomically via
  wsl --exec argv (no inline shell data), then continue staging_wsl -> wsl_staged ->
  software_validated -> kernel_apply -> commit -> completed.
- Any other package, foreign distro, different BasePath, or wrong install ID: fail closed
  with no mutation.
