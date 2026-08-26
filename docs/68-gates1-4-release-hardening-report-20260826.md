# Gates 1–4 release hardening report — 2026-08-26

Status: implementation complete for the locally controllable Execution 2 work. A public beta artifact
is not yet claimable because the final signing certificate, approved legal notices, signed kernel
release, minimal rootfs, production relay URL, and clean-machine/hardware qualification are external
release inputs.

## Completed in this pass

- Added a schema-2 package manifest covering every shipped file. Setup rejects missing, unexpected,
  or SHA-256-mismatched files before mutation.
- Added detached CMS verification against the Windows trust chain and code-signing EKU. Unsigned builds
  are limited to explicit internal QA; `-Release` fails closed without the certificate and required
  artifacts.
- Added Authenticode signing hooks for `SwitchTradeSetup.exe` and `SwitchTrade.exe`, plus fail-closed
  release checks for a non-loopback HTTPS relay and approved notice input.
- Added non-secret installer resume state and an HKCU RunOnce continuation for WSL/`usbipd-win`
  restart boundaries. The package is verified again when setup resumes.
- Corrected kernel module handling. `.vhd`/`.vhdx` may use WSL `kernelModules`; the kernel repository's
  `modules-<release>.tar.gz` is extracted into `/lib/modules` inside the isolated distro and followed by
  `depmod`. Installed kernel/module filenames include the release and content identity so an update
  cannot overwrite the retained rollback artifact.
- Added kernel release, `rtl8xxxu` vermagic, firmware, profiled driver binding, and actual-RX gates.
  Policy-blocked custom-kernel startup restores the previous `.wslconfig` and emits a stable unsupported
  condition.
- Replaced generic recovery copy with stage-specific native guidance for version, control, relay,
  radio, session, and decoder failures. The client never advises users to reset or unregister WSL.

## Evidence run

- PowerShell parser: PASS for all changed installer scripts.
- `python -m pytest tests/test_installer_lifecycle.py tests/test_gate4_runtime.py -q`: 14 passed.
- Full suite in a clean WSL virtual environment with pinned dependencies: 204 passed, 3 skipped.
- Native setup bootstrap Release build: PASS, zero warnings/errors.
- Native WPF desktop Release build: PASS, zero warnings/errors.
- Internal full package assembly: PASS.
- Schema-2 full artifact verification: PASS.
- Deliberately modified `payload/release-config.json`: rejected with
  `PACKAGE_ARTIFACT_MISMATCH` as expected.
- Kernel lifecycle simulation: PASS, including proof that a modules tar is not written to
  `.wslconfig` as `kernelModules`.

## Release inputs still required

1. Approve final logo/icon, legal notices, and support destination.
2. Supply a trusted code-signing certificate/private key through the release environment.
3. Publish a versioned kernel, modules archive, manifest, and detached signature from the separate
   kernel repository.
4. Produce and freeze the minimal rootfs and production HTTPS relay URL.
5. Build the signed package, then qualify install/resume/update/rollback/uninstall on a clean Windows
   11 24H2 machine and both physical RTL8192EU adapters.

Until those inputs and qualifications exist, the correct label is **release mechanism implemented,
private-beta package not yet signed or qualified**.
