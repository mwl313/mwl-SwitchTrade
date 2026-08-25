# 29 — Payload-track independent progress

**Branch:** `golden-capture-re`  
**Date:** 2026-08-24

This progress is deliberately independent of the other agent's raw-radio and LDN/Pia reverse engineering. It implements the downstream handoff and Pokémon-analysis layers so they can consume the protocol agent's output as soon as it is committed.

## Implemented

### Versioned payload handoff

`tools/payload_decoder.py` defines and validates `payload-stream.v1` records. It preserves:

- capture and room identity;
- nanosecond timestamp;
- direction and MAC/IP roles;
- Pia/Reliable IDs;
- retransmission and completeness flags;
- raw decrypted payload bytes;
- source pcap frame references.

Malformed records fail with a line-numbered schema error. Unknown fields are retained for forward compatibility.

### GBA/RFU parsing

The module independently parses:

- `0x57` GBA carriers (`C`, `A`, `K`, and `T`);
- parent and child LLSF headers;
- parent multiplayer-ID command slots;
- 14-byte RFU commands;
- block initialization, fragments, requests, player IDs, held keys, and link-close commands.

### Block reassembly

`RfuBlockAssembler` groups `SEND_BLOCK_INIT`/`SEND_BLOCK` sequences by direction, records fragment indexes and source offsets, reports missing fragments, and never marks a partial block complete.

### Gen III candidate validation

`scan_pokemon_candidates()`:

- checks 80-byte box and 100-byte party candidates;
- supports canonical `.pk3` and encrypted/shuffled `.ek3` wire form;
- reuses the existing `tools/pk3-tool.py` checksum/decryption oracle;
- validates the species ID and secure-region checksum;
- returns raw bytes, canonical bytes, decoded fields, and provenance;
- rejects incomplete or raw-capture-sized inputs instead of treating a pcap as a game payload.

## Verification

The standard-library test suite currently passes **13 tests**:

- payload schema round-trip and malformed-record rejection;
- JSONL line-number diagnostics;
- GBA carrier truncation and unexpected-prefix handling;
- parent RFU slot/command decoding;
- complete and incomplete block reassembly;
- canonical Salamence `.pk3` detection;
- encrypted `.ek3` detection;
- zero/truncated/oversized-input negative cases.

The existing tracked `archive/pokemon/fixtures/0373_SALAMENCE.pk3` fixture validates to species SALAMENCE, checksum OK, and the expected IV values. Raw golden pcaps are intentionally rejected by the candidate scanner until the protocol agent supplies decrypted/reassembled payload blocks.

## What remains blocked on the protocol handoff

- LDN CCMP decryption and key/session handling;
- Pia/Reliable datagram reconstruction from raw 802.11;
- native RFU payload extraction from the two-Switch pcap;
- confirmation that the current capture contains a complete Pokémon block despite channel hopping;
- native trade-state semantics and field mapping.

## Next action when the protocol agent commits

1. Validate its output against `PayloadRecord.from_dict()`.
2. Run carrier parsing and RFU block reassembly on the existing all-channel capture.
3. Report complete/incomplete blocks and candidate Pokémon records.
4. Compare any candidate against the known Switch-side Pokémon fixture.
5. Use a fixed-channel repeat and one-field differential trades to map fields and validate trade events.
