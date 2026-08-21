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

1. **Phase 2 상세설계** (`docs/05-phase2-design.md`) — RemoteTransport + 릴레이 서버
2. LAN 2브리지 테스트 → 인터넷 (Tailscale 활용) 검증
3. Phase 3: 세션 ID 매칭 + 클라이언트

## 파일/백업

- 트레이드 결과: `received-20260821/`, `received-20260821-2/`
- VM 백업: `backup-vm-20260821/` (코드/키/몬 파일)
- 워크플로우: `docs/04-trade-workflow.md`
