# SwitchTrade Development History

## 1. Origin and objective

SwitchTrade began as an investigation into whether the Nintendo Switch FireRed/LeafGreen Direct
Connection feature could be made usable between two remote consoles. The early reference point was
the open-source `frlg-ldn-trade` implementation, which demonstrated PC-to-Switch trading. The project
then expanded the endpoint, packet analysis, WSL hardware layer, authoritative relay, native client,
and installer needed for a two-player product.

This history records engineering milestones and corrected conclusions. It deliberately omits private
agent transcripts, raw captures, credentials, player data, and commit-by-commit narration.

## 2. August 20–21: local proof and hardware baseline

The first milestone was reproducing a local FireRed/LeafGreen trade using the upstream emulator-style
endpoint. The project established:

- a compatible Realtek USB adapter could advertise/join a Switch LDN room;
- real rooms could appear on channels 1, 6, or 11 rather than one fixed channel;
- live radio setup needed deterministic phy/interface cleanup;
- packet injection required the correct radiotap/802.11 form;
- the original VM workflow could trade but was vulnerable to driver hangs and USB ownership drift.

Two early architectures were explored: transparent 802.11 frame relay and protocol-aware endpoint
emulation. Transparent relay produced useful capture/injection tooling but did not provide a complete,
controllable internet trade lifecycle. The protocol-aware path became the product core.

## 3. August 22–23: beacon debugging and the first golden capture

The host path initially created an interface without producing a Switch-visible room. Hostapd-backed
AP operation was introduced because `rtl8xxxu` did not reliably start periodic beaconing through a
minimal nl80211 start-AP path.

The first large “golden” capture proved the observer received known Switch frames and substantial
Wi-Fi traffic, but its interpretation was corrected twice:

1. not all data frames were simply “to the router”; randomized client unicast traffic was present;
2. more importantly, channel-6-only capture could not decide whether a Direct Connection session
   occurred on channel 1, 11, or 5 GHz.

That correction led to explicit channel-aware experiments and the rule that every capture starts with
a receiver health gate.

The LDN advertisement was reconstructed field by field: communication ID, scene, protocol 3,
application version, six-player limit, Pia application header, custom base85 record, trainer/session
identity, and the non-zero partner information required by the Switch room filter.

## 4. August 24: native handshake reverse engineering

A controlled two-Switch room was captured on a known channel. This isolated the native Net/Session,
Pia, Reliable, GBA adapter, LLSF, and RFU layers without unrelated infrastructure traffic.

The endpoint advanced through a sequence of visible live gates:

- room appears in the Switch list;
- room selection reaches “awaiting response”;
- parent sends the correct Net and Session-new exchange;
- Switch shows the endpoint's “OK” response;
- Reliable INIT and selective ACK open the stream;
- RFU C/A connect and bidirectional NI complete;
- player IDs and UNI rows enter the multiplayer room;
- movement and seat state are exchanged;
- trainer cards and parties populate the trade menu;
- selection and confirmation start the animation;
- finish commands, save barriers, and post-save re-entry complete;
- the trade remains committed after returning to a neutral state.

Several failures were protocol gates rather than random instability. Examples include station ID
direction, missing Session types, wrong parent/child T offsets, K acknowledgement shape, NI ownership,
rolling RFU tag handling, barrier initiation order, and save-round counts. Each resolved gate became a
deterministic unit or replay test.

The final successful PC-host cycle traded a Pokémon, saved it, returned to the trade menu, and then
exited. A later native error after room departure identified an independent teardown-grace issue:
ending LDN before the avatar/scene transition completed.

Movement jitter was traced mainly to cadence and WAN behavior. Scheduling changed from accumulated
relative sleeps to the title's absolute VBlank cadence. Remaining subjective smoothness work was
deferred because it does not block protocol correctness.

## 5. August 24–25: WSL and radio engineering

The project moved from VMware to an isolated WSL distribution so USB ownership and deployment could
be managed by the product. A custom WSL kernel and module bundle were made reproducible and verifiable.

Hardware findings:

- RTL8192EU with in-kernel `rtl8xxxu` passed room join, full trade, and a 30-minute receive soak;
- RTL8188EU could observe traffic but failed the required control-port association and could deadlock
  under AP+monitor concurrency, including receive-death behavior;
- card presence alone was not a sufficient health signal;
- the hardware policy needed data-driven profiles, staged diagnostics, and quarantine states.

The RTL8192EU became the beta candidate. RTL8188EU was retained as a future driver task, not advertised
as a reliable beta card. Experimental upstream driver candidates were added to the matrix without
automatic promotion.

## 6. August 25: product architecture and contracts

The prototype was reorganized into three product layers:

1. native Windows client;
2. isolated WSL radio/protocol runtime;
3. hosted authoritative relay.

Room identity and radio role were separated. A room has stable `member_a`/`member_b` seats; each
connection attempt independently chooses which member creates the physical Switch room. This makes
role inversion user-friendly without changing tunnel identity.

The relay gained:

- two-seat authority persisted in SQLite;
- idempotent commands and ordered room events;
- ready/online/reconnect state;
- rotating hashed member/reconnect credentials;
- attempt creation, creator selection, role lock, phases, leave, close, and recovery;
- authenticated attempt-bound RFU WebSockets;
- public room directory capability;
- rate limits, health, metrics, container deployment, and an end-to-end hosting smoke.

The local control layer gained separate control, relay, radio, and session readiness, plus hardware
selection, diagnostics, room APIs, endpoint orchestration, structured logging, and redacted support
bundles.

## 7. August 25–26: native UI and distribution

The browser prototype was retired in favor of one self-contained WPF executable. The UI evolved into
a dark native client with stable left alignment, consistent control sizing, tab-based Settings,
server-authoritative public/private room flows, real device selection, recovery screens, party cards,
and accessible state announcements.

Installer work established:

- one guided native Setup interface with progress UI;
- hash-complete schema-2 package manifests;
- an isolated `SwitchTrade` distro and staged atomic runtime replacement;
- custom kernel placement outside Unicode-sensitive user paths;
- backup/rollback of the global WSL kernel configuration;
- reboot continuation without secret arguments;
- pinned `usbipd-win` prerequisite handling;
- Install, Update, Repair, Rollback, Uninstall, and Audit actions;
- control-first startup so the app and WSL service launch together;
- short user-facing completion/errors instead of raw PowerShell output.

The public relay was integrated at `https://relay.pangyostonefist.org`. Public browsing remains
capability-gated: the UI only enables it when the live relay reports the required contract.

Room leave/close was made idempotent and local teardown was separated from relay cleanup so a temporary
authority failure no longer misreports the already-completed local disconnect.

## 8. Distribution cleanup milestone

For the beta release, the repository surface was reduced to maintained runtime code and five public
documents. Retired web UI, duplicate design kits, VM backups, Pokémon outputs, cached agent material,
and other vestigial artifacts were removed. Raw captures and dated development notes are ignored and
do not enter the public tree or release package.

A persistent Credits entry was added to the native shell for Min W. Lim and the open-source projects
that provided the key technical foundation.

## 9. Important corrected assumptions

### “Channel 6 is the Switch channel”

False. Channel 6 was a convenient default, not a native guarantee. Rooms were observed on channels 1,
6, and 11 and can be recreated on a different channel.

### “The card did not hear the Switch”

Too broad. Known Switch-originated frames were received. Missing session traffic could be caused by
channel coverage, while a separate class of failures came from control-port/AP+monitor driver defects.

### “All data frames belong to the household router”

False. The capture included randomized client unicast. More importantly, router traffic in a
single-channel capture did not identify the Direct Connection data path.

### “Opening the RFU connection automatically implements every feature”

Only partly. Once a correct RFU stream is open, movement/input records travel without relay-side input
decoding. A new game feature can still have different setup blocks, commands, barriers, and teardown
that the local endpoint must implement or transparently preserve.

### “WSL removes driver defects”

False. WSL removed VMware USB ownership and made deployment controllable, but it still runs Linux
drivers. A custom kernel can add or patch a driver; it cannot make an incompatible hardware/driver
combination reliable without evidence.

## 10. Windows 10 compatibility branch

The original private-beta installer intentionally rejected every build below Windows 11 24H2. The
`win10support` work changed the technical baseline to Windows 10 22H2 x64 build 19045 while retaining
Windows 11 support. Host detection now rejects Server and ARM64 explicitly, distinguishes an old WSL
stub from current Microsoft Store WSL, can update WSL with prerequisite consent, and accepts firmware
virtualization before the optional Windows features have activated the hypervisor. Native projects
compile against the Windows 10 build 19041 SDK surface while Setup enforces build 19045.

These changes make a complete Windows 10 installation possible in code. Physical Windows 10
qualification remains required before it becomes a release claim.

## 11. Current state

The repository contains the complete beta client, local runtime, relay service, installer, hardware
policy, diagnostics, protocol implementation, and package tooling. The Direct Connection trade cycle
has passed a real PC-to-Switch completion gate. The remaining work outside the beta is maintained only
in [Future TODO](FUTURE_TODO.md).
