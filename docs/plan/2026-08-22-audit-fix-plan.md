# MWL-SwitchTrade Audit 수정 계획 (2026-08-22)

> 작성: 옥스 알파 (opencode plan 모드) | 정리: 아리아
> 대상: CRITICAL-1/2, H-1/2/3, MEDIUM ①②③ | 제약: git push 금지, 작은 단위 커밋, 실기 검증은 스위치 필요(분리 표기), VM 동기화 tar+scp
> 리포 구분: **emu 코드 → `emu/` 별도 리포(브랜치 stabilize)**, 스크립트/문서 → 프로젝트 리포

## 0. 배경 (Audit 확정 이슈)

| 등급 | ID | 내용 |
|---|---|---|
| CRITICAL-1 | C-4 무효 | --target-bssid의 args/kwargs 주입 방식은 ldn 0.0.17 `Station._connect_network(self)`(인자 없음, attrs 지역변수)에 끼워넣을 곳이 없음. 설치/pinning 로그만 뜨고 실제 주입 없음 (VM 소스 직접 확인) |
| CRITICAL-2 | 래퍼 v5 불일치 | VM run_trade.sh가 ①구 클론 경로 실행(패치 무시) ②usbreset 0bda:8179 하드코딩(현재 카드 818b) ③--phy 강제+C-2 우회+금지된 phy0 폴백 |
| HIGH-1 | D-1 한계 | fail_after는 checkpoint에서만 발동 — 커널 blocking hang엔 무력. 스캔 타임아웃 30s == _ready.wait 예산 30s라 스레드 overlap 위험 |
| HIGH-2 | pin race | 전역 _ASSOC_TARGET 단일 슬롯 — 재시도 시 늙은 attempt 스레드 finally가 새 pin 덮어쓰기 가능 |
| HIGH-3 | C-1 미검증 | attempt 2~3 재시도 시 monitor 사전셋업 없이 join되는 것 실기 미검증 |
| MED① | detect_phy | 카드 2개 동시장착 시 sorted() 문자열 정렬 임의 선택 ("phy10"<"phy2") |
| MED② | free_radio 로그 | 삭제 실패도 "removed" 성공 로그 |
| MED③ | C-4 로그 | 패치 설치 실패해도 "pinning" 로그 출력 |

## 1. 워크패키지 요약 (1 WP = 오픈코드 위임 1회 = 독립 커밋)

| WP | 이슈 | 리포 | 변경 파일 | 오프라인 검증 | 실기 검증 |
|---|---|---|---|---|---|
| A | — (준비) | 프로젝트 | `docs/plan/*`, `docs/research/ldn-0.0.17-src/` 커밋 | 문서 검토 | 불필요 |
| B | **CRITICAL-1** + MEDIUM③ | emu | `frlgsim/transport.py`, `tests/test_bssid_patch.py`(신규) | 스텁 유닛테스트 | ⭕ 2스위치 |
| C | H-2 | emu | `frlgsim/transport.py`, 테스트 추가 | 스텁 유닛테스트 | ⭕ 재시도 경로 |
| D | H-1 | emu | `frlgsim/transport.py` | 예산 계산 유닛테스트 | ⭕ 스캔 타임아웃 |
| E | MEDIUM② (+H-3 체크리스트화) | emu | `frlgsim/transport.py` | 로그 분기 유닛테스트 | ⭕ attempt 2~3 |
| F | MEDIUM① | emu | `frlgtrade.py`, `tests/test_detect_phy.py`(신규) | tempdir sysfs 테스트 | ⭕ 카드 2개 |
| G | **CRITICAL-2** | 프로젝트 | `scripts/run_trade.sh`(신규 v6), `docs/04-trade-workflow.md` | shellcheck + dry-run | ⭕ VM 스모크 |
| H | 문서 수렴 | 프로젝트 | `STATUS.md`, `handoff/`, docs | — | 불필요 |

## 2. WP 상세

### WP-A — 준비: 플랜 저장 + ldn 소스 스냅샷 커밋 ✅ (이 커밋)
- 근거 소스(ldn 0.0.17)를 리포에 고정 (`docs/research/ldn-0.0.17-src/`).

### WP-B — CRITICAL-1: C-4 재구현 (`_wlan` 요청 감시 방식) + MEDIUM③
- **목적**: args/kwargs 주입이 구조적으로 불가능한 ldn 0.0.17에서 실제 ATTR_MAC 주입이 일어나게 한다.
- **변경**: `emu/frlgsim/transport.py`, 신규 `emu/tests/test_bssid_patch.py`
- **구현 접근** (§3 추천안 = (a)+(b-lite)):
  1. 기존 몽키패치 골격 유지 (설치 가드/버전드리프트 폴백).
  2. 래퍼를 asynccontextmanager로 재작성: `station._wlan`을 프록시로 임시 교체 → 원본 CM 수명 동안 유지 → 종료 시 원복.
  3. 프록시는 `__getattr__` 전달 + `request(cmd, attrs)`만 가로채어 `cmd == NL80211_CMD_CONNECT`이고 attrs가 Mapping일 때 `attrs[NL80211_ATTR_MAC] = bssid` in-place 주입 (attrs는 호출자 지역 dict — 참조 공유로 원본 request까지 전달, wlan.py 1309–1336행 구조와 일치). `receive()` 등은 무수정 전달 (`_process_messages`가 사용).
  4. **(b-lite)** CM 진입 후 `station._host_address`(=커널 CONNECT 이벤트의 실제 BSSID, 1348행) ≠ pin이면 즉시 예외 → start() attempts 재시도.
  5. **MED③**: "pinning..." 로그는 patch 설치 True일 때만.
- **검증**: Mac — fake ldn/nl80211 스텁 유닛테스트 6건 (CONNECT만 주입 / NEW_KEY·DISCONNECT 무영향 / receive 전달 / pin 없으면 stock / host_address 불일치 예외 / 실패 시 폴백). 기존 9테스트 회귀. **VM**: dmesg assoc MAC == 대상 BSSID.
- **위험**: `_host_address` 비공개 의존 → getattr 가드, 없으면 검증 생략(주입은 유지). target_bssid=None 경로 회귀 0.

### WP-C — H-2: `_ASSOC_TARGET` 토큰화
- set/clear에 generation 토큰 — 늙은 스레드 clear 무효화. WP-B 이후 착수(같은 코드 영역).

### WP-D — H-1: 타임아웃 예산 계층화 + 스레드 overlap 가드
- 스캔 `fail_after(20)` 축소, `start(timeout=45)` 확대 (내부 < 외부 보장). 재시도 전 이전 스레드 join(grace) 후 alive면 남은 시도 포기+명확한 에러. D-1 주석에 "커널 hang 근본 방어 아님" 명시.

### WP-E — MEDIUM② + H-3: free_radio 삭제 결과 정직 로그
- 삭제 후 재조회 확인 → removed / FAILED 구분 로그. H-3은 §5 실기 체크리스트 항목으로 분리.

### WP-F — MEDIUM①: `detect_phy` 결정적 선택
- phy 번호 자연 정렬 최솟값 선택 + 복수 후보 경고. `detect_phy(log, roots=None)` 파라미터화.

### WP-G — CRITICAL-2: 래퍼 v6 (`scripts/run_trade.sh`) + 문서 갱신
- SCRIPT_DIR 기준 emu 탐색(env 오버라이드 가능) / lsusb 0bda:8179·**818b** 자동 감지 usbreset(+sysfs authorized 토글 폴백 = C-6 씨앗) / modprobe 금지 유지 / --phy 강제 제거(C-2 위임) / stale 프로세스 정리(D-9 씨앗) / 본체 `timeout 900` 워치독 / --dry-run 모드.
- docs/04-trade-workflow.md를 v6 표준으로 갱신 (v5 폐기 표기).

### WP-H — 문서 수렴
- STATUS/handoff 갱신, "실기 검증 필요" 목록 명시, ldn 업스트림 diff 초안 준비 ((c) 트랙 씨앗).

## 3. CRITICAL-1 접근 비교·추천

| 접근 | 판정 |
|---|---|
| (a) `_wlan.request` 프록시 주입 | ✅ **주전략** — 0.0.17 소스(1336행 참조 전달)와 정확히 일치, 조인 수명으로 스코프 한정, site-packages 무수정, 실패 시 stock 폴백 |
| (b) 조인 후 BSSID 검증 | ✅ **b-lite 통합** — iw 파싱 대신 ldn 내부값 `_host_address`(1348행) 활용, 불일치 시 예외→attempts 재시도 |
| (c) 업스트림 기여 | 🕐 병행 준비 — diff 초안 WP-H에서 준비, 런타임 패치에 `ldn.__version__` 가드로 upstream 반영 시 자동 무효화 |

## 4. 실행 순서·의존성

```
A (플랜 저장+스냅샷 커밋)
└─ B (C-4 재구현) ── C (토큰화) ── D (예산 계층)
G (래퍼 v6) — B와 병렬 가능
E, F 독립 / H 마지막
```

- 커밋 스타일: `transport: ...` / `frlgtrade: ...` / `scripts: ...` / `docs: ...`, push 금지.
- 각 WP 완료 시 Mac 회귀: test_relay_offline.py + test_fsm_hook.py (+신규).

## 5. 실기 검증 통합 체크리스트 (스위치 켤 때 한 번에)

```
0. 동기화: emu(stabilize HEAD) + scripts/ tar+scp → VM ~/emu 교체, 래퍼 v6 설치
1. 기반: lsmod rtl8xxxu / nmcli wlx unmanaged / setup-nm-unmanaged.sh 적용(재부팅 적용)
2. 감지: lsusb(8179|818b) → frlgtrade auto-detect 로그 = 실제 phy (F)
3. 단독 스캔: scan_phy.py found 1, fail_after 동작 (D)
4. 연속 join ×3 (kill 포함): 잔류 vif 0, removed/FAILED 로그 정직 (E, H-3)
5. C-4: --target-bssid auto → patched/pinning 로그 + 조인 성공,
       dmesg assoc MAC == 대상 BSSID, 2스위치 동시 광고에서 자기 스위치만 연결 (B)
6. race: 조인 타임아웃 유도 → 재시도 attempt에서 pinning 유지 (C)
7. H-1: 스캔 방해 상황 → TooSlowError → 재시도 → VM 생존(SSH 유지) (D)
8. 래퍼 v6: 경로 무관 실행, 818b 리셋 자동감지, --phy 미지정, 종료 후 up 유지 (G)
9. E2E: 트레이드 1회 (docs/04 워크플로우) → received .pk3 확인
10. 기록: docs/07 실측 추가 + handoff 갱신, 미통과 항목은 잔여 목록으로
```

---
*계획 수립: 2026-08-22, 옥스 알파(opencode plan) + 아리아 통합. 실행 승인: 주인님 (2026-08-22)*
