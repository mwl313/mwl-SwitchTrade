# SwitchTrade replacement installer

This directory is the only supported source for new installer packages. The PowerShell engine in
`installer/` is frozen migration evidence and must not be selected by release builds.

The replacement has three deliberately small layers:

1. `SwitchTrade.Provisioner` owns the versioned WSL appliance and custom-kernel lifecycle.
2. `wix/Desktop.wixproj` installs the self-contained WPF client and shortcuts.
3. `wix/Bundle.wixproj` chains prerequisites, the MSI, and the provisioner with Burn.

The provisioner is idempotent. Install is fresh-only, Repair creates and validates a new side-by-side
runtime before switching the active pointer, and Uninstall removes only ownership-verified
SwitchTrade resources. A Wi-Fi adapter is never an installer prerequisite.

Builds use `Build-ReplacementPackage.ps1`. `Build-ImmutableWsl.ps1` creates the appliance on a build
host and may create a disposable `SwitchTradeBuilder-*` WSL distribution, which is always
unregistered in `finally`.

## Build and validation

The supported release command is:

```powershell
pwsh -NoProfile -File installer/replacement/Build-ReplacementPackage.ps1
```

Release builds require a clean tracked worktree. Internal-only builds may explicitly pass
`-AllowDirtyForDevelopment`. The builder verifies pinned WSL and usbipd MSI hashes, exact firmware
and wheel hashes, the immutable appliance metadata, every release payload, all native self-tests,
and WiX compilation before publishing one compressed `SwitchTradeSetup.exe`.

Validate a built directory without changing the host installation:

```powershell
pwsh -NoProfile -File installer/replacement/Test-ReplacementPackage.ps1 `
  -PackageDirectory artifacts/replacement/release-beta-<commit>
```

On a development machine with current Store WSL, add `-RunDisposableWslLifecycle` to install,
health-check, same-version Repair, and Uninstall an isolated Unicode-path runtime. This gate writes
the temporary kernel setting to the real user `.wslconfig`, keeps the kernel in a protected ASCII
ProgramData path, proves the packaged custom kernel actually boots, restores the original config,
and refuses changes to unrelated distributions.

## Lifecycle invariants

- Install is fresh-only at the provisioner boundary; the Burn chain uses fresh-replacement Repair so
  legacy and interrupted installations converge through one path.
- Repair validates a new side-by-side runtime before atomically switching the active pointer.
- A failure before pointer commit removes only the verified candidate and restores the prior kernel
  configuration. A failure while deleting the old runtime after commit is deferred and cannot make
  Burn roll back the matching desktop MSI.
- Uninstall verifies runtime name, registered location, and immutable ownership marker before
  unregistering. It restores the prior `.wslconfig`, then removes SwitchTrade-owned local state.
- WSL, unrelated distributions, and usbipd-win remain installed.
- Hardware is configured after installation; no adapter is needed for Install or Repair.
- WSL cannot resolve a custom-kernel path below some non-ASCII Windows profile names. Runtime and
  user state remain per-user under LocalAppData, while the hash-verified kernel is stored under the
  current SID in protected ASCII ProgramData storage readable only by that user, SYSTEM, and
  administrators.

The appliance is assembled from a SHA-256-pinned Canonical Ubuntu Base image and pinned Ubuntu
package snapshot, exact wheel hashes, pinned firmware, and a matching kernel/modules bundle. User
machines perform no `apt` or `pip` work.

## External qualification boundary

Automated software validation cannot replace clean Windows snapshots or physical radios. A release
remains a private-beta candidate until reboot continuation and Install/Repair/Uninstall pass on clean
Windows 10 19045 and Windows 11 hosts, followed by adapter onboarding and a two-PC Switch trade.
