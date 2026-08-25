# SwitchTrade Native UI/UX Redesign — Codex Handoff

- Document date: 2026-08-25
- Repository: https://github.com/mwl313/mwl-SwitchTrade
- Required branch: production-beta
- Repository snapshot reviewed: e1b1fa7a897be49fe495ea69bb9f6fb68802f01d
- Deliverable type: design, product-flow, frontend-architecture, API-state, and implementation handoff
- Primary client: native Windows WPF application
- Default product language: English
- Status: proposed design baseline; implementation must not silently invent unavailable backend behavior

---

# 0. Instructions to Codex

Read this document completely before editing the repository.

This handoff replaces all previous visual-design assumptions for the final native application. The old Emerald/pixel design, bitmap font, Canvas viewport, thick faux-console bezel, green panel system, and prototype layout are not part of the new direction.

The expected workflow is:

1. Check out and inspect the production-beta branch.
2. Read the authoritative source documents and current implementation files listed below.
3. Compare this handoff against the actual current code.
4. Produce a short gap report and staged implementation plan.
5. Do not claim that a planned server-authoritative feature is already real.
6. Keep mock or fixture-based functionality visibly labeled as Demo or Preview.
7. Preserve all radio, RFU, tunnel, hardware-profile, diagnostics, installer, and protocol boundaries unless a later approved task explicitly changes them.
8. When implementation is authorized, update the implementation and the maintained UI-flow documentation in the same change.
9. Verify the native WPF application, not only the optional web/debug client.
10. Do not reintroduce the retired pixel UI through another font, bezel, canvas, or retro-game skin.

This is a product redesign, not a cosmetic recolor. The information architecture, user terminology, navigation, state handling, backend contracts, accessibility, and recovery behavior must be treated as one system.

---

# 1. Product Definition

SwitchTrade connects two unmodified Nintendo Switch consoles running supported official Game Boy Pokémon software over the internet by bridging their local wireless communication through two PCs.

The user should experience SwitchTrade as:

> A simple Windows connection assistant that helps two trainers find each other and complete a trade on their own Switch consoles.

The ordinary user should not need to understand:

- WSL
- Python
- FastAPI
- USB/IP
- LDN
- Pia
- Reliable
- RFU
- endpoint roles
- host/guest tunnel slots
- AP or monitor mode
- relay implementation
- packet counters
- driver modules
- internal run directories

Those details may appear only in an explicitly opened technical Details or Support area when they are useful for recovery.

The product’s main job on each screen is to tell the user:

1. What is happening now?
2. Who needs to act: me, my partner, or SwitchTrade?
3. What single action should happen next?
4. If something failed, what is the safest next action?

---

# 2. Authoritative Source Priority

When documents conflict, use this order:

1. This handoff after owner approval
2. docs/55-beta-distribution-preflight-checklist-20260825.md
3. docs/50-current-product-demo-todo-20260825.md
4. docs/54-native-ui-flow-and-runtime-structure-20260825.md
5. Actual production-beta code
6. Older design and UX documents only for historical context

Required reading:

- docs/50-current-product-demo-todo-20260825.md
- docs/54-native-ui-flow-and-runtime-structure-20260825.md
- docs/55-beta-distribution-preflight-checklist-20260825.md
- apps/desktop/SwitchTrade.Desktop/App.xaml
- apps/desktop/SwitchTrade.Desktop/App.xaml.cs
- apps/desktop/SwitchTrade.Desktop/MainWindow.xaml
- apps/desktop/SwitchTrade.Desktop/MainWindow.xaml.cs
- apps/desktop/SwitchTrade.Desktop/SwitchTrade.Desktop.csproj
- switchtrade/control.py
- switchtrade/relay_client.py
- switchtrade/endpoint.py
- relay/server.py
- installer/Launch-SwitchTrade.ps1

Historical documents such as docs/17-uiux-설계.md, docs/18-user-flow.md, apps/web/SwitchTrade-UI-Kit, and assets/ui/SwitchTrade-UI-Kit.zip must not constrain the new visual direction where they conflict with this handoff or the current product architecture.

Useful source links:

- Current native shell:
  https://github.com/mwl313/mwl-SwitchTrade/blob/production-beta/apps/desktop/SwitchTrade.Desktop/MainWindow.xaml
- Current code-behind navigation and API calls:
  https://github.com/mwl313/mwl-SwitchTrade/blob/production-beta/apps/desktop/SwitchTrade.Desktop/MainWindow.xaml.cs
- Current control API:
  https://github.com/mwl313/mwl-SwitchTrade/blob/production-beta/switchtrade/control.py
- Current relay:
  https://github.com/mwl313/mwl-SwitchTrade/blob/production-beta/relay/server.py
- Current beta experience requirements:
  https://github.com/mwl313/mwl-SwitchTrade/blob/production-beta/docs/55-beta-distribution-preflight-checklist-20260825.md

---

# 3. Verified Current-State Audit

## 3.1 Native desktop architecture

The current primary desktop client is a small .NET 10 WPF application.

Current characteristics:

- One MainWindow shell
- One ContentControl used to swap imperative screen content
- Most screens dynamically built as StackPanel children
- Navigation, API requests, session flags, launcher behavior, and window lifecycle combined in MainWindow.xaml.cs
- No view-model layer
- No navigation stack
- No reusable screen views
- No typed application state model
- No server event subscription
- One global two-second status poll
- One global status label that collapses multiple subsystems into BACKEND
- Escape may stop the active endpoint and jump directly to Home

The old web UI kit is not referenced by the WPF project. It may therefore be retired without changing radio or runtime behavior.

## 3.2 Current implemented screens

The current native screen identifiers are effectively:

- main
- host
- join
- public
- lobby
- configuration

Current flow:

- Main -> Host -> Lobby
- Main -> Join with inline private code -> Lobby
- Main -> Join -> disabled Public Demo -> Join
- Main -> Configuration
- Lobby -> local endpoint start/stop -> Main

The maintained Mermaid diagram and actual WPF flow do not completely match. In particular, private-code entry is not currently a separate native scene.

## 3.3 Current backend limitations that affect truthful UX

The existing private flow is sufficient for internal tunnel validation, but not for the intended authoritative two-person product lobby.

Current control.py behavior:

- Trade groups are kept in a local in-memory dictionary per PC.
- Creating a group obtains a relay session code and stores room metadata only on the local control process.
- Joining checks the relay session but does not obtain authoritative creator metadata.
- A remote joiner may receive a generic room name.
- There is no shared server-authoritative online, ready, reconnect, owner, room-role, expiration, or ordered room state.
- The public endpoint exposes only local-demo groups from that same process.
- Public metadata is too small for the proposed search experience.

Current relay/server.py behavior:

- Two WebSocket slots named host and guest
- Session ID and retained advertisement
- No real public directory
- No room metadata service
- No authenticated member identity
- No reconnect token
- No ready state
- No atomic room-creator claim
- No role transfer
- No authoritative leave or expiration UX state

Current endpoint behavior couples online group role to radio behavior. Therefore, the requirement that either member may create the room on their Switch cannot be implemented truthfully through UI copy alone.

Current party state:

- Decoder and fixtures exist.
- The decoder observer is not yet integrated into the production endpoint boundary.
- The control API does not expose live validated party snapshots.
- The WPF client has no party screen.

---

# 4. Design Goals

The final native UI must be:

- Clean
- Modern
- Deliberate
- Windows-native
- Fast to understand
- Comfortable for nontechnical users
- Honest about Demo versus live functionality
- Resilient to startup, adapter, network, partner, and decoding failures
- Fully keyboard accessible
- Screen-reader compatible
- Usable from 100% through 200% Windows scaling
- Structurally ready for real public rooms and live party data

The visual identity must not resemble:

- The retired Pokémon Emerald pixel prototype
- A generic AI-generated dashboard
- A game-emulator skin
- A network administration panel
- A developer diagnostics console

---

# 5. Explicit Non-Goals

Do not:

- Reuse the old bitmap font
- Reuse the 240 by 160 Canvas viewport
- Reuse the green Emerald palette
- Reuse faux Game Boy or console bezels
- Use all-uppercase sentences
- Use Cascadia Mono for normal UI copy
- Build a left-sidebar dashboard for the ordinary flow
- Fill Home with cards, KPIs, charts, or status widgets
- Use neon glow, glassmorphism, gradient blobs, or decorative particle effects
- Use emoji as product icons
- Expose raw exception text in primary UI
- Let hover be the only way to access information
- Treat Demo public rooms as real remote trainers
- Show incomplete or invalid Pokémon data as fact
- Block trading because optional party decoding or analytics is unavailable
- Infer the remote member’s state from local button clicks
- Continue coupling Trade Room ownership to the per-attempt Switch room role
- Add fake Ready, reconnect, remote party, or creator-assignment behavior without corresponding backend state

---

# 6. Terminology

## 6.1 Required user-facing terminology

| Current or internal term | Required user-facing term |
| --- | --- |
| Link Desk | Home |
| Group | Trade Room |
| Host a Trade Group | Create a Trade Room |
| Join a Trade Group | Remove generic intermediate page |
| Group name | Room name |
| Group passcode | Room code |
| Configuration | Settings |
| Hardware profile | Wi-Fi adapter |
| Certified hardware | Supported adapter |
| Experimental hardware | Test-only adapter, Advanced only |
| Host endpoint | Hidden from ordinary UI |
| Guest endpoint | Hidden from ordinary UI |
| Host / guest | You / Partner, or creator / finder for one attempt |
| Start radio and tunnel | Connect both Switches |
| Session | Connection |
| Backend offline | A specific user-facing failure sentence |
| Relay | Online service, only when explanation is necessary |
| Run ID | Support code in ordinary UI |
| RFU / LDN / Pia / Reliable | Hidden outside technical Details |

## 6.2 Room naming rule

There are two different room concepts. Never call both simply Room without context.

- Trade Room: SwitchTrade’s online two-person membership space
- Room on your Switch: the in-game room created or searched from the console

Recommended copy:

- Create a Trade Room
- Join a Trade Room
- Create the room on your Switch
- Find your partner’s room
- The room appeared on your Switch
- Both Switches are connected

Avoid:

- Host room
- Guest room
- Endpoint room
- RFU room
- Parent room
- Child room

## 6.3 User identities

Separate these concepts:

- Trade Room owner: stable room ownership
- Member A and Member B: stable server membership
- You and Partner: local presentation
- Switch room creator and finder: per-attempt temporary roles
- Tunnel or endpoint role: internal implementation only

---

# 7. Information Architecture

## 7.1 Global application shell

Ordinary screens use one restrained native shell:

- Native Windows title bar
- App wordmark or compact brand mark
- Back action when safe
- Current scene title
- Small readiness summary at the right
- Settings access
- Main content area
- Optional bottom action row only when the current task needs it

No permanent sidebar in the ordinary flow.

Settings may use a short internal navigation list because it is a true settings surface.

## 7.2 Home destinations

Home should not contain a generic Join screen that adds an unnecessary decision layer.

Home destinations:

1. Create a Trade Room
2. Browse Public Rooms
3. Have a room code? Join a private room
4. Settings

Visual hierarchy:

- Create is the primary action.
- Browse Public Rooms is the secondary action.
- Join with a room code is a quiet tertiary action.
- Settings is in the top-right shell, not an equal Home card.

## 7.3 Persistent Trade Room shell

After joining or creating, the user remains inside one persistent Trade Room shell.

The shell changes state for:

- Waiting for partner
- Ready check
- Choosing the Switch room creator
- Creator instructions
- Finder instructions
- Connecting
- Connected trading
- Reconnecting
- Recoverable error
- Trade confirmed
- Connection ended

Do not push a new full page for every phase. The room name, membership, partner, and room code should remain spatially stable.

---

# 8. Complete Screen Flow

~~~mermaid
flowchart TD
    Launch([Launch SwitchTrade]) --> Startup["Starting SwitchTrade"]
    Startup -->|Ready| Home
    Startup -->|"Needs attention"| StartupRecovery["Startup Recovery"]
    StartupRecovery -->|Retry| Startup
    StartupRecovery --> Settings

    Home --> Create["Create a Trade Room"]
    Home --> Public["Browse Public Rooms"]
    Home --> Private["Join with a Room Code"]
    Home --> Settings

    Create --> TradeRoom["Trade Room"]
    Public --> PublicPreview["Selected Room Preview"]
    PublicPreview --> TradeRoom
    Private --> PrivatePreview["Resolved Room Preview"]
    PrivatePreview --> TradeRoom

    TradeRoom --> Waiting["Waiting for Partner"]
    Waiting --> Ready["Ready Check"]
    Ready --> Assign["Choose Who Creates on Switch"]
    Assign --> CreatorGuide["Create on My Switch"]
    Assign --> FinderGuide["Find My Partner's Room"]
    CreatorGuide --> Connecting
    FinderGuide --> Connecting

    Connecting -->|Connected| Trading["Party and Trading View"]
    Connecting -->|Issue| RoomRecovery["Connection Recovery"]
    RoomRecovery -->|Retry| Assign
    RoomRecovery -->|"Partner left"| Waiting

    Trading -->|"Another trade"| Trading
    Trading -->|"End connection"| TradeRoom
    TradeRoom -->|Leave| Home
~~~

---

# 9. Navigation Rules

- Escape closes the topmost temporary layer first:
  1. Pokémon popover
  2. Filter drawer
  3. Dialog
  4. Details pane on narrow layouts
  5. Previous safe scene
- Escape must never silently terminate an active Trade Room or endpoint.
- Alt+Left performs safe Back navigation.
- Back from a private-code error preserves the entered code until the user leaves the scene.
- Back from a public room preview preserves search text, filters, sort, scroll, and selected result.
- Settings opened during an active Trade Room must not silently stop the connection.
- Leaving a Trade Room requires confirmation when:
  - a partner is present
  - either user is Ready
  - a connection attempt is active
  - the Switches are connected
- Closing the window during an active connection requires a clear confirmation.
- Reconnection and retry should preserve Trade Room membership whenever safe.
- A failed connection attempt creates or resets an attempt state, not the entire Trade Room.
- Startup recovery should offer resumption when a valid reconnect token or recoverable previous room exists.

---

# 10. Detailed Screen Specifications

## 10.1 Startup

Purpose:

- Hide ordinary implementation startup
- Explain progress only when the app does not become ready immediately
- Route a specific failure to a specific recovery

Layout:

- Centered compact SwitchTrade brand
- One primary sentence: Starting SwitchTrade…
- Three plain-language stages:
  - Preparing the app
  - Connecting online
  - Checking your Wi-Fi adapter
- Current stage uses icon plus text, not color alone
- Details remains hidden unless startup takes longer than expected

Behavior:

- If ready quickly, transition without showing a prolonged splash.
- Do not flash between offline and ready due to polling.
- Use a bounded timeout.
- Show Cancel only when canceling is safe.
- If a stage fails, route to Startup Recovery with the exact stage retained.

Required states:

- starting
- ready
- slower_than_expected
- canceled
- local_service_failed
- online_service_failed
- adapter_missing
- adapter_unhealthy
- version_mismatch
- repair_required

## 10.2 First-Run Setup

This may cooperate with the installer, but the daily app must be able to explain incomplete setup.

Steps:

1. Welcome
2. System check
3. Required system changes and consent
4. Install or resume after reboot
5. Connect and verify supported Wi-Fi adapter
6. Ready

Requirements:

- Explain the custom WSL kernel’s global effect before consent.
- Preserve and restore prior configuration according to docs/55.
- Do not show PowerShell or WSL commands in the normal path.
- Technical checklist belongs in expandable Details.
- If reboot is required, explain that setup will resume.
- Do not imply success until the real health gate passes.

## 10.3 Startup Recovery

Structure:

- Specific heading
- One plain-language explanation
- One primary recovery action
- One secondary route
- Technical Details collapsed
- Support code and Copy for fatal cases

Examples:

- SwitchTrade couldn’t start.
- Connect your SwitchTrade Wi-Fi adapter.
- Another app is using the adapter.
- SwitchTrade needs to repair its setup.
- This version of the app and its runtime do not match.

Do not use BACKEND OFFLINE as a catch-all.

## 10.4 Home

Header:

- SwitchTrade
- readiness summary
- Settings

Main content:

- Title: Trade Pokémon with another trainer
- Short supporting sentence
- Primary action: Create a Trade Room
- Secondary action: Browse Public Rooms
- Tertiary action: Have a room code? Join a private room

Readiness behavior:

- When fully ready: small positive status, not a large dashboard.
- When an adapter or service needs attention: one inline notice above the actions.
- Unsafe actions are disabled with a reason and route to the relevant recovery.
- Settings and Support remain available.

Do not:

- Show technical component status as four permanent cards
- Show USB IDs on Home
- Show logs, packet counters, or run IDs
- Use a grid of equal cards

## 10.5 Create a Trade Room

Layout:

- Focused form, approximately 600 DIP wide at normal desktop size
- No unrelated sidebar
- Back and scene title
- Primary action fixed or consistently positioned at the bottom

Fields:

1. Room name
   - Required
   - Maximum length aligned with backend validation
   - Human-readable error
2. Who can find this room?
   - Code only
   - Listed publicly
3. Public-only fields shown through progressive disclosure:
   - Trainer display name
   - Game version
   - Language
   - Pokémon offered
   - Pokémon wanted
   - Optional coarse region disclosure
   - Optional short note

Public privacy rules:

- Never publish decoded trainer ID by default.
- Region must be coarse and explicitly disclosed.
- Explain what becomes visible.
- Public-room metadata is independent from optional committed-trade analytics consent.

Actions:

- Create Trade Room
- Cancel

Loading:

- Keep the button label visible and add progress.
- Prevent duplicate submission.
- Preserve form data on recoverable failure.

Success:

- Enter Trade Room.
- Private rooms show the generated room code and sharing actions.
- Demo public creation must show Demo Preview labeling if not backed by the real public service.

## 10.6 Join a Private Trade Room

This is a dedicated scene.

Layout:

- Back
- Title: Join a private Trade Room
- One large normal TextBox, not six independent character boxes
- Paste action
- Supporting instruction
- Inline resolved-room preview after successful lookup
- Primary action

Input behavior:

- Case insensitive
- Display uppercase
- Remove spaces and hyphens
- Accept paste
- Respect server code length
- Never clear the code after a recoverable error
- Announce validation errors accessibly
- Enter submits only when valid

Resolution states:

- idle
- validating
- found
- not_found
- expired
- full
- version_incompatible
- online_service_unavailable
- rate_limited
- retrying

Resolved preview:

- Room name
- Creator display name when available
- Private label
- Current occupancy
- Compatibility
- Join Trade Room

Do not enter a room automatically before the user sees what was resolved.

## 10.7 Browse Public Rooms

Desktop layout:

- Top search and filter bar
- Dense list on the left
- Selected-room details pane on the right
- At narrow widths, the details pane becomes the next scene or overlay
- Preserve list state on return

Top controls:

- Search by selector
- Search input
- Filters
- Sort
- Clear filters when any filter is active
- Refresh

Search-by values:

- Any field
- Room name
- Trainer display name
- Pokémon offered
- Pokémon wanted

Filters:

- Availability: Open only / All
- Game: FireRed / LeafGreen / data-driven future options
- Language
- Coarse region, only when disclosed
- Connection quality: Excellent / Good / Any

Sort:

- Best match
- Lowest latency
- Recently opened

Result-row fields:

- Availability with text and icon
- Room name
- Trainer display name
- Game
- Language
- Pokémon offered and wanted where present
- Coarse region where consented
- Connection latency and qualitative label
- Occupancy, always maximum two for the current scope
- Preview or Join action

Terminology:

- Network round-trip time must not be called signal strength.
- Use Connection quality and optionally show milliseconds.

Public Demo contract:

- Persistent banner:
  Public Rooms Preview — sample data in this build
- Search, filters, sorting, loading, no-results, and selection must genuinely work against sample data.
- Use Preview room, not Join, while no remote public service exists.
- A preview may demonstrate the Trade Room layout but must retain a Demo Preview label.
- Do not create a fake remote partner success state without explicit preview labeling.
- Structure the data provider so the real server can replace the mock without replacing the screen.

Required states:

- initial_loading
- loaded
- refreshing_with_existing_results
- empty_directory
- no_filter_matches
- stale_results
- service_unavailable
- selected_room_closed
- selected_room_full
- rate_limited
- demo_preview

## 10.8 Public Room Preview

Desktop:

- Use the right details pane when sufficient width exists.
- On narrow width, use a dedicated scene.

Fields:

- Room name
- Trainer display name
- Public / Demo Preview
- Game
- Language
- Offering
- Looking for
- Coarse region
- Connection quality
- Occupancy
- Short note
- Compatibility

Actions:

- Preview Trade Room in Demo
- Join Trade Room when backed by real service
- Back to results

When the selected result changes state between selection and action, show the new state without losing the public-room query.

## 10.9 Trade Room Shell

Stable regions:

- Room name
- Private/Public/Demo status
- Room code for private rooms
- Copy or Share invitation
- You seat
- Partner seat
- Linkline between seats
- Main task and instruction area
- Help
- Leave

Do not display host or guest.

Private code sharing:

- Copy room code
- Copy a formatted invitation message
- QR sharing is later scope unless separately approved

Member seat content:

- You or partner display name
- Online / reconnecting / offline
- Not ready / ready
- Current plain-language instruction
- No internal endpoint role

## 10.10 Waiting for Partner

Main sentence:

> Waiting for another trainer to join.

Show:

- You seat occupied
- Partner seat visibly empty
- Room code and Copy for private rooms
- Public visibility status when public
- Safe Leave action

Do not run the radio endpoint merely because the room exists.

## 10.11 Ready Check

Both users see server-authoritative state.

Main sentence:

> Get ready when your Switch and adapter are nearby.

Actions:

- I’m ready
- Not ready or Cancel ready

Ready means member readiness only. It must not directly mean that this local user owns a hardcoded host role.

The UI must not infer partner readiness. It must display ordered server state.

## 10.12 Choosing Who Creates the Room on Switch

Both ready members may see:

- Primary: Create the room on my Switch
- Secondary waiting state: Wait for my partner

Rules:

1. A creator claim is an atomic server operation.
2. Exactly one member wins.
3. Simultaneous claims do not surface as an error.
4. The losing member automatically becomes the finder for that attempt.
5. Transfer is allowed only before the connection reaches its locked phase.
6. Creator cancellation returns to creator selection while preserving Trade Room membership.
7. The room owner is not automatically the Switch room creator.
8. The user never sees host, guest, parent, child, AP, or monitor language.

Loser copy:

> Your partner is creating the room. We’ll help you find it.

Transfer copy:

> Have my partner create it instead

## 10.13 Creator Guide

Title:

> Create the room on your Switch

Content:

- Three short numbered steps based on the verified supported game flow
- Highlight only the current step
- Indicate whether SwitchTrade is waiting, detecting, or has found the room
- Automatically advance when real runtime evidence confirms progress
- Do not require a fake Done button if the app can detect the event

Secondary:

- Have my partner create it instead, only before role lock
- Connection help
- Cancel connection attempt

Failure examples:

- room not detected
- likely 5 GHz room
- adapter issue
- room closed
- partner disconnected
- timeout

## 10.14 Finder Guide

Title:

> Find your partner’s room

Content:

- Open the correct search screen on the Switch
- Keep the search screen open
- When the partner’s room is mirrored locally, update the instruction
- Tell the user to select the named room
- Show automatic detection progress

Do not explain beacon replay or remote injection.

## 10.15 Connecting

Use the Linkline as a restrained progress metaphor.

Display exactly one primary sentence for the current phase:

- Looking for your Switch
- Waiting for your partner’s Switch
- Connecting both players
- The room appeared on your Switch
- Joining the room
- Both Switches are connected

Optional details reveal:

- App service
- Online service
- Wi-Fi adapter
- Current connection

Ordinary labels must not be Backend, Relay, Radio, or Session.

Actions:

- Cancel connection
- Connection help
- Retry only when appropriate

The main action must not move or change unpredictably every polling cycle.

## 10.16 Trading and Party View

Top:

- Compact room identity
- Both members connected
- Nonintrusive status
- Reconnecting warning when needed

Main:

- Two side-by-side player panels
- You on the left
- Partner on the right
- Each panel contains a two-column by three-row party grid
- Empty slots are explicit
- One Pokémon detail popover at a time

Bottom:

- End connection
- Connection help
- Optional support code only when an error exists

Do not interrupt the whole view with a full completion page after each trade.

Confirmed trade behavior:

- Show a concise Trade confirmed notification.
- Update validated party snapshots when new complete data arrives.
- Allow the game and Trade Room to continue for another trade.
- Do not report an offer, animation, canceled save, rollback, or disconnect as confirmed.

## 10.17 Settings

Settings categories:

1. General
   - language
   - launch behavior
   - appearance when supported
2. Connection
   - detected supported adapter
   - current readiness
   - select adapter when more than one is safe
   - Check again
   - Fix connection
3. Privacy
   - optional analytics consent
   - fields and purpose
   - export or deletion route when implemented
4. Support
   - Create support file
   - Copy support code
   - version
   - open logs only through an advanced explicit action
5. Advanced
   - test-only devices
   - technical component details
   - only when necessary

Ordinary Connection view should show friendly adapter names and Supported or Needs attention. USB ID and driver/module details belong in expandable technical information.

---

# 11. Trade Room State Model

The current local role string plus session-started Boolean is insufficient.

Use orthogonal state domains.

## 11.1 RoomMembership

Suggested fields:

- room_id
- name
- visibility
- room_code when private
- owner_member_id
- member_a
- member_b
- membership_version
- room_state
- created_at
- expires_at
- demo_mode

Each member:

- member_id
- display_name
- is_local
- online_state
- ready_state
- reconnect_deadline
- joined_at
- compatibility

## 11.2 ConnectionAttempt

Suggested fields:

- attempt_id
- room_id
- attempt_number
- phase
- creator_member_id
- local_instruction
- role_locked
- started_at
- updated_at
- recoverable_error
- retry_count
- server_state_version

Suggested phases:

- idle
- ready_check
- choosing_creator
- creator_guidance
- finder_guidance
- discovering
- connecting
- room_found
- connected
- trading
- reconnecting
- recovering
- completed
- canceled
- failed

## 11.3 DeviceReadiness

Keep independent axes:

- app service
- online service
- Wi-Fi adapter
- Switch discovery
- current connection

Each axis needs:

- status
- user_message
- technical_code
- primary_recovery_action
- updated_at

## 11.4 PartyView

Per member:

- snapshot_id
- member_id
- attempt_id
- observed_at
- validity
- completeness
- six ordered slots
- source version
- invalidation reason

A new connection or teardown clears or invalidates party state.

## 11.5 State diagram

~~~mermaid
stateDiagram-v2
    [*] --> WaitingForPartner
    WaitingForPartner --> ReadyCheck: Partner joins
    ReadyCheck --> ChooseCreator: Both ready
    ChooseCreator --> CreatorGuide: My claim wins
    ChooseCreator --> FinderGuide: Partner claim wins
    CreatorGuide --> Connecting
    FinderGuide --> Connecting
    Connecting --> Trading: Connected
    Connecting --> Recovering: Timeout or device issue
    Recovering --> ChooseCreator: Retry or reassign
    Recovering --> WaitingForPartner: Partner leaves
    Trading --> Trading: Another trade
    Trading --> ReadyCheck: End connection
    WaitingForPartner --> [*]: Leave or expire
~~~

---

# 12. Public Room Data Model

The public demo and future service should share one presentation model.

Suggested PublicRoomSummary:

- room_id
- room_name
- trainer_display_name
- game_version
- language
- offering_species_or_tags
- wanted_species_or_tags
- optional_note
- coarse_region
- region_disclosure
- occupancy
- maximum_occupancy
- availability
- connection_latency_ms
- connection_quality
- created_at
- updated_at
- compatibility
- demo_mode

Privacy:

- Do not expose raw source IP.
- Do not expose precise location.
- Do not automatically publish trainer ID.
- Do not use optional analytics consent as implicit public-listing consent.
- Explain every public field before room creation.
- Region is optional and coarse.

Search should be data-driven and not hardcode UI logic to only FireRed and LeafGreen forever.

---

# 13. Party Grid and Pokémon Popover

## 13.1 Party grid

Each panel:

- Exactly six ordered slots
- Two columns by three rows
- Stable geometry
- Empty slots explicit
- Keyboard navigation
- Same focus and hover affordance
- No information available exclusively through color

Slot content:

- Licensed sprite or approved neutral silhouette
- Nickname
- Species
- Level
- Held-item indicator when available
- Verification or unavailable state
- Empty slot label

Sprite policy:

- Do not copy unapproved proprietary assets into the repository.
- Until asset licensing is approved, use a neutral silhouette or data-first placeholder.
- The UI layout must not depend on a specific sprite pack.

## 13.2 Popover behavior

- Hover or focus opens a compact summary after a short stable delay.
- Click or Enter pins the popover.
- Escape closes it.
- Only one popover is open.
- Pointer may move into the popover without closing it.
- At screen edges, place the popover inward.
- Keyboard focus remains logical.
- Click outside closes when safe.
- Popover content must be accessible as ordinary controls and text.

Sections:

- Summary
- Stats
- Moves
- Trainer

Fields:

- nickname
- species
- level
- gender when validated
- nature
- held item
- party stats
- IVs
- EVs
- four moves
- OT
- trainer identifiers
- validation state
- source state

Data-language mapping:

- observed -> Read from game
- derived -> Calculated
- unavailable -> Unavailable
- incomplete -> Still verifying
- checksum-valid complete record -> Verified

Rules:

- Only complete checksum-valid observed records may be presented as fact.
- Derived values must be labeled.
- Unknown fields stay unknown.
- A corrupt or incomplete record must not be rendered as a normal Pokémon.
- Trainer ID is collapsed by default to reduce accidental screen-sharing exposure.

Decoder failure copy:

> Party details aren’t available right now. Trading can continue.

The party UI is optional presentation. It must never become a dependency of the RFU tunnel or trade operation.

---

# 14. Status, Loading, Error, Retry, and Recovery

## 14.1 Global principles

- Explain the problem in one sentence.
- Emphasize one primary recovery action.
- Keep technical details collapsed.
- Preserve safe user input and Trade Room membership.
- Never display raw exception text as the headline.
- Include a support code for fatal failures.
- Do not erase existing public results during a background refresh failure.
- Do not change button labels into vague words such as Working.
- Keep the original action label and add a progress indicator.
- Disable duplicate destructive actions while a request is active.
- Announce meaningful stage changes, not every poll result.

## 14.2 Copy and action matrix

| Situation | Primary message | Primary action | Preserve |
| --- | --- | --- | --- |
| Slow startup | SwitchTrade is taking longer than expected to start. | Try again | setup progress |
| Local service failure | SwitchTrade couldn’t start. | Repair setup | support code |
| Online service unavailable | Online rooms are temporarily unavailable. | Retry | search and room form |
| Adapter not connected | Connect your SwitchTrade Wi-Fi adapter. | Check again | current scene |
| Adapter in use | Another app is using the Wi-Fi adapter. | Check again | current scene |
| Unsupported adapter | This adapter isn’t supported for trading. | Choose another device | settings |
| Private code not found | We couldn’t find that Trade Room. Check the code and try again. | Try again | code |
| Private room expired | That Trade Room has expired. | Back | code for copy |
| Room full | This Trade Room already has two players. | Back | prior browser state |
| Public no matches | No open rooms match these filters. | Reset filters | search text optional |
| Public refresh failed | We couldn’t refresh the room list. | Try again | old results |
| Likely 5 GHz room | This room is using 5 GHz. Recreate it on 2.4 GHz. | Check again | room membership |
| Switch room not found | We couldn’t find the room on your Switch. | Try again | room membership |
| Partner disconnect | Your partner is reconnecting. We’ll keep their place. | Wait | seat and room |
| Connection interrupted | Keep the game open while we reconnect. | Retry now | attempt when safe |
| Creator canceled | Choose who will create the room on the Switch. | Choose again | membership and code |
| Recovery failed | We couldn’t restore this connection. | Return to Trade Room | membership |
| Party unavailable | Party details aren’t available. Trading can continue. | Dismiss | connection |
| Version mismatch | SwitchTrade needs an update before this connection can continue. | Update or Learn more | diagnostics |
| Fatal error | We couldn’t complete this connection. | Create support file | support code |

Do not invent an exact reconnect duration in UI unless supplied by authoritative server state. When available, display the server deadline as a countdown.

---

# 15. Visual Identity — Linkline

## 15.1 Concept

Linkline expresses one idea: two trainers at separate ends become connected.

Use it consistently in:

- Waiting seats
- Ready state
- Creator/finder assignment
- Connecting progress
- Party panel identity
- Reconnection state

The motif is a thin line with two clear endpoints, not a decorative network diagram.

States:

- waiting: neutral broken line
- both present: both endpoints visible
- connecting: restrained movement or progress along the line
- connected: continuous line
- reconnecting: interrupted segment plus text
- error: line remains structural; error is communicated by icon and text

## 15.2 Palette

| Token | Value | Use |
| --- | --- | --- |
| Canvas | #F5F6F8 | application background |
| Surface | #FFFFFF | focused work surface |
| Surface subtle | #EEF1F5 | subdued rows and empty states |
| Primary text | #181A20 | headings and body |
| Secondary text | #5F6571 | secondary copy |
| Border | #D9DDE5 | 1 DIP separators |
| You / Link Blue | #375BD2 | local player and primary accent |
| Blue tint | #EAF0FF | soft selected background |
| Partner Teal | #0F766E | partner identity |
| Teal tint | #E7F5F2 | soft partner background |
| Success | #21825B | success status |
| Warning | #A45F0B | warning status |
| Danger | #B42318 | destructive and error |
| Focus | Windows system accent | 2 DIP focus outline |

Validate all final combinations for WCAG 2.2 AA. Do not assume these values automatically pass in every filled state.

## 15.3 Typography

Primary family:

- Segoe UI Variable Text
- Segoe UI fallback

Display:

- Segoe UI Variable Display
- Semibold only for important headings

Monospace:

- Cascadia Mono only for room codes, support codes, and intentionally technical values

Suggested type scale:

| Role | Size / line height |
| --- | --- |
| Screen title | 26 / 34 DIP, Semibold |
| Section title | 20 / 28 DIP, Semibold |
| Action label | 15 / 22 DIP, Semibold |
| Body | 15 / 22 DIP, Regular |
| Secondary | 13 / 19 DIP, Regular |
| Room code | 20 / 26 DIP, Semibold monospace |
| Support code | 14 / 20 DIP, monospace |

Do not use uppercase to create hierarchy.

## 15.4 Geometry

- 1 DIP borders
- Control radius: 6 DIP
- Surface radius: 10 DIP
- Dialog or popover radius: 12 DIP
- Focus outline: 2 DIP
- Minimum pointer target: 44 by 44 DIP
- Shadows only for dialogs, menus, and popovers
- No large decorative shadows on ordinary content surfaces

Spacing scale:

- 4
- 8
- 12
- 16
- 24
- 32
- 48 DIP

Suggested shell:

- Default window near current desktop size
- Minimum width sufficient for one-column safe layout
- Main content maximum width around 960 DIP
- Outer content padding 24 to 32 DIP at normal width
- Two-pane Public Rooms collapses below its safe width
- Party panels stack only if required by narrow width or very high scaling

---

# 16. Component System

## 16.1 Shell and navigation

- AppShell
- SceneHeader
- BackButton
- ReadinessSummary
- SettingsButton
- BottomActionBar
- SafeLeaveDialog

## 16.2 Inputs

- TextField
- RoomCodeField
- SearchField
- SearchBySelector
- SegmentedControl
- ComboBox
- FilterDrawer
- Checkbox
- ConsentRow

## 16.3 Actions

- PrimaryButton
- SecondaryButton
- TextButton
- DestructiveButton
- IconButton with visible accessible name or tooltip
- CopyButton

Every action requires:

- default
- hover
- pressed
- keyboard focus
- disabled with reason
- loading
- error recovery where applicable

## 16.4 Content

- InlineNotice
- EmptyState
- LoadingState
- RecoveryPanel
- TechnicalDetailsDisclosure
- RoomListRow
- RoomDetailsPane
- RoomCode
- PlayerSeat
- ReadyControl
- ConnectionStepper
- Linkline
- PartyGrid
- PokemonSlot
- PokemonPopover
- ConfirmationDialog
- Toast
- SupportCode

## 16.5 Status design

Do not turn every state into a pill.

Use:

- icon
- short text
- optional concise supporting sentence

Use badges only for compact categorical metadata such as:

- Private
- Public
- Demo Preview
- Supported
- Test-only

---

# 17. Motion

Motion should clarify state, not decorate.

Suggested durations:

- hover and focus feedback: 120 ms
- small scene-content transition: 180 ms
- dialog and drawer: 200 to 240 ms
- connection progress: continuous but restrained

Allowed:

- short opacity transition
- small vertical or horizontal content shift
- Linkline progress
- brief background acknowledgment after validated party update
- toast entry and exit

Do not:

- bounce buttons
- pulse the whole screen
- animate every status poll
- use loading shimmer indefinitely when a normal progress line works
- animate Pokémon data before validation
- delay navigation for visual effect

Reduce Motion:

- remove Linkline movement
- remove scene translation
- use immediate or opacity-only state changes
- keep progress understandable through text

---

# 18. Accessibility and Keyboard

## 18.1 General requirements

- WCAG 2.2 AA
- Windows High Contrast
- Windows 100% to 200% scaling
- No clipped text
- No fixed-height containers that cut localized copy
- Status never communicated by color alone
- Every icon has accessible text
- Logical tab order matches visual order
- Visible focus
- No hover-only information
- Screen-reader announcements for meaningful state changes
- Polling must not repeatedly announce unchanged status

## 18.2 Keyboard map

Global:

- Tab / Shift+Tab: move focus
- Enter / Space: activate
- Escape: close top temporary layer or safe Back
- Alt+Left: Back
- Ctrl+Comma: Settings
- F5: refresh current recoverable data

Public Rooms:

- Ctrl+K: focus search
- Up / Down: move through list
- Enter: open selected details
- Escape: close details before leaving browser

Segmented controls:

- Left / Right: change selection

Party grid:

- Arrow keys: move through six slots
- Home / End: first or last slot where appropriate
- Enter / Space: pin details
- Escape: close details
- Tab exits the grid predictably

Room code:

- Paste supported
- Spaces and hyphens normalized
- Case insensitive
- Error associated with the field
- Enter submits when valid

## 18.3 WPF accessibility

Use and verify:

- AutomationProperties.Name
- AutomationProperties.HelpText
- AutomationProperties.LiveSetting
- AutomationProperties.LabeledBy
- proper Button, TextBox, ListBox, ComboBox, TabControl, and Expander semantics
- focus restoration after dialog close
- focus restoration after public-room preview
- meaningful window and scene titles
- no Canvas-only interactive UI for the native app

Announce only meaningful phase changes, such as:

- Partner joined
- Both trainers are ready
- Your partner will create the room
- Both Switches are connected
- Partner disconnected
- Connection restored
- Trade confirmed

Do not announce every two-second status response.

---

# 19. Proposed WPF Architecture

Do not expand the current imperative MainWindow.xaml.cs pattern.

Recommended project structure:

- App.xaml
- App.xaml.cs
- Themes/
  - Tokens.xaml
  - LightTheme.xaml
  - HighContrast adaptations
  - Controls.xaml
- Models/
  - AppReadiness
  - TradeRoom
  - MemberState
  - ConnectionAttempt
  - PublicRoomSummary
  - PartySnapshot
  - PokemonViewData
  - RecoveryAction
- Services/
  - ControlApiClient
  - RoomStateService
  - NavigationService
  - SettingsService
  - ClipboardService
  - DialogService
  - AccessibilityAnnouncementService
- ViewModels/
  - StartupViewModel
  - HomeViewModel
  - CreateTradeRoomViewModel
  - JoinPrivateRoomViewModel
  - PublicRoomsViewModel
  - TradeRoomViewModel
  - TradingViewModel
  - SettingsViewModel
  - RecoveryViewModel
- Views/
  - StartupView
  - HomeView
  - CreateTradeRoomView
  - JoinPrivateRoomView
  - PublicRoomsView
  - TradeRoomView
  - TradingView
  - SettingsView
  - RecoveryView
- Components/
  - PlayerSeat
  - Linkline
  - RoomListRow
  - PartyGrid
  - PokemonSlot
  - PokemonPopover
  - InlineNotice
  - RecoveryPanel
- Navigation/
  - routes and safe back-stack rules

A lightweight in-house MVVM pattern is acceptable if a third-party framework is not wanted. The requirement is separation of concerns, testable view models, and reusable controls, not a particular library.

MainWindow responsibilities should become:

- host the shell
- host navigation content
- coordinate safe close
- expose global dialogs
- avoid direct room or network logic

ControlApiClient responsibilities:

- typed requests and responses
- cancellation
- bounded timeouts
- error mapping
- version compatibility
- no raw exceptions passed directly to UI

---

# 20. API and Backend Requirements

Endpoint names below are suggested contracts, not permission to break existing APIs without migration planning.

## 20.1 App readiness

Needed capabilities:

- combined user-facing readiness
- separate internal subsystem state
- startup stages
- version compatibility
- recoverable action identifiers
- support code

Possible local API:

- GET /api/app/readiness
- POST /api/app/retry
- POST /api/app/repair
- POST /api/support-bundle

## 20.2 Adapter settings

Needed capabilities:

- detect attached adapters
- distinguish duplicate USB IDs
- show supported versus test-only
- choose safe adapter
- recheck
- repair route
- current health-gate result

Possible local API:

- GET /api/adapters
- POST /api/adapters/select
- POST /api/adapters/recheck
- POST /api/adapters/repair

Do not confuse the static profile registry with current detected device health.

## 20.3 Authoritative Trade Rooms

Needed server capabilities:

- exactly two member seats
- stable member identity
- room ownership
- online state
- ready state
- reconnect token and deadline
- ordered room version
- atomic creator claim
- role transfer before lock
- attempt phase
- leave
- close
- expiration
- idempotent operations

Possible local or relay-facing API concepts:

- POST /api/trade-rooms
- POST /api/trade-rooms/join
- GET /api/trade-rooms/current
- POST /api/trade-rooms/{room_id}/ready
- POST /api/trade-rooms/{room_id}/attempts
- POST /api/trade-rooms/{room_id}/attempts/{attempt_id}/claim-creator
- POST /api/trade-rooms/{room_id}/attempts/{attempt_id}/transfer-creator
- POST /api/trade-rooms/{room_id}/attempts/{attempt_id}/cancel
- POST /api/trade-rooms/{room_id}/attempts/{attempt_id}/retry
- DELETE /api/trade-rooms/{room_id}/members/me
- DELETE /api/trade-rooms/{room_id}

The final naming may differ. Semantics are mandatory.

## 20.4 State delivery

The UI must receive authoritative changes through:

- server events, WebSocket, SSE, or carefully versioned polling
- monotonically ordered room versions
- stale update rejection
- reconnect recovery
- idempotent commands

Never infer the partner’s state from a local click.

## 20.5 Explicit room role

Replace group-owner-derived endpoint behavior with an explicitly assigned per-attempt role.

The local endpoint launch must use:

- stable member or tunnel identity
- assigned Switch room role for this attempt
- attempt ID
- room ID
- role-lock version

Internal host/guest naming may remain temporarily for compatibility, but the mapping must be driven by the server-assigned attempt role, not by who created or joined the Trade Room.

## 20.6 Public directory

Real public search requires:

- directory publication
- TTL and heartbeat
- metadata schema
- pagination
- filtering and sorting
- room compatibility
- open/full/connecting state
- rate controls
- authentication
- abuse reporting and blocking when public release expands
- regional relay selection later
- privacy and disclosure controls

Until implemented, use a typed local mock provider with Demo Preview labels.

## 20.7 Party snapshots

Needed local API behavior:

- decoder observer remains passive
- no mutation or delay of RFU data
- party reassembly per member and direction
- publish only complete checksum-valid snapshots
- clear or invalidate on teardown
- newer snapshot replaces older snapshot by version
- explicit unavailable and invalid states
- trading remains functional without snapshots

Possible API:

- GET /api/trade-rooms/{room_id}/party
- event: party_snapshot_updated
- event: party_snapshot_invalidated
- event: trade_committed

## 20.8 Trade commit

Exactly one idempotent committed-trade event may be emitted only after protocol evidence proves completion.

Do not treat these as committed:

- offer
- selection
- acceptance prompt
- animation start
- animation end without commit
- failed save
- rollback
- cancel
- disconnect
- communication error

---

# 21. Demo Versus Real Feature Matrix

| Area | Current real implementation | May be implemented as labeled Demo | Must be real before beta claim |
| --- | --- | --- | --- |
| Native WPF launch | yes | no | yes |
| Local service auto-start | foundation exists | no | hardened |
| Trade Room creation | narrow local/relay session | UI preview metadata | authoritative shared room |
| Private code join | narrow relay lookup | room preview | authoritative membership |
| Public browser | no real directory | search/filter/sort sample data | real service only for production claim |
| Partner online/ready | no | visual fixture preview only | server-authoritative |
| Either member creates Switch room | no | documented prototype only | atomic server assignment plus endpoint mapping |
| Role transfer | no | prototype only | real state operation |
| Reconnect seat | no | prototype only | server token and deadline |
| Connection stages | partial local endpoint state | fixture demonstration | real runtime evidence |
| Party grid | no live UI data | fixture preview labeled | live validated snapshots |
| Pokémon popover | UI can be built | fixture preview | live validated records |
| Trade committed | decoder research exists | fixture event | idempotent verified event |
| Adapter selection and repair | profile list only | UI shell | real detect/select/recheck/repair |
| Support bundle | backend endpoint exists | no | expose safely in UI |

---

# 22. File Change Map for Later Implementation

Presentation:

- apps/desktop/SwitchTrade.Desktop/App.xaml
- apps/desktop/SwitchTrade.Desktop/App.xaml.cs
- apps/desktop/SwitchTrade.Desktop/MainWindow.xaml
- apps/desktop/SwitchTrade.Desktop/MainWindow.xaml.cs
- apps/desktop/SwitchTrade.Desktop/SwitchTrade.Desktop.csproj
- new Themes, Models, Services, ViewModels, Views, Components, Navigation files

Backend and runtime:

- switchtrade/control.py
- switchtrade/relay_client.py
- switchtrade/endpoint.py
- relay/server.py
- installer/Launch-SwitchTrade.ps1

Optional debug client:

- apps/web/app/page.tsx
- apps/web/app/globals.css

The optional web client must either:

1. follow the same API and terminology, or
2. be explicitly labeled as an internal debug client

It must not remain a competing obsolete product design.

Documentation:

- docs/50-current-product-demo-todo-20260825.md
- docs/54-native-ui-flow-and-runtime-structure-20260825.md
- docs/55-beta-distribution-preflight-checklist-20260825.md
- mark the old visual system as retired or archive it when authorized

Tests:

- view-model navigation tests
- safe-close tests
- public filtering tests
- private code normalization tests
- lobby authority tests
- atomic creator-claim tests
- role-transfer tests
- reconnect tests
- stale version tests
- party snapshot validity tests
- trade-commit idempotency tests
- accessibility smoke tests
- DPI and localization layout tests

---

# 23. Recommended Implementation Phases

## Phase 0 — Freeze design and contracts

- Approve terminology
- Approve screen flow
- Approve visual direction
- Approve Demo labeling
- Approve state domains
- Approve API semantics
- Update docs/54 design section
- Do not claim completion yet

## Phase 1 — Refactor native presentation foundation

- Split MainWindow code-behind
- Add typed API client
- Add navigation
- Add theme tokens
- Add reusable controls
- Implement safe shell
- Implement Home, Startup, Recovery, Settings shell
- Preserve existing working APIs

## Phase 2 — Implement honest UI-only flows

- Create Trade Room form
- Separate Private Join scene
- Public Demo provider
- Search, filters, sort, results, room preview
- Demo Preview labeling
- fixture-only Party preview for visual QA
- keyboard and scaling QA

Do not display fake remote Ready or creator assignment as live.

## Phase 3 — Authoritative room backend

- shared room metadata
- two stable seats
- ready state
- ordered state versions
- reconnect tokens
- leave, close, expiration
- client state subscription
- migrate existing group APIs safely

## Phase 4 — Creator assignment and endpoint integration

- per-attempt creator claim
- simultaneous-claim resolution
- transfer before lock
- endpoint role driven by assignment
- cancellation and retry
- real creator/finder guide transitions
- failure recovery

## Phase 5 — Live party and commit data

- passive decoder observer
- validated party snapshots
- API and events
- 2 by 3 grids
- popover provenance
- invalidation
- idempotent trade commit
- analytics independence

## Phase 6 — Beta hardening

- adapter select/recheck/repair
- support file UX
- startup timeouts
- version mismatch
- safe close
- failure injection
- DPI, keyboard, screen reader, High Contrast
- two-PC two-Switch validation
- documentation freeze

---

# 24. Test Plan

## 24.1 Navigation

- Home routes correctly.
- Private code is a dedicated scene.
- Back preserves public query.
- Escape closes temporary layers first.
- Escape never silently ends active Trade Room.
- Settings does not terminate active connection.
- Leave confirmation appears only when needed.

## 24.2 Forms

- Room name validation
- Private/public progressive fields
- duplicate submission prevention
- private code paste
- code normalization
- recoverable errors preserve input
- field errors are announced and associated

## 24.3 Public browser

- search by every field
- combined search
- each filter
- sorting
- clear filters
- no results
- empty directory
- refresh with existing results
- stale room
- full room
- service failure
- Demo Preview label never disappears

## 24.4 Lobby authority

- second member joins
- ready and cancel-ready
- both ready
- simultaneous creator claims
- exactly one winner
- loser automatically becomes finder
- transfer before lock
- transfer denied after lock
- creator cancellation
- partner disconnect and reconnect
- reconnect timeout
- stale state version rejected
- room survives connection retry

## 24.5 Connection recovery

- adapter removal
- likely 5 GHz
- Switch not found
- online service interruption
- endpoint crash
- WSL crash
- app restart
- stale previous process
- clean teardown
- immediate retry

## 24.6 Party UI

- six valid slots
- empty slots
- one Pokémon
- mixed empty slots
- updated snapshot
- invalidated snapshot
- incomplete record
- corrupt checksum
- derived field label
- unavailable field
- popover focus
- pinned popover
- edge placement
- decoder unavailable while trading continues

## 24.7 Accessibility

- keyboard-only complete private flow
- keyboard-only public browser
- keyboard-only party inspection
- screen-reader names
- live announcements without polling spam
- 100, 125, 150, 175, and 200 percent scaling
- High Contrast
- Reduce Motion
- long localized strings
- minimum pointer targets
- visible focus

---

# 25. Acceptance Criteria

## 25.1 Visual

- No old pixel font
- No faux console bezel
- No Emerald green prototype frame
- No all-uppercase body copy
- No generic dashboard
- No decorative sidebar in ordinary flow
- Linkline identity is restrained and consistent
- Segoe UI Variable used for normal UI
- Room code is the only prominent monospace product value

## 25.2 Terminology

- Group removed from user-facing room terminology
- Configuration renamed Settings
- Host and Guest absent from ordinary UI
- Endpoint absent from ordinary UI
- Backend Offline removed
- Radio and Tunnel hidden
- Trade Room and room on your Switch distinguished

## 25.3 Flow

- Separate Private Join scene
- Searchable Public Demo
- persistent Trade Room shell
- creator and finder instructions
- retry without room loss
- safe leave
- safe window close
- no false remote state

## 25.4 Public Demo

- visible sample-data notice
- real client-side search, filtering, sorting
- Preview room, not misleading live Join
- no fake live partner claim
- future data-provider boundary

## 25.5 Lobby

- room ownership independent from Switch room creator
- both users can claim creator
- simultaneous claims resolve without user-facing error
- transfer only before lock
- authoritative Ready and online state
- reconnect keeps seat for authoritative deadline

## 25.6 Party

- two side-by-side player panels
- each grid is two columns by three rows
- empty slots explicit
- keyboard and pointer equivalents
- complete checksum-valid facts only
- provenance labels
- decoder failure does not block trading

## 25.7 Recovery

- every major failure has one plain-language message
- one primary action
- technical Details collapsed
- support code for fatal failures
- user data and room membership preserved when safe
- no raw exception headline

## 25.8 Accessibility

- WCAG 2.2 AA
- visible focus
- keyboard-complete
- screen-reader labels
- no color-only state
- no hover-only information
- High Contrast
- Reduce Motion
- 200 percent scaling without clipping

## 25.9 Technical truth

- UI never claims server-authoritative behavior before it exists
- UI never claims live public rooms while using mock data
- UI never claims live party data while using fixtures
- endpoint role comes from per-attempt assignment
- decoding remains passive
- analytics remains optional
- radio and tunnel remain independent from party presentation

---

# 26. Default Decisions Unless the Owner Overrides Them

1. Public rooms use a fully interactive sample-data browser labeled Preview.
2. Public Demo action text is Preview room, not Join.
3. The first beta visual target is Light theme plus Windows High Contrast.
4. Dark theme is later unless separately prioritized.
5. Home has direct Create, Browse Public, and Join with Code paths.
6. Private code input is one accessible TextBox, not six separate boxes.
7. Waiting, ready, creator choice, guidance, connecting, and trading are states inside one persistent Trade Room shell.
8. Trade confirmation is inline; it does not interrupt with a full completion screen.
9. Pokémon assets remain neutral placeholders until licensing is approved.
10. Technical state is available through Details, not permanent dashboard cards.
11. The optional web client does not define the native product design.
12. The old Emerald UI system is retired.

---

# 27. Required Codex Handoff Response Before Implementation

Before making large changes, Codex should return:

1. Current code versus this specification gap table
2. Proposed file and class structure
3. API changes separated from UI-only changes
4. Demo-only versus real behavior matrix
5. Ordered implementation phases
6. Risks and migration strategy
7. Test plan
8. Confirmation that production-beta is the working branch
9. Confirmation that the old pixel UI is not being reused
10. Any owner decisions that remain genuinely blocking

After owner approval, Codex may implement the approved phase, verify it, and update docs/54 in the same change.

---

# Final Product Test

The redesign is successful when a nontechnical user can:

1. Launch one native Windows app.
2. Understand whether SwitchTrade is ready.
3. Create a Trade Room or join one with a code.
4. Browse and search the clearly labeled Public Preview.
5. See a partner join and become Ready through authoritative state.
6. Choose either trainer to create the room on their Switch.
7. Follow plain-language console instructions.
8. Recover from common adapter, room, network, and partner problems without losing the Trade Room unnecessarily.
9. See both validated parties in two 2 by 3 grids.
10. Inspect Pokémon details with mouse or keyboard.
11. Complete additional trades without restarting the room.
12. Leave safely.
13. Create a support file when recovery fails.
14. Never need to understand WSL, RFU, host/guest, relay, or endpoint terminology.
