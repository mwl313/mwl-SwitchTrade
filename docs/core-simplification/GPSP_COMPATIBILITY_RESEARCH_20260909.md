# gpSP discovery defect and compatibility research

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
