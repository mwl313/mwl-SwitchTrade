# Repository preflight completion and relay handoff — 2026-08-26

Status: all preflight work that can be completed inside this repository without release credentials,
an external host, a clean qualification PC, or two physical Switch endpoints is implemented. This is
an internal `0.2.0-beta.1` release candidate, not release approval.

## Completed product path

The native `SwitchTrade.exe` starts the adjacent hidden launcher, which starts the isolated
`SwitchTrade` WSL runtime and local control API. The control service owns adapter selection, USB/IP
attachment, the fail-closed radio health gate, endpoint lifecycle, diagnostics, room credentials, and
passive party projection. The Windows client never embeds the radio protocol or member credentials.

Private rooms use one server-authoritative two-member model:

1. create or join returns one stable member seat and scoped member/reconnect credentials;
2. both members become ready;
3. exactly one active connection attempt is created;
4. the first valid creator claim wins atomically and the creator/finder roles are locked;
5. each endpoint connects its immutable relay seat with both a bearer credential and that attempt ID;
6. the relay forwards bounded RFU envelopes opaquely and stores no game payload;
7. terminal attempt, leave, removal, close, expiry, or reconnect-grace failure invalidates the path.

The private room code is exactly six characters. Knowing that code is insufficient to occupy a seat,
mutate room state, reconnect a member, or open a production RFU tunnel. The legacy unauthenticated
relay endpoints are disabled in production mode.

## Relay hosting handoff

The hosting operator should deploy the exact committed revision using:

```bash
docker compose -f relay/compose.yaml build --pull
docker compose -f relay/compose.yaml up -d
python -m relay.smoke https://relay.example.invalid
```

The container is non-root, read-only apart from its persistent SQLite authority volume, single-worker,
and loopback-bound for a same-host TLS reverse proxy. The repository root `.dockerignore` limits the
build context to the relay and shared tunnel package. Full ingress, backup, logging, restart, TLS, and
promotion requirements are in `relay/DEPLOYMENT.md`.

The hosting operator owns the machine, DNS, certificate, encrypted persistent volume, backup/restore,
alerts, and the final public HTTPS base URL. They must keep one worker/replica for beta, enable WebSocket
upgrades, restrict `/metrics`, and leave `SWITCHTRADE_ENABLE_LEGACY_RELAY=0`. No deployment credential,
certificate, or secret belongs in Git.

After staged restart and two-NAT tests pass, the operator gives the packaging owner only the public
HTTPS base URL. `installer/Build-Package.ps1 -Release` rejects HTTP and loopback URLs, writes the URL to
`payload/release-config.json`, hashes it in the complete package manifest, and signs that manifest.
Daily launch verifies the installed manifest signature and configuration hash before using the URL.

## Distribution completion

The installer now provides a native setup window for Install, Update, Repair, Rollback, and Uninstall.
It requires explicit prerequisite and global custom-kernel consent, can release VMware ownership only
with consent, enumerates profiled USB devices by Windows bus ID, labels experimental hardware, and can
defer adapter setup. The selected USB identity is preserved through both Windows USB/IP preparation and
the WSL driver/RX gate.

Package verification is fail-closed: a release requires a trusted code-signing certificate, detached
manifest signature, Authenticode-signed native executables, complete artifact hashes, approved notices,
a pinned USB/IP package, minimal rootfs, and signed kernel/modules metadata. Update/rollback swaps the
Windows app, WSL runtime, and retained kernel state together. Uninstall removes only SwitchTrade-owned
files and unregisters only the named SwitchTrade distro when the user explicitly requests purge.

## Internal evidence

- pinned Linux/WSL suite: 212 passed, 3 skipped;
- focused authority/tunnel/installer/runtime suite: 35 passed;
- production-mode credentialed relay hosting smoke: passed;
- native WPF Release build, single-file publish, and built-in self-test: passed with zero warnings/errors;
- native setup Release build: passed with zero warnings/errors;
- PowerShell parser, Bash parser, Python compilation, package-manifest tamper rejection, and kernel
  lifecycle simulation: passed;
- Docker Compose YAML parsed successfully; Docker image execution was not available on this workstation,
  so the hosting operator must perform the documented container build and health check.

No Switch hardware was needed or used for this pass. The relay payload replay uses the tracked
checksum-valid Salamence fixture and proves byte-exact opaque transport in both directions; it is not a
substitute for real WAN/radio qualification.

## External release blockers only

1. Owner/GPT final visual approval, public icons/logo, legal notices, and real support destination.
2. Signed kernel/modules/firmware artifacts from the separate kernel repository.
3. Trusted Windows code-signing certificate, signed rootfs/package inputs, and reproducible release
   archive/checksum retention.
4. Relay deployment behind public TLS plus backup restore, restart, and two-NAT qualification by the
   hosting operator.
5. Clean Windows 11 24H2 install/reboot/coexistence/Defender/SmartScreen/lifecycle qualification.
6. Both RTL8192EU adapters and two-PC/two-WSL/two-Switch discovery, full trade, teardown, immediate reuse,
   decoder comparison, and WAN impairment qualification.
7. Written Gate 8 approval after the accepted Gate 0 exception and every remaining external result are
   recorded in `docs/55`.

Privacy/consent/analytics remain owner-external. The present client and relay expose no Privacy tab,
trade-statistics ingestion, Pokémon upload, trainer upload, raw-IP analytics, or location collection.
