# STATUS — 진행 상태 (2026-08-24)

> 마지막 갱신: 2026-08-24 — **player-zero selection 실기 PASS · confirmation/START 구현 완료/실기 대기**

## 🏆 핵심 성과

**2026-08-21**: 트레이드 2세션 연속 성공 — 마일스톤 M0 달성 (워크플로우 v1 재현)
**2026-08-22 낮**: P0+P1 안정화 패치 전체 실기 검증 — T0~T3 통과(7/8) (`docs/11-실기테스트-리포트-20260822.md`)
- C-4 BSSID 고정 **실증** (dmesg assoc MAC 일치), kill 후 vif 청소, phy 자동감지, 래퍼 v6.1
- nl80211 임포트 버그 2연쇄 수정 (f249d8f → 5514b66), T4 다중 방 선택 픽스(63e5572), start_remote 미기동 픽스(ad591b5)
**2026-08-22 저녁**: **프로젝트 방향 전환 확정 + STEP 1~5 완료**
- **framerelay(트랙 B) = 프로덕션 메인**, EMU(트랙 A) = 동결·폴백 보존 (`emu/README_MWL.md`, `emu/HANDOFF.md`)
- MWL-SwitchTrade-v2 껍데기 삭제 (고유 내용 0 확인 후)
- STEP 1~4 오픈코드 위임 완료: audit 청소(`0185cf8`) / RFU 비콘 인코더(`b4f329e`) / 호스트 모드(`0c8d7c8`) / EchoGuard 설계+rate limiter(`ffa79d9`)
- **V-1 실측 완료 — 시나리오 A 확정** (`fd99200`): 주입↔재캡처 바이트 완전 일치(8/8회), 드라이버 FCS 덮어쓰기 없음(rtl8xxxu+커널 7.0). → EchoGuard sha1 유지, 재구현 불필요
**2026-08-24**: **WSL2 무선 기반 카드별 판정**
- RTL8192EU는 custom WSL 6.18.35.2 + usbipd-win에서 monitor RX, CH1~13, health gate 및
  외부 RF TX injection(G4) 통과. 30분 연속 RX는 41,394 packets/0 kernel drops로 통과했다.
- RTL8188EU는 세 WSL kernel의 mainline `rtl8xxxu`에서 firmware MCU start `-11`로 실패하지만,
  pinned vendor `8188eu`는 monitor RX, CH1~13, 양방향 외부 RF TX와 frame-type G4를 통과했다.
  patched artifact는 warning-free load/RX를 통과했다. standalone AP beacon 108개도 외부 수신됐지만
  AP+monitor add/delete가 vendor cfg80211에서 deadlock되므로 project host role은 안전하게 차단한다.
  patched 5분 soak는 8,474 packets/0 kernel drops와 post-soak RX로 통과했다.
- profile-driven selector가 exact USB/driver/module/vermagic/SHA/role/actual-RX를 검사한 뒤 command를
  실행한다. Windows preflight도 VMware/usbipd 소유권 충돌을 실행 전에 차단한다.
- framerelay의 double-radiotap injection 결함을 수정했다(`82dd0d3`). MonitorRadio가 bare 802.11
  frame에 radiotap을 정확히 한 번만 붙이는 계약을 회귀 test로 고정했다.
- WSL runtime/keys를 설치하고 modular `ccm`/`cmac`/`tun` preflight를 추가했다. RTL8192EU에서 실제
  `HostTransport`가 AP+monitor/TAP/FRLG room-ready까지 통과하고 iface 0개로 clean stop했다.
- selector는 host teardown 후 netdev 0개 상태를 자동 복구하고, multi-vif monitor 우선 선택 및 stale
  vif 제거를 수행한다. HostTransport도 udev-renamed AP를 phy-scope로 정리한다.
- 상세: `docs/24-wsl-radio-validation-20260824.md`.
- Native Switch A/B 고정 CH1 capture에서 18,252 Pia datagram을 실패 0으로 복호화했다. Net `0x11`
  의 six-record station table, Session `0 -> 2/5 -> 6`, 첫 Reliable bootstrap과 graceful teardown까지
  확보했다. PC-host의 empty station table/accept 누락을 byte-verified 구현으로 교정했다. 상세:
  `docs/30-native-fixed-handshake-20260824.md`.
- Corrected PC-host smoke에서 Switch association과 강한 RF 수신은 통과했지만 ARP가 TAP에 도달하지
  않았다. RTL8192EU `rtl8xxxu`가 Protected/CCMP header+MIC를 남기고 payload만 hardware-decrypt한
  형태를 Kinnay가 재복호화해 silent drop한 것이 확정됐다. runtime compatibility adapter와 실측 pcap
  replay는 8/8 data, 7/7 ARP deliverable PASS했고 patched live join도 다음 항목처럼 통과했다. 상세:
  `docs/31-pc-host-monitor-ccmp-20260824.md`.
- Patched live 재검증에서 ARP request/reply, Net `0x12`, Session `0 -> 2/5 -> 6`, FireRed Reliable
  INIT까지 실기 PASS했다. Pia 119 datagram 모두 decrypt 성공, 실패 0. 화면의 동일한 unavailable은
  이제 PC가 guest `fff0`/`WC`를 ACK/`WA`하지 않는 host/parent Reliable gate 때문임이 확정됐다.
- Native CH1 gold의 `INIT fff0 -> ACK fff1 -> WC -> WA+ACK fff2 -> guest ACK fff1`를 exact decode했고,
  beacon RFU session id가 `WA` host id임을 확정했다. 별도 parent bootstrap으로 구현하고 native-byte
  test에 고정했다(`emu` `4478ec9`). child/right-seat RFU는 계속 차단되어 있으며 다음 실기 gate는
  Switch의 `WA` ACK이다. 상세: `docs/32-parent-reliable-bootstrap-20260824.md`.
- `pc_host_parent_wa_live_20260824_151803`에서 Switch가 PC `WA`를 ACK해
  `parent_link_accepted=True`가 실기 PASS했다. 79 Pia record decrypt 실패 0. 이후 Switch가 동일한 child
  NI_START를 17회 반복해 다음 실패층이 RFU NI임을 확정했다. Native gold를 18,257 CCMP/18,252 Pia 실패
  0으로 재검증하고 parent poll, child-NI ACK, `WG=0`, five-frame `JOIN_GROUP_OK`, `WG=1`를 byte-locked
  구현했다(`emu` `c69e213`). 다음 실기 gate는 `parent_ni_complete`와 child UNI 진입이다. 상세:
  `docs/33-parent-ni-gate-20260824.md`.
- `pc_host_parent_ni_live_20260824_154857`에서 Switch가 parent NI의 `JOIN_GROUP_OK=5`를 수락하고
  화면에 `CODEX says OK` → `Pokemon Trades! Awaiting other members!`를 표시했다. 5,456 Pia record는
  decrypt 실패 0이며, `WG=1` 뒤 parent/child UNI가 각각 0개라 마지막 대기 원인을 parent UNI 부재로
  확정했다. Native의 73-byte UNI(`460005` + 14-byte row 5개), `SEND_PLAYER_IDS`, LinkPlayer 교환,
  trainer-card/seat gate를 구현하고 137/137 test를 통과했다(`emu` `5c556ab`). 상세:
  `docs/34-live-parent-ni-pass-and-uni-bootstrap-20260824.md`.
- `pc_host_parent_uni_live_20260824_162720`에서 Switch가 `SEND_PLAYER_IDS`, type-0 block request와 양쪽
  LinkPlayer block을 실기 수락했다. PC는 Switch를 `GIRL v0x4004`로 복원했다. 직후 PC parent가 child용
  standby count 0을 약 5초 일찍 선제 전송해 communication error가 난 것이 native 18,252-Pia gold와의
  byte/timing 비교로 확정됐다. Parent는 child count 0/1을 기다려 각각 2회 응답하고 native idle gap 뒤
  card/seat로 진행하도록 교정했다(`emu` `e2979c7`, 137/137). 상세:
  `docs/35-live-linkplayer-pass-parent-standby-order-20260824.md`.
- `pc_host_parent_standby_live_20260824_165140`은 조기 parent standby가 사라졌음을 확인했지만, parent
  Reliable의 연속 seq hole 복구가 직렬화되어 LinkPlayer가 `WG=1` 뒤 약 3.17초를 소비했다. Switch는
  final fragment가 parent row 1에 반사되고 해당 Reliable 범위를 ACK한 뒤에도 `WG=1 + 3.557초`에 명시적
  `WD`를 보내 종료했다. Native는 같은 구간을 약 0.55초에 끝낸다. Guest 경로는 유지하고 parent만
  first-NACK/67ms/full-six-window recovery로 교정했으며 `WD` 종료도 처리한다(`emu` `31b29bf`, 138/138).
  상세: `docs/36-live-parent-deadline-and-reliable-recovery-20260824.md`.
- fast-recovery 재실기에서는 LinkPlayer가 약 `WG=1 + 1.7초`로 단축됐지만 게임 communication error 뒤
  Switch native `2318-0006`가 추가 표시되고 child가 `WD`를 보냈다. Incoming Reliable AppData는
  `fff0..0064` 완전 연속이고 child fragment `0..16`도 모두 PC에 도달했다. 그러나 한 Pia datagram에
  여러 child `T`가 합쳐질 때 단일 `_parent_child_cmd`가 덮어써져 parent row 1에는
  `3,5,7,12,13,16`만 반사됐다. Parent-only state-change FIFO로 `0..16` 순차 반사를 보장하고 exact
  repeat는 합쳤다(`emu` `0a8d9a0`, 139/139). 두 카드 post-RX health gate도 통과했다. 다음은 이 수정의
  실기 join이다. 상세: `docs/37-live-batched-child-reflection-fix-20260824.md`.
- `pc_host_parent_reflection_fifo_live_20260824_175304`에서 FIFO가 child LinkPlayer `0..16`을 전부 parent
  row 1에 순차 반사해 실기 PASS했다. Trainer card와 standby count 0/1 뒤 양 avatar가 trading room에
  입장했고 이동도 안정적으로 공유됐다. Chair에서 trade를 시작하자 child는 count 2를 반복했지만 PC
  parent가 count 2 없이 count 3으로 건너뛰어 black-screen mutual wait가 발생했다. 두 capture 모두 kernel
  drop 0, 양 카드 post-RX PASS다. Parent shim을 entry counts `0..3` 전체에 적용해 child count와 동일하게
  2회 응답하고 follower-engine 선행 count를 차단했다(`emu` `ff81318`, 139 PASS). 상세:
  `docs/38-live-trading-room-pass-post-seat-standby-fix-20260824.md`.
- `pc_host_post_seat_standby_live_20260824_181522`에서 `ff81318`이 실기 PASS했다. Child READY 뒤
  `child count 2 -> parent count 2(2회) -> child count 3 -> parent count 3(2회)`가 정확히 성립했다.
  Switch는 정상 pre-trade 문구 `Communication standby... Please wait.`에서 대기했으며, 이후 PC parent가
  `SEND_HELD_KEYS`만 계속하고 party request를 0개 보낸 것이 새 경계다. `pret/pokefirered`의
  `BufferTradeParties`를 재검증해 player zero가 `1,1,1,3,4`(party 3쌍/mail/ribbons)를 11-frame gap과
  양방향 block-complete gate로 pull하도록 구현했다(`emu` `0b8a2ab`, 139 functional PASS). Capture는 양
  radio kernel drop 0, Pia decrypt fail 0, post-RX 양쪽 PASS다. 상세:
  `docs/39-post-seat-live-pass-parent-party-pulls-20260824.md`.
- `pc_host_parent_party_pulls_live_20260824_183308`에서 `0b8a2ab`이 실기 PASS했다. Parent가
  `type 1 x3 -> type 3 -> type 4`를 순서대로 pull했고 Switch의 party 3쌍/mail/ribbons block이 모두
  완성된 뒤 `P5_IN_TRADE`에 진입했다. 사용자가 실제 Pokémon trade selection 화면 표시를 확인했다.
  Pia 4,567/4,567 auth PASS, 모든 pcap kernel drop 0, 양 card post-RX PASS다. 다음 정확한 경계는
  child `READY_TO_TRADE`와 CODEX local selection을 합쳐 player zero가 `SET_MONS_TO_TRADE`를 broadcast하는
  leader-only FSM이다. 상세: `docs/40-live-party-menu-pass-next-leader-gate-20260824.md`.
- player-zero selection gate를 `emu` `b26b588`에 구현했다. Parent mode는 CODEX 선택을 로컬 READY로
  기록해 follower-only `READY_TO_TRADE` 전송을 막고, child READY block/cursor를 완성한 뒤 owner-zero
  `SET_MONS_TO_TRADE`를 CODEX cursor로 broadcast한다. Party pull response count도
  `(17,17,17,19,4)`로 exact-gate해 후속 LINKCMD 오인 가능성을 제거했다. WSL ordinary 136/136,
  Windows relay 4/4(총 140 functional) PASS. 다음 실기 PASS 기준은 사용자가 Pokémon을 선택한 뒤
  Switch에 `Is this trade okay?`가 표시되는 것이다. 상세:
  `docs/41-player-zero-selection-implemented-20260824.md`.
- `pc_host_leader_selection_live_20260824_190447`에서 `b26b588`이 실기 PASS했다. Child
  `READY_TO_TRADE cursor=1` 뒤 parent가 owner-zero `SET_MONS_TO_TRADE`를 보냈고 사용자가 실제
  `Is this trade okay?` 화면을 확인했다. 사용자의 실수로 Yes까지 눌러 child `INIT_BLOCK`도 확보했다.
  이후 native error는 CODEX를 그 경계에서 의도적으로 중단한 결과다. Pia 5,398/5,398 auth, pcap 3개
  kernel drop 0, post-RX 양쪽 PASS, teardown clean. Local owner-zero `INIT_BLOCK`과 child INIT을 모두
  gate한 뒤 owner-zero `START_TRADE`를 보내고 `S7_ANIM`으로 진입하도록 구현했다(`emu` `2d66c08`,
  140 functional PASS). 다음 실기는 trade animation 시작 화면이 PASS 기준이다. 상세:
  `docs/42-selection-live-pass-start-trade-ready-20260824.md`.
- ldn 0.0.17 local-self DESTROY 수정은 no-peer stop(1.191초)만 해결했다. joined WA 실기 종료에서는
  radio thread가 15초 뒤에도 살아 있었다. process exit 후 selector stale-AP 청소와 양 카드 post-RX는
  PASS했지만 joined-session teardown root cause는 thread stack 확보 전까지 미해결이다.

## 📈 Phase 진행도 (2026-08-22 기준)

| Phase | 내용 | 진행도 |
|---|---|---|
| 0 | 환경 준비 | ✅ 100% |
| 1 | PoC 재현 | ✅ 100% |
| **2a** | 릴레이 인프라 (RemoteTransport+relay 서버+FSM 훅) | ✅ 100% |
| **2b** | LAN 2브리지 실기 | 🔄 ~70% — 단독 트레이드·양방향 조인 실증, E2E 양방향 교환만 잔여 |
| **2b'** | framerelay 코어 | ✅ leader selection 실기 완료; confirmation/START 구현·실기 대기 — finish/commit 잔여 |
| 3 | 세션 시스템 + GUI (PySide6 확정, `docs/13-userside-app-plan.md`) | 설계 완료 |
| 4 | 프로덕션 배포 (WSL2 길 A, `docs/12-wsl2-poc-windows.md`) | α G1~G4는 8192EU PASS, G5/G6 잔여 |

## 🔀 리포 구조 (2026-08-22 확정)

| 리포 | 역할 |
|---|---|
| **mwl313/mwl-SwitchTrade** | 문서·릴레이 서버·WSL2 배포 인프라·스크립트 |
| **mwl313/frlg-ldn-trade-emu** (emu/) | **동작 코드 본체** — framerelay(메인) + EMU(동결). `emu/HANDOFF.md`가 작업 대장 |

- 검토 브랜치: main은 `golden-capture-re`, emulator는 `gptsolreview`가 최신이며 push 완료. emulator의
  최신 parent party-pull 구현은 `0b8a2ab`, post-seat standby 수정은 `ff81318`, batched-child reflection 수정은 `0a8d9a0`, parent Reliable deadline 수정은 `31b29bf`,
  double-radiotap 회귀 방지는 `82dd0d3`이다.
  `framerelay-dev`는 그 이전 기능 기준선이다.
- ~~MWL-SwitchTrade-v2~~: 삭제됨 (고유 내용 0)

## 하드웨어 매트릭스 (`docs/14-hardware-matrix.md`)

| 카드 | HOST(방 개설) | GUEST | 비고 |
|---|---|---|---|
| RTL8192EU (`0bda:818b`) VM/WSL | 🟡 PC-host visible trade menu live PASS | ✅ | leader trade와 repeated clean teardown 잔여 |
| RTL8188EU (`0bda:8179`) WSL/vendor | ❌ project HOST 차단 | ✅ | standalone AP PASS, AP+monitor deadlock; monitor RX/TX G4 PASS |

## 알려진 미해결 이슈

1. **EMU E2E 미완주** (T4): 릴레이 WS 미기동 버그 수정(ad591b5) 후 재실행 필요 — 단, EMU는 동결이라 회귀 도구 용도
2. CanTradeSelectedMon 게이트 (EMU 한계) — framerelay와 무관
3. RX decrypt FAILED 간헐 (VM1+8192EU 초기)
4. 호스트 모드(--mode host): discovery/LDN/ARP/Pia Session/parent `WA`/NI/UNI/LinkPlayer/trainer-card/
   trading-room/이동/post-seat counts 0..3까지 실기 PASS. deadline-safe Reliable, batched row-one FIFO,
   reactive standby와 player-zero party pulls 실기 완료. 다음은 leader selection/confirm/trade
   구현·검증이다.
   `timeout --foreground`로 Ctrl-C 전달을 수정했지만 joined-session adapter
   teardown은 다음 graceful stop에서 별도 재검증한다.
5. 8188EU mainline firmware start 실패는 vendor-driver로 우회했다. out-of-tree driver 유지보수와
   실제 Switch G5/G6는 잔여 risk다.

## 다음 단계 (순서대로)

> **2026-08-22 밤 갱신**: STEP 6~9 완료!
> - STEP 6: rate limiter bridge 연결 (`1fef24c`)
> - STEP 7: AP+monitor 공존 PASS (`93d2277`, docs/15)
> - STEP 8: 호스트 모드 방 개설 + beacon head 패치로 **EMU 방 VM2 스캔 발견** (`bf22a85`, docs/16)
> - STEP 9: framerelay 캡처→0x20→WS 파이프라인 첫 무선 실증 (`46b492d`, docs/16)

1. ~~STEP 6~~ ✅ / ~~STEP 7~~ ✅ / ~~STEP 8~~ ✅ / ~~STEP 9~~ ✅
2. **STEP 10 discovery/join/room entry**: ✅ `ARP -> Net -> Session -> Reliable -> WA/NI/UNI ->
   LinkPlayer -> trainer card -> trading room/이동 -> post-seat count 2/3 -> party exchange -> visible
   trade menu` 실기 PASS. 다음 gate는 player-zero `SET_MONS_TO_TRADE` leadership.
3. **STEP 11**: 🏆 framerelay E2E (스위치 A·B) — B 화면에 "A의 방" = 목표② 달성
4. **α트랙 G1~G4**: 두 카드 기준 ✅(8188 patched warning-free guest/relay). 다음은 G5 로컬 루프, G6 Switch E2E
5. **STEP 10~13**: 스위치 실기 (호스트 모드 → framerelay E2E 🏆 → 안정성 5종)
6. 프로덕션: γ(GUI 셸) / δ(릴레이 운영) / β(installer)

상세 실행 절차: `emu/HANDOFF.md` STEP 5~13 | 마스터 로드맵: `docs/12-framerelay-구조와-로드맵.md`

## 파일/백업

- 트레이드 결과: `received-20260821/`, `received-20260821-2/`
- VM 백업: `backup-vm-20260821/`
- 워크플로우: `docs/04-trade-workflow.md` (래퍼 v6.1 기준)
- T4 로그 백업(Mac /tmp): `logs_t4h3.txt`, `logs_t4g.txt` — 영구 보관 원하면 received/로 이동 필요
