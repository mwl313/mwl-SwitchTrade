# Party snapshot and trade commit contract v1 — 2026-08-25

> Status: frozen for private-beta implementation.
> Contract version: `party-commit.v1`.
> Scope: passive local decoding, two temporary party views, and fail-closed trade commit detection.

This contract turns the existing Gen III decoder and golden-capture evidence into a stable boundary for
the desktop UI and the future statistics service. It does not move decoding into the relay and does not
allow decoding to delay or modify RFU traffic.

## 1. Invariants

1. The decoder is a passive observer of locally terminated Reliable AppData.
2. The RFU forwarding path never waits for, retries because of, or is modified by the decoder.
3. Reassembly state is isolated by `attempt_id`, member, direction, and stream sequence.
4. Only complete, checksum-valid Gen III records may appear as identified Pokémon.
5. A missing, stale, or failed party view never blocks room entry, movement, trading, or leaving.
6. Party snapshots are local and ephemeral. They are not analytics payloads.
7. A trade commit is emitted only after durable post-trade evidence. Ambiguity fails closed.
8. Raw RFU payloads, session keys, captures, and decrypted buffers never enter UI events or routine logs.

## 2. Observer boundary

The endpoint tees a bounded copy of already-authenticated, locally terminated AppData to the decoder.
The forwarding write remains the primary path. The observer uses a bounded queue and may drop its own
work under pressure; it may not apply backpressure to the radio or tunnel.

On queue overflow, malformed input, sequence gaps, or decoder failure:

- record a redacted diagnostic counter;
- invalidate the affected in-progress reconstruction;
- publish `party.unavailable` if a previously visible snapshot becomes untrustworthy;
- continue the connection unchanged.

## 3. Party snapshot

Each member has at most one current snapshot for an attempt.

```json
{
  "contract_version": "party-commit.v1",
  "snapshot_id": "ps_01...",
  "snapshot_version": 4,
  "attempt_id": "att_01...",
  "member_id": "mem_01...",
  "observed_at": "2026-08-25T12:34:56.123Z",
  "validity": "complete_checksum_valid",
  "slots": [
    {
      "slot": 1,
      "occupied": true,
      "record_hash": "sha256:...",
      "species": {"value": "Bulbasaur", "provenance": "observed"},
      "nickname": {"value": "BULBASAUR", "provenance": "observed"},
      "level": {"value": 12, "provenance": "derived"},
      "nature": {"value": "Calm", "provenance": "derived"},
      "held_item": {"value": null, "provenance": "observed"},
      "current_hp": {"value": 31, "provenance": "observed"},
      "max_hp": {"value": 31, "provenance": "observed"},
      "stats": {
        "attack": {"value": 17, "provenance": "observed"},
        "defense": {"value": 18, "provenance": "observed"},
        "speed": {"value": 16, "provenance": "observed"},
        "sp_attack": {"value": 20, "provenance": "observed"},
        "sp_defense": {"value": 21, "provenance": "observed"}
      },
      "ivs": {
        "hp": {"value": 12, "provenance": "observed"},
        "attack": {"value": 8, "provenance": "observed"},
        "defense": {"value": 27, "provenance": "observed"},
        "speed": {"value": 14, "provenance": "observed"},
        "sp_attack": {"value": 19, "provenance": "observed"},
        "sp_defense": {"value": 22, "provenance": "observed"}
      },
      "trainer": {
        "name": {"value": "RED", "provenance": "observed"},
        "trainer_id": {"value": 12345, "provenance": "observed"},
        "secret_id": {"value": null, "provenance": "unavailable"},
        "language": {"value": "English", "provenance": "observed"}
      }
    }
  ]
}
```

The array always represents six ordered slots. Empty slots use `occupied=false` and omit Pokémon
fields. Every displayed field carries `observed`, `derived`, or `unavailable` provenance; the client
must not invent a zero, default label, or estimated value.

## 4. Publication and invalidation

Publish `party.snapshot.updated` only when all occupied records in the reconstructed party are complete
and checksum-valid. A newer valid snapshot replaces the prior version atomically.

Invalidate the snapshot when:

- a new connection attempt starts;
- the endpoint observes a newer incomplete party generation that supersedes it;
- the member leaves or the RFU session tears down;
- sequence loss or decoder failure makes the current generation uncertain.

The UI may retain a neutral “Party data unavailable” placeholder, but not stale Pokémon.

## 5. Commit classifier

The classifier maintains a monotonic `trade_index` per attempt and correlates both directions. The
golden captures support these checkpoints:

1. valid pre-trade party snapshots and offered-record identities;
2. trade start and bilateral confirmation traffic, including `CONFIRM_FINISH_TRADE` evidence;
3. completed save sequence for both peers;
4. valid post-save party rebuild showing the exchanged record hashes in their new parties;
5. return to a stable trade-menu or neutral protocol state.

A successful animation, offer, confirmation prompt, one-sided save, or temporary post-animation party
change is not sufficient. Disconnects, native Switch errors, rollback to the original parties, checksum
failure, and incomplete post-save evidence must produce no commit.

If step 5 cannot be proven but the durable post-save exchange in steps 2–4 is conclusive, the classifier
may mark the result `committed_with_teardown_error`; it must preserve the evidence flags so this policy
can be audited. Any weaker combination fails closed.

## 6. Commit event and idempotency

```json
{
  "contract_version": "party-commit.v1",
  "event": "trade.committed",
  "commit_id": "tc_01...",
  "attempt_id": "att_01...",
  "trade_index": 1,
  "committed_at": "2026-08-25T12:40:01.002Z",
  "outcome": "committed",
  "member_a_record_hash": "sha256:...",
  "member_b_record_hash": "sha256:...",
  "evidence": {
    "bilateral_finish": true,
    "bilateral_save": true,
    "post_save_party_rebuild": true,
    "stable_return": true
  },
  "statistics_eligible": false
}
```

`commit_id` is derived or uniquely constrained from `attempt_id`, `trade_index`, and the canonical pair
of exchanged record hashes. Retries return the existing result. The room event stream may contain the
minimal event above; full decoded records remain in the local observer unless the separate consent and
statistics contract authorizes a minimized upload.

## 7. Local UI API

- `GET /api/v1/trade-room/parties` returns the current two snapshot envelopes or explicit unavailable
  states.
- `party.snapshot.updated` replaces one member's view.
- `party.snapshot.invalidated` clears one member's view.
- `party.unavailable` supplies a reason code and a non-blocking recovery message.
- `trade.committed` updates the local success/history presentation once by `commit_id`.

Events use the ordered local stream defined in `room-control.v1`. The UI treats unknown species assets,
unavailable fields, and decoder failure as presentation fallbacks, never connection errors.

## 8. Statistics boundary

Party snapshots are never uploaded. Only after `trade.committed` may the statistics adapter consider
the two exchanged records, and only when a valid external consent grant permits the documented scope.
The statistics adapter receives an immutable commit projection; it cannot query decoder buffers.

## 9. Required implementation checks

- decoder work cannot stall a tunnel or radio write;
- incomplete and checksum-invalid records never render;
- a new attempt clears both old parties;
- duplicate frames and process restarts do not duplicate a commit;
- failed and rolled-back golden captures produce zero commits;
- the proven completed capture produces exactly one commit;
- analytics disabled/offline does not change the connection or commit result;
- support logs contain identifiers and evidence flags, not raw Pokémon records or payload bytes.

## 10. Evidence and remaining implementation work

The record decoder is supported by `docs/35` and the full-trade evidence in `docs/36` and `docs/47`.
Those documents demonstrate complete party records and the durable trade timeline; they do not mean the
semantic classifier, deduplication, API projection, or privacy gate is already implemented. Those items
remain post-overhaul backend work against this contract.
