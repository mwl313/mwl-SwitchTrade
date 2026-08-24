# 34 — Pokémon payload reverse-engineering live validation (2026-08-24)

This supersedes the “no native payload bytes yet” conclusion in
`docs/33-pokemon-payload-re-protocol-handoff-audit-20260824.md` for the party
payload boundary.

## New protocol-agent milestone

The emulator repository `gptsolreview` reached a real Switch party-selection
screen using commit `0b8a2ab` (later documented at `9ffc8dc`). The live run
completed the parent-side pulls for:

```text
party pair 1, party pair 2, party pair 3, mail, ribbons
```

The Switch's menu became visibly usable. The run stopped before a Pokémon was
selected and confirmed, so this is a payload milestone but not yet a completed
trade transaction.

Evidence is local and intentionally ignored:

`logs/golden/pc_host_parent_party_pulls_live_20260824_183308/`

The capture manifest reports 4,567/4,567 Pia datagrams authenticated, zero
kernel drops, and successful post-test RX health checks on both radios.

## Independent payload validation

Using the protocol agent's current Pia/Reliable/RFU semantics and the existing
payload scanner, the captured JSONL was decoded without relying on the emulator
trade FSM:

```text
Pia datagrams processed       4,567
Pia authentication failures   0
Reliable application messages 8,702
child GBA T frames            1,701
complete RFU blocks            7
```

The seven complete blocks include the LinkPlayer/trainer/menu data. The third
party block is 204 bytes on the wire (200 bytes of party data plus RFU padding)
and contains two checksum-valid Gen III wire records:

| Offset | Species | Nickname | Level | Checksum |
|---:|---|---|---:|---|
| 0 | BULBASAUR (#1) | BULBASAUR | 6 | valid |
| 100 | RATTATA (#19) | RATTATA | 3 | valid |

The decoded records also expose the expected Gen III fields: PID, OT IDs,
language, held item, experience, moves, EVs, IVs, nature, and calculated stats.
This is the first direct validation that real Pokémon bytes from a Switch
session can pass through:

```text
Pia decrypt -> Reliable parse -> GBA/RFU parse -> fragment reassembly -> pk3 decode
```

No raw pcap, session key, or Pokémon block was added to Git.

## What is now possible

The project can now identify Pokémon contained in a Switch's synchronized party
data before the actual trade confirmation. This is enough to validate the
payload extraction pipeline and to build a live party/roster decoder.

## What remains for full trade decoding

The live run stopped at the menu. It did not yet capture:

- the user's selected trade slot;
- player-zero `SET_MONS_TO_TRADE` leadership;
- `START_TRADE` and the transfer animation;
- `CONFIRM_FINISH_TRADE` and the post-trade save exchange;
- a received `.pk3` from a completed native Switch trade.

Therefore the protocol handoff is now sufficient for **real party payload
decoding**, but not yet for proving which Pokémon was exchanged or for mapping
the complete offer/confirm/commit transaction. The next live gate is one
controlled selection and confirmation with a known Pokémon on each Switch.

## Branch status

This report originally belonged to the independent `pokemon-payload-re` branch. Both histories are
now merged on `production-beta`, with protocol runtime code tracked under `bridge/`.
