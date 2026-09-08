# Selected-room advertisement observations

## Scope and result

User-authorized, scan-only observations on 2026-09-09, source branch
`codex/gpsp-endpoint` at `79295ad5eb6ea10469ccd576866a56081ea6e9db`.
Immutable runtime overlay:
`c05dbb9e126c394c80a25a4a8228f18eb29c3e0405f46d15ec0ec4614dd426ab`.
Observer SHA256:
`2f75178ed8e65cf53119fa5951c0f2827f49cec13ad48d176a71269905e2c7d0`.

The existing source-verified radio gate and production Direct A scanner/resource
ownership were used by `tests/physical_advertisement_observer.py`. The user alone
operated the same game/trainer profile, leaving and creating the waiting rooms.
The observer never joined a room, made an AP/Pair, started a VM/emulator, accessed
ROMs/saves, or sent game traffic. This is NOT an end-to-end RFU qualification.

| User-selected waiting-room condition | Observations | Candidate activity value |
| --- | --- | --- |
| Trade, first room | 3 | 4 |
| Trade, leave and reopen | 3 | 4 |
| Single Battle | 3 | 1 |
| Double Battle | 3 | 2 |
| Multi Battle, no other participants | 3 | 3 |

Each room's three selected decoded records were identical. Between rooms,
the existing session field at offsets 10-11 changed. Reopening Trade preserved
everything else. Changing activity also changed byte 16; the other bytes stayed
constant. The low-field values shown above are **candidate interpretations**,
not proof of a complete mask, its upper bit, or all possible activity values.
Exact raw values and trainer identity are intentionally excluded from this file.

## Preservation

The 15 selected 24-byte observations and one no-record cancellation report are
retained privately in the managed runtime and copied byte-for-byte into the
Git-ignored `.qualification/advertisement-observations-20260909/` directory.
The private README records labels, conditions, source identities and limits;
SHA256SUMS records all 16 JSON file hashes. Each copied file was checked against
the original. Original files were not overwritten. Keys, whole advertisements,
MAC/IP captures, ROMs, saves and gameplay payloads were not copied.

Keep raw material private and out of public issues/commits. This is a local
backup on the same PC, not an off-device disaster-recovery backup. Derive future
public regression vectors from synthetic inputs, not copied trainer records.

## Cleanup evidence

Before collecting records, an acquired scan monitor was cancelled through the
real StageSession.stop path. It retained A_CANCELLED as the intentional result;
runtime sockets, scan factory and VIF were all released without cleanup errors.
Each of the 15 later normal scans also reported verified cleanup. Read-only
post-set checks found no observer/guardian or generated VIF/TAP residue.

At diagnostic close, the exact run-owned USB attachment was detached and its
client field verified empty. The temporary keeper was stopped only after its
command/start identity matched. No keeper/observer/Core/guardian, Windows WSL
owner, or wireless interface remained; the separate Internet path was unchanged.
No WSL reset, broad process kill or guessed-interface deletion was used.

This narrowly rechecks the physical scan-cancel path repaired for MTA-CORE-021.
It does not relabel trial04's original cleanup failure or prove all association,
active-session, driver-failure and disconnect paths.

## What this enables, and what it does not

The observations are useful for future discovery classification and preserving
Trade/Single/Double/Multi distinctions when converting Switch advertisements to
native RFU metadata. They do not establish neighboring language/version/gender/
progression bits, started-state transitions, partner data, or trade parameters:
those variables were not independently changed in this packet.

Battle support additionally needs real bidirectional RFU exchange, timing/ACK,
termination and next-generation qualification. A Multi waiting advertisement
does not prove four-participant slot assignment, routing or lifecycle support.
No battle capability is registered or claimed by this evidence.

MTA-GPSP-002 remains unresolved: the production converter has not changed.
The subsequent [gold reanalysis](GPSP_GOLD_AD_NI_REANALYSIS_20260909.md) recovered
native NI for both existing profiles and matched one to these advertisements.
Private provenance records corrections without changing the original
observations or hashes. Missing
field packing still needs independent evidence rather than a hard-coded profile.
See the [compatibility investigation](GPSP_COMPATIBILITY_RESEARCH_20260909.md).
