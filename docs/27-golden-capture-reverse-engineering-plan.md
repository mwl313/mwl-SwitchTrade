# 27 — Golden-capture reverse-engineering plan

**Branch:** `golden-capture-re`  
**Date:** 2026-08-24  
**Scope:** offline analysis of the newest tracked native-radio capture and the follow-up capture required for FRLG trade-payload reverse engineering.

## Executive finding

The newest tracked artifact is a strong **LDN discovery/join-gate capture**, but it is not yet a completed Switch-to-Switch trade capture.

The repository's capture README and [docs/26](26-pc-host-discovery-join-gate-20260824.md) report five successful room discoveries and joins, followed by the Switch leaving after the Pia timeout. The PC host was still running the joiner/right-seat state machine, so no Pia datagram was emitted. This means the capture is excellent for reverse engineering the wireless/LDN layer, but it cannot yet reveal FRLG trade messages or a Pokémon payload.

This distinction is a release gate: we must not claim `.pk3`, IV/EV, or full game-state extraction from this capture.

## Artifact inventory and integrity

The capture set is under `logs/golden/pc_host_20260824_085514/`:

| Artifact | Size | Role | Integrity |
|---|---:|---|---|
| `observer_startup.pcap` | 118,759 bytes | pre-session RF baseline | SHA-256 recorded in `SHA256SUMS.txt` |
| `observer_session.pcap` | 1,359,767 bytes | external RTL8188EU observer | SHA-256 recorded in `SHA256SUMS.txt` |
| `host_pia.jsonl` | 173 bytes | host-side Pia telemetry | SHA-256 recorded in `SHA256SUMS.txt` |
| `README.md` | 583 bytes | capture conditions and result | SHA-256 recorded in `SHA256SUMS.txt` |

The pcap files are classic little-endian pcap with link type `IEEE802_11_RADIO` (radiotap), 262,144-byte snapshot length. The session capture contains 5,325 records over approximately 144.8 seconds, all observed on 2.4 GHz channel 6 / 2437 MHz. The capture was independently checked with the WSL `tcpdump` reader and a standard-library pcap/radiotap inventory; no files were modified.

## What is actually in `observer_session.pcap`

Initial inventory:

| Observation | Count/evidence | Interpretation |
|---|---:|---|
| Nintendo vendor action frames | 1,098 | periodic LDN advertisements from PC host |
| Vendor-action prefix | `7f0022aa04000101` | consistent Nintendo LDN action format |
| Open authentication frames | 10 | repeated Switch join attempts |
| Association requests | 6 | standard 802.11 join path is visible |
| Association responses | 6 | host accepted the station |
| Data frames | 123 | LDN and unrelated local RF data are mixed |
| Protected data frames | 52 | CCMP-protected frames are present |
| Participant transitions | `1/6 -> 2/6 -> 1/6`, repeated | Switch joined, then timed out and left |
| Pia packets in `host_pia.jsonl` | 0 | only one session-metadata record; no UDP handshake |

The documented identities and session fields are:

- PC LDN host/BSSID: `a0:47:d7:b0:2b:39`
- Switch station: `98:41:5c:79:41:38`
- LDN protocol: 3
- Application version: 88
- Channel: 6
- Comm ID: `0x01006fa0233f8000`
- Scene ID: `22287`
- Security/accept fields: `1 / 0`
- Application data: 122 bytes

The capture also contains ordinary router traffic and neighboring stations. Analysis must scope by the LDN BSSID and participant MACs before interpreting protected data.

## What this capture can answer now

High-confidence targets:

1. Exact LDN advertisement layout and periodicity.
2. Protocol-3 version, security mode, channel, comm ID, scene ID, and application-data bytes.
3. Standard authentication/association ordering and retry behavior.
4. Participant-table transitions and join timeout timing.
5. LDN CCMP packet-number behavior and the direction of host/station data frames.
6. Decrypted LDN custom-auth and ARP payloads, subject to the authorized session parameters.

Not answerable from this artifact:

- Pia handshake message semantics.
- RFU link-state or trade-room messages.
- A native FRLG `.pk3` payload.
- Which Pokémon fields are transmitted during a completed trade.
- Arbitrary in-game memory or state that never crosses the wireless link.

## Important crypto boundary

The existing LDN source already contains the relevant protocol primitives:

- `ldn.wlan.DataFrame.decrypt()` performs the AES-CCM/CCMP data-frame operation.
- `KeyDerivation.derive_data_key(server_random, password)` derives the LDN data key.
- `APNetwork._process_data_frame()` decrypts a frame and converts SNAP data to TAP.

Therefore, the missing work is primarily an **offline capture adapter and reassembler**, not a new cryptographic design. `server_random` can be read from the LDN advertisement, but `prod.keys` plus `server_random` are not automatically sufficient if the session password is unknown. The passphrase/session parameters must be recorded from an authorized controlled endpoint; keys must remain outside Git.

## Staged reverse-engineering plan

### Stage 0 — Freeze and verify the evidence (complete)

- Keep the original pcap bytes immutable.
- Verify every file against `SHA256SUMS.txt`.
- Record capture role, card chipset, driver, channel, BSSID, Switch MAC, protocol version, and screen timeline.
- Keep the startup pcap as a negative/control fixture.

**Exit criterion:** hashes match and the capture manifest is complete.

### Stage 1 — Build a deterministic pcap/radiotap inventory (next)

Implement a read-only analyzer that emits JSON/CSV rather than changing the original capture. It must:

- parse classic pcap and radiotap headers;
- preserve timestamp, channel, RSSI, antenna, RX flags, and FCS indicators;
- decode 802.11 management/data headers, ToDS/FromDS, QoS, retry, and protection bits;
- identify LDN vendor actions by OUI/type/prefix;
- extract source, destination, BSSID, sequence number, fragment number, and CCMP PN;
- separate the LDN BSSID from SK router and neighbor BSS traffic.

**Exit criterion:** the analyzer reproduces the counts above and produces a timestamped five-attempt join timeline.

### Stage 2 — Offline LDN decryption and link-layer validation

Reuse the checked-in LDN parser instead of duplicating its cryptographic formulas:

1. Extract `server_random`, security mode, protocol, network identity, and the configured password/session parameters.
2. Derive the LDN data key without writing key material to the repository.
3. Reconstruct `DataFrame` objects with the original source MAC, protected bit, CCMP header, and AAD.
4. Verify the AES-CCM tag for every candidate LDN protected frame.
5. Reject duplicates/retries correctly and report missing PN ranges.
6. Emit decrypted SNAP/Ethernet payloads and an analysis pcap/JSON sidecar.

**Exit criterion:** all decryptable LDN frames pass authentication, and at least the documented custom-auth/ARP payloads decode consistently in both directions.

### Stage 3 — LDN control/session fixtures

Create byte-exact fixtures from this capture for:

- vendor action advertisement;
- probe/auth/association;
- protocol-3 custom authentication request/response;
- participant join and leave transitions;
- timeout and retry sequences.

Compare each fixture with `_related/LDN/ldn/__init__.py` and the current host implementation. The goal is to make the capture a regression test for the already-passed discovery/join gate.

**Exit criterion:** a fresh decoder can classify every LDN event in all five attempts and explain the timeout without relying on log text.

### Stage 4 — Obtain the missing game-layer capture (blocking)

This is the current blocker. A completed trade capture must contain:

- a native Switch host or a PC host with the host-side Pia state machine fixed;
- LDN join completion;
- bidirectional Pia UDP records;
- RFU handshake, link-player exchange, trainer-card exchange, trade-room entry, offer/accept, and completion;
- known Pokémon inputs and a synchronized screen recording.

The next PC-host run should implement the documented host role: participant 0/leader, initiate Net `0x11`, process `0x12`, accept the joiner session, and only then enter the RFU/game flow. Alternatively, capture two actual Switches trading locally. Do not call the current artifact a trade payload capture until Pia packets exist.

**Exit criterion:** both directions show nonzero Pia traffic and the capture reaches a verified trade-complete screen.

### Stage 5 — Pia/RFU and trade-payload decoding

Once Stage 4 exists:

1. Decode UDP framing, session IDs, packet IDs, retransmissions, and direction.
2. Reuse the simulator structures in `_related/frlg-ldn-trade-emu/frlgsim/` as hypotheses, not as proof of native wire layout.
3. Align RFU messages with screen timestamps and known state transitions.
4. Search for recognizable Gen III record boundaries, lengths, checksums, and repeated fields.
5. Extract candidate `.pk3` records and validate them with `tools/pk3-tool.py` and independent checksums.

**Exit criterion:** a known test Pokémon is recovered from a native capture and validates byte-for-byte or field-for-field against the known input.

### Stage 6 — Differential mapping and generalization

Repeat the completed trade with exactly one controlled change at a time:

- species;
- level/experience;
- held item;
- nickname/trainer name;
- moves;
- IV/EV values where controllable;
- sender/receiver and trade direction.

Use aligned decrypted messages to map fields. Only fields that change in the transmitted payload may be claimed as recoverable. Repeat each case to distinguish data from counters, random values, padding, and checksums.

**Exit criterion:** field mappings reproduce new captures that were not used to create the hypothesis.

### Stage 7 — Production-grade observer (after validation)

Separate the passive observer from the relay path. Add:

- health-gate and channel verification;
- loss/duplicate/PN diagnostics;
- secure key injection from a file descriptor or environment, never Git;
- pcap preservation plus structured JSON export;
- redaction options for MACs and Pokémon identity;
- a clear “wire-observed” versus “inferred” status for every field.

## Acceptance criteria for the next true golden trade capture

The capture is ready for game-layer reverse engineering only when all of these are true:

- raw radiotap pcap is preserved and hash recorded;
- the actual LDN channel is known and fixed for the session;
- both Switch MACs and the host/BSSID are recorded;
- LDN advertisement, auth, association, and protected data are present;
- decryption succeeds for the LDN frames with authorized session parameters;
- Pia UDP traffic exists in both directions;
- the screen timeline proves join, trade-room, offer, accept, and completion;
- the exact Pokémon inputs are known;
- at least one repeated capture produces the same decoded structure.

## Current decision

Proceed with Stages 1–3 using `observer_session.pcap`. Treat Stage 4 as the explicit blocker for Pokémon/game-state reverse engineering. The branch deliberately contains a plan and evidence boundary first; decoder implementation should begin only after the plan's fixtures and the missing completed-trade capture are available.
