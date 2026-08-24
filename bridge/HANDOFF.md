# HANDOFF — frlg-ldn-trade-emu 리포 인계 문서

> 작성: 2026-08-22 | 작성자: 아리아 (ox-alpha 세션)
> 인수자: 다음 개발 세션 (사람 또는 에이전트)
> **읽기 전에**: 프로젝트 전체 그림·배포 전략은 mwl-SwitchTrade 리포의 docs/를 참조하세요.
> 이 문서는 **이 리포(동작 코드 본체) 안에서 무엇을 어떻게 끝내는지**만 다룹니다.

---

## 2026-08-24 override — absolute-VBlank movement cadence fixed

Commit `53d8878` replaces `work + sleep(full VBlank)` in `run_live()` with a monotonic absolute
59.727 Hz deadline. Busy Pia/Reliable/RFU work is now subtracted from the 16.74 ms period instead of
being added to it, which is the root cause of the user's ~half-rate jittery remote-avatar movement.
Late ticks resynchronize to the current clock without producing catch-up bursts. Connection setup,
active gameplay, and the post-disconnect tail all use the same pacer.

Focused parent/Pia is 16/16 PASS and the ordinary WSL suite is 139/139 PASS. The user explicitly
deferred the visual hardware comparison until returning, so do not claim live smoothness yet and do
not request a full trade merely to test cadence; room entry plus walking is sufficient.

Authoritative report:
`mwl-SwitchTrade/docs/48-absolute-vblank-movement-cadence-fix-20260824.md`.

---

## 2026-08-24 override — full trade and atomic room exit live PASS

The PC-host one-trade golden path is complete on real hardware. Capture
`logs/golden/pc_host_atomic_exit_switcha_retry_live_20260824_212450/`, Switch A, and build `946bc63`
passed Pia/Reliable/RFU bootstrap, room entry, party exchange, trade animation, commit/save, post-save
menu rebuild, final cancel, return-field standbys 11/12, atomic two-player `EXIT_ROOM`,
`READY_CLOSE_LINK`, and RFU `D`. CODEX offered the user's captured Rattata and saved a valid Magikarp.
All pcaps had zero kernel drops, Pia logged zero decrypt failures, and both radios passed post-RX.

The atomic invariant is hardware-proven: child `EXIT_ROOM` must arm `linkstate.exit()` inside
`Sim._on_gba_in()` before the same tick's parent UNI generation. Do not move this back to the outer
loop; the old consecutive-frame response hung at the escort dialogue.

The user saw native `2318-0006` only after the termination animation had completed. Build `57a25c9`
fixes this outer LDN tail: after parent-mode RFU `D`, stop game frames but keep the AP alive until the
Switch leaves or five seconds elapse. It passes focused parent 15/15 and ordinary WSL 138/138 but is
hardware-unverified by user choice. The successful trade/room termination itself is not conditional
on that follow-up.

The two preceding Switch B failures were earlier protocol boundaries (one before held keys, one in
animation before `READY_FINISH_TRADE`) and did not reach atomic exit. The unchanged-build Switch A
pass plus zero drops/post-RX PASS rules out a deterministic `946bc63` or adapter receive-death defect.

Authoritative report:
`mwl-SwitchTrade/docs/47-full-trade-atomic-exit-pass-20260824.md`.

---

## 2026-08-24 override — full save/menu re-entry live PASS; final close delay ready

Build `5cb19af` passed the full real-Switch post-save reconstruction gate. CODEX offered the user's
captured Rattata, received and saved a valid 100-byte Pidgey, mirrored Switch-originated save counts
5 through 10, re-armed the five parent party/mail/ribbon pulls, and completed them at 247.3 s. The
user directly confirmed that the Switch returned successfully to the usable Pokémon trade screen.

Evidence: `logs/golden/pc_host_parent_reentry_live_20260824_200611/` (local/ignored,
integrity-locked by `MANIFEST.md`). Pia contains 17,708 datagrams with zero decrypt failure logged;
all three captures had zero kernel drops; both radios passed post-test actual-RX and were restored to
channel 6.

Only the final graceful close remains. `5cb19af` sent owner-zero `BOTH_CANCEL_TRADE` on the same
frame as the final ribbon block, while the Switch was entering `CB2_CreateTradeMenu` state 7. The ROM
does not install `CB1_UpdateLink` until state 22, after rebuilding the sprites/backgrounds/HP bars
and completing the palette fade, so the early command was not consumed and counts 11/12 were not
answered.

Commit `823288b` adds a one-time 120-frame menu-build wait after the final post-save block, then
sends the existing final cancel. It passes the focused wire regression, 136 ordinary WSL tests, and
4/4 Windows relay tests. This is not hardware-proven yet. The next live run must offer
`mons/0001_BULBASAUR_user_20260824.pk3` (last run used Rattata) and prove final cancel, counts 11/12,
room exit, and no native communication error. Do not modify lower layers; join, Reliable, trade,
finish, save, and party re-entry all passed.

Authoritative report:
`mwl-SwitchTrade/docs/45-parent-menu-reentry-live-pass-final-close-delay-20260824.md`.

---

## 2026-08-24 override — CONFIRM_FINISH live PASS; reactive save return ready

Commit `812fb90` passed its exact real-Switch gate. Local and child `READY_FINISH_TRADE` completed,
parent sent owner-zero `CONFIRM_FINISH_TRADE`, and the received Rattata was committed to a valid
100-byte `received.pk3`. After the forced return-path disconnect, the user confirmed Salamence
remained on the Switch, proving its cartridge-side save also persisted.

The Switch then completed standby counts 5 through 10. The old save-chain driver immediately
invented count 11, which the Switch never answered; the screen remained at
`Communication standby... Please wait.`. This isolates the remaining failure after the commit.

Evidence: `logs/golden/pc_host_confirm_finish_live_20260824_194059/` (local/ignored; integrity-locked
by `MANIFEST.md`). Pia captured 20,421 datagrams with no decrypt failure logged, all three pcaps had
zero kernel drops, and both post-test actual-RX gates passed.

Commit `cea2d75` applies the minimal source-defined fix: while the ROM performs its real save, CODEX
does not predict a barrier count or delay. It waits for each Switch-originated
`READY_EXIT_STANDBY` and uses the existing reactive responder. Party re-exchange remains the normal
chain terminator; the dead-host watchdog remains only a safety net. The regression test proves an
idle post-confirm tick cannot invent or advance a count.

WSL ordinary is 136 PASS and Windows relay is 4/4 PASS (140 functional). This commit is not yet
hardware-proven. Resume with one full trade; PASS is post-save party re-exchange, CODEX Cancel, and
graceful room exit. Persistence is already proven.

Authoritative report:
`mwl-SwitchTrade/docs/44-confirm-finish-live-pass-save-count-fix-20260824.md`.

---

## 2026-08-24 override — full animation live PASS; finish commit implemented

Commit `2d66c08` passed its complete real-Switch gate. Both confirmation blocks completed, parent
sent owner-zero `START_TRADE`, the count-4 scene-seam standby completed, the full animation ran, and
the user saw `Take good care of SALAMENCE`. The child then sent `READY_FINISH_TRADE`.

The host was stopped at that boundary. After returning to neutral, the Switch restored the user's
original Rattata. This independently proves the visible swap is provisional until the
player-zero finish-confirm transaction.

Evidence: `logs/golden/pc_host_start_trade_live_20260824_191729/` (local/ignored, integrity-locked by
`MANIFEST.md`). Pia was 7333/7333 authenticated with zero failures; all three pcaps had zero kernel
drops; both post-test actual-RX gates passed. Joined-session teardown again exceeded 15 seconds, but
exact stale-AP cleanup and both radio health checks passed.

Commit `812fb90` implements only the source-defined next gate:

- separately latch local and child `READY_FINISH_TRADE` after START;
- wait for the local owner-zero READY send and child READY block to complete;
- send owner-zero `CONFIRM_FINISH_TRADE` only when both are ready and no sender is active;
- commit locally at that same boundary and enter the existing save/return state.

The focused wire test proves owner zero, the two-sided finish gate, one commit, and entry into the
leaving sequence. WSL ordinary is 136/136 and Windows relay is 4/4 (140 functional passes). The full
Windows discovery run's six `test_detect_phy` setup errors are Windows/Linux-symlink fixture
incompatibility, not failures in this patch.

This commit is not hardware-proven yet. All live processes are stopped while the user is away. On
resume, PASS requires parent `CONFIRM_FINISH_TRADE`, visible save/return progress, and no rollback
after neutral state. Do not claim full completion until the next capture proves the leader
save/return/menu-reentry path.

Authoritative report: `mwl-SwitchTrade/docs/43-full-animation-pass-confirm-finish-ready-20260824.md`.

---

## 2026-08-24 override — selection live PASS; confirmation/START implemented

The `b26b588` live run passed its exact hardware gate. The Switch sent
`READY_TO_TRADE cursor=1`; the parent immediately broadcast
`SET_MONS_TO_TRADE local_cursor=1 child_cursor=1`; and the user visibly reached
`Is this trade okay?`. The user accidentally confirmed Yes, yielding the additional child
`INIT_BLOCK` at 194.2s. CODEX was intentionally stopped there, so the subsequent native error was
expected and is not a protocol regression.

Evidence: `logs/golden/pc_host_leader_selection_live_20260824_190447/` (local/ignored). Pia was
5398/5398 authenticated with zero failures, all three pcaps had zero kernel drops, both post-test
actual-RX gates passed, and teardown was clean.

Commit `2d66c08` implements only the next source-defined leader gate:

- CODEX applies the existing validity/confirm-YES path and sends owner-zero `INIT_BLOCK` after
  `SET_MONS_TO_TRADE`;
- the parent separately latches the Switch's completed `INIT_BLOCK`;
- only after both confirmations complete does player zero broadcast owner-zero `START_TRADE`;
- the local engine enters `S7_ANIM`, allowing the existing wireless scene-seam standby/animation
  path to take over.

The test proves both owner-zero INIT blocks, their exact 20-byte payloads, child confirmation
reassembly, the two-sided gate, and `S7_ANIM`. WSL ordinary is 136/136 and Windows relay is 4/4
(140 functional passes). WSL discovery still has only the known missing-`uvicorn` relay setup error.

Next live PASS: after the user selects and confirms a Pokémon, observe parent `INIT_BLOCK`, child
`INIT_BLOCK`, parent `START_TRADE`, and the visible start of the trade animation. Stop there before
implementing player-zero `CONFIRM_FINISH_TRADE`.

Authoritative report: `mwl-SwitchTrade/docs/42-selection-live-pass-start-trade-ready-20260824.md`.

---

## 2026-08-24 override — player-zero selection broadcast implemented; live test pending

Commit `b26b588` implements the next source-defined parent transition without extending beyond the
next observable gate. Parent mode now:

- records CODEX's configured Pokémon selection locally instead of emitting the follower-only
  `READY_TO_TRADE`;
- reassembles the Switch's 20-byte `READY_TO_TRADE` block and retains its cursor;
- after the already-live-proven five party pulls complete, sends an owner-zero
  `SET_MONS_TO_TRADE` containing CODEX's cursor;
- stores the Switch cursor for later validity/received-Pokémon handling;
- requires the exact response counts `(17,17,17,19,4)` for the party/mail/ribbon pulls, preventing
  a later two-fragment LINKCMD from falsely satisfying the ribbon gate.

This matches `pret/pokefirered` `SetReadyToTrade`, `Leader_ReadLinkBuffer`, and
`Leader_HandleCommunication`: player one transmits READY, player zero records its own READY locally,
and only player zero broadcasts SET_MONS after both are ready.

Verification: the focused wire test checks the real leader selection branch, child block
reassembly, owner-zero INIT framing, the exact `SET_MONS_TO_TRADE` payload, both cursors, and the
`S6_CONFIRM` transition. WSL ordinary tests are 136/136 and Windows relay integration is 4/4, for
140 functional passes. WSL discovery still reports only the known relay `setUpClass` environment
error because that venv lacks `uvicorn`.

This implementation is not hardware-proven yet. The next live test must stop when the user selects
a Pokémon and the Switch displays `Is this trade okay?`. Confirmation is deliberately not driven in
this commit. The following source-defined layer is both players' `INIT_BLOCK`, followed by the
player-zero `START_TRADE` broadcast.

Authoritative report:
`mwl-SwitchTrade/docs/41-player-zero-selection-implemented-20260824.md`.

---

## 2026-08-24 override — parent party exchange and visible trade menu live PASS

The real Switch accepted `0b8a2ab` through all five parent pulls:

```text
type 1 party pair #1 -> child block complete
type 1 party pair #2 -> child block complete
type 1 party pair #3 -> child block complete
type 3 mail          -> child block complete
type 4 ribbons       -> child block complete
```

At 502.2s the engine reached `P5_IN_TRADE`, and the user confirmed the Pokémon trade/party-selection
screen was visibly open. Pia authentication was 4567/4567 with zero failures, every capture had zero
kernel drops, and both radios passed post-test actual RX. The host vifs disappeared promptly on this
stop; the 15-second teardown timeout did not reproduce.

The exact next boundary is player-zero leadership after menu selections. The current `TradeEngine`
is follower-oriented: it emits `READY_TO_TRADE`, `INIT_BLOCK`, and `READY_FINISH_TRADE`, then reacts
to leader broadcasts. Parent mode must instead aggregate its configured local selection with the
Switch's `READY_TO_TRADE`, then send owner-zero `SET_MONS_TO_TRADE`. Later owner-zero duties are
`START_TRADE` after both `INIT_BLOCK` confirmations and `CONFIRM_FINISH_TRADE` after both
`READY_FINISH_TRADE` blocks.

Implement the selection transition as a contained parent shim and preserve the live-proven follower
path. The next live PASS is the Switch showing `Is this trade okay?` after the user selects a Pokémon
and chooses Trade. Authoritative report:
`mwl-SwitchTrade/docs/40-live-party-menu-pass-next-leader-gate-20260824.md`. Evidence is local/ignored
at `logs/golden/pc_host_parent_party_pulls_live_20260824_183308/`.

---

## 2026-08-24 override — post-seat barriers live PASS; player-zero party pulls implemented

The live `ff81318` retest passed the exact required hardware order:

```text
child READY -> parent READY
child count 2 -> parent count 2 twice
child count 3 -> parent count 3 twice
```

The Switch then remained at `Communication standby... Please wait.`. It sent no later AppData, while
the PC parent continued `SEND_HELD_KEYS` and issued no `SEND_BLOCK_REQ`. This proves the count-order
fix and moves the boundary to the previously acknowledged missing player-zero `BufferTradeParties`
driver. Discovery, CCMP, Pia, Reliable, row-one FIFO, room entry, movement, and counts 0..3 are all
behind the boundary.

Commit `0b8a2ab` implements only that next source-defined gate. After child count 3 completes it:

- latches the trade-menu/held-key cutoff;
- issues request types `1,1,1,3,4` (three 200-byte party pairs, 220-byte mail, 40-byte ribbons);
- preserves the ROM's `timer > 10` delay between requests;
- advances only after both the PC block sender and a new complete child block epoch finish.

Verification: parent/Pia 12/12, WSL ordinary 135/135, Windows relay 4/4, 139 functional tests total.
The WSL discovery command still reports the pre-existing relay `setUpClass` error because that venv
lacks `uvicorn`; the same four relay tests pass in `.audit-venv`.

Next live gate: run one health-gated CODEX-host join on `0b8a2ab`, enter the room, sit, and make no
extra input until the party menu appears. A pass is five ordered request/dual-block completions and a
visible trade selection menu. Stop at the first new boundary; the likely subsequent unproved layer is
player-zero `SET_MONS_TO_TRADE` / `START_TRADE` / confirmation leadership.

Authoritative analysis: `mwl-SwitchTrade/docs/39-post-seat-live-pass-parent-party-pulls-20260824.md`.
Local immutable evidence:
`logs/golden/pc_host_post_seat_standby_live_20260824_181522/`.

---

## 2026-08-24 override — trading-room live PASS; post-seat counts 2/3 fixed

The live `0a8d9a0` retest passed every parent-host gate through interactive room movement. Child
LinkPlayer fragments `0..16` all occupied parent row one in order, both trainer cards and standby
counts 0/1 passed, both avatars entered the trading room, and held-key movement remained stable.

The first new failure occurred only after the user sat and initiated the trade. Decrypted Pia showed:

```text
child READY 0x16 -> parent READY
child READY_EXIT_STANDBY count=2 (repeated)
parent READY_EXIT_STANDBY count=3 (repeated; no parent count=2)
```

This was a software role-inversion deadlock, not radio/Reliable loss. Parent mode applied the
child-initiated leader rule only to counts 0/1, while the reused follower TradeEngine advanced to
count 3 as soon as reflected child count 2 set its apparent `barrier.host_count`.

`ff81318` extends the existing parent shim through all four entry counts `0..3`: reply twice with the
child's exact count, preserve the measured gaps only after 0/1, and suppress follower-engine entry
standbys until the child initiates each round. The guest path is unchanged. Verification is parent/Pia
12/12, WSL ordinary 135/135, and Windows relay 4/4 (139 passes total).

Next live gate: use `ff81318`, enter the CODEX room, sit, and initiate trade. Required order is child 2
-> parent 2, child 3 -> parent 3, then trade-menu/party traffic. Do not retune discovery, radio, CCMP,
Pia, Reliable, or row-one FIFO; all passed in the same capture. Authoritative analysis:
`mwl-SwitchTrade/docs/38-live-trading-room-pass-post-seat-standby-fix-20260824.md`.

Evidence is local/ignored at
`logs/golden/pc_host_parent_reflection_fifo_live_20260824_175304/`. Joined-session teardown remains a
separate defect: the radio thread exceeded its 15-second grace, but selector recovery and both post-RX
health checks passed.

---

## 2026-08-24 override — parent Reliable and NI gates live-proven/implemented

The first corrected one-Switch host capture crossed ARP and Pia, then showed
the Switch retransmitting `WC` because the PC did not participate in Reliable.
The native CH1 two-Switch gold locked the missing bootstrap:

```text
guest INIT fff0, FireRed metadata
host  CTRL ACK: next=fff1
guest WC fff1: connect id 1a51
host  INIT fff0: WA = 57410600 fcc3 1a51 0000
host  CTRL ACK: next=fff2 (batched after WA)
guest CTRL ACK: next=fff1
```

`fcc3` is the native host's beacon RFU session id, not a new random value.  The
2026-08-24 `pc_host_parent_wa_live_20260824_151803` run proved the implementation
on hardware: the Switch ACKed PC `WA`, `parent_link_accepted=True`, and all 79
captured Pia records authenticated.  It then repeated a child NI_START 17 times
because the PC emitted only Pia Reliable ACKs.

The native post-WA exchange was decoded with 18,257/18,257 protected frames and
18,252/18,252 Pia datagrams authenticating.  Host mode now additionally:

- emits the parent idle `T` poll;
- mirrors each child NI subframe with the three-byte parent LLSF ACK;
- emits `WG=0` after the child's NI NULL;
- sends the exact five-frame parent NI transfer carrying `JOIN_GROUP_OK=5`;
- advances that transfer only on a matching child RFU ACK;
- emits `WG=1` and periodic parent idle polls after bidirectional NI completes.

`HostConnectionManager.connected` deliberately remains false.  Parent UNI is
still a distinct final room-entry gate; the mature child/RIGHT-seat engine must
not be released in host mode.

Teardown correction: skipping ldn's local self-DESTROY fixes a no-peer stop
(1.191 s), but the joined live run still left the host radio thread alive after
the 15-second grace.  Treat joined-session teardown as unresolved.  The stale
AP was removed only after the process exited, then both radios passed post-test
actual RX.

Verification baseline:

```text
python -m unittest -v tests.test_pia_host                 # 8/8 PASS
ordinary emulator suite (relay integration excluded)     # 131/131 PASS
relay integration in current venv                        # setup error: uvicorn absent
RTL8192EU no-peer host stop                               # PASS, stop 1.191 s
RTL8192EU joined-session host stop                        # FAIL, thread alive after 15 s
both radios post-test actual RX                           # PASS
```

## 2026-08-24 override — native PC-host Session bytes acquired

The old “EMU frozen” decision below predates the WSL dual-radio gold and the
real Switch PC-host test.  The current `gptsolreview` branch has reopened only
the PC-host interoperability path:

- LDN protocol 3 / application version 88 is now wire-correct.
- A real Switch displays and joins the PC-created room.
- The 2026-08-24 observer capture proved LDN authentication succeeds but the
  old joiner-only Pia manager emits zero host outreach.
- A fixed-channel native two-Switch capture supplied the complete missing gate:
  six NetStation records, Session `0 -> 2/5 -> 6`, and the first Reliable exchange.
- `HostConnectionManager` now emits the byte-verified Net `0x11`, Session type `2`,
  and Session type `5`, then recognizes the Switch's type `6` finalize.
- The first corrected smoke test exposed a lower-layer rtl8xxxu representation bug: the
  monitor vif retained Protected/CCMP header/MIC around hardware-decrypted SNAP. Kinnay
  double-decrypted and silently dropped every Switch ARP before `ldn-tap`.
- `install_monitor_ccmp_compat()` normalizes that retained-wrapper form at runtime. Tests and
  replay of the exact failing pcap deliver 8/8 Switch data frames and 7/7 ARPs.
- Patched live validation passed ARP, Net `0x12`, Session `0 -> 2/5 -> 6`, and FireRed Reliable
  INIT with 119/119 Pia decrypts. The Switch then sent 77 sequential `WC` connect requests
  because the PC did not ACK `fff0` or send the native host `WA` accept.
- `connected` intentionally remains false after `pia_connected`: the existing Reliable/RFU
  engine is the guest/child role. The next implementation is now authorized by live evidence:
  host bulk ACK of `fff0`, native `WA` accept, then parent RFU/NI direction.

Focused gates: `python -m unittest -v tests.test_pia_host` (6 tests) and
`python -m unittest -v tests.test_monitor_ccmp_compat` (2 tests).
The legacy join path is unchanged apart from fixing `parse_net()` so the fixed
fields following an inner `size=0` header are no longer discarded and applying
the documented LDN constant-ID permutation.

Main analysis/handoff:

- `mwl-SwitchTrade/docs/30-native-fixed-handshake-20260824.md`
- `mwl-SwitchTrade/docs/31-pc-host-monitor-ccmp-20260824.md`
- `mwl-SwitchTrade/handoff/HANDOFF-20260824-native-host-session.md`

---

## 0. 리포 정체성 선언 (2026-08-22 방향 전환 반영)

| 항목 | 결정 |
|---|---|
| 이 리포의 역할 | **동작 코드 본체** — framerelay(프로덕션) + legacy EMU(동결 보존) |
| EMU 트랙 (frlgtrade.py 조인 경로, frlgsim/) | 🔒 **개발 종료·동결** — 폴백 자산으로만 보존. 신규 기능 추가 금지 |
| framerelay (framerelay/, common/mwlb.py) | ⭐ **유일한 활성 개발 트랙** — 프로덕션 본체 |
| 배포 형태 | WSL2 서비스 (framerelay를 띄우는 것) — 절차서는 mwl-SwitchTrade docs/12-wsl2-poc-windows.md |
| upstream (tornadus/frlg-ldn-trade) | 동기화 중단. AGPL 출처 표기만 유지 |

**브랜치 현황** (2026-08-22 기준):
- `framerelay-dev` = `origin/main` = `3836984` — **모든 기능이 main에 반영 완료**
- 로컬 `main`, `stabilize`는 framerelay-dev의 부분집합 → 히스토리 손실 없음, 필요 없으면 삭제 가능
- 앞으로 작업은 **framerelay-dev에서 → main으로 PR/머지** 권장 (또는 직접 main 커밋도 무방)

---

## 1. 이 세션(2026-08-22)까지 반영된 기능 — 커밋 대장

| # | 커밋 | 기능 | 검증 |
|---|---|---|---|
| 1 | `1622751` | **framerelay 코어**: radio.py(모니터 캡처/radiotap 8B 주입/BSSID 필터) + bridge.py(투명 중계/EchoGuard/비콘 재생) + CLI + 테스트 23건 | 오프라인 ✅ |
| 2 | `5514b66` | nl80211 임포트 수정 — `ldn.wlan` 모듈 글로벌 참조 (실환경·스텁 양쪽 호환) | 오프라인 ✅ + 실기 ✅(T2.3) |
| 3 | `63e5572` | 다중 방 선택 픽스 — comm-id 미매칭 + joinable≥2일 때 최소 참가자 방 선택 | 오프라인 ✅ + 실기 ✅(T4h2 guest) |
| 4 | `ad591b5` | 릴레이 WS 스레드 미기동 픽스 (`start_remote()` 호출 누락 — T4에서 발견한 치명 버그) | 오프라인 ✅ |
| 5 | `0185cf8` | audit 청소 H-1~H-4/M-1/M-2/M-5: heartbeat 10s, outbox cap 200(newest-wins), WS 무한 백오프, 비콘 TTL 1.5s, EchoGuard prune, recv errno 분류, websockets 명시 | 오프라인 ✅ |
| 6 | `b4f329e` | RFU 비콘(application_data) 인코더 `frlgsim/beacon.py` — roundtrip 테스트 | 오프라인 ✅ |
| 7 | `0c8d7c8` | **호스트 모드** `--mode host` — HostTransport(ldn create_network)로 브리지가 직접 방 개설 | 오프라인 ✅ / 실기 ❌미검증 |
| 8 | `3836984` | TokenBucket rate limiter (200fps) — EchoGuard 안전망용. **아직 bridge.py에 미연결 (의도적)** | 오프라인 ✅ (15케이스) |

기반 안정화(stabilize 계열, WP-B~H): BSSID 고정(`--target-bssid auto`) 실기 실증, 스캔 타임아웃 계층, free_radio 정직 로그, phy 자연정렬, 래퍼 v6.1 — 전부 framerelay-dev 히스토리에 포함.

## 2. 사용법 빠른 참조

```bash
# [트랙 B] framerelay 브리지 (프로덕션 본체) — 각 스위치 옆 PC에서 1개씩
sudo .venv/bin/python -m framerelay \
    --iface wlx00ada7117309 \
    --host-mac <로컬_스위치_MAC=LDN softAP BSSID> \
    --relay-url http://<릴레이>:8788 --session-id <6자리> \
    --role host|guest --verbose

# [트랙 A·동결] EMU 조인 (폴백/회귀 테스트용)
sudo bash run_trade_v6.sh --live --verbose --keys /root/.switch/prod.keys \
    --trades 1 --target-bssid auto \
    [--relay-url ... --session-id ... --role host|guest] \
    -o 받을파일.pk3 줄파일.pk3

# [신규] 호스트 모드 (브리지가 방을 엶 — 8192EU 필수, AP 지원 카드)
sudo .venv/bin/python frlgtrade.py --mode host ...
```

릴레이 서버: `uvicorn relay.server:app --host 0.0.0.0 --port 8788` (mwl-SwitchTrade 리포 relay/)
세션 생성: `curl -X POST http://127.0.0.1:8788/session/create`

## 3. 검증 상태 매트릭스

| 항목 | 오프라인 | 실기 |
|---|---|---|
| framerelay 데이터플레인(캡처→0x20→WS→주입) | ✅ 23케이스 | ❌ 미실측 |
| radiotap 8B TX 헤더 주입 성공 | ✅ (구현) | ✅ **V-1로 확정 (2026-08-22)** — 주입↔재캡처 바이트 완전 일치 8/8회 |
| EchoGuard 바이트 동등성 전제 | ✅ **시나리오 A 확정** (`fd99200`) | ✅ **V-1 완료** — 드라이버 FCS 덮어쓰기 없음(rtl8xxxu+커널 7.0). 카드/커널 변경 시 재실행 |
| 호스트 모드(create_network) | ✅ 컴파일+회귀만 | ❌ 미실측 (STEP 7 AP+monitor 실측이 선행) |
| 비콘 TTL/백오프/outbox cap | ✅ | ❌ (장애 주입 테스트 필요) |

## 4. 알려진 미해결 이슈

1. ~~V-1~~ → ✅ **해소 (2026-08-22)**: 시나리오 A 확정. STEP 6은 "rate limiter를 bridge.py에 연결"로 재정의됨 (EchoGuard 재구현 불필요)
2. **CanTradeSelectedMon 게이트**: T4 E2E에서 양쪽 EMU가 자기 파티 기준으로 취소 판정 (EMU 트랙 한계 — framerelay와 무관하나 회귀 테스트 시 참고)
3. RX decrypt FAILED 간헐 관찰 (VM1+8192EU, Pia 확립 초기)
4. 8188EU 수신 사망 잦음 → authorized 토글 복구 절차 확립됨. card-watch.sh 감시 권장

---

## 5. 🎯 앞으로 이 리포에서 해야 할 일 (끝까지 — 순서대로)

### STEP 5 — ✅ V-1 실측 완료 (2026-08-22, `fd99200`)
- **결과: 시나리오 A 확정** — 같은 카드 위 모니터 vif 2개(vif_tx/vif_rx)로 주입→재캡처 8/8회 바이트 완전 일치
- 드라이버(rtl8xxxu)는 모니터 주입 시 FCS를 계산·덮어쓰지 않음 (틀린 FCS도 그대로 통과 확인)
- 캡처 radiotap에 FCS-present 비트 없음. PACKET_IGNORE_OUTGOING 지원(커널 7.0)
- 상세 기록: mwl-SwitchTrade docs/13 §0
- **파급**: STEP 6 재정의 — EchoGuard 재구현 불필요 → "rate limiter를 bridge.py에 연결"로 변경

### STEP 6 — ✅ rate limiter 연결 완료 (2026-08-22, `1fef24c`)
- ~~EchoGuard 재구현~~ 불필요 (V-1 시나리오 A 확정 — 현행 sha1 유지)
- 완료: TokenBucket을 bridge.py 양방향 데이터 경로(capture→relay / ws→inject)에 연결
  - 기본 200fps (docs/13 §7), 드롭 시 stats["dropped_rate"] 카운트 + 1/s 스로틀 경고
  - CLI `--rate-fps` 오버라이드, stop() 종료 로그에 limiter 통계 포함
  - 테스트 23→28케이스 (양방향 캡·정상 트래픽 통과·stats 라인 검증)
- 전체 회귀: 7개 스위트 전부 통과

### STEP 7 — AP+monitor 동시 vif 실측 (VM1, 8192EU)
- `iw phy` valid interface combinations 확인 → create_network(AP) + monitor 공존 확인
- 호스트 모드의 하드웨어 전제 검증. 실패 시 호스트 모드는 8192EU 단독 운용으로 제한 기록

### STEP 8 — 호스트 모드 브로드캐스트 검증 (VM1+VM2, 스위치 불필요) 🎯
- VM1이 `--mode host`로 방 개설 → **VM2 카드가 스캔해서 EMU 방이 보이는지**
- VM2에서 비콘 디코딩(`_dump_beacon`) → beacon.py 인코더 산출물과 필드 대조
- 통과하면 스위치 없이도 브로드캐스트 정합성 확보

### STEP 9 — framerelay 무선 단독 흐름 관찰 (VM1+VM2)
- 호스트 모드(VM1) 상태에서 framerelay 캡처→0x20→WS 로그 흐름 확인
- EchoGuard 동작(셀프 에코 차단) 실측

### STEP 10 — 호스트 모드 실기 검증 (스위치 A)
- 스위치 A 화면의 방 검색 리스트에 EMU 방 표시 + 조인 성공
- 실패 시: application_data 필드별 디버깅 (beacon.py)

### STEP 11 — framerelay 실기 E2E 🏆 (스위치 A·B, 케이블/거리 분리 권장)
- **B 화면에 "A의 방" 표시 = 목표② 달성 순간**
- 조인 → 트레이드 완주. ACK 유실률 관찰 (docs/12 §V-4)
- 막히면 플랜 B: 관리 프레임만 중계 + 데이터 Pia 우회 (07-framerelay-design §4)

### STEP 12 — 안정성 시나리오 5종
- 네트워크 5초 차단 회복 / WS 재접속(백오프 실측) / 장시간 유지 / 비콘 TTL 동작 / outbox cap 동작

### STEP 13+ — 배포 연계 (mwl-SwitchTrade 리포와 공동)
- WSL2 서비스 패키징 시 이 리포에서 필요한 것: `framerelay/ common/mwlb.py requirements.txt` (+선택: frlgsim 제외 가능)
- usbipd-win 카드 attach → G1~G6 게이트는 docs/12-wsl2-poc-windows.md 따름

### 리포 관리 잔무 (틈날 때)
- [ ] 로컬 `stabilize` 브랜치 처리 (내용 포함됨 — 삭제 또는 태그)
- [ ] `tests/` 전체를 CI로 (GitHub Actions — 별도 `mwl313/wsl2-kernel-build` 패턴 참고)
- [ ] README.md 갱신 (방향 전환 반영: framerelay 메인, EMU 동결 표기)
- [ ] THIRD-PARTY-LICENSES.md (AGPL 출처) — 통합 작업 시 mwl-SwitchTrade 쪽과 정합 유지

## 6. 절대 규칙 (변경 금지 사항)

1. **push는 mwl-SwitchTrade 오너 승인 후** (기본 금지 유지)
2. frlgsim/(EMU) 파일 수정 금지 — 동결. 단, transport.py의 nl80211 참조 구조는 framerelay와 무관하게 유지할 것
3. `common/mwlb.py` 프레임 포맷 변경 금지 — Track A(legacy)와 바이트 동등성 계약
4. 릴레이 서버(relay/server.py, mwl-SwitchTrade 리포) 수정 시 HEARTBEAT_TIMEOUT과 bridge heartbeat(10s) 비율 유지
5. 테스트 깨진 채로 커밋 금지 — py_compile + tests/ 전부 통과 조건

## 7. 참조 문서 (mwl-SwitchTrade 리포)

| 문서 | 내용 |
|---|---|
| docs/12-framerelay-구조와-로드맵.md | 전체 그림 + STEP 1~17 마스터 로드맵 (본 핸드오프 STEP 5~13의 상위 문서) |
| docs/10-framerelay-audit-20260822.md | audit 원문 (H/M/L 이슈 — STEP 1에서 H·M 대부분 해소, 잔여 M-3/M-4/M-6/L급) |
| docs/13 (echoguard design prep) | V-1 결과별 분기 설계 |
| docs/14-hardware-matrix.md | 카드 매트릭스 (호스트=8192EU 필수 등) |
| docs/12-wsl2-poc-windows.md | WSL2 배포 게이트 G1~G6 |
| docs/11-실기테스트-리포트-20260822.md | T0~T4 실측 전체 기록 |

---
*끝. 질문은 mwl-SwitchTrade 리포 docs/ 또는 이 커밋 히스토리로 추적 가능합니다.*
