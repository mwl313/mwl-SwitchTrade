# Gates 1–6 authority and distribution report — 2026-08-26

## Result

Implementation has advanced through the automatable portion of Gate 6. The repository now contains a
server-authoritative two-member room path, credentialed opaque RFU relay, native Windows bootstrapper,
isolated WSL/runtime provisioning, reversible custom-kernel configuration, hardware preflight, and an
internal checksummed package build.

This is **not a private-beta release**. Public TLS deployment, signed release inputs, clean-machine and
reboot tests, Defender/SmartScreen evidence, and two-PC/two-Switch qualification remain external gates.
Gate 0 is still owner-deferred. No privacy tab, consent UI, analytics upload, IP/location collection, or
committed-trade server database was implemented.

## Gate 5 implementation

- `relay/authority.py` persists room-control state and ordered events in SQLite.
- Room/member/attempt/event identifiers are time-ordered UUIDv7 values.
- A six-character room code is only a locator. Each immutable seat has a high-entropy member token and
  rotating reconnect token; the database stores only SHA-256 hashes.
- Exactly two active seats are permitted. Mutations require bearer authority and UUIDv7 idempotency
  keys. Presence heartbeats, reconnect deadlines, room expiration, rate limits, message-size limits,
  and restart persistence are bounded.
- Creator selection is one atomic transaction and is independent of room ownership and tunnel seat.
  Either trainer can win by pressing Connect first. Transfer is permitted before role lock.
- The RFU WebSocket validates the credential/seat pair, keeps `member_a`/`member_b` tunnel direction
  stable, and forwards validated envelopes without decoding or retaining their game payload.
- `/health`, private operational `/metrics`, JSON operational logs, and the operator runbook in
  `relay/DEPLOYMENT.md` are present. The container is intended to sit behind TLS ingress; localhost is
  still the only environment exercised here.

## Gate 4 client integration

- WPF create/join actions target `/api/v1/trade-room`; the legacy process-local group API remains only
  for regression compatibility.
- Member and reconnect credentials remain in mode-0600 WSL runtime files. WPF never receives them.
- Both users publish readiness. The local control service waits for the authoritative two-member state,
  creates or joins the same attempt, receives the immutable tunnel seat plus creator/finder assignment,
  locks the role, and only then launches the endpoint.
- The endpoint receives a credential-file path rather than a bearer token on its command line.
- WPF polls membership, presence, readiness, occupancy, and role assignment. Before assignment it gives
  neutral instructions instead of assuming that the owner creates the Switch room.
- Endpoint completion, failure, trading-room evidence, teardown, retry, and leave/close are reflected
  back into authoritative state. Reconnect automatically rotates stored credentials after a 401.

## Gates 1–3 implementation

- `SwitchTradeSetup.exe` is a native self-contained .NET bootstrapper. It invokes the allowlisted setup
  actions hidden and presents success/failure natively; it does not open a browser.
- Package construction checksums the native WPF EXE, rootfs, release configuration, optional pinned
  usbipd MSI, and optional kernel/modules inputs. The retired web demo is not bundled.
- Setup audits Windows build/architecture, virtualization, free space, pending reboot, WSL, usbipd,
  existing distributions, `.wslconfig`, VMware ownership, and kernel-input presence.
- Install/repair/update provisions only the named `SwitchTrade` distro and atomically swaps the Windows
  application while retaining one prior version. Rollback swaps the retained app and kernel. Uninstall
  removes only SwitchTrade app paths and restores the previous WSL configuration; distro purge requires
  an explicit switch and names only `SwitchTrade`.
- Kernel lifecycle code requires an explicit global-impact acceptance, validates hashes, preserves the
  complete prior `.wslconfig`, changes only `kernel`/`kernelModules`, retains release rollback metadata,
  uses bounded `wsl --shutdown`, and restores the exact original file on uninstall.
- Administrator work is limited to setup/repair binding and accepted VMware release. Ordinary launch
  can attach a previously bound adapter without self-elevating.
- Setup and every production endpoint run the common USB/driver/module/RX/channel/role health gate.
  `ldn 0.0.17` permits 2.4-GHz LDN channels 1, 6, and 11; generic channels 2–5 and 7–13 are not part of
  that protocol scan set. The 2.4-GHz-only RTL8192EU path must instruct the user to recreate a likely
  5-GHz Switch room.

## Internal evidence

- Linux/WSL repository suite: 196 passed, 2 Windows-only lifecycle tests skipped.
- Focused Windows authority, tunnel, diagnostics, decoder, and lifecycle suite: 33 passed.
- WPF Release build: zero warnings and zero errors; native self-test passed.
- Setup Release build: zero warnings and zero errors.
- Kernel lifecycle simulation: install v1, update v2, release rollback to v1, and byte-exact restoration
  of a pre-existing `.wslconfig` all passed without changing the real machine configuration.
- Network integration proves unauthenticated authoritative WebSockets are rejected, both valid seats
  exchange arbitrary opaque RFU payloads, simultaneous creator claims yield one winner, secrets do not
  appear in WPF responses/SQLite, and duplicate commands increment room state once.
- A checksummed internal upgrade/repair package was built. It intentionally lacks a rootfs, signed
  kernel/modules manifest, pinned usbipd MSI, public HTTPS relay URL, and signatures, so clean install
  must refuse it rather than silently use developer dependencies.

## Remaining work before Gate 6 can close

1. Close Gate 0: owner/GPT visual approval, production icons, legal notices, support destination.
2. Publish signed/versioned rootfs, custom kernel/modules, usbipd, manifest, desktop, and setup inputs.
3. Configure an actual `https://` relay through signed release configuration and run two endpoints
   behind different consumer NATs.
4. Add safe reboot-resume state to setup. The current prerequisite path explains the reboot and asks
   the user to rerun; it does not resume automatically after sign-in.
5. On a clean supported Windows 11 machine, run install, first/repeated launch, repair, update, rollback,
   uninstall, reinstall, optional named-distro purge, and verify no unrelated distro/path is touched.
6. Repeat on a machine with existing distros and a nontrivial `.wslconfig`; compare the restored file
   byte-for-byte after rollback/uninstall.
7. Verify signatures, Defender, SmartScreen, shortcut behavior, no daily UAC, USB detach/reattach, and
   application support bundles.
8. Proceed to Gate 7 with the second RTL8192EU and two real PCs/Switches. RTL8188EU remains quarantined.

Privacy/analytics remain an externally administered future stream. Because no analytics endpoint is
present, trading and local party display have no privacy-service dependency.
