# SwitchTrade audit validation record

Last updated: 2026-08-27

This file preserves the reproducible commands and observed results for the reliability audit. It is
not a substitute for clean-host or physical qualification. The reviewed runtime code checkpoint is
`33712f3`; the final documentation-only commit and package identify their own exact source revision
in Git and `manifest.json`.

## Locked Python environment

The Windows audit environment used CPython 3.12.14 created by `uv` and installed only the repository
lock:

```powershell
uv venv .audit-venv --python 3.12
uv pip install --python .audit-venv\Scripts\python.exe -r test-requirements.txt
.\.audit-venv\Scripts\python.exe -m pytest -q
```

Observed result at `33712f3`: **310 passed, 3 skipped**. The Windows skips require native Linux/WSL
`nl80211` or native POSIX process/lock behavior; Ubuntu CI owns those paths.

## Repeated authority and restart matrix

The following seven tests were run together ten times (70 executions):

```text
test_manual_roles_are_validated_and_locked_atomically
test_concurrent_peer_loss_and_stale_phase_cannot_reactivate_attempt
test_owner_close_cancels_attempt_and_peer_cleanup_cannot_reopen_room
test_hashed_credentials_and_room_state_survive_service_restart
test_database_writer_is_single_instance_and_releases_on_close
test_authoritative_clients_reconnect_after_relay_restart_without_replaying_stale_frames
test_rotated_credentials_leave_and_remote_close_cleanup_across_two_controls
```

Observed result: **70/70 passed**.

## Windows lifecycle simulations

These scripts were run independently under Windows PowerShell 5.1 and PowerShell 7 with unique
temporary roots:

```powershell
installer\Test-SetupLifecycle.ps1
installer\Test-KernelLifecycle.ps1
installer\Test-RollbackRecoveryLifecycle.ps1
```

All six invocations passed. The rollback test launches separate processes and forces termination
after WSL, kernel, and Windows transitions and before metadata publication. Fresh Repair enters the
real package gate and lifecycle wrapper, converges, and supports reverse Rollback. It also rejects a
same-release replacement package without changing transaction state.

## Native builds and scripts

```powershell
dotnet build apps\desktop\SwitchTrade.Desktop\SwitchTrade.Desktop.csproj -c Release
dotnet build installer\bootstrap\SwitchTrade.Setup.csproj -c Release
SwitchTrade.exe --self-test
wsl -d Ubuntu -- bash -lc 'git ls-files "*.sh" | xargs -r shellcheck'
bash scripts/tests/test-radio-workflow.sh
```

Both Release builds completed with zero warnings and zero errors. The desktop self-test, all tracked
ShellCheck inputs, and the fake-sysfs radio workflow passed.

## Relay and RFU

The credentialed `relay.smoke` path ran against a local production-mode uvicorn process. It rejected
the legacy unauthenticated endpoint, created and joined an authoritative room, locked complementary
roles, forwarded opaque RFU in both directions, and closed the room.

`tests/test_transport_resource_soak.py` then forwarded 4,096 ordered deterministic frames in each
direction (8,192 total). It asserts queue high-water marks, zero drop/stale/invalid frames, session
cleanup, RSS/threads, bounded logs, credential redaction, and platform resource counts (Windows
handles; Linux `/proc` FDs/sockets). The focused soak passed twice consecutively on Windows; it is
also part of the root suite, while Linux CI owns the FD/socket branch.

The repository does not contain a real byte-exact capture spanning the entire FRLG lifecycle from
discovery through teardown. Existing real vectors cover a CH11 advertisement, native join/accept,
and reliable bootstrap. Later trade checkpoints are deterministic simulator semantics. The missing
full transcript must be captured during physical qualification; no bytes were fabricated.

## Dependency checks

```powershell
.\.audit-venv\Scripts\python.exe scripts\run-pip-audit.py
dotnet list apps\desktop\SwitchTrade.Desktop\SwitchTrade.Desktop.csproj package --vulnerable --include-transitive
dotnet list installer\bootstrap\SwitchTrade.Setup.csproj package --vulnerable --include-transitive
```

The Python audit found no unreviewed known vulnerability; its seven reviewed reachability exceptions
are version-bound and expiring. Both .NET graphs reported no known vulnerable package.

## Package gate

The final gate builds the production unsigned-private-beta package twice from one clean commit, using
the verified Linux CPython 3.12 wheelhouse and retained kernel/rootfs/usbipd inputs. Acceptance requires
identical ZIP SHA-256 values, package integrity verification, successful extraction, exact release and
input hashes in `manifest.json`, and no test/internal-development payload. Artifact paths and hashes
are reported in the final handoff because recording an archive hash inside the source commit would
change that commit and create a circular build identity.
