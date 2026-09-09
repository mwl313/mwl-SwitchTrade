# gpSP discovery / native acceptance repair — 2026-09-09

Branch: `codex/gpsp-endpoint`; implementation base:
`30ade542a980c95b55b2a85a6aa41d0e36ac7b25`. No main/relay protocol change.
No physical trial, user VM/game/save/config operation is part of this packet.
Private raw observations, identities and capture material stay local/ignored.

## Confirmed defects and repair

1. MTA-GPSP-002: a Switch 24-byte search record was merely endian-swapped and
   sent as native RFU game data. These are different layouts. Encode native
   serial2 + gname13 + checksum1 + uname8, then pack the six RFU1 network words.
   Preserve trainer fields; keep the Switch RFU session in its connection field,
   not inside gname. Never substitute a different trainer/template advertisement.
2. MTA-GPSP-003: native parent WA uses Reliable INIT flags0x0F, not just0x07.
   Dispatch using opcode plus flags; INIT is not a synonym for J metadata.
   Validate WA identity/length/state and retain upper-bit/duplicate guards.
3. Qualification gap: the old homebrew joined the first server without checking
   game discovery. Its replacement checks raw native serial/checksum and the
   supported Trade profile after real stock gpSP BCRD_FETCH, before connecting.
   The library's string helper strips zero bytes, so use its public raw RFU
   command response for binary gname. Two independent ARM builds must match.
4. Translator errors now use the existing gpSP error base: CLI shows the actual
   corrective action, preserving the technical code/cause in the log.

## Mapping evidence and explicit support ceiling

Search-record offsets are not native gname offsets:

| Switch record | Native broadcast |
| --- | --- |
| trainer ID at0:2 | gname2:4 |
| encoded name at2:10 | uname8, exact bytes including EOS/padding |
| session at10:12 | RFU peer/session header, not native game data |
| activity byte16 low7 | gname10 low7 |
| byte16 high1 | gname11 gender low1, supported by the paired observed profiles |
| byte17 low3 version, next3 language | native compatibility version bits10–13, language bits0–3 |
| byte17 high1 started | recognized; already-started rooms rejected for admission |

Current qualified input is **empty English FireRed/LeafGreen Direct Corner
Trade**, activity4, version4/5, language2, unstarted, unknown fields zero.
Other activities, languages, nonzero opaque partner/progress fields, and the
unproven byte17 bit6 are rejected as `TRANSLATOR_ADVERTISEMENT_UNSUPPORTED`.
This is not a general decoder for every game state, Mystery Gift or battle.
There is no silent fallback that clears unknown flags and advertises a fake room.

Private verification compared three observations for each of two profiles to
authenticated native NI from matching trainer identities. All native gname/name
bytes agree after accounting for the **post-join NI started bit versus empty-room
advertisement**. These are cross-run comparisons, not simultaneous identical
room states; the two profiles also vary version and gender together. Expanded
claims need additional independent evidence. Source captures and raw identities
are not fixtures or public artifacts; checked-in vectors use synthetic data.

The third-party repository provided useful corroboration, not an implementation
to execute or a complete protocol specification:

- [MercuryEnigma mystery_stamps_pi findings at c1ea7a2](https://github.com/MercuryEnigma/frlg-ldn-trade/blob/c1ea7a2729a509cddc0aa27daed801086e0354d9/docs/joyspot_discovery_findings.md)
  confirms the activity/version/language/started search-word positions; its bit7
  and possible card flag remain hypotheses. No upstream code/captures copied.
- [Native FRLG structure](https://github.com/pret/pokefirered/blob/c75f352304d529f6ba92d4f74b9cf8b5c3810788/include/link_rfu.h)
  and [native RFU configuration/candidate decoding](https://github.com/pret/pokefirered/blob/c75f352304d529f6ba92d4f74b9cf8b5c3810788/src/librfu_rfu.c)
  establish gname layout, serial and checksum.
- [Pinned gpSP RFU implementation](https://github.com/libretro/gpsp/blob/74db5e5/rfu.c)
  establishes RFU1 word order and raw broadcast response.

## Qualification and limits

- Before commit: 126 focused checks passed on each Windows Python3.12/3.14.
  Short stock-process probe04 passed native INIT WA and both generations
  (9 and4 complete bidirectional exchanges), with clean socket/process/desktop
  teardown and unchanged stock runtime. This was a dirty development source
  and short duration: it is NOT exact-SHA final qualification or a long soak.
  The two earlier short failures are preserved in the incident record.
- Independent format checker now passes production output; frozen pre-fix
  bytes still fail. Valid checksum alone does not pass a wrong activity/profile.
- Tests cover two versions, both gender bits, EOS/zero padding, session separation,
  unsupported fields, sticky failure, native INIT WA, malformed identity and
  flags, bounded queues, two-generation endpoint and real WebSocket relay paths.
- Full process harness exercises native dev/CLI, Core/WireClient/real relay,
  actual Switch driver/Direct A/StageSession/LDN/TunnelSim/CoreTunnelAdapter,
  actual RetroArch1.22.2/pinned gpSP, and the licensed discovery-checking homebrew.
  Only hardware/OS primitives and physical game input are substituted.
- Short probes are debugging evidence, not the mandatory >180s waits/30-minute
  soak. Final CI attestation additionally requires the new fixture hash and the
  discovery gate for both generations; old first-server evidence cannot pass.
- Successful commercial game discovery, NI/game compatibility, Pokémon exchange,
  VM scheduling and actual Wi-Fi behavior still require the next user-operated
  physical trial. Do not describe homebrew exchanges as a successful trade.

## Next physical trial (only when the user returns)

Update Host and VM to the same pushed feature-branch SHA. No relay redeployment,
Python/core reinstall or settings/save modification is required for this packet.
Keep the pinned core and the existing local Netplay target127.0.0.1:55435.

1. Host: set the common Core relay URL; run `./dev.ps1 run host --log-dir
   .qualification/physical-gpsp-05`. Open an empty English FR/LG Trade Group
   Leader room when prompted; leave it open.
2. VM: after updating, keep RetroArch/game running and execute `./dev.ps1 run
   join <new-code> --emulator gpsp --relay <common-https-url> --log-dir
   .qualification/physical-gpsp-05`. Connect local Netplay manually, then choose
   Join Group after the CLI prompt. Do not reuse an expired previous Pair code.
3. Verify the leader appears in the game's list, select it, then check both
   CLI status and the game. `Bridge active` proves RFU traffic, not trade success.
4. Preserve logs from both PCs on failure; do not keep retrying. Counts should
   advance from advertisement writes to connect_request/connect_accept and then
   client_send/host_send/client_ack. Record the first stable failure separately
   from cleanup. Share no raw captures, trainer fields, keys or save files publicly.
5. After a normal room exit, use the same Pair/process/Netplay for a second room.
   Ctrl+C ends only owned SwitchTrade resources. See the
   [VMware runbook](GPSP_VMWARE_RUNBOOK.md) for installation, owned cleanup and
   residue checks. Leave all physical software stopped until the user returns.

## Modularity

Conversion remains inside `endpoints/retroarch_gpsp`; Switch-to-Switch does not
use it. Core/Relay remain endpoint-neutral and payload-opaque. Another emulator
needs its own transport/protocol adapter and qualification, not recapturing all
Pokémon actions if it exposes equivalent RFU bytes. RFU1 is gpSP-specific; no
mGBA/VBA capability or automatic frontend control was added.
