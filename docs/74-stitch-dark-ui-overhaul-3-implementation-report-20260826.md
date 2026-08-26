# Visual Overhaul 3 implementation report — 2026-08-26

## Outcome

Visual Overhaul 3 is implemented on `codex/visual-overhaul-3` as a native WPF change. It preserves
the existing EXE → isolated WSL control layer → hosted authority/opaque relay architecture and does
not add a browser runtime. The previous synthetic public-room and party-preview paths were removed.

Privacy, consent, analytics, IP/location collection, and trade-statistics upload were intentionally
not implemented by owner direction.

## Inputs and provenance

- Tracked handoff: `docs/73-stitch-dark-ui-codex-integration-handoff-20260826.md`
- Handoff SHA-256: `E8F0957C14C666BDAB765E89153CAE40524954ED3450045CD5C0CB3E0388C472`
- Stitch reference ZIP SHA-256: `833685222A3410551007388CA6886A680CA22DFB537C5700890B1AA14F0B9A6D`
- Local extracted reference during implementation: `artifacts/stitch-ui-reference-20260826/`

The ZIP's PNGs, layout hierarchy, and dark visual rhythm were inspected. Its HTML, Tailwind CDN,
Google Fonts imports, hot-linked images, synthetic rooms, synthetic parties, avatars, and activity
logs were not copied into the product or committed as runtime dependencies.

## Native visual system

- Replaced the light resource dictionary with `Themes/Colors.Dark.xaml` using the exact dark,
  surface, text, green, blue, You, Partner, and error tokens from the handoff.
- Rebuilt the persistent shell with a fixed wordmark, readiness, Settings, reserved Back row,
  24-DIP outer gutters, a 1080-DIP content boundary, 1240×860 default size, and 960×700 minimum.
- Embedded Space Grotesk, Inter, and Space Mono from the official Google Fonts repository. Each SIL
  OFL file is embedded, retained with source, and attributed in `legal/THIRD-PARTY-NOTICES.txt`.
- Preserved Windows High Contrast resources, keyboard focus, reduced-motion behavior, native WPF
  accessibility peers, minimum 44-DIP controls, and left-aligned stable geometry.
- Replaced the system ComboBox rendering with a native dark closed/popup template. Normal, hover,
  keyboard focus, selected, and disabled states have explicit contrasting foreground/background
  pairs. Adapter values use a user-facing, bus-first label and ellipsis rather than raw record text.

## Screen implementation

- Home: full-width neon-green Create action and equal Browse/Private actions with no preview labels.
- Create: 7/5 layout, sticky action bar, required room/trainer/game/language fields, `None` defaults,
  Private/Public radio selection, and always-active optional listing/invitation metadata.
- Private join: one accessible six-character input with paste, normalization, and one atomic join.
- Public rooms: real master/detail directory with search, filters, sorting, loading, empty, error,
  full/stale handling, required trainer name, and one opaque atomic join.
- Trade Room: persistent authoritative room/member/attempt projection, server-assigned creator/finder
  guidance, safe connection/teardown controls, wide You-left/Partner-right party panels, compact
  Partner-above-You order, and checksum-valid party details.
- Settings: stable Connection/Support/Advanced tabs, readable device/profile selectors, explicit
  experimental warning, quarantined blocking, diagnostics, support bundle, and technical boundary.
- Recovery: factual retry/settings actions only; no interface-preview bypass.

## Backend work required by the real UI

- Added durable public listing IDs and sanitized `public-directory.v1` projections to the SQLite room
  authority.
- Added real list/detail/atomic-join endpoints to the hosted relay, relay client, local control API,
  typed WPF gateway, and public-room view model.
- Private room creation/join remains unchanged and authoritative. Public join credentials are saved by
  the local control layer and never returned to WPF.
- Public listings exclude room codes, member/reconnect tokens, IP/location data, relay internals, and
  precise network data.
- Public UI enablement is gated by the deployed relay's `/health` capability advertisement. A missing,
  old, or unreachable relay cannot expose a misleading public-room action.
- Authoritative WPF room projection now carries room state, attempt phase, role lock, presence, and
  shared readiness. Trade success still comes only from idempotent commit evidence; party data still
  requires complete checksum-valid observer snapshots.

## Removed release-visible synthetic paths

- Deleted `PublicRoomPreviewProvider`.
- Removed demo/preview navigation and recovery bypasses.
- Removed sample rooms, parties, trainers, signal indicators, activity logs, and fabricated latency.
- Legacy compatibility endpoints retain their API surface for older clients but no longer label their
  scope as `local_demo`.

## Visual evidence

- [Home](assets/ui-overhaul-3/home-1240x860.png)
- [Home at the 960×700 minimum](assets/ui-overhaul-3/home-960x700.png)
- [Create a Trade Room](assets/ui-overhaul-3/create-1240x860.png)
- [Create at the 960×700 minimum](assets/ui-overhaul-3/create-960x700.png)
- [Adapter dropdown contrast at the 960×700 minimum](assets/ui-overhaul-3/settings-adapter-expanded-960x700.png)
- [Real authoritative public directory at the 960×700 minimum](assets/ui-overhaul-3/public-real-960x700.png)
- [Trade Room after a real atomic public join](assets/ui-overhaul-3/trade-room-public-joined-960x700.png)

## Verification

The final verification matrix is recorded after the implementation is frozen:

- WPF Release build: PASS, zero warnings and zero errors
- Native self-test: PASS, exit code 0
- Self-contained single-file `win-x64` publish: PASS; output contains only `SwitchTrade.exe`
- Python tests: PASS, 86 tests
- Release-visible synthetic-content audit: PASS; no demo/preview/sample/mock/fixture/placeholder
  strings remain in the native desktop, local runtime, or relay release source
- Public directory security, atomic join, capability gate, and durable restart tests: PASS
- Native end-to-end public UI: PASS; an ephemeral real public listing was created by a second local
  control client, rendered without synthetic data, joined atomically through WPF, projected as a
  two-member Trade Room, then removed with its credentials and authority record

## Work intentionally left outside this branch

- Owner visual acceptance and legal-notice approval.
- Deployed relay update/operational qualification if the hosting branch does not yet include
  `public-directory.v1`.
- Clean-machine installer/reboot/coexistence/rollback qualification.
- Two-PC, two-RTL8192EU, two-Switch room/trade/recovery/second-session qualification.
- WAN impairment, staged relay restart, backup/restore, and two-NAT qualification.
- Privacy/analytics/statistics functionality of any kind.
