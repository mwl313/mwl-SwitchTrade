# 11 — framerelay(트랙 B) 통신 구조 & 잔여 작업 로드맵 (2026-08-22)

> 작성: 아리아 | 브랜치: framerelay-dev (프로젝트·emu 양쪽)
> 목적: framerelay 개발의 기준 문서 — 통신 구조 전체 그림 + STEP별 잔여 작업 풀 리스트

---

## 1. 전체 그림

```
[Switch B] ←802.11→ [브리지B: radio.py] ←MWLB/WS→ [relay:8788] ←MWLB/WS→ [브리지A: radio.py] ←802.11→ [Switch A]
                     캡처→0x20 포장                    순수 bytes 파이프              0x20 풀기→주입
```

- 두 스위치는 **진짜 같은 방에 있는 것처럼** 동작 — 브리지는 프레임을 절대 해석하지 않음 (투명 중계)
- 암호화도 스위치끼리 직접 수행 → 브리지는 내용을 못 읽음
- 동기화 버그라는 개념 자체가 없는 구조 (트랙 A 대비 최대 장점)

## 2. 데이터 플로우 (한 프레임의 여정)

| 단계 | 컴포넌트 | 동작 |
|---|---|---|
| ① 캡처 | `MonitorRadio.recv()` | AF_PACKET raw 소켓 → radiotap 헤더 제거 → bare 802.11 프레임 |
| ② 필터 | `radio.accepts()` | addr1/2/3 중 내 스위치 MAC(`--host-mac`) 있을 때만 통과 |
| ③ 에코차단 | `EchoGuard.duplicate()` | 자기가 방금 주입한 프레임 재캡처 시 폐기 (무한 ping-pong 방지) |
| ④ 비콘캐시 | `is_beacon()` → `BeaconCache.add()` | 비콘만 캐시 (스캔 유지용) |
| ⑤ 포장·전송 | `mwlb.build_frame(0x20, frame)` → WS | relay는 bytes 파이프라 내용 몰라요 |
| ⑥ 수신·주입 | `on_ws_message()` | 0x20만 골라 → EchoGuard.record → radiotap 8B 헤더 부착 → 공중 주입 |
| ⑦ 비콘재생 | `BeaconReplayer` (100ms) | 캐시된 비콘 재주입 — B의 스캔이 A의 방을 놓치지 않게 |

### 구성 요소
| 파일 | 역할 | 크기 |
|---|---|---|
| `common/mwlb.py` | 공용 코덱 `[MWLB][type][len BE][payload]`, MSG_FRAME_RELAY=0x20, Track A와 바이트 동등성 보장 | 61줄 |
| `framerelay/radio.py` | 모니터 캡처(AF_PACKET)/주입(radiotap 8B 실측 헤더 필수)/BSSID 필터(addr1/2/3) | 185줄 |
| `framerelay/bridge.py` | 중계 루프 + EchoGuard + BeaconCache/Replayer + WS heartbeat·재연결(3회) | 312줄 |
| `framerelay/__main__.py` | CLI: `--iface --host-mac --relay-url --session-id --role host/guest --verbose` | 77줄 |
| `tests/test_framerelay.py` | 오프라인 23케이스 (양단 A→릴레이→B 왕복 시뮬 포함) | 366줄 |

---

## 3. 신규 발견: 호스트 모드 (방 브로드캐스트) — 프로토콜 이미 존재

kinnay/LDN에 호스트 모드가 완전히 구현돼 있음 (소스 확인 완료):

| 구성요소 | 위치 | 내용 |
|---|---|---|
| `CreateNetworkParam` | ldn/__init__.py:1074 | comm-id, scene_id, max_participants(8), **application_data**(RFU 검색 비콘), accept_policy, channel, password |
| `create_network(param)` | ldn/__init__.py:1953 | 호스트 모드 진입 |
| `Station.create()` | wlan.py:1436 | AP 기동 + 관리프레임 등록 |
| `_start_ap()` | wlan.py:1572 | **실제 브로드캐스트**: NL80211_CMD_START_AP + 직접 조립한 비콘(BEACON_HEAD/TAIL) + interval 100ms |

### 필요한 정보 (전부 확보됨)
- comm-id: `0x01006fa0233f8000` (스위치 광고 실측값)
- application_data: 0x5C Pia 헤더 + base85 인코딩 24B (TID·이니셜·RFU 세션ID) — **디코더만 있고 인코더 미구현**
- password: GBA 에뮬레이터 패스프레이즈 (transport.py 상수)

### 하드웨어 조건 (2026-08-22 실측)
- VM1 **8192EU: AP 모드 지원** ✅ (managed/AP/VLAN/monitor)
- VM2 8188EU: AP 없음 ❌ (managed/monitor만) → **호스트 역할은 VM1 담당**

### 호스트 모드의 이점
```
기존: 스위치A(리더 방 개설) ← EMU/framerelay 조인
신규: 브리지A가 방을 브로드캐스트 → 스위치A가 방 검색해서 조인 (조작 단순화)
```

---

## 4. 잔여 작업 풀 리스트 (실행 순서 + 하드웨어 티어)

> **상태 갱신 2026-08-22 밤**: STEP 1~6 완료. STEP 6은 "EchoGuard 재구현"에서
> "**rate limiter를 bridge.py에 연결**"로 재정의됨 — V-1 실측(docs/13 §0)으로 시나리오 A가
> 확정되어 EchoGuard 자체 변경은 불필요해졌기 때문. 커밋 `3836984`에서 의도적으로 미연결로
> 남겨둔 안전망(TokenBucket)만 연결하면 됨.

### 하드웨어 티어
| 티어 | 필요한 것 |
|---|---|
| 🖥️ T0 | Mac만 |
| 💻 T1 | VM1 + 8192EU |
| 💻💻 T2 | VM1+VM2+카드 둘 다 |
| 🎮 T3 | 스위치 A·B 포함 전부 |

### STEP 1~4: 🔥 지금 바로 (T0) — ✅ **전부 완료**
| # | 작업 | 상태 |
|---|---|---|
| 1 | framerelay audit 청소 (D-2~D-6) | ✅ `0185cf8` — heartbeat 10s/outbox cap/무한 백오프/비콘 TTL/prune/errno 분류/websockets |
| 2 | application_data 인코더 (H-1) | ✅ `b4f329e` — frlgsim/beacon.py + roundtrip 테스트 |
| 3 | 호스트 모드 CLI (H-2) | ✅ `0c8d7c8` — HostTransport + --mode host (join 경로 무수정, **실기 미검증**) |
| 4 | EchoGuard 설계 확정 준비 | ✅ `ffa79d9` — docs/13 분기표 + rate_limit.py(15테스트, 미연결) |

### STEP 5~7: 💻 VM1 필요
| # | 작업 | 판정 |
|---|---|---|
| 5 | V-1 주입↔재캡처 바이트 동등성 ⭐ | ✅ **완료 (`fd99200`)** — **시나리오 A 확정**: 바이트 완전 일치(8/8회), 드라이버 FCS 덮어쓰기 없음(rtl8xxxu+커널 7.0). 카드/커널 변경 시 재실행 |
| 6 | ~~EchoGuard 재구현~~ → **rate limiter 연결** (재정의) | ✅ **완료 (`1fef24c`)** — 양방향 경로 연결, 기본 200fps, 테스트 23→28 |
| 7 | H-3 AP+모니터 동시 vif 실측 | ⬜ 8192EU에서 vif 2개 + 채널 유지 (호스트 모드 전제) |

### STEP 8~9: 💻💻 VM2 추가
| # | 작업 | 판정 |
|---|---|---|
| 8 | **호스트 모드 브로드캐스트 검증** 🎯 | VM1이 방 개설 → VM2 카드가 스캔해서 EMU 방 보이는지 (스위치 없이 검증!) |
| 9 | framerelay 무선 단독 테스트 | 호스트 모드 + framerelay 캡처 흐름 관찰 |

### STEP 10~13: 🎮 스위치 필요
| # | 작업 | 판정 |
|---|---|---|
| 10 | 호스트 모드 최종 검증 | 스위치 A 방 리스트에 EMU 방 표시 + 조인 |
| 11 | **T4 재실행 — EMU E2E** 🏆 | 릴레이 세션 동기화(start_remote 수정 효과) → 양방향 교환 = 목표① 완료 |
| 12 | **framerelay E2E** 🏆🏆 | B 화면에 "DESTROY의 방" 표시 = 목표② 달성. ACK/SIFS 리스크(V-4) 관찰, 막히면 플랜 B |
| 13 | 안정성 시나리오 5종 | 끊김 회복/재조인/장시간 |

### STEP 13+: 🌐 프로덕션 (목표③)
| # | 작업 |
|---|---|
| 14 | 2c 인터넷 배포 (Cloudflare Tunnel + 이기종 네트워크 테스트) |
| 15 | Phase 3 UI (세션 ID 공유·클라이언트) |
| 16 | WSL2 PoC (Windows 배포 경로) |
| 17 | 원클릭 설치 스크립트 |
| 18 | **Switch-to-Switch 전용** generic Pia/RFU slot+block tunnel 명세/구현 |
| 19 | Union Room 이동/입장 native gold + LAN/WAN smoothness gate |
| 20 | single battle -> double battle 순서의 byte-pass-through E2E; PC battle emulator는 만들지 않음 |

### 백로그
- C-6 도중 카드 사망 자동복구 / RX decrypt fail 규명 / ldn 업스트림 PR(diff 초안 있음) / push 상시화
- 기능 확장은 두 실제 Switch가 game state를 실행하는 구조로만 진행. 상세 scope/non-goals:
  `docs/46-future-switch-to-switch-features-todo-20260824.md`.

---

## 진행 전략

```
[완료] STEP 1~5 (Mac+VM1) ─▶ [다음] 6(rate limiter 연결)+7(AP+monitor) ─▶ [VM2] 8~9 ─▶ [스위치] 10~13 ─▶ 13+ 프로덕션
                                        │
                        11 통과=목표① / 12 통과=목표② (목표①은 EMU 동결로 framerelay에 흡수됨)
```

**핵심**: STEP 8에서 스위치 없이 브로드캐스트를 검증할 수 있어서, 스위치 켜는 순간엔 거의 확정된 상태로 최종 확인만 남음.

## 5. 리포 구조 (2026-08-22 확정)

| 리포 | 역할 |
|---|---|
| **mwl313/mwl-SwitchTrade** (이 리포) | 문서·릴레이 서버·WSL2 배포 인프라·스크립트 |
| **mwl313/frlg-ldn-trade-emu** (emu/) | **동작 코드 본체** — framerelay(메인) + EMU(동결·폴백). `emu/README_MWL.md` + `emu/HANDOFF.md` 필독 |
| ~~MWL-SwitchTrade-v2~~ | ❌ 삭제됨 (2026-08-22) — 고유 내용 0 확인 후 제거, framerelay는 원본 emu에서 개발됐었음 |
