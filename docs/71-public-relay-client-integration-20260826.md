# Public relay and unsigned private-beta integration — 2026-08-26

## Preserved integration baseline

The hosting agent force-updated `origin/production-beta` from `df59539` to `f61710b`. The rewritten
baseline commit `e4d9527` has the exact same Git tree as `df59539`; the remote then adds the relay URL,
deployment memo, and kernel-workflow source. The pre-existing local icon work is preserved independently
on `codex/icon-pre-server-sync-20260826` and was cherry-picked onto the remote baseline before further
work. No client or hosting progress was discarded.

## Live relay evidence

Public endpoint: `https://relay.pangyostonefist.org`

- `GET /health` returned HTTP 200 with `room-control.v1` and `payload_mode=opaque`.
- legacy unauthenticated `POST /session/create` returned HTTP 404.
- the credentialed hosting smoke created and joined a two-seat room, marked both members ready, created
  one attempt, atomically selected and locked the creator, connected both scoped RFU WebSocket seats,
  relayed opaque bytes in both directions, and closed the room.
- Cloudflare rejected Python's default `Python-urllib` User-Agent with HTTP 403. The product client and
  smoke now send `SwitchTrade/<version>` on every HTTP request; the unmodified smoke command then passes.
- WebSocket transport passed through the public Cloudflare ingress in both directions.
- public `GET /metrics` returned HTTP 403, confirming the metrics endpoint is not exposed through the
  public ingress.

The deployment is live and suitable for client integration. Operational acceptance still requires a
documented backup/restore exercise, staged restart/reconnect, and two endpoints
behind different NATs.

## Release configuration

`payload/release-config.json` is the repository SSOT for the default public relay. The package builder
loads this file unless an explicit `-RelayUrl` override is supplied, writes the selected URL into the
packaged payload, and includes its hash in the schema-2 manifest.

## Owner code-signing exception

The owner explicitly declined Windows code signing for this private beta. The signed `-Release` path is
retained for a future public release. The current distribution uses `-UnsignedPrivateBeta`, requires the
complete install inputs and a non-loopback HTTPS relay, names and labels the artifact as unsigned, shows
an unavoidable publisher warning before the setup UI, and permits ordinary double-click installation.

SHA-256 manifests still detect corruption within the downloaded package. Without a trusted signature,
they cannot prove publisher identity or defend against an attacker replacing both payload and manifest.
Windows displays an unknown publisher and managed systems may block installation. This is an accepted
private-beta limitation, not a claim of signed-release security.

## Kernel progress reconciliation

The application repository remains the kernel-build SSOT and the separate `wsl2-kernel-build` repository
remains its Actions execution mirror. The hosting-agent baseline had copied the older minimal `main`
workflow and accidentally omitted the later `gptsolreview` hardware-expansion work. The SSOT now preserves
both lines of progress:

- the beta-qualified `linux-msft-wsl-6.18.35.2` ref is the default;
- RTL8192EU firmware, regulatory database, USB/IP, rtl8xxxu, TUN/TAP, CCM, and CMAC are required;
- validated `extra_kernel_config` and `extra_firmware` inputs keep new in-kernel drivers expandable;
- the pinned, patched RTL8188EU vendor build remains opt-in and explicitly experimental;
- each artifact now includes kernel, module, and firmware SHA-256 identities in `manifest.json`.

The source and execution mirror were byte-identical at dispatch. Actions run `32929972152` succeeded from
mirror commit `f8e38eb06e6fd0b511923d39b9c23acf7ae01fb8`. The independent application-side verifier accepted
the `6.18.35.2-microsoft-standard-WSL2+` kernel, modules, firmware manifest, required radio/USB/IP/TUN and
crypto modules, and confirmed that the default artifact excludes the quarantined vendor RTL8188EU module.
External RTL8192EU and two-Switch qualification is still required; artifact verification is not hardware
qualification.

## Reproducibility and notices

All direct and transitive Python runtime distributions are now exactly pinned to the clean WSL set that
passes the full suite. The repository notice inventory covers the AGPL/GPL bridge components, installed
Python distribution licenses, self-contained .NET runtime, WSL kernel source offer, Realtek firmware,
wireless regulatory database, Ubuntu rootfs license locations, and the unmodified usbipd-win prerequisite.
It is the package builder's default notice input. Technical inventory is complete; final legal approval
remains an owner/reviewer release decision.
The archive builder also writes a sibling SHA-256 file so the exact private-beta download can be retained
and checked independently of the manifest inside the archive.

Hardware quick diagnostics now scope kernel failures to the selected USB topology and its currently
bound driver. This prevents an RTL8192EU run from inheriting an RTL8188EU failure left earlier in the
same boot's dmesg, and recognizes an externally loaded vendor module through `/sys/module` when no
installed `modinfo` record exists. Both behaviors are regression-tested against the live two-card state.

## Remaining release gates

Candidate `SwitchTrade-unsigned-private-beta-91f5a3e.zip` is now built from the verified kernel, minimal
rootfs, native EXE, official usbipd MSI, public-relay config, and tracked notices. Its schema-2 manifest
covers 129 artifacts, both staged and post-ZIP integrity checks pass, Setup audit exits 0, and archive
SHA-256 is `88706f57c12efc360d9067b3d2971c2ea68b91b8c61d802a82e0265eceb66667`.
Full evidence is in `docs/72`.

1. Approve the tracked third-party notices and current visual exception. The real support destination is
   the repository's enabled GitHub Issues page and is linked from the native Support tab.
2. Complete relay backup/restore, staged restart/reconnect, and two-NAT operational tests.
3. Complete clean-Windows install, reboot/resume, coexistence, repair, update, rollback, uninstall, and
   reinstall qualification for the unsigned package.
4. Qualify both RTL8192EU adapters and the two-PC/two-WSL/two-Switch production path, including both
   creator assignments, full trade/save/exit, immediate reuse, party display, and WAN impairment.
5. Retain the exact candidate/checksum externally, preserve a tested rollback release, and record written
   private-beta approval before publication.

The owner has deferred further visual overhaul. The current icon wiring is implemented and build-tested;
visual redesign remains backlog and does not change the relay, endpoint, or installer contracts.
