# 33 — Pokémon payload branch and protocol handoff audit (2026-08-24)

## Branch separation

This payload track is now isolated on the local branch `pokemon-payload-re`.
It was created from `golden-capture-re` at commit `4807402` so the protocol
findings and the payload decoder foundation are available as a reproducible
baseline. Future commits on `golden-capture-re` do not automatically enter this
branch.

The emulator is a separate Git repository under `_related/frlg-ldn-trade-emu`.
Its protocol branch is `gptsolreview` at `4478ec9`. That repository and branch
remain independent of this payload branch.

The payload decoder owns the downstream boundary:

```text
802.11/CCMP -> Pia -> Reliable -> GBA/RFU -> block reassembly -> Gen III mon
```

The protocol track owns the first three layers and the live PC-host parent
handshake. Neither branch should silently replace the other layer.

## What the protocol work supplies

The current protocol handoff is enough to define and implement the downstream
decoder interface:

- native room identity, channel, station IDs, LDN protocol 3, application
  version 88, and the session-specific SSID inputs;
- verified Pia AES-GCM framing, compression threshold, station footer, and
  variable-ID addressing;
- Reliable message tiling and the 8-byte Reliable header, including sequence,
  ACK/window, flags, and duplicate/retransmit behavior;
- GBA `0x57` frame layout and the child/parent `T` carrier distinction;
- RFU/LLSF command meanings already represented in the emulator (`SEND_BLOCK_INIT`,
  `SEND_BLOCK`, `SEND_BLOCK_REQ`, held-key/control commands, and 14-byte slots);
- exact native opening bytes (`INIT -> ACK -> WC -> WA -> ACK`) and a guarded
  host/parent bootstrap implementation.

These facts are sufficient for the parser and reassembler in
`tools/payload_decoder.py` to consume a future `payload-stream.v1` file and to
validate candidate `.pk3`/`.ek3` records without depending on the live host
engine.

## What is still missing for full Pokémon decoding

The handoff is not yet a full payload-decoding input. Specifically, the current
main repository contains no committed `payload-stream.v1` JSONL, no decrypted
native RFU block export, and no pcap-to-Pia-to-RFU adapter that preserves source
frame IDs and direction. The protocol commits are documentation and emulator
behavior; they do not hand the payload branch the bytes that must be decoded.

The evidence has three different scopes and must not be conflated:

| Evidence | What it proves | Payload status |
|---|---|---|
| `logs/golden/discovery_20260824_081253/` | Two Switches exchanged LDN traffic; all-channel discovery found CH1/CH11 and both radios received it | Hopping gaps prevent lossless stream reconstruction by itself |
| `logs/golden/native_fixed_handshake_20260824_live/` | Fixed-channel native room creation, join, trading-room entry, idle period, and graceful exit; 18,252 Pia datagrams were reportedly decrypted with zero auth failures | Strong protocol gold, but the handoff documents no completed Pokémon offer/confirm and no exported RFU blocks |
| `logs/golden/pc_host_ccmp_fix_live_20260824_144343/pc_host_pia.jsonl` | PC-host ARP/Pia boundary and Reliable `INIT/WC` retransmission behavior | Control capture only; it contains no native Pokémon trade payload |

The fixed-channel capture therefore answers “how do the Switches establish and
carry the LDN/RFU session?” It does not, as currently documented, answer “which
Pokémon bytes crossed the link?” A full decode claim requires a fixed-channel
run with an explicit one-Pokémon offer, confirmation, transfer, and a clean
end marker, plus a decrypted/reassembled export from that run.

## Is the other agent's work sufficient right now?

**For parser development: yes.** The protocol work gives enough wire semantics
to finish the payload-side parser, define validation rules, and test against
synthetic or emulator-generated RFU blocks.

**For decoding a real Pokémon from the native capture: no.** We still need all
of the following from the protocol side (or an equivalent offline extractor):

1. decrypt every relevant Pia datagram from the fixed-channel trade run;
2. decompress and tile every Reliable message while retaining direction,
   timestamp, sequence, and source 802.11 frame references;
3. extract each complete GBA `0x57`/RFU carrier and preserve its LLSF slot;
4. emit `SEND_BLOCK_INIT` plus every `SEND_BLOCK` fragment and mark missing or
   duplicate fragments explicitly;
5. identify which reassembled block is the Pokémon transfer and provide the
   expected offered species/slot as ground truth for validation.

The live host parent `T`/NI implementation is needed to make the PC a trading
participant, but it is **not** a prerequisite for passive decoding once a
lossless native trade stream is available. Conversely, a complete protocol
handshake without RFU block bytes cannot produce a Pokémon payload.

## Current payload-branch readiness

Already present:

- schema validation for `payload-stream.v1` records;
- GBA carrier and child/parent RFU slot parsing;
- block fragment reassembly that never labels an incomplete block complete;
- Gen III 80-byte box / 100-byte party candidate scanning;
- checksum, species, language, and character-map plausibility checks;
- regression fixtures and standard-library tests.

The scanner intentionally rejects raw pcap-sized input. This is a safety gate:
raw encrypted captures must first pass through the protocol extractor rather
than being mistaken for Pokémon bytes.

## Next required handoff artifact

The protocol agent should provide one ignored/local artifact (it need not commit
secrets or raw pcaps) with this minimum record shape:

```json
{"schema":"payload-stream.v1","capture_id":"native-trade-...",
 "timestamp_ns":0,"direction":"peer_to_host","payload_hex":"...",
 "source_frames":[1264],"complete":true,"room_id":"...",
 "reliable_seq":65520,"rfu_state":"..."}
```

The stream must be generated from the fixed-channel native trade capture, not
from the PC-host bootstrap control run. Once present, this branch can run the
RFU block assembler and Pokémon candidate scanner and report exact species,
slot, checksum, and confidence results.

## Audit conclusion

The branch separation is complete and the ownership boundary is clear. The
protocol agent's work removes the cryptographic and framing unknowns, but it
has not yet delivered the lossless, source-mapped RFU/Pokémon byte stream
required for full decoding. The next dependency is therefore a data-extraction
handoff (or a fixed-channel trade capture plus extractor), not another change to
the Gen III parser.
