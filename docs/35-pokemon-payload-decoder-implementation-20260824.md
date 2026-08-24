# 35 — Pokémon payload decoder implementation and reproducible run (2026-08-24)

## Scope completed

The payload track now has a reusable offline path for the protocol agent's
encrypted Pia JSONL captures:

```text
Pia JSONL -> AES-GCM/decompression -> Pia Reliable -> GBA 0x57/T
-> parent/child RFU LLSF -> RFU block reassembly -> Gen III scanner
```

Implemented files:

- `tools/extract_pokemon_payload.py` — command-line extractor. It reuses the
  emulator repository's verified Pia/Reliable implementation and emits only
  decoded metadata; it never writes keys or raw payload bytes to the report.
- `tools/payload_decoder.py` — duplicate RFU INITs are idempotent, parent UNI
  rows keep independent block state, invalid fragment indices are reported, and
  incomplete blocks are never marked complete.
- `tests/test_payload_decoder.py` — 16 standard-library regression tests,
  including duplicate INITs, interleaved parent rows, and invalid fragments.

## Reproducible command

Run in the emulator virtual environment because Pia AES-GCM and zstandard are
installed there:

```text
wsl -d Ubuntu -- bash -lc \
  "cd /mnt/c/Users/임민우/Desktop/switchtrade/_related/frlg-ldn-trade-emu && \
   .venv/bin/python /mnt/c/Users/임민우/Desktop/switchtrade/tools/extract_pokemon_payload.py \
   /mnt/c/Users/임민우/Desktop/switchtrade/logs/golden/pc_host_parent_party_pulls_live_20260824_183308/pc_host_pia.jsonl \
   -o /mnt/c/Users/임민우/Desktop/switchtrade/logs/golden/pc_host_parent_party_pulls_live_20260824_183308/pokemon_payload_report.json"
```

The report is local/ignored. It contains block metadata and decoded Pokémon
fields, not raw RFU or Pokémon hex.

## Validation result

Against `pc_host_parent_party_pulls_live_20260824_183308/`:

```text
Pia datagrams                 4,567
Pia authentication failures   0
Reliable messages              8,506
GBA T carriers                 5,194
complete RFU blocks            21
```

The report contains complete, checksum-valid Gen III records for:

| Direction / row | Pokémon | Level | Meaning |
|---|---|---:|---|
| host → peer / row 0 | SALAMENCE (two party records) | 100 | PC host's configured party |
| peer → host | BULBASAUR | 6 | Switch party payload |
| peer → host | RATTATA | 3 | Switch party payload |
| host → peer / reflected row 1 | BULBASAUR, RATTATA | 6, 3 | RFU reflection of the Switch data |

Each record exposes the normal Gen III fields: species, nickname, PID, trainer
IDs, language, OT name, held item, experience, moves, EVs, IVs, nature, stats,
and checksum status.

One terminal `host_to_peer` control block is incomplete because the live run was
stopped at the party-selection boundary. This is reported as an issue with its
last source sequence; no Pokémon candidate from it is accepted as complete.

## What this proves

The project can now decode concrete Pokémon data from a real Switch RFU stream,
not merely identify Pokémon names or count packets. The Gen III wire form
(`.ek3`) and canonical form (`.pk3`) are both supported by the existing scanner.

## Deliberately deferred boundary

The capture ends after the party-selection menu opens. It does not contain the
user's selected slot, player-zero `SET_MONS_TO_TRADE`, `START_TRADE`,
`CONFIRM_FINISH_TRADE`, or a received Pokémon after the save/commit sequence.

The next capture must use known Pokémon on both consoles and continue through:

```text
select slot -> SET_MONS_TO_TRADE -> confirm -> START_TRADE
-> transfer/save -> CONFIRM_FINISH_TRADE -> clean exit
```

That run will let the decoder distinguish synchronized party data from the
actual offered and received Pokémon. No change to the RFU/Pokémon parser is
required before that capture; the missing information is on the wire, not in
the decoder.

## Verification status

```text
py -3.14 -m unittest discover -s tests -v   16/16 PASS
py -3.14 -m compileall -q tools tests        PASS
live Pia JSONL extraction                    PASS (decrypt failures = 0)
```
