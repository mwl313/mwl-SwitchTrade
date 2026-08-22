# STATUS — 진행 상태 (2026-08-22)

> 마지막 갱신: 2026-08-22 — **P0/P1 안정화 완료 + 실기 테스트 T0~T3 통과, T4 블로커 수정 대기**

## 🏆 핵심 성과

**2026-08-21**: 트레이드 2세션 연속 성공 — 마일스톤 M0 달성 (워크플로우 v1 재현)
**2026-08-22**: P0+P1 안정화 패치 전체 실기 검증 — T0~T3 통과(7/8), T4에서 신규 버그 발견·수정안 확정
- 상세: `docs/11-실기테스트-리포트-20260822.md`
- C-4 BSSID 고정 **실증** (dmesg assoc MAC 일치), kill 후 vif 청소, phy 자동감지, 래퍼 v6.1 전부 실기 확인
- nl80211 임포트 버그 2연쇄 수정 (f249d8f → 5514b66) — 오프라인 스텁으로는 발견 불가능했던 케이스

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
| 래퍼 | run_trade.sh v5 (usbreset 방식) — **v6 신규(`scripts/run_trade.sh`, 8e3d5f7)·VM 미배포** |
| 스캔 | `/home/aria/scan_phy.py` (trio.fail_after 30s) |

## 알려진 문제 & 대응

| 문제 | 대응 |
|---|---|
| 카드 수신 사망 (USB 절전/IQK, 30분~1시간 주기) | usbreset → pnputil(Windows) → usbreset 조합. 최후 Windows 재시작 |
| 스캔 found 0 (카드 생존) | 스위치 앱 재시작 → 리더 재진입 (5GHz/슬립 대응) |
| EBUSY | wlx down 후 스캔 / unmanaged 확인 |
| ldnclient 잔여 vif | `sudo iw dev ldnclient del` (조인 전 정리) |
| 프로세스 잔류 | `sudo pkill -INT -f frlgtrade.py` |

## 🧩 P2 완료 — Audit 수정 플랜 WP-B~G (2026-08-22)

플랜: `docs/plan/2026-08-22-audit-fix-plan.md` (WP-A 준비 = 955248a, ldn 0.0.17 소스 스냅샷 고정)

| WP | 내용 | 리포 | 커밋 |
|---|---|---|---|
| B | **C-4(CRITICAL-1) 재구현** — args 주입(87bd4fe)은 ldn 0.0.17 구조상 무효로 폐기 → `station._wlan` 요청 프록시로 NL80211_ATTR_MAC 실주입 + b-lite(조인 후 `_host_address` 불일치 즉시 예외→재시도) + MED③(pinning 로그는 실제 패치 성공 시만) + 버전 가드. 신규 테스트 9건 | emu | `e91c6ac` |
| C | H-2 pin race — **별도 커밋 없음**. WP-D의 join-grace 직렬화(늙은 스레드 완전 회수 후 다음 attempt, grace 초과 시 잔여 시도 포기)로 구조적 차단. `_ASSOC_TARGET` 세대 토큰화는 미구현 (플랜 원안 대비 잔여) | emu | ba10d61에 흡수 |
| D | **H-1 타임아웃 예산 계층화** — 스캔 fail_after 30→20 < start 기본 30→45 + 재시도 전 이전 스레드 join(grace 15s)·alive면 포기 + D-1 주석 갱신(fail_after는 checkpoint에서만 발동 — 커널 hang 근본 방어 아님, 외부 워치독 병행 필수) | emu | `ba10d61` |
| E | **MEDIUM② free_radio 정직 로그** — 삭제 후 sysfs 재조회로 removed/FAILED 구분 + 전체 실패 시 sudo 루트 힌트 1회. 신규 테스트 6건 | emu | `b500543` |
| F | **MEDIUM① detect_phy 결정적 선택** — phy 번호 자연 정렬 최솟값(phy2 < phy10) + 복수 후보 경고 + roots 파라미터화. 신규 테스트 5건 | emu | `8c21eba` |
| G | **CRITICAL-2 래퍼 v6** — `scripts/run_trade.sh`: SCRIPT_DIR 탐색+EMU_DIR 오버라이드, 카드 ID 자동 감지 리셋(8179/**818b**, sysfs authorized 폴백), --phy는 C-2 위임, stale 프로세스 정리(D-9), timeout 900 워치독, --dry-run. docs/04 v6 기준 갱신(v5 폐기). VM 배포 후 적용 | 프로젝트 | `8e3d5f7` |

**⚠️ Mac 오프라인 검증만 완료 — 실기 검증은 스위치 필요.** 오프라인 회귀 29건 전부 통과 (relay 4 + FSM 5 + bssid 9 + free_radio 6 + detect_phy 5, 2026-08-22 실행). 실기 체크리스트는 플랜 §5, VM 동기화(tar+scp) 전까지 VM 미적용.


## 다음 단계

0. **P0+P1+P2 안정화·Audit 수정 완료 (2026-08-22)**: P0 = D-1(커밋 5fb729f) + C-1(6f747af). P1 = C-3(79c2e51, `scripts/setup-nm-unmanaged.sh`) + C-2(332c69b, --phy USB ID 자동 감지) + C-4(87bd4fe → WP-B 재구현 e91c6ac). P2 = 위 WP-B~G 표. 모두 오픈코드(ox-alpha) 위임. **⚠️ Mac 로컬에만 커밋됨 — VM 동기화(tar+scp) 전까지 VM 미적용. 실기 검증(스위치) 전**
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
