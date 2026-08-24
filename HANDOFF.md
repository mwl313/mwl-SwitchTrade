# HANDOFF — frlg-ldn-trade-emu 리포 인계 문서

> 작성: 2026-08-22 | 작성자: 아리아 (ox-alpha 세션)
> 인수자: 다음 개발 세션 (사람 또는 에이전트)
> **읽기 전에**: 프로젝트 전체 그림·배포 전략은 mwl-SwitchTrade 리포의 docs/를 참조하세요.
> 이 문서는 **이 리포(동작 코드 본체) 안에서 무엇을 어떻게 끝내는지**만 다룹니다.

---

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

Focused gates: `python -m unittest -v tests.test_pia_host` (5 tests) and
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
- [ ] `tests/` 전체를 CI로 (GitHub Actions — mwl-SwitchTrade scripts/wsl2/github-build/ 패턴 참고)
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
