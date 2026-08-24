# 27 — Native two-Switch golden-capture reverse-engineering plan

**Branch:** `golden-capture-re`
**Date:** 2026-08-24
**Primary evidence:** `logs/golden/discovery_20260824_081253/`
**Interpretation source:** [docs/25-goldencapture-2차-WSL-결과.md](25-goldencapture-2차-WSL-결과.md)

## Correction to the first branch analysis

The first draft of this plan analyzed the wrong artifact: `pc_host_20260824_085514/` is a later PC-host join-gate test. It is retained as a control capture, but it is not the native two-Switch session requested here.

The correct golden set is:

```text
logs/golden/discovery_20260824_081253/
  rtl8192eu_allch.pcap
  rtl8188eu_allch.pcap
  README.md
  SHA256SUMS.txt
```

This capture documents the user flow: two actual Switches entered the room, approached the trade chair, exchanged one Pokémon, ended, and left. It is therefore the correct evidence for native Switch-to-Switch LDN traffic. However, both radios hopped channels every 0.4 seconds, so it is a discovery/coverage gold, not a lossless fixed-channel replay gold. It can support protocol hypotheses and partial decoding; a fixed-channel repeat is still required before claiming complete game-payload recovery.

## Integrity and independent inventory

The recorded hashes match the files on disk:

```text
9cc0bcf18a09f0620e63e05849d8b9c7135150b7ac421510ce3e78d48d4eb712  rtl8192eu_allch.pcap
677f5535680754222393df19a9dd2ccB823C5582BAC0A8D0BB8365290B562EC4  rtl8188eu_allch.pcap
```

The second hash is shown in the capture document with mixed case; hash comparison is case-insensitive. The local `Get-FileHash` result matches it.

Independent pcap/radiotap inventory and WSL `tcpdump` verification found:

| Capture | Records | Size | Duration | Kernel drops |
|---|---:|---:|---:|---:|
| RTL8192EU | 13,341 | 2,506,764 bytes | ~254.9 s | 0 |
| RTL8188EU | 7,061 | 1,581,242 bytes | ~254.9 s | 0 |

The captures contain all 2.4 GHz frequencies used by the 1–13 hopper. The LDN room was observed first on channel 11 and then in a new room instance on channel 1.

## What the capture proves

### It is direct Switch-to-Switch LDN, not router traffic

The LDN identities are:

- Switch A / LDN host BSSID: `a4:c1:e8:66:73:25`
- Switch B / LDN participant: `98:41:5c:79:41:38`
- LDN IPs: `169.254.120.1` and `169.254.120.2`
- Comm ID: `0x01006fa0233f8000`
- Scene ID: `22287`
- Protocol: 3
- LDN version: 4
- Application version: 88 (`0x58`)
- Security mode / accept policy: `1 / 0`
- Maximum participants: 6

The TP-Link BSSID `68:ff:7b:ef:67:e8` appears in the capture, but its authentication/EAPOL/protected data are boot/license traffic. It is not the BSSID or transmitter/receiver for the direct LDN exchange.

### Direct encrypted traffic is present on both cards

The RTL8192EU capture contains:

- 1,622 protected data frames: Switch B → Switch A
- 1,539 protected data frames: Switch A → Switch B
- 183 host-local broadcasts
- 171 peer broadcasts
- 280 Nintendo vendor-action advertisements
- 271 LDN beacons

The RTL8188EU independently contains:

- 316 protected frames: Switch A → Switch B
- 307 protected frames: Switch B → Switch A
- 62 Nintendo vendor-action advertisements
- 69 LDN beacons

This is strong evidence that both cards received real LDN traffic and that the 8188EU was not receive-dead during the experiment. The counts must not be compared as a receive-rate benchmark because both cards were hopping and were not listening to the same channel at the same instants.

### The advertisements are already partly decoded

The capture document reports successful decryption with `ldn 0.0.17` and the verified `prod.keys`. The first CH11 advertisement and the later CH1 advertisement have different SSID, server-random, challenge, and RFU session ID values. The safer interpretation is two consecutive LDN room instances, not one room simply moving channels.

The initial 122-byte `application_data` matches the current RFU beacon encoder byte-for-byte. After the peer joins, the participant count changes from 1 to 2 and the RFU partner word changes from `0x1584` to `0x9584`.

## What can be reverse engineered from this capture

High-confidence targets:

1. LDN advertisement format, encryption mode, timing, channel selection, and room identity.
2. Standard 802.11 authentication/association sequence.
3. Protocol-3 custom authentication and protected data-frame direction.
4. Participant-count and partner-word state transitions.
5. CCMP packet-number, sequence-number, retry, and loss behavior.
6. The existence and rough timing of RFU/game traffic after the direct LDN link forms.

Conditional targets:

- Pia/RFU message boundaries.
- Link-state and trainer-card messages.
- Trade-state transitions.
- Pokémon record bytes or a complete `.pk3`.

The conditional items cannot be asserted from ciphertext counts alone. They require decryption, reassembly, and validation against known game inputs. Hopping creates gaps, so a missing byte may be a capture gap rather than an absent protocol field.

## Key and crypto boundary

The existing LDN implementation already contains the relevant primitives:

- `ldn.wlan.DataFrame.decrypt()` performs AES-CCM/CCMP data-frame decryption.
- `KeyDerivation.derive_data_key(server_random, password)` derives the LDN data key.
- The advertisement/authentication paths implement protocol-3 AES-GCM handling.
- The runtime converts decrypted SNAP data to TAP.

The new work is an offline capture adapter and robust reassembler, not a new crypto scheme. The analyzer must use the authorized verified `prod.keys` and the known GBA application passphrase without committing either to Git. `server_random` is present in the advertisement, but it is not by itself a guarantee that every required session parameter is available to a passive observer.

## Staged reverse-engineering plan

### Stage 0 — Preserve evidence (complete)

- Treat both pcaps and their hashes as immutable.
- Keep the README, tcpdump logs, health-gate result, and screen/timeline notes beside the capture.
- Preserve `pc_host_20260824_085514/` as a separate PC-host control set, not as native-trade evidence.

**Exit criterion:** hashes match and the capture manifest is reproducible.

### Stage 1 — Build a deterministic pcap/radiotap inventory (next)

Create a read-only analyzer that emits JSON/CSV and never rewrites the source pcap. It must:

- parse classic pcap and radiotap headers;
- retain timestamp, actual reported frequency, RSSI, RX flags, and FCS indicators;
- decode 802.11 management/data headers, ToDS/FromDS, QoS, retry, sequence, and fragment fields;
- identify Nintendo vendor actions and LDN BSSID/peer MACs;
- classify router bootstrap traffic separately;
- emit a channel-hop timeline and a per-direction packet-loss estimate.

**Exit criterion:** the analyzer reproduces the file counts and the direct-frame counts above and generates the two-room timeline.

### Stage 2 — Decrypt and validate the LDN layer

Reuse the checked-in LDN implementation rather than duplicating its formulas:

1. Extract protocol, security mode, SSID, `server_random`, challenge, and application data from each room instance.
2. Select the correct passphrase/session parameters for the native GBA application.
3. Reconstruct each captured `DataFrame`, including source MAC, protected bit, CCMP header, packet number, and AAD.
4. Verify the AES-CCM tag and record failures by packet, direction, channel, and radio.
5. Dedupe retries using sequence/fragment and CCMP PN without hiding duplicate evidence.
6. Export decrypted SNAP/Ethernet payloads plus a sidecar describing gaps.

**Exit criterion:** advertisement/authentication decryption is reproducible and the protected direct frames produce valid plaintext for both directions. A decryption failure must distinguish wrong key/parameters from a missed hopped-channel frame.

### Stage 3 — Reassemble network and Pia/RFU streams

For each room instance:

- reassemble 802.11 fragments and retries;
- recover Ethernet/SNAP and 169.254.x.x IP traffic;
- reassemble UDP datagrams by direction and timestamp;
- identify Pia packet IDs, session IDs, retransmissions, and reliable-channel boundaries;
- compare recovered messages with `_related/frlg-ldn-trade-emu/frlgsim/pia_connect.py`, `rfu.py`, `reliable.py`, and `trade.py` as hypotheses only.

The all-channel capture should be used to locate messages and state transitions, not to prove byte-complete payloads. Any message whose sequence is interrupted by hopping must be marked incomplete.

**Exit criterion:** a timeline shows LDN authentication, Pia/RFU establishment, link-player/trainer-card activity, trade-room entry, and the trade attempt, with an explicit completeness score for each stream.

### Stage 4 — Extract and validate Pokémon data

Only after Stage 3:

1. Search decrypted messages for stable record lengths, checksums, and known Gen III markers.
2. Compare candidate records against known input `.pk3` files.
3. Validate with `tools/pk3-tool.py` and independent checksum/structure checks.
4. Record exactly which fields are observed, inferred, or absent.

Do not claim IV/EV, trainer identity, or full `.pk3` recovery merely because the trade completed. Those fields are recoverable only if the native wire payload contains them and the capture contains every required fragment.

**Exit criterion:** at least one known native trade Pokémon is recovered and validates on a second capture.

### Stage 5 — Differential mapping

Repeat a fixed-channel trade while changing one input at a time:

- species;
- level/experience;
- held item;
- nickname and trainer name;
- moves;
- IV/EV values where controllable;
- trade direction and sender/receiver.

Align decrypted messages and separate field bytes from counters, random values, padding, and checksums. Use at least two repeats per condition.

**Exit criterion:** a field map predicts bytes in a new capture that was not used to form the hypothesis.

### Stage 6 — Produce the real replay-grade gold

Repeat the same two-Switch trade with:

1. Discovery hopping on Radio A only.
2. Immediate fixed-channel lock on Radio B after the LDN advertisement identifies the active channel.
3. Both radios fixed to that channel whenever possible.
4. Capture beginning before the join and ending after leave.
5. Screen recording and explicit markers for room creation, join, chair, offer, accept, completion, and exit.
6. A known Pokémon and a second repeated trade.

This removes the primary ambiguity in the current set: whether a missing message was never sent or was missed during a 0.4-second hop.

### Stage 7 — Production observer

After validation, separate passive analysis from relay/injection and add:

- radio health gate and channel lock verification;
- PN/sequence/drop diagnostics;
- secure key/passphrase injection;
- immutable pcap retention and structured export;
- “observed” versus “inferred” labels for every game field;
- redaction controls for MACs and Pokémon identity.

## Acceptance criteria for a complete game-layer golden capture

- Both real Switch MACs and the active LDN BSSID are identified.
- The capture contains LDN advertisement, authentication, association, and direct protected data.
- Decryption succeeds in both directions with authorized parameters.
- Pia/RFU packets exist in both directions and are reassembled without unexplained gaps.
- The screen timeline proves trade-room entry, offer, accept, completion, and exit.
- The exact Pokémon inputs are recorded.
- A second capture reproduces the decoded structure.

## Current decision

Use `rtl8192eu_allch.pcap` as the primary reverse-engineering source and `rtl8188eu_allch.pcap` as an independent RX corroboration/control. Proceed immediately with Stages 1–3. Treat Stage 6 as the next required experiment before making claims about complete trade-payload or internal game-state extraction.
