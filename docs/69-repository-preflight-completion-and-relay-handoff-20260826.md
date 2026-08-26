# Repository preflight completion and relay handoff — 2026-08-26

Status: the public relay is live, repository-controlled integration is complete, and a checksummed
unsigned candidate has been built from the verified kernel/rootfs/input set. Clean-machine and hardware,
relay-operations, and two-Switch qualification remain. The owner explicitly selected an unsigned private
beta, so this is not publisher-verified release approval.

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

## Relay hosting status

`https://relay.pangyostonefist.org` returned the expected health contract, rejected the legacy
unauthenticated endpoint, and passed authenticated two-seat room lifecycle plus opaque bidirectional RFU
WebSocket smoke on 2026-08-26. The Python client now sends a versioned SwitchTrade User-Agent because the
Cloudflare ingress rejects Python's default User-Agent. Full evidence is in `docs/71`.

Future origins should deploy the exact committed revision using:

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

Backup/restore, staged restart/reconnect, restricted metrics, and two-NAT tests still require operator
evidence. The repository default URL is stored in `payload/release-config.json`; packaging copies the
selected URL into the package and hashes it in the complete manifest. A signed public release would also
sign that manifest, while the owner-approved private beta visibly identifies the unsigned limitation.

## Distribution completion

The installer now provides a native setup window for Install, Update, Repair, Rollback, and Uninstall.
It requires explicit prerequisite and global custom-kernel consent, can release VMware ownership only
with consent, enumerates profiled USB devices by Windows bus ID, labels experimental hardware, and can
defer adapter setup. The selected USB identity is preserved through both Windows USB/IP preparation and
the WSL driver/RX gate.

Package verification remains fail-closed for signed releases. The owner-approved unsigned private-beta
mode instead requires complete inputs, a public HTTPS relay, explicit artifact naming and warning, and a
complete SHA-256 manifest, while truthfully providing no publisher-authenticity claim. Update/rollback
swaps the Windows app, WSL runtime, and retained kernel state together. Uninstall removes only
SwitchTrade-owned files and unregisters only the named SwitchTrade distro when explicitly requested.

## Internal evidence

- clean pinned Linux/WSL suite: 221 passed, 3 skipped;
- Windows-local suite: 81 passed;
- focused authority/tunnel/installer/runtime suite: 35 passed;
- production-mode credentialed relay hosting smoke: passed again against the public deployment;
- native WPF Release build, single-file publish, and built-in self-test: passed with zero warnings/errors;
- native setup Release build: passed with zero warnings/errors;
- PowerShell parser, Bash parser, Python compilation, package-manifest tamper rejection, and kernel
  lifecycle simulation: passed;
- web production dependency audit: no known vulnerabilities; lint and desktop bundle passed;
- kernel mirror Actions run `32929972152`: passed; the independent verifier accepted the kernel,
  module/firmware hashes, required modules, and default vendor-8188 exclusion;
- candidate `SwitchTrade-unsigned-private-beta-91f5a3e.zip`: staged and ZIP round-trip integrity passed,
  Setup audit returned 0, archive SHA-256
  `88706f57c12efc360d9067b3d2971c2ea68b91b8c61d802a82e0265eceb66667`;
- Docker Compose YAML parsed successfully; Docker image execution was not available on this workstation,
  so the hosting operator must perform the documented container build and health check.

No Switch hardware was needed or used for this pass. The relay payload replay uses the tracked
checksum-valid Salamence fixture and proves byte-exact opaque transport in both directions; it is not a
substitute for real WAN/radio qualification.

## Remaining private-beta gates

1. Owner-deferred final visual and legal-notice approval. Icon wiring, the factual notice inventory, and
   the real GitHub Issues support destination are complete.
2. External retention of the exact unsigned private-beta archive/checksum and one tested rollback
   release. Windows code signing is waived by the owner for this beta and remains a future public-release
   feature.
3. Relay backup/restore, staged restart/reconnect, and two-NAT qualification. Public metrics denial is
   already verified.
4. Clean Windows 11 24H2 install/reboot/coexistence/Defender/SmartScreen/lifecycle qualification,
   including the expected unknown-publisher behavior.
5. Both RTL8192EU adapters and two-PC/two-WSL/two-Switch discovery, full trade, teardown, immediate reuse,
   decoder comparison, and WAN impairment qualification.
6. Written Gate 8 approval after the accepted Gate 0 exception and every remaining external result are
   recorded in `docs/55`.

Privacy/consent/analytics remain owner-external. The present client and relay expose no Privacy tab,
trade-statistics ingestion, Pokémon upload, trainer upload, raw-IP analytics, or location collection.
