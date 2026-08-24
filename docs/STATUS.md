# STATUS — 진행 상태 (2026-08-24)

> 마지막 갱신: 2026-08-24 — **PC-host parent Reliable ACK/WC/WA 구현 · 실기 WA gate 대기**

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
- ldn 0.0.17이 종료 때 local AP 자신에게 DESTROY control frame을 보내 rtl8xxxu netlink가 대기하던
  HostTransport hang도 수정했다. RTL8192EU 실제 room stop 1.191초, vif 0개, post-stop RX PASS.

## 📈 Phase 진행도 (2026-08-22 기준)

| Phase | 내용 | 진행도 |
|---|---|---|
| 0 | 환경 준비 | ✅ 100% |
| 1 | PoC 재현 | ✅ 100% |
| **2a** | 릴레이 인프라 (RemoteTransport+relay 서버+FSM 훅) | ✅ 100% |
| **2b** | LAN 2브리지 실기 | 🔄 ~70% — 단독 트레이드·양방향 조인 실증, E2E 양방향 교환만 잔여 |
| **2b'** | framerelay 코어 | ✅ STEP 6~10 discovery/join 완료 — 다음은 live WA gate와 parent T/NI, STEP 11/G6 |
| 3 | 세션 시스템 + GUI (PySide6 확정, `docs/13-userside-app-plan.md`) | 설계 완료 |
| 4 | 프로덕션 배포 (WSL2 길 A, `docs/12-wsl2-poc-windows.md`) | α G1~G4는 8192EU PASS, G5/G6 잔여 |

## 🔀 리포 구조 (2026-08-22 확정)

| 리포 | 역할 |
|---|---|
| **mwl313/mwl-SwitchTrade** | 문서·릴레이 서버·WSL2 배포 인프라·스크립트 |
| **mwl313/frlg-ldn-trade-emu** (emu/) | **동작 코드 본체** — framerelay(메인) + EMU(동결). `emu/HANDOFF.md`가 작업 대장 |

- 검토 브랜치: main은 `golden-capture-re`, emulator는 `gptsolreview`가 최신이며 push 완료. emulator의
  최신 parent Reliable/teardown 수정은 `4478ec9`이며 double-radiotap 회귀 방지는 `82dd0d3`이다.
  `framerelay-dev`는 그 이전 기능 기준선이다.
- ~~MWL-SwitchTrade-v2~~: 삭제됨 (고유 내용 0)

## 하드웨어 매트릭스 (`docs/14-hardware-matrix.md`)

| 카드 | HOST(방 개설) | GUEST | 비고 |
|---|---|---|---|
| RTL8192EU (`0bda:818b`) VM/WSL | 🟡 ARP/Pia live PASS, ACK/WC/WA 구현 | ✅ | graceful teardown PASS; parent T/NI 잔여 |
| RTL8188EU (`0bda:8179`) WSL/vendor | ❌ project HOST 차단 | ✅ | standalone AP PASS, AP+monitor deadlock; monitor RX/TX G4 PASS |

## 알려진 미해결 이슈

1. **EMU E2E 미완주** (T4): 릴레이 WS 미기동 버그 수정(ad591b5) 후 재실행 필요 — 단, EMU는 동결이라 회귀 도구 용도
2. CanTradeSelectedMon 게이트 (EMU 한계) — framerelay와 무관
3. RX decrypt FAILED 간헐 (VM1+8192EU 초기)
4. 호스트 모드(--mode host): discovery/LDN/ARP/Pia Session/guest Reliable INIT까지 실증,
   host/parent ACK+`WA`와 graceful teardown 구현/오프라인+radio 검증 완료. 다음은 `WA` 실기 ACK 후
   parent `T`/NI 방향 구현이다.
5. 8188EU mainline firmware start 실패는 vendor-driver로 우회했다. out-of-tree driver 유지보수와
   실제 Switch G5/G6는 잔여 risk다.

## 다음 단계 (순서대로)

> **2026-08-22 밤 갱신**: STEP 6~9 완료!
> - STEP 6: rate limiter bridge 연결 (`1fef24c`)
> - STEP 7: AP+monitor 공존 PASS (`93d2277`, docs/15)
> - STEP 8: 호스트 모드 방 개설 + beacon head 패치로 **EMU 방 VM2 스캔 발견** (`bf22a85`, docs/16)
> - STEP 9: framerelay 캡처→0x20→WS 파이프라인 첫 무선 실증 (`46b492d`, docs/16)

1. ~~STEP 6~~ ✅ / ~~STEP 7~~ ✅ / ~~STEP 8~~ ✅ / ~~STEP 9~~ ✅
2. **STEP 10 discovery/join**: ✅ `ARP -> Net 0x11/0x12 -> Session 0/2/5/6 -> Reliable INIT` 실기 PASS.
   host bulk ACK + `WA`는 구현/회귀 PASS. 다음 gate는 Switch의 `WA` ACK 실기 확인 후 parent `T`/NI.
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
