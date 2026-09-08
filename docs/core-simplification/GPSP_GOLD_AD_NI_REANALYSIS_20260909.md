# gpSP advertisement / native NI gold reanalysis

## Status and scope

Baseline: `codex/gpsp-endpoint` at
`34c891012a793a7087c20e85c0a3771980fbcb00`, local/remote equal and worktree clean.
This packet reuses existing local gold; it does not start a radio, WSL, VM,
RetroArch, Pair, relay deployment or physical test. No ROM/save was opened.

**MTA-GPSP-002 remains OPEN.** Native initial game information is now recovered
and independently checked, but the exact Switch advertisement packing is not
proved. Product conversion and Core/Relay are unchanged. Do not retry the same
gpSP game-discovery test expecting a fix from this packet.

## Verified inputs and extraction

Existing capture hashes match their original capture manifests:

| Existing gold input | SHA256 |
| --- | --- |
| Native fixed CH1, RTL8192 | `e6df7e03b2d33c11aaec112306f4605706a11afd9fd35fc9dd97ad768257d0b5` |
| Native fixed CH1, RTL8188 | `9e0efa267bdcd8f21bace046d756ef3fda7518fbc5cf26ddba4f77b361c7dbbd` |
| PC-host atomic-exit Switch-A retry, inbound Pia JSONL | `3ffd05417043ea258529594f5decada800d1e6ce8630377fe3d56b956c2f352c` |

The local reader uses the installed LDN advertisement/key derivation code and
existing Pia/Reliable/GBA/LLSF parsers. For QoS data, the CCM nonce/AAD includes
the original QoS TID and authenticates the MIC; it does not remove authentication
to make packets parse. Windows' absent ioctl module is inert for offline imports;
socket construction is explicitly forbidden by this private analysis process.
Keys remain local and are never output or included in reports.

| Input | Protected Wi-Fi authenticated | Pia authenticated | Auth failures |
| --- | ---: | ---: | ---: |
| Fixed CH1 RTL8192 | 18,257 | 18,252 | 0 |
| Fixed CH1 RTL8188 | 16,109 | 16,104 | 0 |
| PC-host JSONL, actual Switch inbound only | Not a Wi-Fi input | 6,581 | 0 |

The two fixed captures also contain respectively one and two decoded plaintext
data frames, not counted as authenticated Wi-Fi frames above. Hopping discovery
captures were inspected separately; one had 33 Wi-Fi authentication failures
under the single-current-room decoder. They are NOT used as lossless mapping
proof. The fixed captures and JSONL above are the authoritative inputs here.

## Findings

1. Both fixed-radio captures independently reconstruct the same complete
   26-byte child NI game record: START, three data windows (12/12/2), END.
   Matching retransmissions are deduplicated. The native game information
   contains the original RFU serial, compatibility fields and username.
2. That native child is NOT the advertised parent. Matching their game fields
   as if they described the same player would create a false conversion rule.
3. The later PC-host capture contains real Switch **inbound** child NI whose
   trainer ID/name match the earlier native advertised parent. PC-generated
   parent data is excluded. This recovers the second profile without another
   join/trade capture. The records are from different rooms/times/roles, not a
   simultaneous same-state observation.
4. The latest selected Trade advertisement equals the earlier native parent's
   decoded record except for the room/session field. This does not prove that
   every hidden field or game state remained identical across both runs.
5. Corrections to game/profile provenance and device-role assignments are kept
   in private evidence only. Original observation JSON files/hashes are preserved.
   Names never substitute for native gender fields. Do not retroactively relabel
   trials with a different scan-only profile. No VM save was opened.

Native NI interpretation follows the public
[RfuGameData definition](https://github.com/pret/pokefirered/blob/master/include/link_rfu.h)
and [version/language constants](https://github.com/pret/pokefirered/blob/c75f352304d529f6ba92d4f74b9cf8b5c3810788/include/constants/global.h).
These specify the native structure, NOT Sloop's separate LDN serialization.
The [SVC47 wrapper](https://github.com/pret/pokefirered/blob/master/src/sloopsvc.c)
copies the game structure into the runtime but does not provide its inverse
advertisement encoder. Source links using `master` were inspected on2026-09-09;
they are not claimed as immutable pinned evidence.

## Small reusable software addition

`tools/gpsp_qualification/ni_identity.py` reuses the existing decoded RfuSlot
boundary, rejects mixed roles/multiple transfers, requires complete bounded NI
windows, rejects conflicting retransmissions, and decodes native game fields.
Its summary omits trainer IDs/names, addresses and raw bytes. Callers must group
by authenticated source and connection before invoking it. This is offline
evidence tooling, not an unused product adapter or a proposed universal emulator
protocol. The private capture reader groups those identities explicitly.

Synthetic tests cover the actual GBA/LLSF decoder, two native profiles, missing
START/data/END, duplicates, receive-side ACKs, changed duplicates, wrong roles,
multiple transfers, malformed lengths/windows/END, all native compatibility
bits and identity-free summaries. The reconstructed private captures also pass
the strict reassembler; no private payload is included in a public test vector.

## Follow-up: second selected advertisement collected

A later user-authorized scan-only packet collected three identical selected
waiting-room records for the second existing profile. Trainer ID and the full
eight-byte name match its previously recovered native child NI. Both profiles
now have advertisement/native-NI correlations, still across different times and
roles. Two opaque game-state bytes differ between their waiting advertisements;
this alone does not isolate co-varying game version and gender or prove the
unexercised language/progression/partner/trade fields.

The first nine scans returned no selected record. The last three of these,
after adding non-identifying counts, found one contract-compatible room but
rejected its name. Existing authenticated NI exposed a diagnostic bug: the
observer required eight-byte equality with FF-filled synthetic name padding.
An exact terminated name with zero bytes after EOS was incorrectly excluded.
Two synthetic cases failed before repair. Selection now compares the exact
encoded name **including EOS**, ignores only bytes after EOS, preserves the raw
record, and still rejects ambiguous rooms, prefixes and missing terminators.
Corrected selection then captured all three records. Original failed outcomes
are preserved, not retrospectively counted as successes. No game restart was
needed; the earlier observations do not establish a 5GHz cause.

Physical source: base `d22fd393481c19fdf481fc0365d66186ff83f78e` with the
explicit dirty diagnostic patch, immutable overlay
`229194736a9b34c26d2bb41b2d8fa3483471c25f64ac7ef36f0104d3c3e0c3f9`, observer
SHA256 `e298a91b5aa06f0b76749bd05304cba4ee13092eae8f4b9440ef21f81df4f186`.
All twelve scans reported released sockets/factory/VIF and no cleanup failure.
The selected records were copied locally with source/destination hash equality;
all evidence remains private. Exact USB attachment and bounded keeper were
released, no wireless/packet-socket or observer residue remained, and the
separate Internet route was unchanged. No VM, Pair, room join or game traffic.

Focused observer regression: **6 passed on Python 3.12 and 6 on Python 3.14**.
No full pytest or CI completion is claimed; CI is not awaited for this packet.
This fixes the diagnostic selector, NOT the production RFU converter.

## Remaining work / exact next input

- The missing mapping is Switch opaque game-state bytes to native compatibility,
  gender, started/activity, partner and trade fields. Identifying a native field
  does not identify where Sloop stores it. The existing first-server homebrew
  test still cannot validate the game's discovery filter.
- Reuse the two recovered native NI records and both selected advertisements.
  The second waiting-room input is now collected; do not request it again or
  restart full-session capture. Next work is offline mapping reconciliation.
  Request another controlled physical observation only if a specific unresolved
  bit cannot be established from the retained evidence or serialization source.
- If profiles differ in both game version and gender, their difference alone
  must not be presented as isolating those two variables. Additional controlled
  evidence or authoritative serialization source may still be needed for
  unexercised bits. Never hard-code a profile to obtain a visible room.
- Once mapping is independently established, fix the endpoint converter and its
  golden vectors, add game-compatible discovery checks to qualification, then
  perform a separately authorized real test. Do not close the issue after a
  serial/checksum-only patch.

Validation for this packet: **33 focused NI/checker tests passed on each of
Python3.12 and3.14**, with no skips. These are local Windows runs;
the production advertisement probe continues to exit1 with serial/checksum
FAIL. No full pytest, actual RetroArch qualification or CI completion is claimed.
Private raw exports/reader/summary are retained under Git-ignored qualification
storage for exact resumption. Only synthetic tooling/tests and this sanitized
record belong in the public commit.
