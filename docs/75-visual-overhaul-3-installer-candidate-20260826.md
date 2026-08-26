# Visual Overhaul 3 installer candidate — 2026-08-26

## Candidate identity

- Branch: `production-beta`
- Application commit: `1e8b4bd7b1d3b794c042d81fc699966262b8cafc`
- Package: `SwitchTrade-unsigned-private-beta-1e8b4bd.zip`
- ZIP SHA-256: `c762f426db6a22c2ceac2bc7165573be03a076332e8ee89878088dc38433bc4c`
- ZIP size: `219373610` bytes
- Local build location: `artifacts/release-candidates/`
- Relay: `https://relay.pangyostonefist.org`
- Signing state: explicitly labeled unsigned private beta, per owner exception

The package manifest reports schema 2, release ID `beta-1e8b4bd`, branch `production-beta`, and the
full application commit above. The packaged Windows client is the native Visual Overhaul 3 WPF build,
not the retired web frontend or the earlier `91f5a3e` client.

The earlier `77dd538`, `9014e8f`, and `28221e1` local candidates are superseded and must not be
distributed. They were retained only as diagnostic evidence for the fixes recorded in `docs/76`.

## Reused verified system inputs

The application and installer source were archived fresh from `1e8b4bd`. The hardware/runtime inputs
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
- New package schema-2 integrity verification: PASS
- `SwitchTradeSetup.exe audit --allow-unsigned-package`: PASS, exit 0
- Packaged `windows/SwitchTrade.exe --self-test`: PASS, exit 0
- Product/installer regression suite: PASS, 86 tests
- Kernel install/update/rollback configuration simulation: PASS
- Real non-ASCII-profile kernel boot and same-release Repair: PASS
- Real module extraction, `depmod`, `rtl8xxxu` vermagic, and firmware-presence gate: PASS
- Actual isolated WSL provisioning and installed WPF self-test: PASS
- Installed `app-readiness.v1` control API startup, compatibility, and graceful shutdown: PASS
- Installed release/commit/branch and public relay configuration: PASS
- Desktop shortcut creation: PASS
- ZIP checksum compared with the sibling `.sha256`: PASS

The generic repository-wide `pytest` command also selects Linux/WSL-only `bridge/tests` and is not a
valid Windows-host release command. On this Windows host it reached 215 passes and one skip, then
reported expected environment failures for missing `ldn`/`zstandard`, Linux sysfs path semantics, and
one host dependency API mismatch. The pinned WSL runtime suite remains the authority for that layer;
no unrelated packages were installed into the user's Ubuntu distribution during this build.

## Remaining release gates

This is a current installable candidate, not release approval. It still requires extraction before
launching `SwitchTradeSetup.exe`, Windows unsigned-publisher acceptance, external clean-machine and
reboot/resume qualification, two physical RTL8192EU endpoints, two-PC/two-Switch qualification, WAN
fault/recovery testing, and private publication approval.
