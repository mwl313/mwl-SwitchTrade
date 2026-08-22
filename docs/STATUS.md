# STATUS — 진행 상태 (2026-08-22)

> 마지막 갱신: 2026-08-22 저녁 — **framerelay 메인 전환 확정 · STEP 1~5 완료 · V-1 시나리오 A 확정**

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

## 📈 Phase 진행도 (2026-08-22 기준)

| Phase | 내용 | 진행도 |
|---|---|---|
| 0 | 환경 준비 | ✅ 100% |
| 1 | PoC 재현 | ✅ 100% |
| **2a** | 릴레이 인프라 (RemoteTransport+relay 서버+FSM 훅) | ✅ 100% |
| **2b** | LAN 2브리지 실기 | 🔄 ~70% — 단독 트레이드·양방향 조인 실증, E2E 양방향 교환만 잔여 |
| **2b'** | framerelay 코어 | 🔄 코드 완성 — STEP 6~7(레이트리미터 연결·AP+monitor 실측) 잔여 |
| 3 | 세션 시스템 + GUI (PySide6 확정, `docs/13-userside-app-plan.md`) | 설계 완료 |
| 4 | 프로덕션 배포 (WSL2 길 A, `docs/12-wsl2-poc-windows.md`) | α트랙 준비 완료 |

## 🔀 리포 구조 (2026-08-22 확정)

| 리포 | 역할 |
|---|---|
| **mwl313/mwl-SwitchTrade** | 문서·릴레이 서버·WSL2 배포 인프라·스크립트 |
| **mwl313/frlg-ldn-trade-emu** (emu/) | **동작 코드 본체** — framerelay(메인) + EMU(동결). `emu/HANDOFF.md`가 작업 대장 |

- 브랜치: `framerelay-dev` = 최신 (양쪽 리포 push 완료). 로컬 `main`/`stabilize`는 부분집합
- ~~MWL-SwitchTrade-v2~~: 삭제됨 (고유 내용 0)

## 하드웨어 매트릭스 (`docs/14-hardware-matrix.md`)

| 카드 | HOST(방 개설) | GUEST | 비고 |
|---|---|---|---|
| RTL8192EU (`0bda:818b`) VM1 | ✅ AP 노출 | ✅ | LDN join 실증(T1/T3) |
| RTL8188EU (`0bda:8179`) VM2 | ❌ AP 없음 | ✅ | join·모니터 실증(T3), 수신 사망 잦음→토글 복구 |

## 알려진 미해결 이슈

1. **EMU E2E 미완주** (T4): 릴레이 WS 미기동 버그 수정(ad591b5) 후 재실행 필요 — 단, EMU는 동결이라 회귀 도구 용도
2. CanTradeSelectedMon 게이트 (EMU 한계) — framerelay와 무관
3. RX decrypt FAILED 간헐 (VM1+8192EU 초기)
4. 호스트 모드(--mode host): 코드 완성, **실기 미검증** — STEP 7(AP+monitor 동시 vif)이 선행
5. 8188EU 수신 사망 → authorized 토글 복구 절차 확립, card-watch 권장

## 다음 단계 (순서대로)

1. **STEP 6 (재정의)**: rate_limit.py → bridge.py 연결 (EchoGuard 재구현은 V-1 시나리오 A로 불필요) — T0
2. **STEP 7**: AP+monitor 동시 vif 실측 (VM1, 8192EU) — 호스트 모드 전제 검증
3. **STEP 8~9**: 호스트 모드 브로드캐스트 검증 (VM1+VM2, 스위치 불필요) 🎯
4. **α트랙**: WSL2 무선 기반 검증 G1~G4 (동글 1개, GitHub Actions 커널 빌드 산출물)
5. **STEP 10~13**: 스위치 실기 (호스트 모드 → framerelay E2E 🏆 → 안정성 5종)
6. 프로덕션: γ(GUI 셸) / δ(릴레이 운영) / β(installer)

상세 실행 절차: `emu/HANDOFF.md` STEP 5~13 | 마스터 로드맵: `docs/12-framerelay-구조와-로드맵.md`

## 파일/백업

- 트레이드 결과: `received-20260821/`, `received-20260821-2/`
- VM 백업: `backup-vm-20260821/`
- 워크플로우: `docs/04-trade-workflow.md` (래퍼 v6.1 기준)
- T4 로그 백업(Mac /tmp): `logs_t4h3.txt`, `logs_t4g.txt` — 영구 보관 원하면 received/로 이동 필요
