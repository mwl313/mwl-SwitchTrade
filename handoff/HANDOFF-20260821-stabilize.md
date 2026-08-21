# 🤝 HANDOFF — MWL-SwitchTrade 트랙 A 안정화 (2026-08-21)

> **작성자**: 아리아 (Haven / Hermes Agent)
> **작성일**: 2026-08-21
> **수신자**: 코딩 에이전트 (OpenCode / Codex / Claude Code 등)
> **목적**: MWL-SwitchTrade 리더-리더 EMU 브리지 — "카드 꽂고 실행만으로 동작"하는 안정화 작업
> **프로젝트 경로**: `/Users/leah/Projects/MWL-SwitchTrade` (코드: `emu/`, 릴레이: `relay/`)

---

## 0. 이 문서를 읽는 에이전트에게

Switch(닌텐도) 간 포켓몬 FRLG 트레이드를 **인터넷으로 중계**하는 브리지 시스템. 트랙 A(리더-리더 EMU)의 연결 안정화가 현재 목표. 최종 목표는 **사용자가 아무것도 모르고 실행해도 동작**하는 수준.

**필수 규칙 (위반 금지)**:
1. 모든 결과·문서·응답은 **한국어**로 작성.
2. **`git push` 절대 금지** — 로컬 커밋까지만. push는 주인님 승인 후에만.
3. **카드 교체 제안 절대 금지** — "카드 교체는 근본적인 해결이 아니다" (주인님 강경 지시). 드라이버/코드로 해결할 것.
4. **코드 변경 전 반드시 이 문서 + `docs/09-testing-audit-20260821.md` 읽을 것.**
5. 무선/드라이버 실측은 VM(SSH)에서만. 로컬 Mac에서 무선 테스트 금지.
6. VM/스위치 재부팅·전원 제어는 주인님 담당. 에이전트가 임의 재부팅 금지.
7. 수치/현황은 추측 금지 — 실제 실행(테스트/로그)으로 확인한 것만 문서에 기재.
8. 작업 단위는 **작게 분할** (프롬프트/커밋 단위). 한 번에 여러 파일 대규모 수정 금지.

---

## 1. 프로젝트 개요

| 항목 | 내용 |
|------|------|
| **프로젝트명** | MWL-SwitchTrade |
| **한 줄 정의** | Switch 2대(각자 리더)를 브리지 2대 + 릴레이로 연결해 원격 트레이드 |
| **최종 목표** | 사용자 = "카드 꽂고 실행만" (도움/체크리스트 없이 동작) |
| **기술 스택** | Python 3.11~3.14, trio, kinnay/LDN, rtl8xxxu(커널 드라이버), FastAPI+websockets(릴레이), Ubuntu VM(VMware) |
| **현재 버전** | 트랙 A (리더-리더 EMU) — Phase 2a 완료, 2b(LAN 실기) 테스트 중 |
| **테스트** | 릴레이 4개 + FSM 훅 5개 = **9개 통과** (직접 실행 확인) |

### 핵심 사용자 시나리오
1. 사용자가 브리지 2대에 카드를 꽂고 프로그램 실행 → 각자 스위치에 자동 연결
2. 릴레이 세션 ID로 양쪽 브리지 연결 → 트레이드 진행

---

## 2. 전체 아키텍처

```
[Switch A: 리더] ←LDN→ [브리지 A = VM1 + 카드] ──┐
                                                  ├─ WSS(릴레이) ─ 서로 연결
[Switch B: 리더] ←LDN→ [브리지 B = VM2 + 카드] ──┘

레이어:
┌─────────────────────────────────────────┐
│ ③ Python 앱 (frlgsim + frlgtrade.py)     │ ← 게임(RFU) 시뮬레이션 + CLI
├─────────────────────────────────────────┤
│ ② transport.py (Live/RemoteTransport)    │ ← LDN join + UDP:12345 데이터 플레인
├─────────────────────────────────────────┤
│ ① kinnay/LDN + nl80211 + rtl8xxxu       │ ← 무선 (모니터/스테이션)
└─────────────────────────────────────────┘
```

---

## 3. 현재 상태 요약

### ✅ 구현 완료
| 모듈 | 상태 | 비고 |
|------|------|------|
| RemoteTransport (transport.py) | ✅ | 릴레이 WS + MWLB 프레임 + 재연결 |
| 릴레이 서버 (relay/server.py) | ✅ | 세션 생성/조인/bytes 파이프 |
| FSM 훅 (sim.py ↔ RemoteTransport) | ✅ | TX/RX 훅 + 루프 방지 |
| CLI 릴레이 옵션 (--relay-url/--session-id/--role) | ✅ | |
| free_radio 하이브리드 패치 | ✅ | nmcli/down 제거 (수신 사망 방지) |
| 최소 참가자 방 선택 | ✅ | 2스위치 동시 광고 시 |
| udev rename 대응 | ✅ | join 후 실제 iface 감지 (실측 검증) |

### ❌ 미구현 / 필요 작업 (코드화 대기)
| 항목 | 상태 | 비고 |
|------|------|------|
| 스캔 hang 방지 (타임아웃 래핑) | 🔴 P0 | ldn.scan이 VM 전체 hang (3회) |
| vif 완전 정리 (free_radio 강화) | 🔴 P0 | rename된 vif 잔류 → EBUSY |
| NM wlx* 전체 unmanaged | 🟠 P1 | 카드 교체에도 면역 |
| BSSID 기반 assoc (--target-bssid) | 🟠 P1 | 2스위치 환경 필수 |
| phy 자동 감지 | 🟠 P1 | 사용자 입력 제거 |
| 카드 생존 감지/자동 리셋 | 🟡 P2 | 카드 수신 사망 자동 대응 |
| 프로세스 자동 정리 | 🟡 P2 | 재실행 안정성 |
| 몬 파일 초과 안내 | 🟢 P3 | UX |

---

## 4. 프로젝트 구조

```
~/Projects/MWL-SwitchTrade/
├── emu/                         # 트랙 A (git 리포, 브랜치 stabilize)
│   ├── frlgtrade.py             # CLI 엔트리 (릴레이 옵션 포함)
│   ├── frlgsim/
│   │   ├── transport.py         # ⭐ Live/RemoteTransport (패치 다수 — 주의)
│   │   ├── sim.py               # 게임 FSM (FSM 훅 포함)
│   │   ├── trade.py             # 트레이드 프로토콜
│   │   └── ...                  # crypto/mon/linkplayer 등
│   ├── tests/                   # test_relay_offline.py(4) + test_fsm_hook.py(5)
│   └── .venv/                   # Python 3.14 venv (ldn/pycryptodome/trio 등)
├── relay/
│   └── server.py                # 공용 릴레이 (FastAPI + websockets)
├── docs/                        # 설계/실측/감사 문서 (아래 §13)
└── handoff/                     # 이 문서
```

---

## 5. ⚠️ 알려진 버그 & 기술 부채 (상세는 docs/09)

### 5.1 🔴 [P0] ldn.scan → VM 전체 hang
- 위치: `ldn.scan` 호출부 (`emu/frlgsim/transport.py` `_run_ldn`)
- 증상: 스캔 실행 시 VM CPU 점유 hang (TCP 22 open + SSH 배너 없음), 재부팅만 복구. **3회 재발**
- 수정 방향: `trio.with_timeout`(30s) 래핑 + 실패 시 graceful 처리 (VM 사망 = 서비스 불가)

### 5.2 🔴 [P0] stale/renamed vif 잔류 → EBUSY / Match already configured
- 위치: `free_radio()` (`transport.py`) — LDN_VIFS 이름 기준이라 **udev rename된 vif(wlx<MAC>)를 못 지움**
- 증상: 이전 실행(크래시/pkill) 후 vif 잔류 → `set_channel EBUSY`, `REGISTER_FRAME Match already configured`, `assoc status 1`
- 수정 방향: phy 소속 **모든** vif 삭제 (이름 무관) — 단, 일반 Wi-Fi 인터페이스(wlx 원본)와 구분 필요

### 5.3 🟠 [P1] NetworkManager 개입
- 위치: VM `/etc/NetworkManager/conf.d/unmanaged-wlx.conf`
- 증상: unmanaged 목록에 없는 카드(예: 8192EU)를 NM이 관리 → REGISTER_FRAME 반복 실패 (15+회)
- 현재: conf에 2개 MAC 추가 + NM 중지로 해결 (임시)
- 수정 방향: `unmanaged-devices=interface-name:wlx*` (MAC 불변) — 카드 교체/추가에도 면역

### 5.4 🟠 [P1] 두 스위치 동일 SSID/채널 → 잘못된 스위치 assoc
- 위치: `ldn.connect_network` (외부 라이브러리 — SSID+채널만 사용, BSSID 미지원)
- 증상: host가 "스위치 A 선택"해도 같은 SSID+채널의 스위치 B에 assoc → 거부(status 1). dmesg로 MAC 확인됨
- 수정 방향: ldn 패치 또는 transport에서 BSSID 지정 (NL80211_ATTR_MAC) — `--target-bssid` 옵션

### 5.5 🟡 [P2] 카드 수신 사망 (silently failing)
- 위치: 드라이버/카드 수준 (rtl8xxxu)
- 증상: 수신 0 (rx_packets=0, dmesg 에러 없음). 8188EU에서 반복 (8192EU는 안정 — 실측)
- 수정 방향: 수신 카운터 감시 + 자동 리셋(sysfs authorized 토글) + 로그

### 5.6 🟡 [P2] phy 번호 증가 / USB 경로 변경
- 증상: 리셋/재부팅마다 phy0→1→2..., USB 버스 2-2→3-2 변경
- 수정 방향: phy 자동 감지(USB ID→wiphy), 리셋 유틸(sysfs 자동 탐색)

### 5.7 🟢 [P3] 기타
- 몬 파일 6개 초과 시 에러 (와일드카드 12개) → 초과 안내
- 릴레이 세션 ID가 로그에 안 남음 → 조회 API/로그 추가
- 프로세스 잔류 (pkill 필요) → 코드에서 자동 정리

---

## 6. 실행 방법 & 환경

### 로컬 (Mac — 오프라인 테스트만)
```bash
cd ~/Projects/MWL-SwitchTrade/emu
.venv/bin/python tests/test_relay_offline.py   # 릴레이 4개
.venv/bin/python tests/test_fsm_hook.py        # FSM 5개
```

### 실기 (VM — 무선 테스트)
```bash
# VM1: aria@100.109.113.113 (SSH 키 ~/.ssh/aria_bridge)
# VM2: aria@100.115.7.43
ssh -i ~/.ssh/aria_bridge aria@100.109.113.113
cd ~/emu
# 카드 확인 → phy 확인 → vif 정리 → 카드 생존 확인 후:
sudo ./.venv/bin/python frlgtrade.py --live --verbose \
  --relay-url http://127.0.0.1:8788 --role host --session-id <SID> \
  --comm-id 0x01006fa0233f8000 --keys /root/.switch/prod.keys --phy phy0 \
  --trades 1 -o ~/mons/received.pk3 '~/mons/<몬>.pk3'
```

**의존성**: Python 3.14 (venv), ldn 0.0.17, pycryptodome, trio, zstandard, websockets, fastapi, uvicorn. 커널 7.0.0-30, rtl8xxxu(인커널 — 커스텀 드라이버 금지).

**VM 환경 주의사항 (실측 확정)**:
- NM reload 금지 (네트워크 전체 사망) — conf 수정 후 재부팅만
- free_radio가 nmcli/down 하면 카드 수신 사망 (하이브리드 패치 반영됨 — 유지)
- ldn 실행 전 wlx/ldn vif 삭제 (phy 독점)
- udev가 ldnclient를 wlx<MAC>으로 rename (패치 반영됨 — 유지)

---

## 7. 로드맵/백로그 (코드화 우선순위 순)

### Phase A — 안정화 코어 (P0)
- [ ] D-1: ldn.scan 타임아웃 래핑 (VM hang 방지)
- [ ] C-1: free_radio vif 완전 정리 (rename 포함)

### Phase B — 환경 면역 (P1)
- [ ] C-3: NM wlx* 전체 unmanaged 설정 (배포 스크립트)
- [ ] C-4: BSSID 기반 assoc (--target-bssid)
- [ ] C-2: phy 자동 감지

### Phase C — 자가 치유 (P2)
- [ ] C-6: 카드 수신 사망 감지 + 자동 리셋
- [ ] D-9: 프로세스 자동 정리
- [ ] D-8: 몬 초과 안내

### Phase D — 출시 준비
- [ ] 설치 스크립트 1개로 환경 준비 (NM conf, 드라이버 확인, venv)
- [ ] "실행만으로 동작" 검증 (체크리스트 없이)

---

## 8. 작업 지시 (코딩 에이전트용)

### ⚡ 구현 에이전트 — 작업 항목
1. **D-1 (P0)**: `_run_ldn`의 `ldn.scan`을 `trio.with_timeout(30)`으로 래핑. 타임아웃 시 명확한 에러 + 재시도 로직 유지. VM hang 재현 방지가 1순위.
2. **C-1 (P0)**: `free_radio()`가 phy 소속 **모든 vif**를 정리하도록 강화 (udev rename된 wlx 포함). 단, "원래 카드 인터페이스"와 "ldn 생성 vif" 구분 로직 주의 (일반 Wi-Fi를 죽이면 안 됨).
3. **C-3 (P1)**: NM conf를 `interface-name:wlx*` 기반으로 변경하는 배포 스크립트.
4. **C-4 (P1)**: ldn 연결에 BSSID 지정 — `--target-bssid` 옵션 추가 (없으면 기존 동작 유지).
5. **C-2 (P1)**: USB ID → phy 자동 감지 (0bda:8179/818b 매핑).

### 🤝 공통
- 모든 변경 후: `test_relay_offline.py` + `test_fsm_hook.py` 회귀 통과 확인
- 실측이 필요한 변경은 VM에서만. 코드만으로 판단하지 말 것.
- 커밋 단위 작게, 메시지 한국어/영어 혼용 가능 (기존 스타일 준수: `transport: ...`)

---

## 9. Definition of Done (안정화 완료 기준)

- [ ] VM 재부팅 → 스크립트 1회 실행 → **스캔이 hang 없이 완료** (30초 타임아웃)
- [ ] 연속 실행 3회 (kill 포함) → **vif 잔류 없이** 각각 정상 join
- [ ] 카드 2종(8188EU/8192EU) 모두 동일 절차로 연결 성공
- [ ] 두 스위치 동시 광고 상태에서 **각 브리지가 자기 스위치에만** 연결 (BSSID)
- [ ] 카드 수신 사망 시 **자동 감지 + 리셋 + 재시도** (수동 개입 0)
- [ ] 9개 테스트 전부 통과 (릴레이 4 + FSM 5)
- [ ] 로컬 커밋 완료 (push 금지)

---

## 10. 참고 자료

| 자료 | 위치 | 용도 |
|------|------|------|
| 테스팅 Audit (전체 이슈) | `docs/09-testing-audit-20260821.md` | ⭐ 이슈 I-1~9 + D-1~9 상세 |
| 2b 실측 기록 | `docs/07-2b-테스트-실측-20260821.md` | 실측 로그/원인 |
| 드라이버 매니저 설계 | `docs/08-driver-manager.md` | 칩셋 지원 매트릭스 |
| Phase 2 설계 | `docs/05-phase2-design.md` | RemoteTransport/릴레이 설계 |
| 코드 구조 | `docs/06-code-structure.md` | 트랙 분리 원칙 |
| 스킬 (운영 절차) | `~/.hermes/skills/.../switch-ldn-trade` | 실측 기반 절차 |

---

## 11. 연락처 & 보고 체계

- **주인님**: 임민우 — 최종 의사결정권자. 보고는 한국어로.
- **아리아**: Haven AI 비서 — 진행 상황 보고·중계.
- 막히는 부분은 추측으로 진행하지 말고 TODO로 남기고 계속 진행.

---

> **면책 문구**: 본 문서의 모든 실측 수치는 2026-08-21 기준 VM/스위치 환경에서 확인된 값입니다. 환경(커널/드라이버/카드)이 바뀌면 재검증이 필요합니다.
