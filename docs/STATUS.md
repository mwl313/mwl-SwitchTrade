# STATUS — 진행 상태 (2026-08-21)

> 마지막 갱신: 2026-08-21 15:40 — **Phase 2 설계 착수**

## 🏆 핵심 성과 (Phase 0/1 완료)

**2026-08-21: 트레이드 2세션 연속 성공 — 마일스톤 M0 달성**
- 1차: 뮤/세레비/지라치 ↔ 꼬렛 3마리
- 2차: 스타터 3마리 + 보만다 Lv.100 ↔ 구구2+꼬렛2
- **워크플로우 v1 재현 확인** — 같은 절차로 연속 성공 = "운이 아니라 절차"

## 📈 Phase 진행도

| Phase | 내용 | 진행도 |
|---|---|---|
| 0 | 환경 준비 | ✅ 100% |
| 1 | PoC 재현 + 코드 이해 | ✅ ~90% (transport 확장점 파악) |
| **2** | **PC↔PC 인터넷 브리지** | 🎯 설계 중 (`docs/05-phase2-design.md`) |
| 3 | 세션 시스템 + 클라이언트 | 0% |
| 4 | 확장 (배틀/GSC) | 0% |

## 현재 환경 (검증된 성공 조합)

| 항목 | 값 |
|---|---|
| VM | aria@100.109.113.113 (Tailscale) |
| 커널 | 7.0.0-30-generic |
| 드라이버 | rtl8xxxu (8188eu/rtl8188eus 사용 금지) |
| NM | wlx unmanaged (`/etc/NetworkManager/conf.d/unmanaged-wlx.conf`) — **reload 금지, 재부팅으로만** |
| transport.py | 하이브리드 패치 (free_radio 유지 + nmcli/down 제거) |
| 래퍼 | run_trade.sh v5 (usbreset 방식) |
| 스캔 | `/home/aria/scan_phy.py` (trio.fail_after 30s) |

## 알려진 문제 & 대응

| 문제 | 대응 |
|---|---|
| 카드 수신 사망 (USB 절전/IQK, 30분~1시간 주기) | usbreset → pnputil(Windows) → usbreset 조합. 최후 Windows 재시작 |
| 스캔 found 0 (카드 생존) | 스위치 앱 재시작 → 리더 재진입 (5GHz/슬립 대응) |
| EBUSY | wlx down 후 스캔 / unmanaged 확인 |
| ldnclient 잔여 vif | `sudo iw dev ldnclient del` (조인 전 정리) |
| 프로세스 잔류 | `sudo pkill -INT -f frlgtrade.py` |

## 다음 단계

0. **P0+P1 안정화 완료 (2026-08-22)**: P0 = D-1(커밋 5fb729f) + C-1(6f747af). P1 = C-3(79c2e51, `scripts/setup-nm-unmanaged.sh`) + C-2(332c69b, --phy USB ID 자동 감지) + C-4(87bd4fe, --target-bSSID 옵트인 BSSID 고정 assoc). 모두 오픈코드(ox-alpha) 위임, 테스트 9건 통과. **⚠️ Mac 로컬에만 커밋됨 — VM 동기화(tar+scp) 전까지 VM 미적용. C-4는 실기 검증 전**
1. **Phase 2a 완료 (2026-08-21)**: RemoteTransport + 공용 릴레이(`relay/server.py`) + FSM 훅(`_notify_remote`/`apply_remote`) — 테스트 9개 전부 통과 (relay 4 + fsm 5)
2. **2b (LAN 2브리지)**: 카드 2대 준비 완료 (8188EU + 8192EU, rtl8xxxu 동일 드라이버, 모니터 TX 검증됨). VM 복제 + 릴레이 경유 트레이드가 다음 마일스톤
3. Phase 3: 세션 ID 매칭 + 클라이언트

## 코드 구조 (2026-08-21 분리)

- 트랙 A (리더-리더 EMU): `emu/` — frlgsim + RemoteTransport + FSM 훅
- 트랙 B (리더-조인 프레임 중계): `framerelay/` — 다른 대화에서 개발 (공용 릴레이 사용)
- 공용: `relay/server.py` — 상세는 `docs/06-code-structure.md`

## 파일/백업

- 트레이드 결과: `received-20260821/`, `received-20260821-2/`
- VM 백업: `backup-vm-20260821/` (코드/키/몬 파일)
- 워크플로우: `docs/04-trade-workflow.md`
