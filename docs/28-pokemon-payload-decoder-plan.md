# 28 — Pokémon payload extraction and trade-state decoder plan

**Branch:** `golden-capture-re`  
**Owner:** payload-analysis track  
**Protocol dependency:** the separate protocol-research agent owns LDN/Pia wire decoding.  
**Primary capture:** `logs/golden/discovery_20260824_081253/`

## Objective

Build a decoder that answers, from an authorized decrypted native session:

1. What trade phase is occurring?
2. Which player is offering, accepting, cancelling, or leaving?
3. Which Pokémon record is transmitted in each direction?
4. Which Gen III fields are actually present and verifiable in that record?
5. How complete and trustworthy is each decoded result when the radio capture has loss or hopping gaps?

The output must preserve raw evidence and provenance. It must never present an inferred field as if it were directly observed.

## Non-goals and evidence boundary

This system will not read Switch memory, reconstruct state that never crossed the link, or bypass console security. It will decode only bytes supplied by the protocol agent after authorized LDN decryption and network/RFU reassembly.

The current all-channel capture documents a real two-Switch trade flow and contains substantial direct encrypted traffic, but 0.4-second channel hopping creates gaps. It is suitable for locating and hypothesizing payloads. A fixed-channel repeat is required before claiming that a Pokémon record or a complete trade message is absent.

## Ownership boundary with the protocol agent

The payload track begins at a versioned intermediate stream. The protocol agent must provide both parsed metadata and the original decrypted bytes.

Minimum input record (`payload-stream.v1`):

```json
{
  "capture_id": "string",
  "room_id": "string",
  "timestamp_ns": 0,
  "src_mac": "aa:bb:cc:dd:ee:ff",
  "dst_mac": "aa:bb:cc:dd:ee:ff",
  "src_ip": "169.254.x.x",
  "dst_ip": "169.254.x.x",
  "direction": "host_to_peer|peer_to_host",
  "pia_packet_id": 0,
  "reliable_seq": 0,
  "flags": 0,
  "retransmit": false,
  "complete": true,
  "payload_hex": "...",
  "source_frames": [0]
}
```

`source_frames` is essential. A decoder that receives only concatenated bytes cannot explain whether a checksum failure is caused by a bad hypothesis or a missing RF frame.

## Decoder architecture

```text
protocol-agent payload-stream.v1
              │
              ▼
       Pia/Reliable record reader
              │
              ▼
      GBA frame boundary parser
       (0x57 C/A/K/T carriers)
              │
              ▼
       RFU LLSF + 14-byte slot parser
              │
       ┌──────┴─────────┐
       ▼                ▼
  game-state events   block assembler
                            │
                            ▼
                    Gen III candidate scanner
                            │
                            ▼
                    .ek3/.pk3 validator
                            │
             ┌──────────────┴──────────────┐
             ▼                             ▼
       Pokémon records                 trade timeline
             │                             │
             └──────────────┬──────────────┘
                            ▼
                  provenance-rich JSON report
```

## Work packages

### P0 — Freeze fixtures and input contract

- Keep both golden pcaps immutable and verify their SHA-256 hashes.
- Preserve the screen/timeline notes and the exact Switch MAC/BSSID roles.
- Store protocol-agent output as append-only JSONL with a schema version.
- Keep `prod.keys` and passphrases outside Git; record only a key-set fingerprint.
- Create negative fixtures from router bootstrap traffic and LDN pre-trade traffic.

**Deliverable:** reproducible input manifest and schema validator.

### P1 — Consume the protocol-agent stream without reimplementing LDN

- Validate direction, source/destination, packet IDs, retransmit markers, and completeness.
- Reject malformed records without discarding them; write a diagnostic reason.
- Group records by room instance, because the current capture contains a CH11 room followed by a new CH1 room with different random/session values.
- Track gaps, duplicate datagrams, and out-of-order delivery.

**Deliverable:** normalized session object with loss and completeness metrics.

### P2 — Parse the game transport carriers

Use the existing simulator structures as initial fixtures, not as proof that every native byte is identical.

- Parse the GBA carrier format `0x57 <type> <length:u16 LE> <body>`.
- Classify `C` connect, `A` accept, `K` acknowledgement, and `T` RFU-slot carriers.
- Treat the Reliable initialization/configuration payload separately; a leading `0x4A` is not automatically a `0x57` game frame.
- Record carrier timestamps, direction, Reliable sequence, and retransmission identity.

Relevant reference implementation: `_related/frlg-ldn-trade-emu/frlgsim/gbaframe.py`.

**Deliverable:** carrier-level JSON and byte-exact fixtures.

### P3 — Decode RFU slots and reassemble blocks

For each `T` carrier:

- Decode the LLSF state, ACK, phase, count, and payload size.
- Split parent UNI payloads into 14-byte command slots by multiplayer ID.
- Decode RFU command words, including:
  - `SEND_BLOCK_INIT` (`0x8800`)
  - `SEND_BLOCK` (`0x8900 | index`)
  - `SEND_BLOCK_REQ` (`0xA100`)
  - `SEND_PLAYER_IDS` (`0x7700`)
  - `SEND_HELD_KEYS` (`0xBE00`)
  - link close/disconnect commands
- Reassemble `SEND_BLOCK` fragments by owner, direction, block ID, and fragment index.
- Preserve incomplete blocks and missing indices instead of padding them silently.
- Record block requests and retransmissions so a repeated fragment is not mistaken for new data.

Relevant reference implementation: `_related/frlg-ldn-trade-emu/frlgsim/rfu.py` and `gbaframe.py`.

**Deliverable:** RFU command stream, block objects, and explicit completeness status.

### P4 — Detect and validate Gen III Pokémon candidates

The project already contains a Gen III parser in `tools/pk3-tool.py` and `frlgsim/mon.py`. The candidate detector will:

1. Search reassembled block payloads at every plausible offset, not only aligned offsets.
2. Test both 80-byte box and 100-byte party candidates.
3. Treat the wire form as encrypted/shuffled `.ek3` and attempt the PID-dependent substructure unshuffle/XOR.
4. Validate the 16-bit checksum over the decrypted 48-byte secure region.
5. Validate supporting plausibility constraints: species range, move IDs, language, character-map terminators, OT/name termination, level range, and party-tail consistency.
6. Preserve both the raw candidate bytes and canonical decrypted bytes.
7. Reject candidates that pass only weak heuristics.

The checksum oracle and encrypted/decrypted handling already exist in [tools/pk3-tool.py](../tools/pk3-tool.py). We will reuse it rather than create a second incompatible parser.

**Deliverable:** candidate records with checksum status, form (`.ek3`/`.pk3`), offset, source block, and confidence.

### P5 — Build the trade-state decoder

The state decoder consumes validated RFU commands and candidate records to produce events such as:

- room discovered/joined;
- Pia connection established;
- player IDs exchanged;
- trainer/link-player data exchanged;
- player seated/ready;
- party block requested/sent/received;
- partner Pokémon displayed/offered;
- offer accepted or cancelled;
- trade animation/commit;
- result saved/left.

State transitions must be tied to observed message bytes and timestamps. Screen markers are validation evidence, not a substitute for a wire event.

**Deliverable:** deterministic session state machine with “observed”, “inferred”, and “unknown” states.

### P6 — Differential payload mapping

Use controlled trades where only one known input changes:

- species;
- nickname;
- trainer name, TID, and SID;
- level and experience;
- held item;
- moves;
- EVs and IVs where controllable;
- sender/receiver direction;
- party slot.

Align the resulting canonical records and RFU blocks. Separate stable field bytes from counters, timestamps, random values, link tags, padding, and checksums. Repeat each condition at least twice.

**Deliverable:** a field map with confidence and the capture IDs that support every mapping.

### P7 — Cross-validation and false-positive control

- Decode the same Pokémon from independent radio captures.
- Compare both radios’ overlapping observations without double-counting them as separate transmissions.
- Replay protocol-agent streams through the decoder and require deterministic output.
- Run the candidate scanner against router traffic and pre-trade LDN traffic; it must not emit valid Pokémon records.
- Deliberately remove fragments and confirm the decoder reports incomplete rather than inventing a valid record.
- Compare extracted records against known `.pk3` files using checksum and field-level equality.

**Deliverable:** test suite and a report that distinguishes observed bytes, decoded fields, inferred events, and unresolved gaps.

### P8 — Production interface

Expose a small CLI/library API:

```text
payload-decode input.jsonl --manifest session.json --output report.json
payload-list-mons report.json
payload-timeline report.json
```

The output should include raw-byte references, not only a pretty summary. Keys are supplied through a secure runtime mechanism only if the protocol agent has not already produced decrypted input.

## Data we plan to obtain

### Session and transport data

- capture and room-instance IDs;
- host/peer MAC and IP roles;
- timestamps and duration of every phase;
- Pia packet IDs and Reliable sequence numbers;
- direction, retransmission, ACK, and gap statistics;
- RFU LLSF state, phase, multiplayer ID, command opcode, and rolling tag;
- block request type, owner, count, fragment index, and completeness;
- channel/radio source and confidence when available.

### Trade-state data

- room join and participant changes;
- player ID/link-player records;
- trainer-card/configuration exchange;
- seat and ready state;
- party synchronization requests and responses;
- offered slot and partner slot;
- offer/accept/cancel transitions;
- trade animation/commit and exit result;
- per-event timestamps and source message references.

### Pokémon data, if transmitted and validated

For every checksum-valid candidate:

- raw wire bytes and canonical bytes;
- `.ek3` versus `.pk3` form;
- PID and nature;
- TID, SID, and OT ID;
- nickname, OT name, language;
- species ID and species name;
- held item;
- experience and level;
- four moves;
- six EV values;
- six IV values;
- party stats where a valid party tail is present;
- checksum and validation status;
- source direction, block/fragment offsets, timestamp range, and completeness.

IVs, EVs, party stats, or any other field remain `not_observed` unless the decoded bytes and independent validation prove that the native session transmitted them.

## Required data and experiments

To complete this work we need:

1. The protocol agent’s decrypted `payload-stream.v1` output for the existing all-channel capture.
2. A fixed-channel repeat of the same two-Switch trade, preferably with both radios recording simultaneously.
3. Exact known `.pk3`/party inputs for each Switch, or a controlled record of the Pokémon offered.
4. A synchronized screen recording and human markers for chair, offer, accept, completion, and exit.
5. At least two differential trades with one Pokémon field changed at a time.
6. A no-trade and router-traffic negative capture.
7. The emulator’s existing JSONL/RFU fixtures for regression comparison.

The current all-channel capture remains valuable as the first native source: it establishes direct protected traffic, real participant roles, and the time window in which the payload decoder should look. It is not sufficient by itself to prove that a missing Pokémon field was not transmitted.

## Acceptance criteria

The payload decoder is considered validated only when:

- it consumes protocol-agent output without needing ad-hoc manual offsets;
- it reconstructs RFU blocks while reporting gaps and retries;
- it extracts a known native Pokémon candidate;
- the candidate passes the Gen III checksum after wire-form decoding;
- species, identity, and at least one additional field match the known input;
- the same logic succeeds on an independent capture;
- trade-state events align with the screen timeline;
- incomplete or unrelated traffic produces no false valid Pokémon;
- every output field has provenance and an observed/inferred/unknown status.

## Immediate implementation order

1. Agree on and validate `payload-stream.v1` with the protocol agent.
2. Implement carrier and RFU-slot parsing using existing simulator fixtures.
3. Implement block reassembly with explicit completeness tracking.
4. Integrate `pk3-tool.py` as the sole Gen III validation oracle.
5. Run the decoder on the existing native capture and report candidate/coverage results.
6. Capture the fixed-channel repeat and perform differential mapping.
7. Add the trade-state report and production CLI only after payload validation.
