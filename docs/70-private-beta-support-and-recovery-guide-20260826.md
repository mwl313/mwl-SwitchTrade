# Private-beta support and recovery guide — 2026-08-26

This guide documents the supported `0.2.0-beta.1` boundary and safe recovery path. It must be updated
when the release manifest, supported hardware, Windows baseline, or setup behavior changes. Replace the
support-destination placeholder only after the owner approves a real destination.

## Supported beta boundary

- Windows 11 24H2 x64, build 26100 or newer.
- WSL 2 with the isolated distro named `SwitchTrade` and the signed project custom-kernel bundle.
- The pinned `usbipd-win` version recorded in the release manifest.
- RTL8192EU USB `0bda:818b` after both physical cards pass Gate 7.
- FireRed/LeafGreen Direct Connection trading between two unmodified Switch consoles.

RTL8188EU `0bda:8179` is quarantined and cannot start a trading attempt. Other profiled adapters are
experimental: users may select them freely and run diagnostics, but they are not beta-supported until
their full capability matrix passes. Windows 10, ARM64 Windows, VMware passthrough, stock WSL kernels,
internal laptop Wi-Fi, and 5 GHz-only adapters are not supported beta claims.

## Recovery order

Always use the smallest named action. Do not reset WSL, unregister Ubuntu, delete another distro,
replace the user's complete `.wslconfig`, or reinstall Windows.

| Visible state | First action | If it persists |
|---|---|---|
| Update required / version mismatch | Run the same signed Setup package and choose **Update** | Export a support bundle; do not bypass compatibility checks |
| Control service unavailable | Use **Retry** once | Run signed Setup **Repair** |
| Relay unavailable | Check ordinary internet access and retry | Confirm the operator's `/health` status and configured release URL |
| Adapter missing | Reconnect the selected USB adapter and choose it in Settings | Run Setup **Repair** once for administrator USB binding |
| Radio health failed | Keep the adapter connected and use **Repair adapter** | Export diagnostics; cold detach/reattach only that adapter |
| Room not found/full/expired | Return to Home and create or join a new six-character room | Do not reuse an expired room code |
| Partner reconnecting | Wait through the bounded reconnect window | Room owner removes the offline member only after grace expires |
| Session failed or Switch room is probably 5 GHz | End the attempt, recreate the Switch room, and retry on discovered 2.4 GHz LDN | Export both endpoints' run IDs if repeated |
| Decoder unavailable/incomplete | Continue trading; party details remain unavailable | Export diagnostics only if the transport also fails |
| Previous update is bad | Run signed Setup **Rollback** | Stop and preserve logs if atomic recovery reports a partial failure |

## Hardware ownership

Normal launch may attach an already-bound adapter without elevation. First install or repair may require
administrator approval for USB/IP binding. Setup changes VMware USB ownership only after explicit
consent. If a selected adapter disappears, close VMware, shut down only the affected SwitchTrade
session, reconnect the physical device, and run Repair; never unregister an unrelated WSL distro.

The custom WSL kernel selection is global to all WSL 2 distributions. Setup backs up the complete prior
`.wslconfig`, merges only its owned kernel settings, and restores the previous file on rollback or
uninstall when SwitchTrade owns the change. A corporate policy rejection is an unsupported condition,
not permission to disable the safety gate.

## Diagnostics and data boundary

Use **Create support bundle** from the app. Record both users' run IDs, approximate UTC time, Windows
build, adapter USB/bus IDs, and the exact visible error. The generated bundle includes redacted version,
health, state-transition, counter, and recovery evidence. It must not include member/reconnect tokens,
room passcodes, raw RFU payloads, Nintendo keys, full Pokémon party data, raw IP addresses, or unrelated
machine inventory.

The product does not require Nintendo prod keys. Never request, copy, attach, or log them.

Current support destination: **owner approval required before release**. Do not publish a placeholder as
if it were a working contact.

## Operator incidents

For a relay incident, remove the affected URL from new signed package configuration, preserve redacted
operational logs and the encrypted authority volume, rotate deployment credentials, deploy the fixed
single-worker image, validate backup restore, and run `python -m relay.smoke` before promotion. Moving a
compromised authority database out of service invalidates its active rooms. The relay stores credential
hashes and room control events, not RFU/Pokémon payloads.

For an installer partial failure, do not manually shuffle application or kernel files. Preserve the
setup output and state directory, then use the same signed package's Repair or Rollback action. A
`ROLLBACK_PARTIAL_FAILURE` requires developer review before another mutation.
