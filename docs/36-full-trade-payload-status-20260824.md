# Full Switch-to-Switch trade payload status (2026-08-24)

## Executive result

The payload track is no longer blocked on another capture or on communication-protocol discovery. The full WSL/PC-host trade capture contains valid Gen III Pokémon records before, during, and after the trade, and the extractor decodes them into Pokémon fields with checksum validation.

The strongest end-to-end proof is the received Magikarp:

- the host log records Magikarp as the Pokémon received and saved;
- the captured 100-byte payload decodes as species 129 (MAGIKARP), level 5, OT `DESTROY`, and checksum-valid;
- its canonical payload SHA-256 is `54133b532e93943ba3dce6fd89d9e0f06c8ba87d70890fa9da760b8f715f3181`;
- that hash matches `logs/golden/pc_host_atomic_exit_switcha_retry_live_20260824_212450/received.pk3`.

The offered Rattata is also independently grounded: its canonical hash is `b008f35eb33502a75ae7b86e1ee9f4ce4abfde689adf0e26187a41b6a112635c`, matching `mons/0019_RATTATA_user_20260824.pk3`.

## Capture and decoder evidence

Capture: `logs/golden/pc_host_atomic_exit_switcha_retry_live_20260824_212450/pc_host_pia.jsonl`

Decoder report: `logs/golden/pc_host_atomic_exit_switcha_retry_live_20260824_212450/pokemon_payload_report_v2.json`

Pipeline totals:

| Measure | Result |
|---|---:|
| Pia datagrams | 12,276 |
| Pia decrypt failures | 0 |
| Reliable messages | 22,815 |
| GBA frames | 14,089 |
| Reassembled RFU blocks | 52 |
| Valid Pokémon records | present in 16 block observations |
| Reported incomplete blocks | 2 |

The two incomplete-block diagnostics are terminal/control-stream artifacts (`host_to_peer` blocks 15 and 22). They do not contain accepted Pokémon candidates. The decoder intentionally reports them instead of silently treating truncated data as valid.

## Payloads observed

The capture exposes the party snapshots and trade-side payloads, not only the single Pokémon selected for exchange. Reflections and retransmissions occur in both directions, so the same payload can appear more than once.

Observed exact payload identities include:

| Pokémon | Species | Level | Role/evidence | Canonical SHA-256 |
|---|---:|---:|---|---|
| Rattata | 19 | 3 | host fixture/offered payload; later appears in the peer's rebuilt party | `b008f35e...` |
| Magikarp | 129 | 5 | received by host; saved `received.pk3` | `54133b53...` |
| Mudkip | 283 | 16 | peer party snapshot | `4836b87d...` |
| Torchic | 280 | 13 | peer party snapshot | `a305fa0a...` |
| Salamence | 397 | 100 | peer party snapshot (one exact payload) | `dec4456a...` |
| Treecko | 277 | 12 | peer party snapshot | `82a3936a...` |
| Salamence | 397 | 100 | peer party snapshot (second exact payload) | `34801221...` |
| Rattata | 19 | 3 | post-trade peer party representation; distinct exact payload form | `263c6a40...` |

The abbreviated hashes above are for readability; the full values are in the decoder report. A species can have more than one exact canonical hash because the 100-byte record includes identity/checksum/tail data, and a post-trade representation may not be byte-for-byte identical to the offered fixture.

## Trade-cycle interpretation

The current report preserves direction, multiplayer ID, block ordinal, request type when known, source sequences, raw SHA-256, canonical SHA-256, and decoded fields. That is sufficient to reconstruct the cycle manually and to prove the transfer:

1. The host publishes its Rattata party/offer.
2. The peer publishes successive party snapshots (Mudkip/Torchic, then Salamence/Treecko, then Salamence/Magikarp).
3. The host receives the Magikarp record and saves it.
4. The host rebuilds its post-trade party with Rattata + Magikarp.
5. The peer's post-trade party rebuild contains Rattata, corroborating that the offered Pokémon crossed the session boundary.

What is not yet automatic is the semantic label for every block (for example, `initial_party_sync`, `offer`, `trade_result`, `post_save_party_rebuild`, `reflection`, or `retransmission`). The evidence needed for those labels is present; the classifier is simply not implemented yet.

## Remaining work

### Payload track (recommended next work)

1. Add a phase classifier that combines block order, direction, multiplayer ID, RFU request type, and host-console timeline to emit stable semantic labels.
2. Add provenance-aware deduplication: collapse reflections/retransmissions to one logical payload while retaining every source sequence and direction.
3. Add a ground-truth verifier that compares canonical hashes against known input/output `.pk3` files and fails closed on checksum/species mismatches.
4. Add a stable JSON/CSV/`.pk3` export interface for downstream UI, statistics, and automation.
5. Add regression fixtures using metadata and hashes (not raw captures or keys) so the decoder can be tested without committing sensitive traffic.
6. Document privacy/security boundaries: do not persist decrypted payloads, keys, or player identifiers unless explicitly enabled by the operator.

### System/integration track

1. Integrate the extractor into the normal capture workflow behind the existing health gate.
2. Make the final report explain partial captures, missing fragments, decrypt failures, and confidence per payload.
3. Verify the post-session teardown fix on hardware. The successful capture closed Pia/Reliable/RFU (`EXIT_ROOM`, `READY_CLOSE_LINK`, RFU D); the native `2318-0006` appeared only afterward during the outer LDN teardown tail. The follow-up keep-alive change is offline-tested but still needs a real Switch run.
4. Fix or isolate the joined-session radio-thread stop timeout so a clean capture does not depend on forceful process teardown.
5. Package the decoder as the production CLI/library and add versioned schema compatibility tests.

## What is no longer required before proceeding

- Another golden trade capture is not required to decode this completed trade.
- The other agent's protocol reverse-engineering branch is not a blocker for Pokémon payload extraction.
- Additional manual byte hunting is not required for the fields already decoded (species, nickname, PID, OT, IDs, level, moves, IVs, EVs, stats, nature, held item, and checksum).

The project is therefore at the transition from discovery to productization: prove the classifier on this capture, expose the decoded payloads through a stable interface, then verify teardown and repeatability on hardware.
