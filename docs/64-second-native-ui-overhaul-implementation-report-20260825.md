# Second native UI overhaul implementation report — 2026-08-25

> Source: `docs/63-second-native-ui-overhaul-codex-handoff-20260825.md`.
> Branch: `production-beta`.
> Privacy override: no Privacy tab, analytics switch, consent prompt, or privacy-setting UI was added.

## Result

The second native WPF audit is implemented as a focused presentation and compatibility hardening pass.
It keeps the existing Python/WSL, RFU, hardware-profile, relay, and installer boundaries intact. The
client still tells the truth about preview data and about the legacy local API; it does not simulate an
authoritative partner, live public directory, verified party, or successful trade.

## Contract decisions C1–C12

All twelve audit ambiguities now have one documented v1 answer in `docs/58` and `docs/59`:

1. Connection attempts may return to the room's ready/waiting phase after failure or cancellation.
2. Ready may be withdrawn before the attempt is locked.
3. Party event names use dotted `party.snapshot.updated` and `party.snapshot.invalidated` names.
4. Pokémon moves and EVs are structured values with provenance, not display-only strings.
5. Private code entry issues one atomic Join action; there is no find-then-join race.
6. Owners close a room for both members; non-owners leave their seat. Window close follows that role.
7. Teardown failure remains visible and recoverable; it is never silently treated as success.
8. The compatibility Create request sends every supported form field.
9. Ending an attempt has an explicit command instead of overloading room close.
10. Primary actions use an explicit allowlist for each authoritative phase.
11. Authoritative room state carries party snapshot references, not full party payloads.
12. The owner may remove a disconnected member only after the documented grace policy.

## Native client changes

- Enabled .NET WPF Fluent Light primitives and layered restrained Linkline color, typography, icon,
  spacing, surface, input, and button resources over them.
- Added Windows High Contrast resource switching and reduced-motion behavior based on system settings.
- Replaced opacity-only button reactions with stable hover, press, disabled, focus, and progress states.
- Removed the global content scroller. Every screen now owns its scrolling, sticky action area, and
  adaptive master/detail behavior.
- Split the monolithic screen dictionary and main view model into individual views, components, and
  screen view models. `Screens.xaml` is now only the template registry.
- Added an `ActiveTradeRoomCoordinator` so a real room and its teardown/recovery state survive opening
  Settings or moving between routes.
- Implemented owner Close versus member Leave semantics, role-aware window-close confirmation, and a
  deliberate force-close recovery choice after a failed teardown.
- Made Join a single atomic, busy-locked operation, added safe clipboard paste, and canceled stale
  Create/Join work when its screen is left so a late response cannot hijack navigation.
- Sent all Create fields through the compatibility gateway and kept internal `host`/`guest` vocabulary
  behind that gateway.
- Added typed search/filter/sort models, typed party data, structured moves, EVs, IVs, stats, trainer
  metadata, and explicit Sample Preview provenance.
- Added per-monitor-v2 DPI awareness, adaptive public/settings/trade layouts, initial focus restoration,
  keyboard shortcuts, live announcements, and stable focus-ring geometry.
- Added a repository solution, pinned .NET 10 SDK policy, and warnings-as-errors build policy. The
  dependency-free desktop self-test remains the current WPF smoke suite until the authoritative room
  reducer exists and warrants a dedicated fixture/test project.

## Compatibility backend changes

The current local control service accepts the expanded Create fields and exposes explicit room-close
and member-leave DELETE routes. These narrow routes preserve the current private-beta compatibility
path; they do not pretend to be the future authenticated `room-control.v1` service.

## Verification

- Pinned solution Release build: zero warnings and zero errors with warnings treated as errors.
- Desktop `--self-test`: validates form rules, preview separation, High Contrast resource loading,
  coordinator start/stop/release, and owner/member room roles.
- Python core suite: 32 passed. Compatibility integration suite: 6 passed, including create metadata,
  owner close, member leave, and route behavior.
- Native runtime QA covers Recovery, Home, Create, Join, Public Rooms, Settings, Trade Room, keyboard
  focus, adaptive layout, and representative screenshots.
- Full Python collection also reaches unrelated optional/platform suites; expected local failures from
  absent Linux `ldn`, optional `zstandard`, Windows sysfs-path emulation, and websocket API-version
  differences are not caused by this UI change.

## Deliberately not implemented

- No Privacy tab or privacy/analytics controls.
- No live `/api/v1` authoritative room reducer, reconnect tokens, role election, or shared readiness.
- No production public directory, live party observer, committed-trade upload, installer, or remote
  service deployment.
- No new UI framework, browser runtime, Electron shell, or design-system dependency.

The next Gate 0 action is final owner/GPT visual approval plus final public assets, legal notices, and
support destination. Backend implementation then follows the ordered gates in `docs/55`.

## Owner follow-up corrections — 2026-08-26

- Restored Settings to three native tabs at every window width; the compact dropdown was removed.
- Normalized Create/Public combo boxes to a fixed 44-DIP height with vertically centered content.
- Gave the fixed Back bar and sticky Create/connection action footers a white surface plus separating
  border so they remain distinct from the gray scrolling canvas.
- Reordered the compact party layout so Partner appears above You; the wide layout remains You-left and
  Partner-right.
- Replaced the boxed Settings tab buttons with unclipped, underline-selected navigation tabs.
- Enlarged the default shell to 1240 by 860 DIPs, raised the minimum to 960 by 700 DIPs, expanded the
  content boundary to 1080 DIPs, and reduced the bottom inset so primary screens need less scrolling.
