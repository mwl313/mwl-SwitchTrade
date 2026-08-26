# WSL custom-kernel Unicode path fix — 2026-08-26

## Symptom

The unsigned Visual Overhaul 3 setup candidate stopped with:

`CUSTOM_KERNEL_START_FAILED: restored the previous WSL configuration; expected 6.18.35.2-microsoft-standard-WSL2+`

Setup had already imported the isolated `SwitchTrade` distro, but it correctly stopped before
provisioning `/opt/switchtrade`, restored the previous `.wslconfig`, and left unrelated WSL data intact.

## Root cause and proof

`Install-SwitchTradeKernel` copied the verified kernel below `%LOCALAPPDATA%\SwitchTrade\kernel`. On the
affected PC this expanded through a Korean Windows account name. WSL 2.7.12 could not start the custom
kernel through that path.

The exact failed kernel file was copied without modification to an ASCII-only path under
`%ProgramData%`. After a bounded WSL shutdown, the same file booted successfully and returned exactly
`6.18.35.2-microsoft-standard-WSL2+`. The pre-probe `.wslconfig` was restored byte-for-byte afterward.
This separates the path failure from the kernel binary, kernel ABI, distro, and custom-kernel build.

## Installer correction

- Per-user state and rollback metadata remain under `%LOCALAPPDATA%\SwitchTrade`.
- WSL-facing kernel and module artifacts now install under `%ProgramData%\SwitchTrade\kernel`.
- `KernelStorageRoot` is explicit at the lifecycle boundary and recorded in `kernel-state.json`.
- Existing application/kernel rollback behavior is unchanged.
- The lifecycle simulation asserts that the installed kernel comes from the dedicated storage root.

## Verification

- ASCII-path real WSL kernel boot probe: PASS
- `.wslconfig` exact restoration after probe: PASS
- Installer lifecycle tests: 7 passed
- Product/installer regression suite: 86 passed

## Follow-on minimal-rootfs bootstrap correction

The first repaired install passed kernel startup and then exposed the next independent pre-provision
gate: the previously built minimal rootfs did not contain `depmod` or `modinfo`. The module archive was
valid and already contained `modules.dep`, `modules.dep.bin`, and `rtl8xxxu.ko`, but Setup correctly
refused to claim ABI verification without the `kmod` tools.

- New rootfs builds include `kmod` from debootstrap.
- WSL provisioning retains `kmod` as a runtime dependency.
- Setup installs `kmod` on demand before module extraction when repairing an older rootfs.
- The existing isolated distro passed real module extraction, `depmod`, `rtl8xxxu` vermagic, and
  firmware-presence verification after the fallback.

## Same-release Repair correction

A second retry exposed a Windows file-lock issue: Repair tried to overwrite the content-addressed
kernel file that WSL was already running. The lifecycle now verifies and reuses an existing kernel or
modules file when its SHA-256 matches, rejects a content-address collision, and preserves the prior
rollback pointer during same-release Repair. The actual partially installed distro then passed a
same-release repair probe with the kernel reused, rollback state preserved, and the expected release
running.

The earlier `77dd538`, `9014e8f`, and `28221e1` packages are superseded and must not be distributed.
`SwitchTrade-unsigned-private-beta-1e8b4bd.zip` passed its first complete actual install on the affected
non-ASCII-profile PC, but the reinstall test below superseded it.

## Reinstall working-directory correction

An uninstall followed by reinstall exposed another independent bootstrap defect. The WSL provisioner
ran `python -m switchtrade.endpoint` without changing to the application root. Python therefore found
the `switchtrade` package only when Setup happened to inherit a working directory containing the
repository. Launching the same Setup normally from Explorer failed with
`ModuleNotFoundError: No module named 'switchtrade'`.

This was not specific to the development PC, Windows account, custom kernel, or radio. Any machine
could encounter it depending on Setup's launch directory.

The provisioner now:

- runs the endpoint self-check from the staged application root;
- performs that check before replacing the active `/opt/switchtrade` runtime; and
- retains the existing runtime unchanged if staging or self-check fails.

The original failure was reproduced with WSL's working directory set to `/`. The corrected provisioner
then completed from the same unrelated directory and activated the staged runtime successfully. The
lifecycle regression test also requires the self-check to precede backup and activation.

The final replacement is `SwitchTrade-unsigned-private-beta-b2c9d36.zip`. It passed package integrity,
Setup Audit, installed WPF self-test, exact kernel/module ABI comparison, Python imports, endpoint
dry-run, control readiness, graceful shutdown, shortcut/config checks, and an actual reinstall launched
from an unrelated Windows working directory.
