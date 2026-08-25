# Native UI flow and runtime structure — 2026-08-25

> Status: source of truth for the currently implemented native Windows UI.
> Maintenance rule: any change to user-visible screens, navigation, controls, status text, API calls,
> automatic startup, or shutdown behavior must update this document in the same change.

This document describes implemented behavior, not planned behavior. The approved redesign source is
`docs/56-native-ui-ux-redesign-handoff-20260825.md`. Release-blocking work that is not implemented
remains in `docs/55-beta-distribution-preflight-checklist-20260825.md`. The final GPT/owner review must
use `docs/62-final-ui-overhaul-gpt-handoff-20260825.md` and the frozen `docs/58`–`docs/61` contracts.

## Current UI flow

```mermaid
flowchart TD
    launch([Launch SwitchTrade]) --> startup[Starting SwitchTrade]
    startup --> check{Local service responds?}
    check -->|Yes| home[Home]
    check -->|No| launcher[Try installed WSL launcher]
    launcher --> retry{Service responds before timeout?}
    retry -->|Yes| home
    retry -->|No| recovery[Startup Recovery]

    recovery -->|Try again| startup
    recovery --> settings[Settings]
    recovery -->|View interface preview| previewHome[Home · Interface Preview]

    home --> create[Create a Trade Room]
    home --> privateJoin[Join a private Trade Room]
    home --> publicRooms[Browse Public Rooms · Demo Preview]
    home --> settings
    previewHome --> create
    previewHome --> privateJoin
    previewHome --> publicRooms
    previewHome --> settings

    create -->|Code only · real local API| realRoom[Trade Room · Current Private Beta]
    create -->|Listed publicly · preview| demoRoom[Trade Room · Demo Preview]
    privateJoin -->|Find via real local API| roomPreview[Private room result]
    roomPreview --> realRoom
    publicRooms -->|Search/filter/sort samples| publicPreview[Public room details · Demo Preview]
    publicPreview --> demoRoom

    realRoom -->|Connect this Switch| active[Current endpoint session]
    active -->|End connection| realRoom
    demoRoom --> party[Two sample parties · 2 × 3 each]
    party --> details[Keyboard/click pinned Pokémon details]

    settings --> connection[Connection profiles]
    settings --> support[Support file]
    settings --> advanced[Advanced technical boundary]

    realRoom -->|Confirmed Back/close| stop[Stop active session if needed]
    stop --> home

    style publicRooms fill:#EAF0FF,stroke:#375BD2
    style demoRoom fill:#EAF0FF,stroke:#375BD2
    style realRoom fill:#E7F5F2,stroke:#0F766E
    style recovery fill:#FFF4DF,stroke:#A45F0B
```

## Features by screen

| UI area | Implemented behavior | Truth boundary |
|---|---|---|
| Global shell | Native WPF light theme, fixed wordmark header, reserved Back row below the header, readiness summary, Settings, scrollable content, keyboard navigation, and live-region announcements | Back appearing never moves the wordmark; readiness is the local control-service status, not a claim that a partner or Switch is connected |
| Startup | Checks `127.0.0.1:8787`, attempts the installed hidden launcher, retries for a bounded period, and routes to Home or Recovery | The progress copy is presentation state, not invented per-stage telemetry |
| Startup Recovery | Try again, Settings, explicitly labeled interface preview, and expandable technical context | Preview does not start online, radio, or Switch behavior |
| Home | Three fixed-width rectangular actions for Create, Browse Public Rooms, and private code entry, plus Settings and an attention notice when in preview/recovery state | Public browsing is labeled as preview |
| Create a Trade Room | Always-visible room/trainer/game/language/offer/wanted/note fields, Private/Public radio selection, required-field validation, and real private-room creation through the existing local API | Room name, trainer name, game, and language are required; Game and Language default to `None`; Public creates a local Demo Preview only |
| Join a private Trade Room | Normalizes a shared code, resolves it through the current API, previews the result, and enters the Trade Room | Occupancy and remote membership are explicitly not authoritative |
| Browse Public Rooms | Interactive local search, field selector, availability/game/language filters, sorting, selection, empty state, and sample detail panel | Every public-room surface says `Public Rooms Preview` or `Demo Preview`; no network directory is queried |
| Settings · Connection | Reads profile-driven adapter compatibility, support state, summary, and technical details; permits recheck | It does not claim to select, repair, attach, or live-probe an adapter |
| Settings · Support | Requests the real local support-bundle endpoint and reports a friendly result | Requires the installed local service |
| Trade Room · real | Room identity, code/invitation copy, user-facing Switch instructions, current endpoint start/stop, status mapping, and safe leave/close | Shared Ready, authoritative membership, either-user creator choice, reconnect, and live parties are named as unavailable |
| Trade Room · demo | Two side-by-side parties, six explicit slots each, neutral initial placeholders, pointer tooltips, click/Enter selection, detailed stats, and Escape dismissal | All trainers, Pokémon, network quality, and party fields are sample data |

## Navigation and keyboard behavior

- Back is hidden when there is no safe history entry.
- The Back row remains reserved when Back is hidden, so the wordmark and content do not shift.
- Narrow scenes use a fixed 640-DIP column anchored to the left content edge under the wordmark and
  Back control. Wide Public/Trade Room scenes use the same left edge and expand rightward within the
  shared 1000-DIP content boundary.
- `Alt+Left` and `Escape` go back; in Demo party details, `Escape` closes details first.
- `Ctrl+,` opens Settings and `F5` refreshes local service status.
- Leaving or closing a real Trade Room asks for confirmation and stops an active endpoint session.
- The UI never silently treats a local click as proof of remote readiness or membership.
- Buttons and party slots are keyboard focusable. Pokémon details are available through selection as
  well as hover, so required information is not hover-only.

## Implemented presentation foundation

- `Themes/Tokens.xaml` owns Linkline colors and common geometry values.
- `Themes/Controls.xaml` owns typography, card, notice, input, focus, and button styles.
- `Models/AppModels.cs` contains typed presentation records.
- `Services/ControlApiClient.cs` is the typed local JSON API boundary and converts technical failures
  into user-facing messages.
- `Services/PublicRoomPreviewProvider.cs` is the sole source of labeled sample rooms and parties.
- `ViewModels/MainViewModel.cs` owns shell navigation and per-screen state.
- `Views/Screens.xaml` contains screen templates; `MainWindow.xaml` is only the persistent shell.

## Known product gaps (not represented as working UI)

- The frozen `room-control.v1` server-authoritative two-member Trade Room, shared online/ready state,
  ordered membership events,
  reconnect tokens, expiration, and conflict handling.
- Either-member room-creator claims independent of stable member identity and group ownership.
- A production public directory and real public room publication.
- Live adapter selection, automatic repair, and full per-stage control/relay/radio/session telemetry.
- The frozen `party-commit.v1` passive decoder party snapshots, checksum-valid live party presentation,
  and fail-closed committed-trade events.
- The frozen externally administered `privacy-statistics.v1` consent decision and server-side
  statistics implementation.
- Per owner direction, optional privacy/analytics settings are not presented in the client. Analytics
  remain disabled until the separately administered external consent workflow exists.
- Production relay deployment, authentication, and two-endpoint internet qualification.

## Runtime structure

```mermaid
flowchart LR
    user[/Windows user/]
    desktop[SwitchTrade.exe · Native WPF]
    launcher[Windows launcher]

    subgraph localRuntime [Isolated SwitchTrade WSL]
        control[Python control service]
        endpoint[RFU endpoint runtime]
        radio[USB radio and driver]
    end

    lobby[Future authoritative room service]
    relay[Relay service]
    switchDevice[/Nintendo Switch/]
    remotePeer[Remote SwitchTrade endpoint]

    user --> desktop
    desktop -->|Local typed JSON API| control
    desktop -.->|Starts when absent| launcher
    launcher -->|USB and WSL preflight| radio
    launcher --> control
    control --> endpoint
    control -.->|Future room state| lobby
    endpoint <--> radio
    radio <--> switchDevice
    endpoint <-->|Opaque RFU envelopes| relay
    relay <--> remotePeer

    style localRuntime fill:#EAF0FF,stroke:#375BD2
    style desktop fill:#FFFFFF,stroke:#D9DDE5
    style lobby fill:#FFF4DF,stroke:#A45F0B,stroke-dasharray: 5 5
```

## Layer terminology

| Term | Exact meaning |
|---|---|
| Native desktop client | `SwitchTrade.exe`, the WPF presentation and local-control client |
| Windows launcher | PowerShell bootstrap that performs Windows/USB/WSL startup work |
| Local control service | Python service bound to loopback at `127.0.0.1:8787` inside the isolated distro |
| RFU endpoint runtime | Health-gated Linux process that owns LDN, Pia, Reliable, radio, and tunnel behavior for one side |
| Relay service | Broker and opaque WebSocket forwarder between endpoint runtimes |
| Authoritative room service | Contracted server state for two members, readiness, role claims, reconnect, and room lifecycle; it does not yet exist in the current client/backend |
| Demo Preview | Local, labeled sample content that never claims a remote user or live service exists |

Technical terms such as endpoint, radio, tunnel, host, and guest may remain in source code or an
explicitly expanded Advanced/Technical details area. Ordinary product copy uses Home, Trade Room,
room code, Settings, you, partner, create the room, and find the room.

## Is the EXE the whole application?

No. The installed product is intended to feel like one app, but its responsibilities stay separated:

1. `SwitchTrade.exe` presents state and invokes the loopback API.
2. The Windows launcher handles elevation, USB ownership, and isolated WSL startup.
3. The Python control service validates requests and manages endpoint processes.
4. The WSL endpoint owns the adapter and transports local Switch communication.
5. A production remote service will provide authoritative rooms and opaque relay transport.

This boundary preserves driver and feature expandability: new qualified adapters stay profile-driven,
and future Switch-to-Switch activities can reuse the feature-neutral RFU transport without embedding
driver or protocol logic in WPF.

## Files that require this documentation check

- `apps/desktop/SwitchTrade.Desktop/App.xaml`
- `apps/desktop/SwitchTrade.Desktop/MainWindow.xaml`
- `apps/desktop/SwitchTrade.Desktop/MainWindow.xaml.cs`
- `apps/desktop/SwitchTrade.Desktop/Themes/*`
- `apps/desktop/SwitchTrade.Desktop/ViewModels/*`
- `apps/desktop/SwitchTrade.Desktop/Views/*`
- `apps/desktop/SwitchTrade.Desktop/Services/*`
- `switchtrade/control.py`
- `installer/Launch-SwitchTrade.ps1`
