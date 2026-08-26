# SwitchTrade Technical Guide

## 1. Purpose and current boundary

SwitchTrade is a Windows application that lets two stock Nintendo Switch consoles run the
FireRed/LeafGreen Direct Connection trade flow over the internet. Each player runs one Windows
client and connects one compatible USB Wi-Fi adapter. The client coordinates an online two-member
room, assigns complementary radio roles, and transports the RFU stream between the two endpoints.

The `0.2.0-beta.1` product boundary is intentionally narrow:

- native Windows WPF client;
- Windows 10 22H2 x64 build 19045 or Windows 11 x64 with current Microsoft Store WSL 2;
- isolated `SwitchTrade` WSL distribution and a verified custom WSL kernel bundle;
- one USB Wi-Fi adapter per endpoint;
- server-authoritative private and public rooms with exactly two active member seats;
- FireRed/LeafGreen Direct Connection trading;
- opaque, authenticated RFU relay transport;
- structured local diagnostics and a redacted support bundle;
- RTL8192EU as the beta hardware candidate.

Battles, Union Room, 5 GHz operation, analytics, automatic updates, and the quarantined RTL8188EU
path are not beta capabilities. They are tracked in [Future TODO](FUTURE_TODO.md).

For the byte-level protocol, read the
[FireRed/LeafGreen Communication Protocol](FRLG_PROTOCOL.md). This guide covers only where that
protocol fits into the product.

## 2. System architecture

```mermaid
flowchart LR
    subgraph PC_A[Player A Windows PC]
      EXE_A[Native WPF app]
      API_A[Local control API\n127.0.0.1:8787]
      WSL_A[Isolated SwitchTrade WSL]
      RADIO_A[USB Wi-Fi radio]
      EXE_A --> API_A --> WSL_A --> RADIO_A
    end

    subgraph CLOUD[Public relay]
      AUTH[Room authority\nHTTP + SQLite]
      RFU[Attempt-bound RFU WebSocket\nopaque envelopes]
    end

    subgraph PC_B[Player B Windows PC]
      EXE_B[Native WPF app]
      API_B[Local control API\n127.0.0.1:8787]
      WSL_B[Isolated SwitchTrade WSL]
      RADIO_B[USB Wi-Fi radio]
      EXE_B --> API_B --> WSL_B --> RADIO_B
    end

    SWITCH_A[Switch A] <-->|2.4 GHz LDN| RADIO_A
    SWITCH_B[Switch B] <-->|2.4 GHz LDN| RADIO_B
    API_A <-->|authoritative control| AUTH
    API_B <-->|authoritative control| AUTH
    WSL_A <-->|RFU envelopes| RFU
    WSL_B <-->|RFU envelopes| RFU
```

The three primary boundaries are:

1. **Windows client.** Presentation, user actions, local orchestration, status, and recovery.
2. **Local WSL endpoint.** Radio ownership, LDN/Pia/RFU protocol work, tunnel endpoint, and hardware
   diagnostics.
3. **Relay service.** Two-seat room authority and opaque bidirectional RFU forwarding. It does not
   emulate the game or decode Pokémon data.

Control and data are deliberately separate. The HTTP authority decides who may connect and what the
current attempt is. The WebSocket data path forwards validated envelopes only for that authorized
attempt.

## 3. Repository map

| Path | Responsibility |
| --- | --- |
| `apps/desktop/` | Native WPF client, view models, API client, launcher, theme, and UI tests. |
| `bridge/` | LDN/Pia/RFU implementation and the FireRed/LeafGreen endpoint. |
| `config/` | Versioned hardware policy, LDN key input, and runtime configuration. Never print key values. |
| `installer/` | Native setup bootstrapper, WSL lifecycle scripts, integrity checks, and package builder. |
| `legal/` | Third-party notice inventory used by the package builder. |
| `payload/` | Release configuration, including the default public relay URL. |
| `relay/` | FastAPI authority, SQLite persistence, RFU WebSocket relay, container files, and hosting smoke. |
| `scripts/` | Runtime radio preparation, health gate, endpoint launcher, and reproducible kernel tooling. |
| `switchtrade/` | Local control API, relay client, tunnel framing, diagnostics, hardware policy, and observer. |
| `tests/` | Cross-layer unit/integration tests and safe deterministic fixtures. |
| `tools/` | Maintained protocol and Pokémon payload analysis utilities. |

There is no browser frontend in the beta. Internal captures, dated research notes, design archives,
and agent handoffs are excluded by `.gitignore`.

## 4. Windows desktop application

The desktop project is `apps/desktop/SwitchTrade.Desktop`. It targets the Windows 10 build 19041 SDK
surface and publishes one self-contained x64 `SwitchTrade.exe`; Setup enforces the qualified build
19045 product minimum. It does not require Electron, WebView2, or an external browser.

The application follows a view-model-driven screen flow:

```mermaid
flowchart TD
    START[Startup and readiness] --> HOME[Home]
    HOME --> CREATE[Create Trade Room]
    HOME --> PRIVATE[Join Private Room]
    HOME --> PUBLIC[Browse Public Rooms]
    CREATE --> LOBBY[Authoritative Trade Room]
    PRIVATE --> LOBBY
    PUBLIC --> DETAILS[Room details] --> LOBBY
    LOBBY --> ROLE[Choose which player creates the Switch room]
    ROLE --> CONNECT[Connect both Switch consoles]
    CONNECT --> ACTIVE[Trading room / party status]
    ACTIVE --> LOBBY
    HOME --> SETTINGS[Settings]
    SETTINGS --> HOME
```

`MainViewModel` owns navigation and product state. `ControlApiClient` is the typed localhost client.
`BackendLauncher` starts the installed WSL launcher when the control service is absent. Views render
only real API state; they do not substitute sample rooms, readiness, trainers, or parties.

Important UI invariants:

- the room authority, not the UI, decides membership and attempt state;
- member A/member B remain stable identities during a room;
- room creator/finder is a per-attempt radio role and can be assigned to either member;
- leave and close are idempotent user operations;
- public browsing is unavailable when the relay does not advertise `public-directory.v1`;
- errors must provide a recovery action rather than exposing command output;
- Credits remain reachable from the bottom-left application shell.

## 5. Installation and runtime lifecycle

`SwitchTradeSetup.exe` is a native bootstrapper contained in the release ZIP. It verifies the package
manifest before running a mutating action. The normal install path is:

1. Verify all payload hashes and reject missing or unexpected files.
2. Require Windows 10 22H2 x64 build 19045 or Windows 11 x64 and reject Server/ARM64 hosts.
3. Enable WSL prerequisites, update legacy inbox WSL to current Microsoft Store WSL, and resume after
   restart through a non-secret RunOnce entry when required.
4. Install the pinned `usbipd-win` prerequisite when required.
5. Import or update the isolated WSL distribution named `SwitchTrade`.
6. Install the bundled kernel and modules under `%ProgramData%\SwitchTrade\kernel`.
7. Back up and merge the SwitchTrade kernel settings into the user's global `.wslconfig` after explicit
   consent.
8. Stage and self-check `/opt/switchtrade` before replacing the active runtime.
9. Install the native app and launcher under the SwitchTrade application directory.
10. Start the local control service and verify readiness.

The endpoint resolves its required LDN key input from `/opt/switchtrade/config/prod.keys` in the
installed application root. It must be included by the source archive/package builder and must never
be copied into logs or support bundles.

The custom kernel setting is global to WSL2 because Windows does not support selecting a WSL kernel
per distribution. Setup preserves the complete previous configuration and restores it on failed
kernel start or explicit rollback. The distro itself remains isolated from the user's other WSL
distributions.

The extracted ZIP is only needed for Setup, Update, Repair, Rollback, or Uninstall. A successful daily
launch uses the installed app and installed WSL runtime. Uninstall does not unregister the distro
unless purge is explicitly selected.

The package manifest records the source commit as `release_id`. Release packages must be built from a
clean committed tree; `installer/Build-Package.ps1` refuses a dirty workspace.

## 6. Local control API

The local service is FastAPI on `127.0.0.1:8787`. It is never intended as a network-facing service.
The maintained v1 surface is:

| Area | Endpoints |
| --- | --- |
| Readiness | `GET /api/v1/app/readiness`, `POST /api/v1/app/retry`, `POST /api/v1/app/repair`, `POST /api/v1/app/shutdown` |
| Rooms | `POST /api/v1/trade-room`, `POST /api/v1/trade-room/join`, `GET /api/v1/trade-room`, `GET /api/v1/trade-room/events` |
| Public directory | `GET /api/v1/public-trade-rooms`, details and join under the same prefix |
| Connection | `POST /api/v1/trade-room/connect`, `POST /api/v1/session/start`, `POST /api/v1/session/stop` |
| Membership | `DELETE /api/v1/trade-room/members/me`, `DELETE /api/v1/trade-room` |
| Hardware | `GET /api/v1/hardware/devices`, `POST /api/v1/hardware/selection`, `POST /api/v1/hardware/diagnostics` |
| Observation | `GET /api/v1/trade-room/parties` |
| Support | `POST /api/v1/support-bundle` |

The service exposes four separate readiness dimensions: local control, relay, radio, and trade
session. Do not collapse them into a single generic “offline” state; each has different recovery.

Legacy `/api/groups*` and `/api/session*` aliases remain only for compatibility during the beta.
New client work should use `/api/v1`.

## 7. Server-authoritative room model

The relay authority lives in `relay/authority.py` and persists rooms and credential hashes in SQLite.
The production server must run one worker and one replica because live WebSocket peers are
process-local.

Room properties:

- exactly two stable seats: `member_a` and `member_b`;
- six-character room code and separate opaque internal room ID;
- private or public visibility;
- required room name, trainer display name, game, and language;
- versioned room document with ordered events;
- ready, online, reconnecting, and left member states;
- short-lived member bearer credentials and rotating reconnect credentials stored only as SHA-256
  hashes;
- a single active connection attempt at a time.

Attempt state advances through creator selection, role lock, Switch discovery/advertising,
connection, trading room, recovery, closing, and a terminal completed/canceled/failed state. Room
identity is independent from the physical Switch-room creator. Either member may claim that role
before it is locked.

Mutations require idempotency/command identifiers and optimistic room-version checks. An expired or
stale attempt cannot mutate a new attempt. Active transport is disconnected before a member is
removed or a room is closed.

See `relay/DEPLOYMENT.md` for TLS, storage, metrics, backup, rate-limit, and hosting requirements.

## 8. RFU tunnel and protocol boundary

`switchtrade/rfu_tunnel.py` defines the binary envelope. A client connects to the credentialed,
attempt-bound WebSocket using its member bearer token. The relay checks direction, kind, size,
attempt, membership, heartbeat, and peer availability, then forwards the envelope without decoding
its RFU payload.

The local endpoint performs the feature-specific work:

- creates or discovers the LDN room;
- establishes Pia and reliable transport;
- maps the FireRed/LeafGreen RFU parent/child behavior;
- maintains VBlank cadence, retransmission, barriers, and teardown;
- exchanges opaque endpoint state needed to keep the two sides synchronized.

This separation allows the relay to remain game-agnostic, but it does not automatically make every
game feature supported. A new mode still needs endpoint-side proof that its setup, barriers, game
commands, and teardown are compatible. The complete known stack is documented in
`FRLG_PROTOCOL.md`.

## 9. Hardware policy and diagnostics

`config/wsl-radio-hardware.tsv` is the source of truth. A profile separates USB identity, driver
strategy, allowed drivers, allowed roles, host engine, status, automatic-selection policy, and
evidence. New adapters are added as data and diagnostics first; core control and UI code should not
special-case product IDs.

Current status:

| Adapter | Driver | Status | Beta behavior |
| --- | --- | --- | --- |
| Realtek RTL8192EU (`0bda:818b`) | in-kernel `rtl8xxxu` | beta candidate | Auto-selectable for host, guest, and relay. Passed real room join, full trade, and 30-minute RX soak; two-adapter qualification remains. |
| Realtek RTL8188EU (`0bda:8179`) | `rtl8xxxu` or optional vendor module | quarantined | Diagnostics/observation only. Control-port association fails and concurrent AP+monitor can deadlock or lose receive. |
| MT7610U, MT7612U, RT2770/3070/3572, RTL8821CU | in-kernel candidates | experimental | Manually selectable with an explicit untested label and diagnostics; not auto-selected. |
| AR9271 | `ath9k_htc` | quarantined | Diagnostics only due to application-specific association failures. |

Every capture and session workflow must pass `scripts/radio-health-gate.sh` first. The gate verifies
USB presence, WSL attachment, kernel/driver binding, phy/interface state, channel configuration, and
real receive activity. A stale interface that merely exists is not healthy.

The staged diagnostic pipeline is in `switchtrade/hardware_diagnostics.py`. It redacts MAC addresses,
tokens, and common secret fields. Experimental adapters may be selected without per-attempt consent,
but the UI must keep the untested disclaimer and diagnostic action visible.

### When a custom kernel rebuild is required

Rebuild the kernel only when the required driver, kernel configuration, firmware-loading support, or
WSL patch is absent from the bundled kernel. A new profile for an already-present in-kernel driver
does not require a rebuild. Firmware-only additions may require a package/kernel-bundle update but
not a kernel compilation. Keep driver-specific choices in the hardware matrix and preparation layer.

## 10. Diagnostics and data handling

`RunLogger` creates structured per-run events and a readable log. Support bundles include a runtime
summary, event log, current configuration, and a privacy manifest. Redaction covers fields named like
tokens/passwords/secrets, MAC addresses, and common inline credential forms.

Rules for new diagnostics:

- log state transitions and stable error codes, not secrets or raw bearer headers;
- cap command output before including it in a bundle;
- never store raw RFU payloads or Pokémon records in the relay;
- never commit support bundles, packet captures, or live player data;
- make diagnostic failures non-destructive and keep Repair explicit;
- make every logged error map to one user-safe recovery action.

The passive party observer is fail-closed. It publishes a safe projection only after complete,
checksum-valid records. A trade commit requires the expected link-command sequence, save barriers,
and swapped post-trade party evidence. The current relay has no analytics or committed-trade ingestion
endpoint.

## 11. Build, test, and package workflow

### Python tests

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

Run the bridge suite from its Linux/WSL dependency environment because it includes sysfs and nl80211
compatibility tests:

```bash
cd bridge
PYTHONPATH=. ./.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

### Native client

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\apps\desktop\Publish.ps1 `
  -Output .\artifacts\native\SwitchTrade
```

The published executable supports the internal `--self-test` path used by release QA.

### Relay

```bash
docker compose -f relay/compose.yaml build --pull
docker compose -f relay/compose.yaml up -d
curl --fail http://127.0.0.1:8788/health
python -m relay.smoke https://relay.example.com
```

### Distribution package

The package builder requires a committed clean tree plus the rootfs, desktop executable, custom
kernel, module archive, kernel manifest, pinned `usbipd-win` MSI, notices, and a public HTTPS relay
URL. Use `-UnsignedPrivateBeta` for the owner-approved beta path or `-Release` with signing inputs for
a signed release. Exact commands and integrity rules are in `installer/README.md`.

Before publishing:

1. Run both Python suites and the native self-test.
2. Run the setup package `audit --allow-unsigned-package` and require exit code zero.
3. Inspect the ZIP manifest and SHA-256 sidecar.
4. Confirm the package `release_id` equals the `main` commit.
5. Upload only the ZIP and checksum generated from that commit.

## 12. Extension boundaries

### Add a radio

Add a hardware profile, ensure its in-kernel module/firmware is present, add deterministic diagnostic
coverage, and qualify observe → join → host → soak before promotion. Avoid product-ID branches in the
UI or endpoint.

### Add a game feature

Keep the relay envelope unchanged unless the transport itself needs a new capability. Add a separate
endpoint feature module for the mode-specific RFU commands, blocks, barriers, and teardown; add replay
fixtures and fail-closed state tests; then run native two-Switch captures and end-to-end qualification.

### Add UI state

Extend the local v1 contract first, then the typed client/view model, then the view. Never infer room
authority from local button history. New real-time state should be ordered and reconnectable.

### Scale the relay

SQLite persistence alone does not make multiple workers safe. Horizontal scaling requires shared
presence, live-peer routing, ordered event delivery, distributed rate limits, and a tested failover
model before increasing worker or replica count.

## 13. Troubleshooting and recovery

| Symptom | First distinction | Safe action |
| --- | --- | --- |
| App cannot start | local control absent vs WSL startup failure | Retry once; then run Setup Repair. Do not manually unregister WSL. |
| Public rooms unavailable | relay unreachable vs missing directory capability | Check readiness and relay `/health`; a private room cannot repair relay availability. |
| No USB adapter | Windows ownership vs WSL attachment | Open Settings, refresh devices, attach the correct bus ID, then run diagnostics. |
| Room not visible on Switch | wrong band/channel vs failed LDN advertisement | Pass health gate, recreate the Switch room, scan all supported 2.4 GHz channels for diagnosis. |
| Adapter stops receiving | driver/phy receive death | Stop the session, free the radio, reattach, and rerun health gate. Do not continue from stale monitor state. |
| Leave/close reports relay unavailable | local teardown vs authority result conflated | Local cleanup must finish idempotently; relay failure is reported separately and can be retried. |
| Native error after successful exit | radio ended before the final room animation | Preserve the teardown grace period; do not treat completed game exit as a failed trade. |

Setup Repair is the supported recovery entry point for installed runtime failures. Manual WSL reset,
distro unregister, or global `.wslconfig` edits can destroy rollback evidence and should not be the
first response.

## 14. Handoff checklist for developers and AI agents

Before changing the project:

1. Read this guide, `FRLG_PROTOCOL.md`, and the relevant component README.
2. Confirm the current branch, clean/dirty state, and exact `main` ancestry.
3. Reproduce with a unit, replay, API, or package audit before requiring a live Switch.
4. Keep room identity, per-attempt radio role, and RFU parent/child role as separate concepts.
5. Keep the relay opaque; do not move protocol emulation or Pokémon decoding into it.
6. Keep WSL isolated and preserve the global kernel rollback contract.
7. Pass the radio health gate before interpreting a capture as protocol evidence.
8. Update maintained docs and `FUTURE_TODO.md` in the same commit.
9. Do not restore retired web UI, dated docs, captures, prod keys, backups, or agent handoffs to the
   public tree.
10. Build release artifacts only from a clean `main` commit and publish their checksum.

When protocol evidence changes, document what was observed, on which channel/role, how it was
decrypted or decoded, and which prior conclusion it replaces. One-channel absence is never proof of
radio silence.
