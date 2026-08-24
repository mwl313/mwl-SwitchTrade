# Phase 2 상세설계 — PC↔PC 인터넷 브리지

> 작성: 2026-08-21 | 상태: 설계 v1 (실측 코드 분석 기반)
> 목표: 서로 다른 두 장소의 Switch(순정 NSO FRLG) 간 트레이드를 인터넷으로 성공시킨다.

---

## 1. 배경: 오늘 검증된 것 (Phase 0/1)

- 단일 브리지(리눅스 VM + RTL8188EU)로 로컬 트레이드 **2세션 연속 성공** (워크플로우 v1)
- kinnay/LDN join(참가자) 경로 실측 완료 — AP 모드 불필요
- frlgsim이 게임(RFU) 레벨에서 동작 — .pk3 트레이드 실측 성공
- **Phase 2 = 이 로컬 성공을 두 대로 늘려 인터넷으로 잇는 것**

## 2. frlgsim 데이터 플레인 분석 (코드 실측)

### 2.1 transport 인터페이스 (확장점)

```python
# frlgsim/sim.py — 전송 경계는 단 2개 메서드
self.t.send(dg, dst)                              # L482: TX (datagram, dst_ip)
for datagram, src_ip in self.t.recv():            # L727: RX (payload, src_ip)
```

| 구현체 | 동작 |
|---|---|
| `ReplayTransport` | 오프라인: 캡처 파일에서 IN 분배, OUT 수집 (회귀 테스트용) |
| `LiveTransport` | 라이브: LDN join → UDP :12345 브로드캐스트 교환 |
| **`RemoteTransport` (신규)** | 라이브 + 원격 피어 터널 — **이것만 구현하면 Phase 2의 브리지 코어 완성** |

### 2.2 LiveTransport 데이터 경로 (실측)

```
TX: UDP 소켓 (SO_BROADCAST, bind 0.0.0.0:12345)
    → dst = 169.254.X.255 (서브넷 브로드캐스트) 또는 unicast
RX: AF_PACKET raw 소켓 (ETH_P_IP, iface 바인딩, non-blocking)
    → _parse_udp: IP 헤더 파싱 → UDP 페이로드 추출
    → 필터: src_ip != our_ip, dst_port == 12345, _accept_dst(dst)
    → 반환: (payload, src_ip) 리스트
```

### 2.3 Pia 프로토콜 (pia_connect.py)

```
UDP :12345 페이로드 = Pia 프로토콜
ConnectionManager 상태머신:
  Net 0x11 (호스트가 브로드캐스트) → Session join (MAC 기반 식별)
  → Session finalize → RTT → Reliable (reliable.py 신뢰 계층)
참가자 식별: src_mac (세션 조인 패킷에 포함) — IP가 아니라 MAC
```

**중요 관찰**: Pia는 참가자를 **MAC 주소**로 식별한다. IP는 전송 수단일 뿐.

## 3. 핵심 설계 결정: 어떤 계층에서 잇는가

### 옵션 비교

| 옵션 | 방식 | 장점 | 단점 |
|---|---|---|---|
| **A. 게임 상태 동기화** (frlgsim↔frlgsim) | 각 브리지의 sim이 로컬 Switch와 세션을 유지하되, "가상 GBA의 행동"을 원격 플레이어의 실제 행동으로 매핑 | 로컬 LDN/Pia 세션 각자 유지 — **지금 동작하는 구조 그대로** | 게임 FSM 내부 수정 필요. 트레이드 외 배틀 확장 시 재작업 |
| B. LDN 프레임 중계 | 무선 프레임을 그대로 양방향 중계 (두 Switch가 "같은 방"인 것처럼) | frlgsim 불필요 (게임 해석 없음) | 각 브리지가 AP로 보여야 함 (호스트 모드) — 카드 조건 급상승. MAC/세션 위장 난이도 높음 |
| **C. Pia 패킷 중계 (선택)** | 각 브리지가 로컬 세션 유지 + **게임 데이터(UDP 페이로드)를 원격으로 중계**, 로컬 주입은 sim의 recv() 합성으로 처리 | 옵션 A의 안정성 + 옵션 B의 단순성. MAC은 Pia 페이로드 내부라 로컬 세션 정합성이 유지됨 | 주입 없이 recv() 합성 → sim의 RX 루프 수정 최소화 |

**선택: 옵션 C** — 근거: (1) send/recv 인터페이스가 이미 추상화되어 있어 RemoteTransport 한 클래스로 구현 가능, (2) 각 로컬 세션(MAC 정합성)이 그대로 유지됨, (3) Pia 페이로드는 순수 데이터라 릴레이가 해석할 필요 없음 (무상태 원칙 유지).

### C의 동작 시나리오 (트레이드 3회 기준)

```
Switch A (리더) ←LDN→ 브리지 A (sim A: "원격 대리자") ←WSS→ 릴레이 ←WSS→ 브리지 B (sim B) ←LDN→ Switch B (리더)
```

1. 양쪽 모두 리더로 방을 연다 (각자의 LDN 세션은 독립 — 같은 방이 아님)
2. sim A/B는 각자 로컬 Switch와 "EMU" 참가자로 연결 (현재 로컬 트레이드와 동일 절차)
3. **게임 트레이드 상태 동기화**: Switch A 플레이어의 선택(보낼 포켓몬) → sim A가 게임 패킷에서 파싱 → `remote.send(상태메시지)` → 릴레이 → sim B 수신 → sim B의 FSM에 "상대 플레이어가 X를 선택했다"로 반영
4. sim B는 그 상태로 Switch B와 트레이드 진행 (가상 GBA가 원격 플레이어의 선택을 대신 수행)
5. 반대 방향도 동일 — 양방향 상태 동기화 루프

**설계 원칙**: Pia 패킷 자체는 로컬에서 완결되고, **원격으로는 "게임 의미 정보"만** 간다. (릴레이가 게임을 몰라도 되는 무상태성은 유지하되, 브리지가 게임 의미를 해석하는 계층이 하나 추가된다.)

## 4. RemoteTransport 상세 설계

### 4.1 클래스 구조

```python
class RemoteTransport(LiveTransport):
    """LiveTransport 상속 + 원격 상태 채널 추가."""

    def __init__(self, ..., relay_url: str, session_id: str, role: str):
        super().__init__(...)
        self._ws = WebSocketClient(relay_url, session_id)
        self._remote_inbox = asyncio.Queue()   # 원격 상태 메시지

    # -- 원격 상태 채널 (릴레이 경유) --
    async def remote_send(self, msg: bytes):
        """게임 의미 메시지를 원격 피어로. {type, payload} 프레임으로 래핑."""
        await self._ws.send(msg)

    def remote_poll(self):
        """원격 메시지 드레인 → FSM 입력 큐로."""
        while not self._remote_inbox.empty():
            yield self._remote_inbox.get_nowait()

    # -- 로컬 데이터 플레인은 LiveTransport 그대로 (UDP :12345) --
```

### 4.2 게임 의미 메시지 스키마 (v1 — 트레이드 한정)

```
Frame: [4B magic "MWLB"] [1B msg_type] [2B len] [payload]

msg_type:
  0x01 TRADE_SELECT   — "상대 플레이어가 슬롯 N 선택"  payload: slot u8
  0x02 TRADE_CONFIRM  — "확인 버튼"                   payload: (없음)
  0x03 TRADE_CANCEL   — 취소                          payload: (없음)
  0x04 HEARTBEAT      — 연결 유지                     payload: ts u32
  0x10 STATE_SYNC     — 트레이드 시작 시 전체 상태    payload: {trades, .pk3 해시}
```

v1은 **트레이드에 필요한 최소 집합**만. (배틀은 Phase 4에서 스키마 확장)

### 4.3 루프 방지 / 멱등성

- 원격 메시지는 **로컬 브로드캐스트로 재주입하지 않는다** — sim의 FSM 입력 큐에 직접 합성한다 (오버더와이어 주입 아예 없음 → 루프 불가능)
- 로컬 RX는 LiveTransport 필터 그대로 (src != our_ip)
- 메시지에 seq + 세션 ID를 넣어 재연결 시 중복/누락 감지

## 5. 릴레이 서버 설계

### 5.1 원칙 (Celio-Server 패턴 답습)

- **무상태 릴레이**: 세션 ID 라우팅만, 게임 데이터 해석 없음
- 2인 세션 고정 (v1: 1:1 트레이드)
- TLS는 리버스 프록시/클라우드플레어에 위임

### 5.2 기술 스택

| 후보 | 평가 |
|---|---|
| **Node.js + Socket.IO** | Celio-Server와 동일 — 검증된 패턴 그대로. 생태계 풍부. **선택** |
| Go + WebSocket | 성능 우수하나 재작성 비용. 후순위 |
| Python + FastAPI/WS | 브리지와 동일 언어. 단일 리포 유지 용이 |

**결정**: v1은 **Python (FastAPI + websockets)** — 브리지(frlgsim)와 동일 언어라 모노리포에서 빠른 반복이 가능. 트래픽이 수십 B/s 수준이라 성능 이슈 없음. 추후 Node.js 이식은 부담 없음.

### 5.3 API

```
POST /session/create          → {session_id}            (6자리: "ABC123")
POST /session/{id}/join       → room에 2번째로 참가      (3번째는 409)
WS   /session/{id}/ws?role=host|guest
     서버는 room의 두 소켓 간 bytes를 그대로 파이프
     (heartbeat 30s, 재연결 시 session_id+role로 재부착, 상대 오프라인 상태 브로드캐스트)
```

### 5.4 배치

- 초기: 공개 VPS (가벼움) 또는 **Cloudflare Tunnel + Mac mini** (기존 인프라 재사용 — 주인님 환경에 이미 터널 있음)
- 세션 ID는 짧게 (6자) — 구두 전달용 (GB-Link 데모 UX 참고)

## 6. 구현 단계 (빈틈없이)

### Phase 2a — 로컬 루프백 검증 (프레임워크 통합 없이)

1. `RemoteTransport` 스켈레톤 + 더미 릴레이(로컬 프로세스) 작성
2. **ReplayTransport 캡처로 오프라인 검증**: 같은 캡처 파일을 두 sim에 물려 "가상의 원격 피어" 흉내 — 상태 메시지 왕복이 FSM을 깨지 않는지
3. frlgsim FSM에 `remote_send`/`remote_poll` 훅 연결 (트레이드 경로만)

### Phase 2b — LAN 실기 (브리지 2대, 같은 네트워크)

4. 두 브리지 준비: 브리지 A = 기존 VM, 브리지 B = **미니DC(이식 후) 또는 노트북 USB 부팅** (일단 VM 복제로도 가능 — 단, Wi-Fi 카드 2대 필요! **하드웨어 선결 과제**)
5. 같은 LAN에서 릴레이 경유 트레이드 성공 — **Phase 2의 첫 성공 기준**
6. 로그로 지연 측정 (턴제 특성상 여유 예상)

### Phase 2c — 인터넷 (NAT 통과)

7. 릴레이를 공개 엔드포인트로 (Cloudflare Tunnel)
8. 두 장소에서 트레이드 성공 — **Phase 2 완료 기준**
9. 재연결/타임아웃 시나리오 5종 검증 (중간 끊김, 재시작, 동시 조인 등)

## 7. 테스트 시나리오 (2b/2c 공통)

| # | 시나리오 | 기대 |
|---|---|---|
| T1 | 양쪽 정상 트레이드 3회 | 성공 + 수신 .pk3 일치 |
| T2 | 한쪽 중간 네트워크 끊김 5초 | Pia 재전송으로 회복 or 명시적 재시도 |
| T3 | 세션 ID 재조인 (중복 조인 거부) | 409 / 방어 동작 |
| T4 | 트레이드 취소 버튼 | 취소 상태 동기화 |
| T5 | 1시간 연결 유지 (절전 대기) | heartbeat 유지, 카드 절전 대응은 로컬 워크플로우대로 |
| T6 | 지연 인젝션 (tc netem 200ms) | 트레이드 완료 (게임 타임아웃 한계 측정) |

## 8. 리스크 & 열린 질문

| 항목 | 리스크 | 대응 |
|---|---|---|
| 게임 FSM 내부 수정 난이도 (sim.py 53KB) | 중 | 트레이드 경로 한정 훅. ReplayTransport 오프라인 회귀로 안전망 |
| **Wi-Fi 카드 2대** (브리지 B 하드웨어) | 중 | RTL8188EU 추가 구매(~1만원) or ALFA 카드. 미니DC 이식과 병행 |
| LDN 세션 ID/호스트 식별 충돌 (양쪽 모두 리더) | 중 | Pia MAC 기반이라 로컬 세션은 독립 — 문제 없을 것으로 예상. 2a에서 오프라인 확인 |
| 게임 타임아웃 (인터넷 왕복 지연) | 낮음 | GB-Link 실측(턴제 여유) + T6에서 측정 |
| frlgsim 업스트림 변경 추적 | 낮음 | 포크 + 하이브리드 패치 유지 중 (git 관리) |
| 닌텐도 정책 | — | 개인 사용/연구 한정 (기존 원칙 유지) |

## 9. 산출물 정의

| 산출물 | 위치 |
|---|---|
| RemoteTransport | `frlgsim/transport.py` 확장 (포크 내) |
| 릴레이 서버 | `relay/` (FastAPI 단일 파일 → 필요 시 분리) |
| FSM 훅 | `frlgsim/sim.py` 트레이드 경로 주석 명시 |
| 설계 검증 로그 | `docs/` 캡처 + 타임라인 |

---

*다음 액션: (1) 브리지 B용 Wi-Fi 카드 확보 여부 결정, (2) RemoteTransport 스켈레톤 + 오프라인 검증(2a)*
