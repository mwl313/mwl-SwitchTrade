# Native UI overhaul implementation report — 2026-08-25

## Scope completed in this change

This change implements the approved presentation work from
`docs/56-native-ui-ux-redesign-handoff-20260825.md` without changing the radio, RFU, tunnel, relay,
installer, hardware-profile, or protocol boundaries.

- Retired the Emerald/pixel/console-bezel presentation.
- Added the Linkline light-theme tokens and reusable WPF control styles.
- Reduced `MainWindow` to a persistent shell with Back, readiness, Settings, scrolling, keyboard
  shortcuts, and accessible announcements.
- Added typed models, a typed loopback control-API client, desktop services, screen view models, and a
  single explicit preview-data provider.
- Added bounded startup, installed-runtime launch attempt, recovery, retry, Settings, and a standalone
  interface-preview route.
- Added Home, private room creation, private code lookup, interactive public sample browsing, public
  sample room creation, Settings, and persistent Trade Room screens.
- Preserved the current narrow real private-room/session endpoints.
- Added safe leave/close behavior that stops an active real session after confirmation.
- Added a labeled party-layout preview with two 2-by-3 grids, empty slots, neutral placeholders,
  pointer tooltips, keyboard/click selection, and pinned sample details.
- Replaced ordinary implementation terminology with user-facing Trade Room language.

## Truthful feature matrix

| Area | State after this change |
|---|---|
| Private room create/join | Uses the existing local API and remains functional when the installed runtime is available |
| Current endpoint session start/stop | Uses the existing local API; internal host/guest values remain hidden from ordinary copy |
| Public room browser and public room creation | Interactive `Demo Preview`; local sample data only |
| Shared membership, online/ready state, and reconnect | Not implemented and not simulated |
| Either-member Switch room creator choice | Not implemented; the current private path explains its role limitation |
| Live party data | Not implemented; only labeled sample parties are rendered |
| Trade commit and statistics | Not implemented; the client exposes no analytics control and uploads nothing |
| Adapter compatibility | Real profile data when the control service is available; live selection and repair are not claimed |

## Architecture result

The refactor keeps future expansion behind stable boundaries:

- WPF owns presentation and calls a typed loopback client.
- The Python/WSL service continues to own hardware and endpoint processes.
- Hardware support remains profile-driven.
- Public rooms, authoritative membership, creator assignment, live parties, and commit events can be
  added as API/state capabilities without putting driver or protocol code in the desktop process.

## Verification record

- `dotnet build apps/desktop/SwitchTrade.Desktop/SwitchTrade.Desktop.csproj -c Release`
  completes with zero warnings and zero errors.
- `apps/desktop/Publish.ps1` produces one self-contained `SwitchTrade.exe`, and its built-in
  `--self-test` passes.
- The source handoff and saved `docs/56` copy are content-equivalent after line-ending normalization.
- Native UI Automation traversed Startup Recovery, Interface Preview, Home, Create, Private Join,
  Settings, Public Rooms, Demo Trade Room, and Pokémon detail selection without a process exit.
- Native window captures at the default size verified the Linkline shell, recovery, form, tab, public
  browser, party-grid, focus, and selected-detail layouts.
- Public sample rows expose their full width, and occupied party slots expose deterministic accessible
  names such as `View sample details for BULBY, Bulbasaur, level 18`.
- `git diff --check` passes.

## Defects found and fixed during native QA

1. Deferred screen templates initially crashed after Recovery because the visibility converter was
   outside their resource dictionary. The converter now lives beside the templates, and all screen
   types were navigated at runtime.
2. Startup could multiply the four-second HTTP timeout across every retry. Readiness probes now have a
   500 ms deadline and the complete retry path is bounded to roughly eight seconds in the worst case.
3. Party buttons initially had no reliable automation name. Occupied and empty slots now expose clear
   names to screen readers and UI tests.
4. Selected Pokémon details initially appeared below both full party grids. The pinned detail sheet now
   opens above the grids, within the current viewport, and remains dismissible with Escape.

## Next approval and backend phases

The room, local-event, party/commit, privacy, and release contracts are now frozen in `docs/58` through
`docs/61`. The immediate next step is the final GPT/owner overhaul in `docs/62`; it must map the WPF to
those real states rather than add more presentation simulation. After approval, implement the
server-authoritative room and local API so the existing WPF state model can replace limitation notices
with verified live state.

## Owner-requested layout and form adjustments

The following owner overrides were applied after the initial Linkline implementation:

- Back now occupies a reserved gray row below the white header, directly under the fixed SwitchTrade
  wordmark. Its visibility no longer changes header geometry.
- Scene columns share a left content edge under the wordmark and Back control. Narrow scenes use a
  fixed 640-DIP width; Public Rooms and Trade Room expand rightward inside a shared 1000-DIP boundary.
- Home uses three equal fixed-width rectangular action buttons. Private code entry is no longer a text
  link.
- Create a Trade Room always shows every input. Private/Public is a radio choice; Room name, Trainer
  display name, Game, and Language are starred and required; Game and Language default to `None`.
- The client Privacy tab and unavailable analytics checkbox were removed. Analytics stay disabled
  until the separately administered external consent workflow is defined and active.

Owner-adjustment QA confirmed that all three Home actions remain exactly 640 DIP wide at 900, 1120,
and 1400 DIP window widths; the wordmark and scene titles share one left edge; Back appears below that
line without moving the header; Game and Language default to `None`; completed required fields enable
the public preview path; and no Privacy tab is exposed.
