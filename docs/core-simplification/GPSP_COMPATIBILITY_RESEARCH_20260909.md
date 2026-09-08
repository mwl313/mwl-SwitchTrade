# gpSP discovery defect and compatibility research

## Latest: controlled waiting-room observations preserved

The user subsequently authorized Switch-only selected-room observation.
[The observation record](GPSP_ADVERTISEMENT_OBSERVATIONS_20260909.md) documents
Trade/reopened Trade/Single/Double/Multi waiting rooms, private evidence
preservation, candidate activity distinctions and verified diagnostic cleanup.
This adds narrow physical scan-cancel evidence; it does not complete the
advertisement conversion or prove battle/trade traffic. Earlier packet claims
below retain their original scope and time.

## Follow-up: ACK-reader lifetime repaired; advertisement mapping still open

Follow-up baseline: `codex/gpsp-endpoint`, local/remote
`7e064308bd72edb751885537d8878716274bc399`, clean before work.
The user approved continuing software research/repair, not another physical run.

### Concrete progress

MTA-CORE-021 has a software reproduction: factory-level netlink readers are
sibling tasks of the scan consumer. Cancellation reaches those readers before
the leaf VIF's shielded deletion waits for its ACK. The kernel can delete the
interface but its confirmation is never dispatched. Shielding only deletion
does not keep a sibling receiver alive. This explains the observed failure
shape; it does not rule out additional physical driver failures.

The production change is limited to the shared resource owner and its three
Direct A/B factory call sites. A shielded factory-owner task keeps its readers
alive until the consumer finishes exact-resource teardown. The consumer's scan,
association and session wait remain cancellable. The factory's context/nurseries
enter and exit in their original task; shutdown/unfinished entry has a bounded
three-second deadline. Genuine missing ACK, failed reader or incomplete cleanup
remains a failure. No release by guessed interface name, global network reset,
dependency modification or increased timeout is used.

Inspected local runtime packages: `ldn==0.0.17`, `python-netlink==0.0.15`,
`trio==0.33.0`. `tests/test_direct_netlink_lifetime.py` adds actual NetlinkSocket
request/ACK dispatch to the actual Direct A/LDN/StageSession path, substituting
only kernel IO. Before repair, cancellation and scan deadline both failed
cleanup (2 failures). The older virtual kernel returned requests directly;
its lack of a receiver task hid this defect. Its kernel identity is now bound
to the StageSession's Trio run, not to an assumption that factory and consumer
share one task. Tests check socket/thread/netdev absence after exit.

Post-repair checks on the final source changes in this packet:

- Python 3.12: ownership/netlink/real Direct faults, **39 passed**.
- Python 3.12: Direct A/B and the actual CLI/real relay/LDN/TunnelSim
  two-Generation no-interruption path, **30 passed, 5 deselected** (other
  interruption variants deliberately excluded from this focused command).
- Python 3.14: ownership/netlink/Direct A/B/real Direct faults, **68 passed**.
- Negative cases retain missing delete ACK as unknown, reject repeated stop,
  bound stalled factory entry/exit, and preserve first functional/cancel failure
  independently of factory cleanup failure. Actual reader failure interrupts
  the consumer instead of becoming a normal user cancellation.

These are local Windows software tests. Full pytest, stock RetroArch process
qualification and same-SHA platform CI are not claimed by this packet. Physical
scan-stop requalification remains required; trial04's original cleanup failure
is unchanged. No WSL, USB, physical Switch, VM, emulator or relay deployment was
operated. Core/Relay wire formats and the gpSP production converter are unchanged.

### Mapping investigation and precise resume point

Rechecked the pinned FireRed `link_rfu.h`, `link_rfu_3.c` and `sloopsvc.c`,
upstream LDN transport, and public fork/repository listings. The game struct is
not a different conditional Switch layout: SVC47 copies the existing game data
and name into Sloop, whose LDN field packing is not implemented in that wrapper.
The available fork trees did not expose a verified inverse. An indexed GBA
bridge repository remains unavailable for source inspection; its description
cannot substitute for mapping evidence. No new mapping was established.

Therefore MTA-GPSP-002 stays in `software_gaps`; the production format probe
still returns FAIL. Do not hard-code language/activity/progression to force a
visible room or claim the full format is merely an endian/checksum adjustment.

Next necessary input is an authoritative encoder/decoder source or separately
authorized controlled Switch advertisement observations with known game states.
For observations: first recheck the corrected owned scan/stop path, then collect
only the selected room's needed fields, change one user-operated game condition
at a time, retain raw material privately, and publish only synthetic derivations.
Unchanged/variable bytes across a few rooms alone do not prove every bitfield.
Do not start that physical activity or request a VM trading retry without the
user's agreement. The VM has no functional advertisement fix to pull yet.

---

## Prior packet record

Baseline: `codex/gpsp-endpoint`, local/remote
`881a9c58cfe8068c45383a0f7f66728b9dff2d10`, clean before this packet.
User authorized normal stop, advertisement repair and compatibility research;
not another physical trial or expansion to new cores/Python runtimes.

## Result: repair remains blocked on the Switch field mapping

**The discovery defect is confirmed, but the production conversion is NOT fixed.**
This packet supplies an independent offline reproducer and prevents a false
completion attestation. It does not install anything, change the relay, guess
game fields or claim a successful Pokemon exchange. Further research did not
justify the earlier assumption that this would be a small checksum-only fix.

Trial 04: Direct A reached A9; Host reached Bridge active. Guest local Netplay
and RFU mode passed; advertisement writes rose to 315 while gpSP packets stayed
zero, state searching, link_ready false. Socket writes do not prove consumption.
The original homebrew picks the first broadcast server; it does not apply
FireRed's serial/checksum/game-activity filter. Its passing traffic/soak evidence
does not close this gap.

### Proven format mismatch

The current translator endian-converts the decoded Switch record without
reconstructing a native GBA broadcast. These are distinct formats:

| Bytes | Decoded Switch record (existing project evidence) | GBA RFU broadcast |
| --- | --- | --- |
| 0-1 | trainer ID | game serial = 2 |
| 2-9 | trainer name | first 8 bytes of game data |
| 10-11 | Switch RFU session ID | game data continuation |
| 12-14 | partner/search fields | game data continuation |
| 15 | partner/search field | checksum |
| 16-23 | partner/search/trade fields | trainer name |

The GBA checksum is the one's complement of the eight-bit sum of game-data
bytes 0-7 and all eight trainer-name bytes. The current synthetic production
advertisement fails both serial and checksum checks. Independent reproducer:

```powershell
.\.audit-venv\Scripts\python.exe tools/gpsp_qualification/check_advertisement.py
```

Expected on this unresolved implementation: exit **1**, `verdict=FAIL`,
`frame=true`, `game_serial=false`, `game_checksum=false`. No hardware or emulator
is started. The checker emits booleans only and never reads a user's ROM/save.
Checker unit tests passing mean the checker works, NOT that conversion passes.

### Missing proof before a real correction

GBA `gname` contains language/progression/version bits, trainer ID, partner
flags, species/type, activity/start and gender/level. Our existing Switch
definition labels eight bytes opaque partner/search information and a separate
trade word. The public game SVC wrapper proves that Switch uses a different
emulator boundary, but does not define Sloop's LDN serialization of these fields.
Neither rearranging all remaining bytes nor hard-coding an English trade profile
is an evidence-backed conversion. Do not forge compatible-looking metadata.

Needed: a verified field-level Switch serialization implementation/specification,
or controlled paired evidence of the same synthetic game-data fields and their
Switch-format advertisement. Vary fields independently, including started state,
language, FireRed/LeafGreen, gender and trade parameters. Keep raw data private;
publish only synthetic vectors and field derivations. Do not obtain new captures,
control devices, modify games or read emulator memory without explicit authority.
Once this mapping is known, replace conversion inside `retroarch_gpsp/rfu.py`,
retain RFU session/retired IDs, update the old golden vector, and require the
independent format probe plus game-level filter coverage before another trial.
Passing this necessary format check alone is still not a full gameplay proof.

## 1. Does this affect Switch to Switch?

**This particular defect does not run on that path.** Switch driver Direct A
exports the original advertisement. `_direct_b_stage()` passes `offer.setup_payload`
to `DirectBStage`, which sets `param.application_data` unchanged. Core/Relay do
not import this gpSP converter. No Core/Relay or Switch advertisement format is
changed by this packet. This is not a blanket physical Switch-to-Switch PASS.

A separate shared Host stop problem was observed in this trial: the active
generation ended at 23:55:34 KST, all its resources released (Pia RX 4180, errors
0). During subsequent no-room scanning, Ctrl+C ended with A_CANCELLED and
`scan.vif.6:TooSlowError`, `scan.factory:BaseExceptionGroup`, both resources
unknown; the CLI returned S_CLEANUP_FAILED. It can affect either pairing because
both use Host Direct A. Its software-versus-driver cause is not established.
After exit the original Core/guardian were absent; no created VIF/TAP remained,
only baseline wlan0. The exact run-owned USB attachment was detached and its
client field verified empty. Later absence is not retroactive cleanup success.
No WSL reset, broad kill, forced detach or automatic retry was performed.

## 2. Game versions and compatibility

The [pret decompilation README](https://github.com/pret/pokefirered/blob/c75f352304d529f6ba92d4f74b9cf8b5c3810788/README.md)
distinguishes English original, Rev 1 (commonly 1.1), and Switch images for both
games. `config.mk` maps `GAME_REVISION=10` to the Switch build: this is an internal
ROM revision, **not** a Switch eShop update version called 1.0 or 1.1.
Different language releases are also separate products, as explained by
[Nintendo](https://www.nintendo.com/en-ca/whatsnew/pokemon-firered-version-and-pokemon-leafgreen-version-are-coming-to-nintendo-switch-in-multiple-languages/).

The relevant original/Rev 1 RFU discovery algorithm uses the same serial 2,
checksum and `RfuGameData` layout. Thus a Rev 0/Rev 1 difference does not explain
our malformed packet. This is a source inference about this specific filter,
not validation of all language/revision/gameplay combinations. Switch adds Sloop
SVC calls and link recovery/flow changes; the software bridge must account for
those boundaries. Do not assume ROM byte identity or full cross-platform
compatibility, and do not recommend replacing a user's game/save to mask this bug.
The user's exact game revisions/languages have not been identified in this packet.

## 3. Wider core and Python support

### Cores

Ordinary RetroArch netplay synchronizes inputs/emulation for one shared system.
gpSP uses the separate Netpacket interface to emulate a GBA wireless adapter.
Therefore **Netplay capable != compatible RFU endpoint**. The
[Libretro API](https://github.com/libretro/libretro-common/blob/master/include/libretro.h)
gives cores control over custom packets and a `protocol_version`; it is not a
universal RFU payload schema. See also the
[Libretro Netplay FAQ](https://docs.libretro.com/guides/netplay-faq/).

New gpSP builds can be qualified and registered; a same protocol string is
useful evidence but not proof of unchanged lifecycle/packet semantics. Current
Windows observer validates exact frontend/core hashes and the live handshake
requires gpSP / gpSP v1.0. Keep those checks until replacement compatibility
criteria and actual-process regressions exist. The measured core screenshot
shows **v1.1.0-74db5e5**; earlier runbook text v1.0-74db5e6 was a label typo,
not a newly observed binary hash mismatch. Supported hashes have not changed.

mGBA/VBA or other cores need their own exposed link interface and adapter;
RFU and wired cable are not interchangeable. Keep conversion in each endpoint,
static lazy registration in composition, and opaque Core/Relay forwarding.
No new adapter/capability or hash bypass is introduced here.

### Python

3.13 is explicitly rejected by the current native entrypoint's `(3,12)/(3,14)`
allowlist and matching qualification tool, not by an identified language-feature
limitation. Extending to standard Windows x64 CPython 3.12-3.14 is feasible but
requires a 3.13 environment, focused/native-process checks and evidence policy
updates. Full 3.13 support has not been tested or enabled here.

The pinned [websockets 17.0.1 release](https://pypi.org/project/websockets/17.0.1/)
requires Python >=3.11 and publishes a cp313-win_amd64 wheel. Current lock has
3.12/3.14 wheels and a universal Python wheel; the absence of a listed cp313
wheel is not by itself proof installation is impossible. The cp313 wheel hash
observed in official release JSON is
`409d93efcaa14f7a99592c5baaef5ec6ca94fba0f5aec1a86f693977c69c9c1c`.

Future `>=3.12` interpreter admission can be made permissive, but it cannot
honestly guarantee all future minor versions, PyPy, x86, ARM64 or free-threaded
builds. Preserve platform/process-API identity and dependency validation; publish
a tested-version matrix and qualify new minors. Free-threaded builds have a
separate [Python compatibility contract](https://docs.python.org/3/howto/free-threading-python.html).
Windows native Python and the managed Switch WSL Python are separate runtimes;
changing the VM interpreter does not update the installed WSL appliance.

## Source anchors and verification boundary

- [gpSP rfu.c at 74db5e5](https://github.com/libretro/gpsp/blob/74db5e5/rfu.c):
  NET_RFU_BROADCAST / RFU_CMD_BCRD_FETCH, six big-endian network words.
- [FireRed librfu_rfu.c](https://github.com/pret/pokefirered/blob/c75f352304d529f6ba92d4f74b9cf8b5c3810788/src/librfu_rfu.c):
  rfu_REQ_configGameData, rfu_STC_readParentCandidateList.
- [FireRed link_rfu.h](https://github.com/pret/pokefirered/blob/c75f352304d529f6ba92d4f74b9cf8b5c3810788/include/link_rfu.h):
  RFU_SERIAL_GAME, RfuGameCompatibilityData, RfuGameData.
- [Switch SVC wrapper](https://github.com/pret/pokefirered/blob/c75f352304d529f6ba92d4f74b9cf8b5c3810788/src/sloopsvc.c):
  svc_47 copies game data/name; svc_45 publishes RFU link status. This is NOT
  Sloop's LDN encoder source. No commercial binary was downloaded or inspected.

Full tests, actual-process soak, game revisions and physical success are not
claimed by this packet. CI is not awaited per user request. GPSP_ACCEPTANCE now
records the open software gap, so even green platform jobs cannot attest final
completion. The existing historical ABC ledger is not re-certified by this work.

Local focused verification: **58 passed on Python 3.12; 58 passed on 3.14**
(`test_gpsp_advertisement_check`, `test_gpsp_qualification`, `test_gpsp_rfu`,
`test_agent_context_policy`). The separate production advertisement probe still
returns **FAIL/exit1** as described above. No tests were skipped or xfailed.
