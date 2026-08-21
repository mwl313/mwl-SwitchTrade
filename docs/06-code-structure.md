# 06 — 코드 구조: 리더-리더(EMU) / 리더-조인(프레임 중계) 분리

> 작성: 2026-08-21 | 결정: 아리아 (주인님 승인)

## 목적

두 프로토콜 트랙을 독립적으로 개발·실행·배포할 수 있게 분리한다.

| 트랙 | 이름 | 방식 | 개발 채팅 |
|---|---|---|---|
| A | 리더-리더 (EMU 브리지) | 스위치 양쪽 리더 + frlgsim이 EMU 참가자로 join, 게임 의미 메시지 동기화 | **이 대화** |
| B | 리더-조인 (프레임 중계) | A=리더, B=참가자, 무선 프레임을 릴레이로 양방향 중계 (radiotap 주입) | 포크된 대화 |

## 분리 원칙

**3레이어:**

1. **공용 코어 (shared)** — 두 트랙 모두 사용
   - `relay/server.py` — 릴레이 서버 (bytes 파이프, 무상태, 게임 해석 없음)
   - MWLB 프레임 코덱 — 트랙 B 시작 시 `common/mwlb.py`로 추출 예정 (트랙 A 코드는 현재 위치 유지)
2. **트랙 A 전용** — `emu/`
   - `frlgsim/` — 게임 해석 (Pia 프로토콜, GBA FSM)
   - `frlgtrade.py` — 실행 엔트리
   - `transport.py`의 `RemoteTransport` — 게임 의미 메시지 (TRADE_SELECT/CONFIRM/CANCEL/HEARTBEAT/STATE_SYNC)
3. **트랙 B 전용** — `framerelay/` (다른 대화에서 생성)
   - `radio.py` — 모니터 캡처/주입 (radiotap 필수, 정원 count 패치)
   - `bridge.py` — 중계 루프 (radio ↔ WS ↔ radio)

## 디렉토리 구조

```
~/Projects/MWL-SwitchTrade/
├── docs/                      # 공용 설계/운영 문서
├── relay/
│   └── server.py              # ⭐ 공용 릴레이 (2026-08-21 emu/relay에서 이동)
├── emu/                       # 트랙 A: 리더-리더 (tornadus/frlg-ldn-trade 포크)
│   ├── frlgsim/               # 게임 해석 (EMU 코어)
│   ├── frlgtrade.py           # 실행 엔트리
│   ├── transport.py           # LiveTransport + RemoteTransport
│   ├── tests/                 # test_relay_offline.py (릴레이 경로 = 프로젝트 루트)
│   └── .venv/
└── framerelay/                # 트랙 B: 리더-조인 (신규, 미생성)
```

## 코드 의존 (겹침/비겹침)

| 모듈 | 트랙 A | 트랙 B | 비고 |
|---|---|---|---|
| `relay/server.py` | ✅ | ✅ | **공용** — bytes 파이프만 |
| MWLB 프레임 형식 | ✅ | ✅ | **공용** — 페이로드가 bytes라 트랙 B도 그대로 사용 |
| `frlgsim/` (게임 해석) | ✅ | ❌ | 트랙 A 전용 |
| `RemoteTransport` | ✅ | △ | 원격 채널 골격은 공용 가능, 메시지 스키마는 A 전용 |
| 모니터 캡처/주입 (radio) | ❌ | ✅ | 트랙 B 전용 (radiotap 필수 — 8/21 실측) |
| 카드/채널 유틸 | ✅ | ✅ | 나중에 `common/wifi.py`로 추출 후보 |

## git 전략

- `emu/` = 독립 git 리포 (tornadus/frlg-ldn-trade 포크) — 업스트림 동기화 유지
- `relay/`, `docs/`, `framerelay/` = MWL-SwitchTrade 프로젝트 리포
- 릴레이 변경 시 **두 리포 모두 커밋 필요 없음** — 릴레이는 프로젝트 리포 소유

## 실행 방법

```bash
# 트랙 A (리더-리더) 오프라인 검증
cd ~/Projects/MWL-SwitchTrade/emu
.venv/bin/python tests/test_relay_offline.py   # 4개 테스트 (릴레이 자동 기동)

# 트랙 A 릴레이 단독 실행
cd ~/Projects/MWL-SwitchTrade
.venv/bin/uvicorn relay.server:app --port 8788   # (emu/.venv 사용 시 경로 지정)
```
