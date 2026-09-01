# SwitchTrade A/B/C connection architecture and readiness gates

Status: normative source of truth, 2026-08-29

This document and `FUTURE_TODO.md` are the two normative project sources for the production
connection rework. This document defines required components, order, ownership, evidence, and
stage boundaries. The TODO records implementation and qualification status. If an older design or
implementation disagrees with either source, it is not authoritative.

The scope is the existing FireRed/LeafGreen path using one supported RTL8192EU (`0bda:818b`) USB
radio per PC, the packaged SwitchTrade WSL runtime, the canonical `ldn.create_network()` host path,
and the hosted relay. Experimental adapters, alternate AP engines, other games, and a claim of full
trade compatibility without a two-PC/two-Switch test are outside this version's scope.

## 1. Decision

The full two-Switch connection can be divided into three functional parts:

- **A — Switch-room side:** detect, parse, and join the room hosted by the Group Leader Switch.
- **B — Mirrored-AP side:** create the mirrored LDN room and accept the Joining Switch.
- **C — Relay bridge:** authenticate both app endpoints, carry A's room advertisement to B, and
  sustain bidirectional RFU communication after both physical sides are ready.

Two lifecycle boundaries are also mandatory:

- **P0 — Common preflight and ownership:** prove the installed runtime and exact radio are usable
  before A or B starts.
- **D — Cleanup and recovery:** prove that endpoint, relay, interfaces, locks, and USB ownership were
  released before reporting a terminal result.

The complete order has to split non-mutating validation, relay authority, and active radio
ownership. Otherwise a PC either holds the USB radio while waiting indefinitely for a partner or
launches an endpoint before an authoritative attempt exists:

```text
P0a passive local/relay validation on both PCs
  -> C0.1 private room, two distinct members, and stable seats
  -> P0b acquire and prepare one exact radio on each PC (in parallel)
  -> C0.2 complementary role readiness and one locked attempt
  -> C0.3 identity-bound endpoint launch, WebSocket authentication, and peer readiness
  -> A detect/parse/join the Group Leader Switch room
  -> C1 carry A's exact advertisement to the other endpoint
  -> B create the mirrored LDN AP and accept the Joining Switch
  -> C2 arm both local bridges, exchange A_READY/B_READY, then sustain RFU
  -> D verified cleanup
```

C therefore surrounds and coordinates A and B. It is not only a final step performed after two
independent radio tests.

The terms **room-side endpoint** and **AP-side endpoint** are preferred over PC A and PC B. Either
physical PC can take either role on a new attempt.

### 1.1 Independent role axes

These identities must never be inferred from a machine name or from one another:

| Axis | Values | Meaning |
| --- | --- | --- |
| Physical machine | arbitrary PC | Installation and hardware identity only. |
| Authoritative seat | `member_a` / `member_b` | Stable relay membership; maps only to relay `host` / `guest` envelope direction. |
| Switch-room role | `creator` / `finder` | `creator` means the nearby Switch is Group Leader (A); `finder` means the nearby Switch joins the app-hosted room (B). |
| Local LDN role | station / AP | A uses `LiveTransport` as a station; B uses `HostTransport` as the LDN AP. |
| Local RFU role | child-side / parent-side | A uses `TunnelSim(parent=False)`; B uses `TunnelSim(parent=True)`. |

The authoritative attempt binds these axes explicitly. A launch acknowledgement is valid only when
its seat, Switch-room role, attempt ID, run ID, launch nonce, endpoint PID, and adapter identity all
match that binding.

### 1.2 Unicode, locale, and process-boundary invariant

ABC+D must work when the Windows account name, profile path, installation path, room display text,
and diagnostic destination contain non-ASCII characters. No stage may assume an English locale or
that redirected Windows-native output is UTF-8. In particular:

- invoke Windows, WSL, `usbipd`, and endpoint processes with typed argument vectors rather than a
  constructed shell command line;
- decode each native boundary according to its actual contract, including UTF-8 and redirected
  UTF-16LE Windows output, before parsing versions or JSON;
- write canonical machine contracts as UTF-8 and accept a BOM only at explicitly documented legacy
  Windows boundaries;
- convert Windows and WSL paths structurally and prove round trips for spaces and non-ASCII user
  names; never interpolate a user path into Linux shell text;
- redact and bound logs after decoding without changing machine-readable identity or failure codes;
- include Korean/non-ASCII profile paths, English and Korean Windows locales, UTF-8/UTF-16LE native
  output, and malformed-byte fail-closed cases in every affected milestone's acceptance tests.

An encoding, locale, or path-conversion failure is its own factual gate failure. It must not be
reported as a radio, relay, room, or cleanup failure.

### 1.3 Production wrapper and observability decision

The 2026-08-31 product decision is recorded in
[`94-production-wrapper-beta-cutover-20260831.md`](94-production-wrapper-beta-cutover-20260831.md):

- production owns one selected radio per PC; simultaneous dual-radio ownership is qualification-only;
- the runtime has no AI/agent dependency and encodes all lifecycle decisions in one deterministic,
  persisted connection-run service;
- the previous production Debug menu is retired as a requirement;
- qualification CLIs remain thin adapters over shared production components and cannot become a
  second product stack;
- the only product diagnosis feature required for beta is a bounded, redacted Desktop support archive
  containing evidence accumulated from application startup, including pre-service failures.

This changes the post-core delivery milestones, not the P0/A/B/C/D gates or evidence definitions.

## 2. Readiness rule

Every stage has three different concepts:

1. **Observed:** a prerequisite or remote signal was seen.
2. **Ready:** the stage completed every required operation and can remain alive.
3. **Sustained:** the stage remains healthy while the next stage communicates through it.

No lower result may be promoted to a higher one. In particular:

- seeing a Switch advertisement is not joining its room;
- starting an AP interface is not transmitting a usable Switch room;
- a Switch seeing a room is not associating with it;
- relay WebSocket connection is not peer readiness;
- A_READY plus B_READY is not a successful trade until C carries real bidirectional RFU traffic;
- functional success is not terminal success until D proves cleanup.

## 3. P0 — Common preflight and ownership

P0 is one shared production path used by normal rooms. Qualification tools may call that same path,
but neither a Debug menu nor a test harness may duplicate it.

### 3.1 P0a — passive validation before radio ownership

| Order | Component | Required state and evidence |
| ---: | --- | --- |
| 1 | Requested-mode topology and user state | Validate only the hardware required by the requested mode: automated = no Switch; guided A or B = one Switch; full C = two compatible Switch games with exactly one host and one searcher. No competing Switch host, local wireless manager, or unrelated test may form a bypass path. |
| 2 | Release and contracts | Desktop, control, wrapper, endpoint, bridge, diagnostic fixture, and relay capability contracts match the installed release. Payload and fixture hashes match their manifest. |
| 3 | Installed local runtime | The SwitchTrade WSL distribution, custom kernel, module tree, Python virtual environment, pinned dependencies, scripts, and `prod.keys` are present and readable. The key file remains private and is never copied into reports. |
| 4 | Required executables and privilege | Windows can run `wsl.exe` and `usbipd.exe`; Linux has root/CAP_NET_ADMIN/CAP_NET_RAW plus `bash`, `flock`, `timeout`, `ip`, `iw`, `tcpdump`, `rfkill`, `readlink`, `pgrep`/`pkill`, `modprobe`, `modinfo`, recovery-only `usbreset`, and the packaged Python. |
| 5 | Relay network path | System time, DNS, TLS certificate/CA validation, HTTPS/WebSocket egress, relay health, and required relay capabilities pass without creating a room or launching work. |
| 6 | Recovery and exclusivity | No normal attempt, diagnostic, endpoint launch, unresolved recovery, or cleanup owns the control/radio locks. Read-only polling has no mutation or launch side effect. |
| 7 | Adapter identity | The saved Windows InstanceId resolves to exactly one connected, authorized `0bda:818b` adapter. Resolve its current bus ID immediately before active use. |
| 8 | Windows USB/IP eligibility | The pinned compatible `usbipd-win` is available; the exact adapter is shared/bound and is not owned by another WSL distribution or process. |
| 9 | WSL/kernel artifacts | The running kernel matches `/lib/modules/<kernel>`. `usbip-core`, `vhci-hcd`, `cfg80211`, `libarc4`, `mac80211`, `led-class`, `rtl8xxxu`, `ccm`, `cmac`, and `tun` are present with matching vermagic. Packaged `tap.ko` is verified as an artifact but need not be loaded separately when `/dev/net/tun` is supplied by `tun`. |
| 10 | Firmware and regulatory data | `rtlwifi/rtl8192eu_nic.bin`, `regulatory.db`, and its signature exist with release-manifest hashes; the configured regulatory domain permits the selected 2.4 GHz channel. |

Only after P0a passes may C0.1 create or reuse the authoritative private room and establish the two
distinct members. P0a failure must leave Windows/WSL hardware ownership unchanged.

### 3.2 P0b — attempt-scoped active radio preparation

P0b runs independently on both PCs after the partner and seats exist, but before either member is
published ready to create the authoritative attempt.

| Order | Component | Required state and evidence |
| ---: | --- | --- |
| 1 | Hardware lease | Acquire the local control-owned attempt and radio locks for the exact saved InstanceId. Capture InstanceId, current bus ID, VID:PID, prior attach state, and ownership provenance. |
| 2 | USB/IP kernel path | Load/verify `usbip-core` and `vhci-hcd`, then attach the exact current bus ID to the exact SwitchTrade WSL distribution once. Do not infer Linux readiness from `ClientIPAddress`. |
| 3 | Linux enumeration | The matching VID:PID appears under Linux USB sysfs, remains stable, and binds to the expected physical device. A timeout or probe error is `unknown`, never proof of absence or readiness. |
| 4 | Radio modules and firmware probe | Load/verify `cfg80211`; load `mac80211` with its `libarc4` dependency; then load `rtl8xxxu` with `led-class`; wait through EFuse and firmware initialization until the exact device has one allowed driver, PHY, and netdev. |
| 5 | LDN crypto and TUN | Explicitly load/verify `ccm`, `cmac`, and `tun`; verify `/dev/net/tun` is the expected character device before any `ldn.connect()` or `ldn.create_network()` call. |
| 6 | Exclusive PHY preparation | Unblock rfkill, prove NetworkManager/wpa_supplicant/other capture tools do not own the PHY, stop stale capture processes, and remove only stale vifs belonging to the selected PHY. |
| 7 | Actual RX health | Receive real 802.11 traffic on the configured health channels, then restore the intended target channel. Interface existence alone is insufficient. |
| 8 | Per-side checkpoint | Publish `P0_SIDE_READY` with run ID, prospective attempt binding, launch generation, exact adapter, PHY/netdev, module/firmware evidence, and monotonic timestamp. |

The radio remains attached to WSL and the lease remains held through C0.2, A or B, C1/C2, and D.
There is no detach/reattach between stages or between creator/finder stages of one diagnostic suite.

The explicit `ccm`, `cmac`, and `tun` load is required because the custom WSL runtime has already
demonstrated that these modular call-site dependencies do not reliably autoload. Their files being
installed is not readiness evidence.

### 3.3 P0_READY invariant

P0_READY means all of the following are simultaneously true:

- the exact selected adapter is attached to the exact active distribution;
- its firmware, driver, PHY, and netdev are live;
- CCMP/CMAC support is loaded;
- TUN support is loaded and `/dev/net/tun` exists;
- the radio passed actual RX;
- one control-owned prospective attempt holds the adapter and launch lock;
- no endpoint has been launched more than once for this attempt.

Both `P0_SIDE_READY` acknowledgements plus C0.1 authority are required before the two members publish
complementary readiness and create C0.2's locked attempt. A changed adapter, bus identity, release,
role, room version, or recovery state invalidates the acknowledgement rather than silently rerunning
P0b.

## 4. A — Switch-room detection, parsing, and join

A runs beside the Switch that selected **Become Leader**. The app is an LDN station joining that
Switch-hosted network. The existing production implementation is `LiveTransport`.

### 4.1 Required components

- P0_READY radio and hardware lease;
- the C0.2 attempt and authenticated remote app peer from C0.3;
- `ldn==0.0.17`, `python-netlink==0.0.15`, `trio==0.33.0`,
  `pycryptodome==3.23.0`, and the installed `prod.keys`;
- `rtl8xxxu`, `led-class`, `cfg80211`, `mac80211`, `libarc4`, `ccm`, `cmac`, and `tun` loaded;
- `LiveTransport`, Nintendo LDN control-port support, TAP/TUN, and UDP port 12345 transport;
- the FRLG communication ID `0x01006FA0233F8000`, scene ID `22287`, protocol `3`, application
  version `88`, 64-byte application passphrase, and advertisement parser;
- one nearby Switch that remains Group Leader throughout A and no competing app or Switch joining it
  directly.

### 4.2 Ordered A gates

| Gate | Required operation | Pass evidence |
| --- | --- | --- |
| A0 Scan preparation | Load `prod.keys`; validate role mapping, optional target-BSSID policy, scan/join deadlines, and FRLG selection criteria before scanning. | Key and policy validation passes; no credential or raw MAC is logged. |
| A1 Radio scan | Scan the supported 2.4 GHz channels without another process changing the PHY. | Actual frames received and channel scan completed. |
| A2 Room identification | Select a room matching FRLG communication ID, scene, protocol, application version, security, and accept policy. | One compatible network selected; optional exact BSSID pinned. |
| A3 Advertisement parsing | Decode and validate the Switch's LDN application data. | Required Pia/RFU fields parse; retain only a redacted hash in reports. |
| A4 Join construction | Build the exact `ConnectNetworkParam` from the selected network, keys, passphrase, name, app version, PHY/netdev, and optional pinned BSSID. | The complete parameter set is bound to the selected A2/A3 network. |
| A5 Station association | Create the station vif on the selected PHY and issue `NL80211_CMD_CONNECT`. | Kernel reports association success to the exact room. |
| A6 Encryption keys | Install pairwise and group CCMP keys through nl80211. | Both `NL80211_CMD_NEW_KEY` operations succeed; no `ENOENT`. |
| A7 Nintendo control port | Complete the LDN custom authentication/control-port exchange. | Control-port activity succeeds and the endpoint remains associated. |
| A8 LDN participant state | Enter the room as the non-host participant and obtain local/host MAC and IP state. | Stable participant record and correct host/local identities. |
| A9 TAP and sockets | Resolve/create the LDN TAP/netdev, configure its `169.254.x.x` participant IP/broadcast, and open the UDP 12345 Pia data plane. | TAP/netdev exists, addresses and host/local identities are correct, sockets are usable. |
| A10 Relay advertisement | Send the exact validated application data to the AP-side endpoint through C1. | The relay accepts one ordered advertisement for this attempt. |
| A11 Hold | Keep the LDN context, station association, TAP, sockets, endpoint process, and tunnel alive. | No disconnect, dead thread, lost PHY, or stale/recreated attempt. |

### 4.3 A result levels

- `A_ROOM_OBSERVED`: compatible advertisement seen.
- `A_ROOM_PARSED`: advertisement validated.
- `A_ASSOCIATED`: 802.11 association completed.
- `A_CONTROL_READY`: CCMP and Nintendo control-port exchange completed.
- `A_READY`: A0–A11 passed and the station, participant state, TAP, sockets, endpoint, tunnel, and
  hardware lease remain healthy through the bounded hold checkpoint.

The guided room test must expose the last completed level. The 2026-08-29 support bundle reached
`A_ROOM_PARSED` and then failed A6; describing that as “room not detected” or a generic radio-gate
failure is incorrect.

## 5. B — Mirrored LDN AP and Switch association

B runs beside the Switch that selected **Join Group**. “Beacon creation” is too narrow: the app must
create a complete Nintendo LDN network, advertise it, authenticate the Switch, maintain participant
state, and expose a usable local data plane. The existing production implementation is
`HostTransport + ldn.create_network()`.

### 5.1 Required components

- P0_READY radio and hardware lease on the AP-side PC;
- the C0.2 attempt and authenticated remote app peer from C0.3;
- A's exact validated application data delivered by C1;
- `ldn==0.0.17`, `python-netlink==0.0.15`, `trio==0.33.0`,
  `pycryptodome==3.23.0`, and the installed `prod.keys`;
- `rtl8xxxu`, `led-class`, `cfg80211`, `mac80211`, `libarc4`, `ccm`, `cmac`, and `tun` loaded;
- host-side AP and monitor vifs, beacon-head compatibility, CCMP monitor compatibility, LDN destroy compatibility, TAP/TUN, and UDP port 12345 transport.
- one nearby Switch that only searches/joins after B reports the room advertised; no second Switch
  hosts a room, because that would create a direct Switch-to-Switch path and bypass B/C.

The hostapd and direct-nl80211 engines remain development prototypes. They are not alternate
production paths in this architecture.

### 5.2 Ordered B gates

| Gate | Required operation | Pass evidence |
| --- | --- | --- |
| B1 Advertisement receipt | Receive A's advertisement only after the authenticated peer-ready barrier. | Attempt, epoch, direction, and sequence are valid; advertisement hash matches A10. |
| B2 Advertisement validation | Validate length and FRLG/LDN identity before touching the radio. | Fixture/live advertisement is accepted for this exact attempt. |
| B3 Radio reset | Remove stale vifs on only the selected PHY while retaining the P0 hardware lease. | No stale AP/station/monitor interface owns the PHY. |
| B4 Network construction | Load `prod.keys`; build `CreateNetworkParam` with protocol 3, scene 22287, communication ID `0x01006FA0233F8000`, app version 88, max participants 6, `ACCEPT_ALL`, the 64-byte passphrase, legal channel, AP/monitor names, and A's application data. | Complete parameter set accepted before launch. |
| B5 AP/monitor/TAP creation | Run the canonical `ldn.create_network()` path with the beacon-head and compatibility patches. | AP, monitor, and TAP resources exist and the LDN context remains alive. |
| B6 TAP and sockets | Configure the host `169.254.x.1` IP/broadcast on the TAP and open the UDP 12345 Pia data plane while the AP context remains alive. | TAP/netdev and sockets are usable before peer traffic arrives. |
| B7 Over-air room advertisement | Transmit the expected room beacon/vendor-action advertisement at the selected channel. | External observation or the real Switch listing the exact room; interface-up alone is insufficient. |
| B8 Switch association | Accept the searching Switch's authentication and association. | LDN participant count changes from 1/6 to 2/6 and the joining peer identity is recorded. |
| B9 Nintendo control port | Complete the joining Switch's LDN control-port exchange. | Control-port activity succeeds and participant state remains connected. |
| B10 Hold | Keep AP advertisement, participant state, TAP, sockets, endpoint, and relay alive. | No peer loss, dead AP thread, channel drift, or duplicate launch. |

### 5.3 B result levels

- `B_AP_CREATED`: AP/monitor/TAP resources exist.
- `B_DATA_PLANE_READY`: the local TAP/IP/UDP data plane is usable.
- `B_ROOM_ADVERTISED`: a compatible room is observable over the air.
- `B_SWITCH_ASSOCIATED`: the real Switch joined and participant count changed.
- `B_CONTROL_READY`: Nintendo control-port exchange completed.
- `B_READY`: B1–B10 passed and the AP, real Switch participant, control port, TAP, sockets, endpoint,
  tunnel, and hardware lease remain healthy through the bounded hold checkpoint.

The AP-association diagnostic proves at most `B_SWITCH_ASSOCIATED` unless it also observes B9 and
the bounded B10 hold. It may not report an AP failure if it never reached B4. The 2026-08-29 run
failed in C0 before AP construction began.

## 6. C — Authoritative relay, advertisement handoff, and RFU bridge

The relay does not forward raw Wi-Fi or extend one LDN network over the internet. Each endpoint
terminates its local LDN connection. C carries versioned, ordered tunnel envelopes between the two
app endpoints, and each endpoint translates between its local LDN/Pia/RFU state and that tunnel.

Required C components are the hosted HTTPS/WebSocket relay and persistent authority store;
`rfu-tunnel.v1`, room/role/attempt contracts, `TunnelClient`, `websockets==17.0.1`, bounded envelope
and sequence gates, heartbeat/reconnect logic, local `PiaCrypto`/Pia Net/Session/Reliable,
`zstandard==0.25.0` where protocol compression requires it, `TunnelSim`, and the read-only party
observer. All are release-pinned in P0; there is no second diagnostic relay or mock production path.

### 6.1 C0 — Authority, attempt creation, endpoint identity, and peer readiness

| Stage/order | Component | Required state and evidence |
| ---: | --- | --- |
| C0.1-1 | Private room | Create one private room through the normal relay API; it is not publicly searchable and has a bounded lifetime. |
| C0.1-2 | Distinct members | Create/join exactly two active members with distinct credentials and stable `member_a`/`member_b` seats. Credentials never enter logs or reports. |
| C0.1-3 | Relay runtime | The deployed relay release, persistent authority store, room/event versioning, TTL/sweeper, rate limits, transport capacity, and process-restart invalidation policy are healthy. Transport state is process-local and a relay restart explicitly fails active attempts. |
| C0.1-4 | Authority freshness | Both controls hold current room versions, capability contracts, member/reconnect authority, and heartbeat presence. No attempt exists yet. |
| P0b | Both radios ready | Each PC independently reaches `P0_SIDE_READY` and retains its hardware lease. A failed or canceled side rolls back readiness before any endpoint launch. |
| C0.2-1 | Complementary intent | Publish exactly one `creator` and one `finder` readiness command using current room versions. A seat or role change invalidates prior readiness. |
| C0.2-2 | Locked attempt | The relay creates one attempt, freezes seats/roles, and returns the same attempt ID and role-lock version to both members. |
| C0.3-1 | One launch per side | Each control launches one wrapper/endpoint with its bound seat, role, attempt ID, diagnostic run ID when applicable, launch nonce, token file, adapter, and PHY. |
| C0.3-2 | Local acknowledgement | The live PID reports matching wrapper and endpoint identities after P0b; stale, duplicate, early, or mismatched acknowledgements fail safely. |
| C0.3-3 | Authenticated WebSockets | Each endpoint connects over TLS with its own member token and attempt ID. Seat-derived tunnel direction must match; relay capacity and protocol limits pass. |
| C0.3-4 | Ordered peer readiness | Each source epoch begins with `PEER_READY`; any retained control/data frames are replayed strictly in source sequence order and only inside the same attempt. |
| C0.3-5 | Relay-ready barrier | Both endpoints accept the other seat's matching readiness and complete a bidirectional unpredictable nonce probe before A starts. |

WebSocket-connected, authenticated, peer-ready, and data-plane-proven are four different states. A
connected endpoint waiting forever for a discarded readiness frame is an ordering failure, not
“relay unreachable.” Relay reconnect creates a new epoch, clears stale queues, re-establishes the
barrier, and never reuses a previous attempt's advertisement or side-ready frame.

### 6.2 C1 — A-to-B advertisement handoff

1. Accept one validated advertisement from A10 only for the bound A endpoint.
2. Bind it to the attempt, source seat, source epoch, monotonically increasing sequence, and a
   redacted SHA-256 hash.
3. Reject stale attempt, credential, seat, direction, duplicate, gap, and epoch data.
4. Replay retained frames in source sequence order, so `PEER_READY` cannot be delivered after a
   later advertisement.
5. Deliver the advertisement exactly once to B after C0.3 and validate its hash against A's local
   evidence before B4.
6. Retain only the bounded control data required for reconnect and erase it at attempt retirement.

### 6.3 C2 — Two-side readiness and sustained RFU bridge

The app terminates the local LDN, Pia Net/Session, crypto, and Pia Reliable layers on each PC. Above
that boundary, `TunnelSim` is feature-neutral: it transports the exact Reliable application payload
containing the GBA/RFU link bytes. The two Switch games—not SwitchTrade—own the trade state machine,
trade barriers, save, and return flow. `PassivePartyObserver` may classify evidence but must never
drive or modify that game state.

| Gate | Required operation | Pass evidence |
| --- | --- | --- |
| C2.1 Local bridge arm | Once a physical leg can emit protocol traffic, initialize that side's Pia crypto, connection variables, Net/Session, Reliable state, observer, and bounded pre-barrier queue without claiming bridge readiness. | The local leg can be serviced without dropping early Switch frames; no unbounded or cross-attempt buffer exists. |
| C2.2 Side-ready messages | A sends `A_READY` only after A11; B sends `B_READY` only after B10. Each message carries the attempt/seat/role binding, endpoint launch identity, advertisement hash, and monotonic stage generation. | The remote endpoint accepts one current side-ready message and rejects stale or mismatched signals. |
| C2.3 Activation barrier | Each endpoint has its own local-ready evidence and the other endpoint's side-ready message for the same locked attempt. | Both publish `C_BRIDGE_READY`; a delayed B Switch does not let A falsely enter an active state. |
| C2.4 Local termination | Each endpoint retains its own SSID/key material, participant identities, TAP, UDP 12345 sockets, Pia connection, and Reliable state. | No raw 802.11, LDN control-port frame, key, packet capture, or MAC address crosses the relay. |
| C2.5 Tunnel mapping | Map seat-derived tunnel directions, A/B parent-child behavior, source/target player IDs, flags, and exact application bytes correctly. | Bidirectional unpredictable probes pass before the activation barrier; real RFU application counters advance after it. |
| C2.6 Ordered transport | Enforce attempt/epoch/sequence ordering, message and queue bounds, backpressure, heartbeat, reconnect generation, and stale-frame rejection. | No duplicate, stale, gap-induced control loss, silent queue clearing, or unbounded backlog. |
| C2.7 End-to-end game flow | Preserve the Switch-generated GBA/RFU payloads through room entry, seat/link establishment, party exchange, trade, bilateral save, stable return, and link close. | Passive evidence and user-visible state agree; the bridge never fabricates a trade transition. |
| C2.8 Sustained liveness | Keep both physical LDN legs, endpoint PIDs, tunnels, authority heartbeats, attempt, locks, and USB leases alive together. | Traffic/heartbeats continue; any lost side fails the attempt exactly once with the original cause retained. |

### 6.4 C result levels

- `C_AUTHENTICATED`: room, roles, attempt, credentials, and WebSockets are valid.
- `C_PEER_READY`: ordered readiness reached both endpoints.
- `C_DATA_PLANE_PROVEN`: a bidirectional unpredictable control nonce crossed the real tunnel.
- `C_ADVERTISEMENT_DELIVERED`: A's exact advertisement reached B.
- `C_BRIDGE_READY`: both endpoints accepted A_READY and B_READY for the same attempt.
- `C_RFU_ACTIVE`: real bidirectional RFU traffic advances on both sides.
- `C_TRADE_COMPLETE`: passive bilateral evidence proves the complete physical trade, save, stable
  return, and clean link-close lifecycle. A user-visible animation or one-sided save alone is not
  sufficient.

## 7. D — Verified cleanup and recovery

D is a distributed protocol with one owner per resource, not one local service controlling both PCs.
Each control service owns only its local endpoint and radio; the relay authority owns the shared
attempt and room. Normal completion, user cancellation, failure, timeout, app close, crash recovery,
and diagnostic cleanup all enter the same idempotent D state machine.

### 7.1 Terminal intent

- A successful trade result requires `C_TRADE_COMPLETE`. Any outcome may then enter D because of a
  clean Switch link close, explicit cancellation, failure, timeout, or application shutdown.
- A user Stop/Close before that point is `canceled`, never `passed`.
- A failure retains its original A/B/C failure as the primary result. Cleanup failure is additional
  critical evidence and must not overwrite the root cause.
- The authority first enters `closing`, freezes new readiness/role changes/retries, and keeps the
  current relay path alive long enough for the in-flight Switch close tail.

### 7.2 Ordered D gates

| Gate | Owner | Required operation and evidence |
| --- | --- | --- |
| D1 Closing intent | Relay authority | Record one idempotent outcome intent (`completed`, `canceled`, or `failed`) and primary failure code while the attempt is still non-terminal `closing`. |
| D2 Game/link close tail | Endpoint | Stop accepting new user work but continue bounded in-flight Pia/Reliable and Switch-generated exit/close frames, including the native close-link tail, until local clean disconnect or deadline. |
| D3 Local bridge drain | Endpoint | Stop new tunnel RFU admission, drain/discard only according to the recorded outcome, finalize observer evidence/capture, and close simulation state without creating game transitions. |
| D4 Local LDN teardown | Endpoint | Close UDP/AF_PACKET sockets, exit `ldn.connect()` or `ldn.create_network()`, send the proper Nintendo disconnect/destroy behavior, join radio threads, then remove only this PHY's station/AP/monitor/TAP vifs. |
| D5 Side-quiescent acknowledgement | Endpoint/control | While identity is still provable, report endpoint outcome, PID, transport/thread exit, interface/PHY state, and primary cause as `D_SIDE_QUIESCENT` for the exact attempt. Forced termination is marked, not hidden. |
| D6 Two-side terminal barrier | Relay authority | After both side acknowledgements—or a bounded forced-failure policy—retire retained frames, terminate the attempt with the preserved outcome, and close both WebSockets. One expected closing disconnect must not become `relay.peer_lost`. |
| D7 Diagnostic resources | Local diagnostic owner | Stop the synthetic peer, close the temporary private room, and delete its credential file. Normal user rooms follow their explicit stay/leave/close policy instead. |
| D8 Endpoint verification | Local control | Prove the exact endpoint PID and launch generation exited; no launcher, child, token, or stale session state remains. Unknown is failure. |
| D9 Linux radio quiescence | Local control | Prove the driver thread is stopped and matching TAP/AP/station/monitor netdevs and PHY activity are absent for a bounded stable interval before detach. |
| D10 USB return | Local control | Quiesce the Linux driver, detach the exact current bus ID once if this run attached it, then prove Windows detached state and matching Linux USB/PHY/netdev absence. Never detach a device the run did not acquire. |
| D11 Release | Local control/authority | Remove private recovery/retained attempt state and release locks only after all owned resources are verified. Only now may Run Again or a new normal attempt become enabled. |

Any `present` or `unknown` cleanup probe produces `DIAG_CLEANUP_FAILED`/`CLEANUP_FAILED`, preserves
the preceding failure, persists minimal private recovery identity, and blocks another run until
startup or explicit recovery proves ownership. Cleanup success requires a bounded quiescent interval,
not a single Windows inventory snapshot.

## 8. Minimal ownership model for the rework

Each responsibility must have exactly one owner:

| Owner | Responsibility |
| --- | --- |
| Desktop UI | User intent, instructions, and factual stage display only. No USB, relay, or retry logic. |
| Local control service | Local locks, exact USB ownership, endpoint launch identity, cancellation, local cleanup, evidence, and recovery. It never claims to have cleaned the remote PC. |
| Relay authority | Room membership, stable seats, role/attempt binding, shared stage barriers, retained-control ordering, terminal outcome, and room retirement. |
| `wsl-radio-prepare.sh` | The single P0 Linux prerequisite, driver, PHY/netdev, TUN, and RX gate. |
| Endpoint | Run exactly one selected A or B transport and the local half of C2. |
| `LiveTransport` | A radio/LDN lifecycle only. |
| `HostTransport` | B radio/LDN lifecycle only. |
| `TunnelClient` | C authority-bound, identity-bound, ordered and bounded envelope transport only. |
| `TunnelSim` | Terminate local Pia/Reliable and forward exact Reliable application payloads; no game/trade state machine. |
| `PassivePartyObserver` | Read-only progress/commit evidence. It never controls or mutates the trade. |
| Support-log exporter | Collect bounded redacted files already emitted by product owners and atomically copy one archive to the Windows Desktop. It never launches, retries, diagnoses, mutates, or cleans a connection. |

Retries are explicit new stage attempts after verified cleanup. GET polling never launches work. A
timeout does not change ownership or invent a different failure classification.

## 9. Cross-cutting contracts

These are required in every P0/A/B/C/D implementation rather than being a separate optional layer:

1. **Identity:** every mutation and checkpoint is bound to release, room version, attempt ID, seat,
   Switch-room role, run/stage generation, launch nonce, endpoint PID/start time, adapter InstanceId,
   VID:PID, bus ID, and PHY as applicable. Stale identity fails closed.
2. **One owner/one launch:** one resource owner, one automatic endpoint launch per side per attempt,
   and one final detach for hardware acquired by that run. Polling and projection are read-only.
3. **Deadlines:** use monotonic, nested budgets for every external boundary—USB enumeration, driver
   probe, scan/join, AP start, user checkpoint, peer readiness, reconnect, close tail, process exit,
   and quiescence. A timeout names the gate that expired.
4. **Continuous liveness:** a passed checkpoint is invalidated if its endpoint, tunnel, heartbeat,
   association, participant, radio thread, PHY, or authority lease is later lost. A/B must remain
   sustained while C runs.
5. **Failure truth:** the report records the last passed gate, first failing gate, stable code,
   bounded timing, and cleanup result. Later `peer_lost`, cancellation, or cleanup errors are
   secondary when an earlier specific cause is known.
6. **Cancellation/recovery:** cancellation is a state transition owned by the worker, not concurrent
   teardown. Crash recovery uses minimal private identity to close the room and release the exact
   owned adapter; uncertain recovery blocks new work.
7. **Security/privacy:** tokens and keys use private files and never enter command lines, UI, logs,
   reports, or bundles. Reports contain hashes/redacted identities, no passcodes, MAC addresses, raw
   packets, trainer/Pokémon data, or imported captures.
8. **Bounded transport:** frame sizes, queue depths, retained controls, retries, backoff, reconnect
   epochs, and logs are bounded. Retention ends with the attempt.
9. **Source/package parity:** tests validate both source and installed payload hashes, pinned Python
   dependencies, kernel/modules/firmware, scripts, and version contracts. A source-only pass does not
   qualify an installer.

### 9.1 Qualification evidence truth table

These tools remain engineering evidence. They are not product screens or beta requirements.

| Qualification | What it can prove | What it cannot prove |
| --- | --- | --- |
| Automated local suite | P0 on one PC, wrapper launch identity, each role policy sequentially, real relay authentication/ordering, synthetic bidirectional nonce, and D cleanup. | A or B physical Switch behavior; simultaneous A/B; a trade. |
| Guided room detection | The room-side PC can execute A through the last explicitly observed A gate against one Group Leader Switch. | B, simultaneous sustain, or an end-to-end trade. |
| Guided AP association | The AP-side PC can execute B through `B_SWITCH_ASSOCIATED` (B8); only additional B9/B10 evidence may promote it to B_READY. | A, simultaneous sustain, or an end-to-end trade. |
| Recommended one-PC suite | The three checks above sequentially with one attached radio and verified cleanup. | `C_BRIDGE_READY`, `C_RFU_ACTIVE`, or `C_TRADE_COMPLETE`. |
| Single-PC dual-adapter C+D suite | Exact two-resource ownership plus hosted C0/C1/C2 and distributed D with synthetic A/B boundaries. | A/B physical behavior, independent PCs, or a trade. |
| Two-PC/two-Switch test | Simultaneous A_READY/B_READY, C2, physical trade, and distributed D. | Nothing beyond the tested release, hardware profile, game/version/language matrix, and network conditions. |

The previous Debug menu proposal is historical and superseded. The product exposes normal connection
controls plus support-log export; it does not expose these qualification modes.

## 10. Product completion order

The standalone P0, Direct A, Direct B, relay C, distributed D, and focused 10/10 Switchless C+D
evidence are sufficient to stop qualification-only development and begin wrapping. Continue in this
order:

1. **P0 cold boot:** all required modules initially unloaded; one gate loads and verifies them, then
   releases the adapter cleanly.
2. **Direct A harness:** one Switch hosts; the installed WSL runtime passes A0–A9 and a bounded
   local hold, then emits the validated advertisement to the harness without desktop, relay, or
   synthetic-peer orchestration. This is local A evidence, not A10/C1 delivery.
3. **Direct B harness:** one Switch searches; the installed WSL runtime passes B2–B10 from a
   release-owned known advertisement without desktop orchestration. Record this as local B evidence,
   not live A-to-B advertisement delivery.
4. **C+D software qualification:** two authenticated endpoints exchange ordered peer readiness,
   retained advertisement, unpredictable nonces, A_READY/B_READY barriers, bounded pre-barrier
   traffic, reconnect generations, terminal intent, two-sided quiescence, and cleanup through the
   real relay. The focused campaign is closed at the user-approved 10/10 result.
5. **Production wrapper and GUI:** make the one-radio deterministic connection-run service the only
   normal application path, attach the minimal UI, and prove support-log export from application
   startup. Do not package the dual-adapter harness as a product feature.
6. **Immutable package smoke:** verify the exact installed normal application, then run one packaged
   Direct A and Direct B smoke to catch runtime drift.
7. **Two-PC/two-Switch test:** bind A_READY and B_READY through C, pass real bidirectional RFU traffic,
   complete the trade/save/stable-return/close lifecycle, and verify distributed D on both PCs.
8. **Production-beta acceptance:** run both nearby role assignments, the separated-distance case,
   cancellation/recovery, installer lifecycle, and log export. Zero duplicate launches, stale
   interfaces, orphan rooms, or unresolved ownership is permitted.

PC A final immutable Direct B run `12e6a535-4770-47ae-9fb3-8d06915af053` passed B2-B10 and verified
full local cleanup. The later returned PC B P0, Direct A, and Direct B evidence was reviewed and
accepted with verified cleanup. Milestone 5/6 and distributed-D software evidence plus the focused
10/10 Switchless C+D campaign qualify the remaining non-physical core boundaries. None of this claims
simultaneous physical `A_READY`/`B_READY`, real RFU activation, `C_TRADE_COMPLETE`, product cutover,
or a trade; those remain the M8-M10 wrapper and final physical acceptance boundary.

## 11. Confirmed critical blockers

1. **Normal application still uses legacy orchestration:** the admitted P0/A/B/C/D implementation and
   distributed endpoint exist, but normal GUI actions have not yet been atomically routed through one
   neutral production connection-run service. No legacy fallback may survive M9.
2. **The source-only production-wrapper corrections are not one accepted immutable package:** the
   installed application, WSL runtime, relay artifact, contracts, and wrapper must share exact release
   identity before product or physical evidence is accepted.
3. **Simultaneous physical composition remains unproved:** standalone A/B and non-physical C/D pass,
   but real `A_READY`/`B_READY`, bidirectional RFU, trade/save/return/close, and distributed D must pass
   through the packaged normal application on two PCs and two Switches.
4. **Application-start evidence is incomplete:** the beta must retain bounded launcher, local-service,
   wrapper, endpoint, stage, and recovery evidence from application startup and export it redacted to
   the Windows Desktop even when startup fails before the service is ready.
5. **Installed desktop startup still requires release qualification:** the transient Lxss false-
   corruption correction is source-tested but needs cold launch, close/relaunch, non-ASCII-profile,
   upgrade, and recovery proof in the new package.

These blockers are also tracked in `FUTURE_TODO.md` and must be closed before another release
candidate is treated as physical-connection qualified.
