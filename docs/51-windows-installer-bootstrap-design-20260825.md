# Windows installer/bootstrap design — 2026-08-25

## Decision

Ship the beta as a signed Windows setup bootstrapper, not as a ZIP plus terminal instructions. The
bootstrapper owns prerequisite detection, WSL installation, the SwitchTrade distro/runtime, USB/IP,
the desktop application, health verification, resume-after-reboot, and rollback.

Users should not be asked to reset or delete an existing WSL distribution. Setup may require:

- one Windows reboot when WSL/Virtual Machine Platform is first enabled;
- a bounded `wsl --shutdown` when changing the SwitchTrade kernel/runtime;
- unplug/replug or one USB detach/attach recovery for the selected radio.

## Package shape

1. `SwitchTradeSetup.exe`: signed elevated bootstrapper with detect/install/repair/uninstall modes.
2. Versioned SwitchTrade WSL distribution (`.wsl` package where supported) containing the pinned
   application-side Linux runtime and tools.
3. Versioned custom WSL kernel bundle from the separate kernel repository.
4. Pinned `usbipd-win` prerequisite installer or verified installation path.
5. Windows control service/application plus the built HTML/CSS frontend.
6. Hardware profiles, release manifest, license notices, and recovery documentation.

The application repository does not absorb kernel source. Release packaging consumes a signed,
versioned kernel artifact and manifest from the separate kernel repository.

## Install sequence

1. Check Windows edition/build, architecture, free space, virtualization, reboot status, WSL version,
   existing distributions, existing `.wslconfig`, `usbipd-win`, WebView2, VMware USB Arbitrator, and
   attached profiled radios.
2. Show the exact changes before elevation. Preserve existing WSL configuration and user data.
3. Enable/update WSL 2 and Virtual Machine Platform if needed. Save resumable setup state and request
   one reboot only when Windows requires it.
4. Resume automatically after sign-in and verify that WSL 2 starts.
5. Install the isolated `SwitchTrade` distribution and pinned runtime.
6. Back up and safely merge the custom-kernel configuration. Never overwrite an unrelated
   `.wslconfig`; show conflicts and retain a one-click rollback copy.
7. Install/verify `usbipd-win`, bind only the chosen adapter, and stop VMware USB ownership only with
   explicit setup consent.
8. Install the Windows application, frontend assets, hardware profiles, and shortcuts.
9. Run the same fail-closed ownership/profile/kernel/driver/module/RX readiness check used by the app.
10. Show success only after the non-Switch readiness layers pass. Switch discovery remains the first
    product-run guide.

## Repair and update

- Repair reruns detection and changes only the failed layer.
- Updates are atomic application + profile + compatible kernel/runtime bundles.
- Record the previous version and keep one rollback bundle.
- A kernel change triggers `wsl --shutdown`, never deletion of the user's unrelated distributions.
- Driver/profile additions are ordinary signed bundle updates unless they require new kernel config;
  only those additions consume a new kernel artifact.

## Uninstall

The uninstaller removes the application and optionally unregisters only the named `SwitchTrade` WSL
distribution. It restores the backed-up `.wslconfig` when SwitchTrade changed it. It must never
unregister another distribution or remove `usbipd-win` if another application may use it without a
separate confirmation.

## Packaging gate

The unattended source can build the bootstrap logic, manifests, UI, and distro layout. Final release
approval still requires a clean Windows test, reboot/resume test, existing-WSL coexistence test,
install/repair/uninstall/rollback test, signed-artifact verification, and two-radio product run.

## Primary platform references

- Microsoft WSL installation: <https://learn.microsoft.com/windows/wsl/install>
- Microsoft USB/IP for WSL: <https://learn.microsoft.com/windows/wsl/connect-usb>
- Microsoft custom WSL distributions: <https://learn.microsoft.com/windows/wsl/build-custom-distro>
- Microsoft WSL configuration: <https://learn.microsoft.com/windows/wsl/wsl-config>
