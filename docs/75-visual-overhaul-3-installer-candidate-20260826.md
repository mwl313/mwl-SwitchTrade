# Visual Overhaul 3 installer candidate — 2026-08-26

## Candidate identity

- Branch: `production-beta`
- Application commit: `71d936c70c25d88b546256a9023a3936eee92e33`
- Package: `SwitchTrade-unsigned-private-beta-71d936c.zip`
- ZIP SHA-256: `1656effd19ac4c7f6577c5b272805566b43fe0fd715a81f1ebc4adf26fb028e8`
- ZIP size: `219382404` bytes
- Local build location: `artifacts/release-candidates/`
- Configured relay: `https://relay.pangyostonefist.org` (DNS/TLS health and public directory restored;
  relay commit `71d936c` deployment remains required for stale-version teardown)
- Signing state: explicitly labeled unsigned private beta, per owner exception

The package manifest reports schema 2, release ID `beta-71d936c`, branch `production-beta`, and the
full application commit above. The packaged Windows client is the native Visual Overhaul 3 WPF build,
not the retired web frontend or the earlier `91f5a3e` client.

The earlier `77dd538`, `9014e8f`, `28221e1`, `1e8b4bd`, `b2c9d36`, `8667888`, and `125fbac` local candidates are
superseded and must not be distributed. They were retained only as diagnostic evidence for the fixes
recorded in `docs/76` and `docs/77`.

## Reused verified system inputs

The application and installer source were archived fresh from `71d936c`. The hardware/runtime inputs
were reused byte-for-byte from the previously integrity-qualified `91f5a3e` candidate because they are
versioned independently of the UI:

- Rootfs SHA-256: `d708ea4be7e7acc8d3ce1a4e5b8d06dd9ac7583c48ca21c4c200b47daf3d2ec3`
- Kernel release: `6.18.35.2-microsoft-standard-WSL2+`
- Kernel SHA-256: `68281fd776455b775cb55a0b1b912dd68a52b0fc9977e0e9fbf6f76ac21cf0b1`
- Modules SHA-256: `de89f1d15a9073afc17d37cd4e221ad9d11a5c2dff91c0f3e91e8f301860c2d1`
- `usbipd-win` version: `5.3.0`
- `usbipd-win` MSI SHA-256: `1c984914aec944de19b64eff232421439629699f8138e3ddc29301175bc6d938`

The old package's complete schema-2 artifact manifest passed before any input was reused. The new
builder then independently checked the kernel/modules manifest and regenerated every package hash.

## Internal verification

- Native WPF Release publish and built-in self-test: PASS
- Native setup progress bootstrap build with zero warnings: PASS
- GUI success output is reduced to a concise completion/package-retention message; CLI output remains
  unchanged for automation and failure diagnostics remain visible
- New package schema-2 integrity verification: PASS
- `SwitchTradeSetup.exe audit --allow-unsigned-package`: PASS, exit 0
- Packaged `windows/SwitchTrade.exe --self-test`: PASS, exit 0
- Product/installer regression suite: PASS, 90 tests
- Kernel install/update/rollback configuration simulation: PASS
- Real non-ASCII-profile kernel boot and same-release Repair: PASS
- Real module extraction, `depmod`, `rtl8xxxu` vermagic, and firmware-presence gate: PASS
- Actual isolated WSL provisioning and installed WPF self-test for the unchanged `b2c9d36` runtime
  base: PASS
- Explorer-equivalent reinstall from an unrelated working directory: PASS; staged self-check ran
  before runtime activation and did not reproduce `ModuleNotFoundError`
- Installed `app-readiness.v1` control API startup, compatibility, and graceful shutdown: PASS
- Installed release/commit/branch and public relay configuration: PASS
- Corrected launcher startup from an unrelated Windows working directory with no USB radio attached:
  PASS; control became ready and version-compatible
- Actual package Update followed by installed WPF launch: PASS; UI Automation reached Home rather than
  the recovery screen, and no radio was required for Settings or online-room navigation
- Launcher failure diagnostics are bounded and preserved under the startup log directory: PASS
- WSL/glibc A/AAAA lookup through the host DNS proxy: PASS with `single-request-reopen`; IPv4 fallback
  remains available when WSL has no IPv6 route
- Member leave after an already-committed remote leave: PASS; stale local credentials are cleared
  without displaying a false relay outage
- Installed owner room creation and close: PASS; remote room version advanced and local authority was
  removed
- Installed Public Rooms proxy: PASS, five consecutive HTTP 200 responses
- Desktop shortcut creation: PASS
- ZIP checksum compared with the sibling `.sha256`: PASS

The generic repository-wide `pytest` command also selects Linux/WSL-only `bridge/tests` and is not a
valid Windows-host release command. On this Windows host it reached 215 passes and one skip, then
reported expected environment failures for missing `ldn`/`zstandard`, Linux sysfs path semantics, and
one host dependency API mismatch. The pinned WSL runtime suite remains the authority for that layer;
no unrelated packages were installed into the user's Ubuntu distribution during this build.

## Remaining release gates

This is a current installable candidate, not release approval. It still requires extraction before
launching `SwitchTradeSetup.exe`, Windows unsigned-publisher acceptance, relay `71d936c` deployment,
external clean-machine and reboot/resume qualification, two physical RTL8192EU endpoints,
two-PC/two-Switch qualification, WAN fault/recovery testing, and private publication approval.
