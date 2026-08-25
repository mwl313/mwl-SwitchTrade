# Final native UI overhaul — GPT handoff — 2026-08-25

> This is the point at which the owner should ask GPT for the final UI/UX overhaul.
> Do not begin installer packaging or redesign the backend contracts during this review.

The preliminary WPF overhaul is running and visually verified. The room, local event, party, commit,
privacy, release, and hardware boundaries are now frozen enough that final UI work will not be built on
invented server behavior.

## 1. Read these sources in order

1. `docs/54-native-ui-flow-and-runtime-structure-20260825.md` — screen flow and process structure.
2. `docs/56-native-ui-ux-redesign-handoff-20260825.md` — original Linkline redesign brief.
3. `docs/57-native-ui-overhaul-implementation-report-20260825.md` — what the preliminary WPF build does.
4. `docs/58-authoritative-room-control-event-contract-v1-20260825.md` — authoritative lobby and events.
5. `docs/59-party-snapshot-and-trade-commit-contract-v1-20260825.md` — two party views and commit truth.
6. `docs/60-external-consent-and-statistics-contract-v1-20260825.md` — no in-client privacy controls.
7. `docs/61-private-beta-release-baseline-20260825.md` — supported claims and identity boundary.
8. `docs/55-beta-distribution-preflight-checklist-20260825.md` — gates and remaining implementation.

Inspect the actual WPF project under `apps/desktop/SwitchTrade.Desktop`; do not design from screenshots
or the retired Emerald HTML kit alone.

## 2. Owner decisions that must be preserved

- Use a modern native Windows/Linkline direction, not the retired Emerald web aesthetic.
- Keep the SwitchTrade wordmark fixed. Back belongs in the reserved gray row beneath its border so it
  never moves the wordmark.
- All scene content shares one left edge with consistent padding.
- Narrow scenes use a consistent 640-DIP content width. Wider operational scenes may grow to the right
  within the existing 1000-DIP content region.
- Home has three equal-size actions: Create a Trade Room, Browse Public Rooms, and Join a Private Room.
- Join a Private Room uses the same button class and geometry as the other Home actions.
- Create always displays all entry fields. Public/Private is a radio choice, not a progressive reveal.
- Room Name, Trainer Display Name, Game, and Language are required and show a red asterisk.
- Game and Language default to `None`; `None` is invalid for submission.
- There is no optional Privacy Settings section and no client Privacy tab. Consent is external.
- Public room browsing must remain labeled Demo Preview until it is real.
- Remote member, connection, party, and trade-success UI must be driven by contract snapshots/events,
  never optimistic timers or fake local counters.

## 3. Contract-to-UI state requirements

The final Trade Room must distinguish, in plain language:

- app/local runtime readiness;
- adapter/radio readiness;
- relay/control reachability;
- remote member presence and readiness;
- physical Switch discovery/connection;
- trading-room state;
- party data available/unavailable;
- reconnecting, recoverable error, closing, and terminal states.

Member A/B identity stays stable. “Create the room on your Switch” and “Find the room” are per-attempt
instructions; either member can claim creator before the role lock. A simultaneous claim must resolve
without presenting the losing member as an error.

The two parties appear side by side as two 2×3 grids only after valid snapshots exist. Hover/focus opens
a compact accessible stat popover. Unknown or unavailable values are labeled honestly. Missing party
data must never imply that the connection failed.

Trade success is shown once per `commit_id`. An animation or acceptance prompt is not success. A durable
trade followed by a teardown error must use the contract outcome and recovery copy rather than falsely
reporting rollback.

## 4. Requested GPT deliverables

Return a repo-grounded final-overhaul package containing:

1. a gap review of current WPF against this handoff;
2. a final screen/state matrix tied to `room-control.v1` and `party-commit.v1`;
3. final copy, typed error, recovery-action, empty/loading/offline, and destructive-confirmation matrix;
4. component, token, layout, icon, logo, and motion decisions appropriate for native WPF;
5. an implementable WPF change plan or direct code changes, without replacing backend contracts;
6. keyboard, screen-reader, contrast, focus, 100–200% scaling, localization-growth, and reduced-motion
   acceptance criteria;
7. a proposal for the remaining public icon/logo treatment, legal/privacy notice placement, and real
   support destination for owner approval;
8. screenshots or a runnable build for approval at representative window sizes.

Do not introduce a web browser, Electron, a custom UI server, a second state framework, or a new design
dependency unless the current WPF platform demonstrably cannot meet a requirement.

## 5. Gate 0 approval checklist

GPT/owner review is complete only when:

- every reachable screen and authoritative state has approved hierarchy and copy;
- the owner overrides in section 2 remain intact;
- remote/party/trade states map to real contract fields and events;
- error, reconnect, cancellation, shutdown, and repair paths are designed;
- accessibility and scaling checks pass;
- public icon/logo assets, product-facing notices, privacy/legal links, and support destination are
  approved or explicitly deferred from the private beta by the owner;
- `docs/54`, `docs/55`, and the WPF implementation are updated together.

## 6. Work after approval

After GPT and the owner approve the final overhaul:

1. Codex implements or reconciles the final WPF changes and closes Gate 0.
2. Implement the authoritative room service, member/reconnect tokens, commands, and ordered events.
3. Split tunnel seat from per-attempt Switch creator/finder role.
4. Connect WPF to the installed local `/api/v1` snapshot/SSE boundary.
5. Integrate the passive party observer and fail-closed trade commit classifier.
6. Run internal state, reconnect, decoder-fixture, rollback, analytics-offline, and UI transition tests.
7. Only then proceed through installer, custom-kernel rollback, two-RTL8192EU hardware qualification,
   signing, and private-beta release gates.
