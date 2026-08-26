# Unsigned private-beta candidate build and remaining gates — 2026-08-26

## Outcome

The repository-controlled build is complete. Candidate `beta-91f5a3e` combines the native Windows app,
isolated Ubuntu WSL rootfs, pinned Python runtime, hardware profiles, public-relay configuration,
project-qualified WSL kernel and modules, official usbipd-win prerequisite, setup bootstrap, recovery
content, and tracked third-party notices. It is explicitly unsigned by owner decision and is not yet an
approved or published beta release.

No work from either development line was discarded. The hosting agent's rewritten `production-beta`
line is the integration base. The previous icon/client lineage is retained at
`codex/icon-pre-server-sync-20260826`, and the combined work is retained at
`codex/production-beta-server-integration` before the final fast-forward of `production-beta`.

## Reproducible kernel evidence

- build mirror: `mwl313/wsl2-kernel-build`, commit
  `f8e38eb06e6fd0b511923d39b9c23acf7ae01fb8`;
- Actions run: `32929972152`, success in 46 minutes 28 seconds;
- kernel release: `6.18.35.2-microsoft-standard-WSL2+`;
- kernel SHA-256: `68281fd776455b775cb55a0b1b912dd68a52b0fc9977e0e9fbf6f76ac21cf0b1`;
- modules SHA-256: `de89f1d15a9073afc17d37cd4e221ad9d11a5c2dff91c0f3e91e8f301860c2d1`;
- firmware manifest SHA-256:
  `3c4f475e5d60b7de0412add3c8fcc3d7080c2955b4dc8f5f3a2bc11ddddd6843`.

`scripts/verify-kernel-artifact.py` independently verified manifest schema and hashes, the declared
release directory, `rtl8xxxu`, `vhci-hcd`, `tun`, `tap`, `ccm`, and `cmac`, and that the default artifact
does not contain the quarantined vendor RTL8188EU module.

## Candidate evidence

- application commit: `91f5a3e61a4b1aadfbf241aafac1178f7efbeea0`;
- archive: `artifacts/SwitchTrade-unsigned-private-beta-91f5a3e.zip`;
- archive size: `218100271` bytes;
- archive SHA-256: `88706f57c12efc360d9067b3d2971c2ea68b91b8c61d802a82e0265eceb66667`;
- rootfs SHA-256: `d708ea4be7e7acc8d3ce1a4e5b8d06dd9ac7583c48ca21c4c200b47daf3d2ec3`;
- native EXE SHA-256: `7d9010fe002f58e0ea7936617d2fad0ebe9f53b76089aa7962c08011579f445f`;
- manifest: schema 2, 129 hashed artifacts, `unsigned_private_beta=true`,
  `signature_required=false`;
- default relay: `https://relay.pangyostonefist.org`.

The staged directory and a newly expanded copy of the ZIP both passed `Test-SwitchTradePackage
-AllowUnsignedPackage`. The sibling checksum matched the archive, and `SwitchTradeSetup.exe audit`
returned exit code 0. The candidate is deliberately kept out of Git because it is a 218 MB build output;
its reproducible identities are recorded here and its source inputs are committed.

## Final automated evidence

- Windows-local Python suite: 81 passed;
- clean temporary WSL/Python 3.14 suite: 221 passed, 3 skipped;
- native WPF and Setup Release builds: zero warnings and zero errors;
- web production dependency audit: no known vulnerabilities;
- web lint and desktop bundle: passed;
- Python runtime audit and both .NET dependency audits: no known vulnerabilities;
- public relay: credentialed two-seat lifecycle and opaque bidirectional WebSocket smoke passed again;
- public `/metrics`: HTTP 403.

## Remaining external gates

1. The owner approves the current visual state and tracked notice inventory, or records an explicit
   private-beta exception. The larger UI overhaul remains owner-deferred.
2. The hosting operator performs and records backup/restore, staged restart/reconnect, and two-client
   testing from different NATs. No server credential is stored in this repository.
3. A clean supported Windows 11 machine with at least 8 GB free space runs install, reboot/resume,
   coexistence with existing WSL configuration, repair, update, rollback, uninstall, reinstall, and the
   expected unsigned/unknown-publisher Defender/SmartScreen checks.
4. The second RTL8192EU is qualified with both PCs, WSL instances, and Switches: both creator
   assignments, discovery, room entry, movement, full trade/save/menu return, graceful exit, immediate
   reuse, party grids/popovers, disconnect/recovery, and WAN impairment.
5. Retain the exact ZIP and sibling checksum outside the development workstation, preserve one tested
   rollback release, record Gate 8 approval, and only then publish the candidate to private testers.

Privacy, trainer/Pokémon upload, IP/location analytics, and trade-statistics ingestion remain excluded
from this client and relay by explicit owner direction.
