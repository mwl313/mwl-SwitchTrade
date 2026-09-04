# Phase B Design Document
## Core Foundation: Minimal Pair Relay + Pair/Generation Supervisor

- Phase: B
- 선행 조건: Phase A Exit Gate 통과
- 후속 Phase: C — Switch LDN Core Integration
- 하드웨어 요구: 없음
- WSL 요구: 기본 단위 테스트에는 없음
- 목표: 구체 endpoint를 모르는 1:1 Core 완성

---

# 1. Purpose

Phase B는 Switch 통신 코드를 연결하지 않는다.

대신 다음 질문에 소프트웨어만으로 답한다.

> 두 사용자가 6자리 코드로 연결되고, Pair를 유지한 채 하나 이상의 독립적인
> Generation을 안전하게 열고, 양방향 opaque packet을 전달하고, 정리할 수 있는가?

Phase B가 성공해야 C에서 Direct A/B와 Wi-Fi lifecycle을 Core에 연결할 수 있다.

---

# 2. Boundary

## 포함

- Core domain model
- endpoint/runtime interfaces
- fake endpoint
- 6자리 Pair service
- access token
- endpoint-neutral WebSocket
- versioned envelope
- epoch/sequence
- bidirectional probe
- generation offer/accept/close
- bounded queue
- reconnect lease
- deterministic cleanup
- software-only end-to-end tests

## 제외

- Switch, Wi-Fi, WSL, USB, `ldn`
- Pia/Reliable/RFU interpretation
- RetroArch/gpSP
- WPF
- 기존 Room Authority 변경/삭제
- public directory/SQLite
- production installer
- physical qualification

---

# 3. Proposed File Layout

```text
switchtrade/
├── core/
│   ├── __init__.py
│   ├── contracts.py
│   ├── errors.py
│   ├── events.py
│   ├── endpoint.py
│   ├── generation.py
│   └── supervisor.py
│
├── transport/
│   ├── __init__.py
│   ├── envelope.py
│   ├── client.py
│   └── protocol.py
│
└── endpoints/
    ├── __init__.py
    ├── base.py
    └── fake.py

relay/
├── core_server.py
├── pair_store.py
└── core_contracts.py

tests/
├── test_core_contracts.py
├── test_core_pair_store.py
├── test_core_transport.py
├── test_core_supervisor.py
└── test_core_end_to_end.py
```

파일 이름은 작게 조정할 수 있지만 dependency boundary는 변경하지 않는다.

---

# 4. Terminology

## Pair Seat

인터넷 pairing 좌석:

```text
host
guest
```

## Generation Role

해당 local-link generation의 역할:

```text
origin
mirror
```

## Endpoint Kind

```text
fake
switch_ldn
retroarch_gpsp
```

B에서는 `fake`만 구현한다.

## Runtime Kind

```text
in_process
managed_wsl
native
```

B에서는 `in_process`만 구현한다.

## Protocol ID

```text
switchtrade.fake.v1
switchtrade.gba-frame.v1
libretro.gpsp-rfu1.v1
```

B에서는 `switchtrade.fake.v1`만 활성화한다.

Pair Seat, Generation Role, Endpoint Kind, Runtime Kind를 하나의 `role` 문자열로 합치지 않는다.

---

# 5. Core Contracts

## 5.1 PairCredentials

```python
@dataclass(frozen=True)
class PairCredentials:
    pair_id: str
    seat: PairSeat
    access_token: str
    reconnect_expires_at: str
    code: str | None = None
```

Guest에게 consume된 code를 계속 인증 수단으로 사용하지 않는다.

## 5.2 EndpointCapabilities

```python
@dataclass(frozen=True)
class EndpointCapabilities:
    endpoint_kind: str
    runtime_kind: str
    protocols: tuple[str, ...]
    generation_roles: tuple[GenerationRole, ...]
```

## 5.3 GenerationOffer

```python
@dataclass(frozen=True)
class GenerationOffer:
    generation_id: str
    protocol_id: str
    origin_endpoint_kind: str
    setup_payload: bytes
```

`setup_payload`는 Relay가 해석하지 않는 opaque bytes다.

## 5.4 LinkPacket

```python
@dataclass(frozen=True)
class LinkPacket:
    generation_id: str
    protocol_id: str
    payload: bytes
    flags: int = 0
```

## 5.5 CleanupReport

```python
@dataclass(frozen=True)
class CleanupReport:
    endpoint_stopped: bool
    local_resources_released: bool
    transport_drained: bool
    details: Mapping[str, object]
```

## 5.6 LocalGeneration

```python
class LocalGeneration(Protocol):
    offer: GenerationOffer

    async def receive(self) -> LinkPacket: ...
    async def send(self, packet: LinkPacket) -> None: ...
    async def close(self, outcome: str) -> CleanupReport: ...
```

## 5.7 EndpointDriver

```python
class EndpointDriver(Protocol):
    capabilities: EndpointCapabilities

    async def prepare(self) -> None: ...
    async def discover(self, cancel: Cancellation) -> LocalGeneration: ...
    async def accept(
        self,
        offer: GenerationOffer,
        cancel: Cancellation,
    ) -> LocalGeneration: ...
    async def close(self) -> CleanupReport: ...
```

B의 fake driver는 memory queue를 사용한다.

---

# 6. Pair Relay

## 6.1 API

### Create

```http
POST /core/v1/pairs
```

Request:

```json
{
  "capabilities": {
    "endpoint_kind": "fake",
    "runtime_kind": "in_process",
    "protocols": ["switchtrade.fake.v1"],
    "generation_roles": ["origin"]
  }
}
```

Response:

```json
{
  "contract_version": "switchtrade-pair.v1",
  "pair_id": "...",
  "code": "381742",
  "seat": "host",
  "access_token": "...",
  "code_expires_at": "...",
  "reconnect_expires_at": "..."
}
```

### Join

```http
POST /core/v1/pairs:join
```

Request:

```json
{
  "code": "381742",
  "capabilities": {
    "endpoint_kind": "fake",
    "runtime_kind": "in_process",
    "protocols": ["switchtrade.fake.v1"],
    "generation_roles": ["mirror"]
  }
}
```

Response:

```json
{
  "contract_version": "switchtrade-pair.v1",
  "pair_id": "...",
  "seat": "guest",
  "access_token": "...",
  "reconnect_expires_at": "...",
  "negotiated_protocols": ["switchtrade.fake.v1"]
}
```

### Status

```http
GET /core/v1/pairs/{pair_id}
Authorization: Bearer ...
```

Read-only. Status는 socket 또는 generation을 만들지 않는다.

### WebSocket

```text
/core/v1/pairs/{pair_id}/ws
Authorization: Bearer ...
```

Seat는 credential로 결정한다.

## 6.2 PairStore

```text
code -> pair_id
pair_id -> PairRecord
token_hash -> pair_id + seat
```

PairRecord:

- created timestamp
- code expiry
- reconnect expiry
- code consumed
- host/guest capabilities
- negotiated protocols
- socket generation per seat
- active generation ID
- last activity

## 6.3 Security and Limits

- code: 6 digits
- token: minimum 256-bit randomness
- token hash storage
- constant-time comparison
- create/join rate limit
- code-guess rate limit
- max live pairs
- one socket per seat
- reconnect retires old socket
- malformed frame close
- max payload
- send timeout
- idle/expiry sweep
- no token/code logging

---

# 7. Wire Protocol

## 7.1 Envelope

권장 fields:

```text
magic
version
kind
source_seat
flags
source_epoch
sequence
generation_id_length
payload_length
generation_id
payload
```

Pair는 authenticated WebSocket path에 바인딩된다.

## 7.2 Kinds

```text
PEER_READY
PROBE_CHALLENGE
PROBE_RESPONSE
CAPABILITIES
GENERATION_OFFER
GENERATION_ACCEPT
GENERATION_CLOSE
DATA
HEARTBEAT
PEER_CLOSE
```

## 7.3 Ordering

- 새 epoch는 `PEER_READY`, sequence 0
- sequence contiguous
- duplicate/stale/gap은 failure
- old epoch retirement
- DATA는 active accepted generation에서만
- OFFER/ACCEPT 전 DATA 금지
- CLOSE 후 DATA 금지
- reconnect 후 probe 재수행
- stale queued data 재전송 금지

## 7.4 Probe

양쪽이 challenge를 보내고 상대 challenge에 답해야 data plane ready다.
WebSocket connect만으로 ready 선언 금지.

---

# 8. Core Supervisor

## 8.1 State

```text
STARTING
PAIRING
WAITING_FOR_PEER
PAIRED
DISCOVERING_LOCAL
WAITING_FOR_OFFER
OPENING_LOCAL
GENERATION_NEGOTIATING
ACTIVE
CLOSING_GENERATION
RECOVERING_PAIR
STOPPING
STOPPED
FAILED
```

## 8.2 Host Policy for B

- Pair host
- default Generation origin
- fake driver `discover()`
- local generation이 peer보다 먼저 존재 가능
- data plane 준비 후 offer
- accept 후 pump

## 8.3 Guest Policy for B

- Pair guest
- default Generation mirror
- offer 대기
- fake driver `accept()`
- local ready 후 accept
- pump

이 mapping은 composition policy이며 wire에 hard-code하지 않는다.

## 8.4 Pump

```text
LocalGeneration.receive()
→ LinkPacket
→ transport DATA
```

```text
transport DATA
→ generation/protocol validation
→ LocalGeneration.send()
```

Rules:

- bounded queue
- no silent drop
- backpressure timeout is failure
- first failure wins
- sibling task cancellation
- deterministic close

## 8.5 Cleanup

Generation close:

1. stop new local admission
2. stop new remote DATA admission
3. bounded drain/discard accounting
4. close LocalGeneration
5. verify CleanupReport
6. exchange generation close
7. clear active generation
8. permit next generation

Pair shutdown:

1. close active generation
2. stop endpoint driver
3. close transport
4. release in-memory credentials
5. stop

---

# 9. Dependency Rules

Tests로 강제:

```text
switchtrade/core
- no ldn
- no bridge.frlgsim
- no wsl.exe
- no FastAPI
- no RetroArch/gpSP

new Relay
- no switchtrade.connection
- no bridge
- no Pokémon/game modules
- no relay.authority

fake endpoint
- core contracts only
```

---

# 10. Test Matrix

## PairStore

- unique code/collision
- one-time consume
- invalid/expired code
- guest already joined
- third participant
- token hash/wrong token
- seat binding
- capacity/expiry sweep
- secret-free public projection

## Wire

- encode/decode/bounds
- invalid magic/version
- wrong seat
- epoch start
- duplicate/gap/stale
- old generation
- DATA before accept/after close

## Client

- reconnect/fresh epoch
- queue reset
- probe
- permanent auth error
- bounded backoff
- cancellation
- no busy loop

## Supervisor

- host/guest connect
- local-before-peer
- peer-before-local
- offer/accept
- bidirectional packet
- local/remote failure
- first failure
- cleanup failure
- next generation barrier
- clean stop

## End-to-End

실제 새 FastAPI app과 WebSocket client 두 개:

- create/join
- code reuse fail
- authenticate/probe
- fake generation
- bidirectional packets
- clean close
- second generation
- no leaks

---

# 11. Acceptance Criteria

1. Core에 hardware/runtime import 없음
2. 기존 Room API untouched/regression green
3. Host 6자리 code
4. Guest one-time join
5. credential determines seat
6. bidirectional probe
7. Pair/Generation lifetime 분리
8. two fake generations
9. stale epoch/generation reject
10. bounded queue/timeout
11. cleanup before next generation
12. software E2E pass
13. physical acceptance claim 없음

---

# 12. Phase B Handoff

- final contracts
- HTTP/WebSocket API
- wire format
- stable errors
- state transitions
- commit list
- tests
- dependency-boundary evidence
- C에 남긴 open decision
