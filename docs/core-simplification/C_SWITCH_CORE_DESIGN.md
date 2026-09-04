# Phase C Design Document
## Switch Core Integration: Direct A/B + TunnelSim + CLI Automation

- Phase: C
- 선행 조건: Phase B Exit Gate 통과
- 후속 Phase: D — Physical Stabilization
- 핵심 목표: 현재 proven Switch LDN/RFU 코드를 새 endpoint-neutral Core에 연결
- 기존 full product: 병렬 보존
- production-ready 선언: 금지, D 이후 판단

---

# 1. Purpose

Phase C는 Phase B의 fake endpoint를 실제 Switch LDN endpoint로 대체할 수 있게 한다.

구현할 흐름:

```text
Host CLI
→ Pair code 생성
→ 실제 Group Leader Switch 방을 계속 탐색
→ 방 발견 시 자동 참가
→ advertisement 전송
→ remote mirror 준비
→ RFU bridge

Guest CLI
→ Pair code 입력
→ advertisement 대기
→ 자동 mirror AP 생성
→ Joining Switch association 대기
→ RFU bridge
```

사용자는 두 PC의 타이밍을 맞추거나 Continue/Ready/Start를 누르지 않는다.

---

# 2. Fixed Role Model

## Pair Host / `leader_side`

- 6자리 code를 생성하는 PC
- Pair seat: `host`
- Generation role: `origin`
- 이 PC 옆의 Switch: Group Leader
- PC radio: 실제 Switch 방 scan 후 station join
- Existing implementation: `DirectAStage`
- `TunnelSim(parent=False)`

## Pair Guest / `mirror_side`

- 6자리 code를 입력하는 PC
- Pair seat: `guest`
- Generation role: `mirror`
- 이 PC 옆의 Switch: Join Group
- PC radio: remote advertisement로 mirror AP
- Existing implementation: `DirectBStage`
- `TunnelSim(parent=True)`

“Host”를 AP host 의미로 재사용하지 않는다.

우선 명칭:

```text
leader_side
mirror_side
origin
mirror
```

---

# 3. Boundary and File Layout

권장 신규 구조:

```text
bridge/
└── __init__.py

switchtrade/
├── endpoints/
│   └── switch_ldn/
│       ├── __init__.py
│       ├── driver.py
│       ├── generation.py
│       ├── connection.py
│       ├── tunnel_adapter.py
│       ├── cleanup.py
│       └── errors.py
│
├── composition.py
└── core_cli.py

tests/
├── test_switch_ldn_driver.py
├── test_switch_ldn_tunnel_adapter.py
├── test_switch_core_composition.py
└── test_switch_core_cli.py
```

기존 Direct A/B와 `bridge/frlgsim`은 가능한 한 제자리에서 재사용한다.

---

# 4. Dependency Direction

```text
core contracts
       ▲
       │
SwitchLdnEndpointDriver
       │
       ├── DirectAStage
       ├── DirectBStage
       ├── StageSession
       ├── TunnelSim
       ├── Pia connection manager
       └── hardware policy
```

금지:

```text
switchtrade/core → switch_ldn
switchtrade/core → ldn
relay/core_server → switch_ldn
relay/core_server → FRLG
```

Composition root와 CLI만 concrete driver를 선택한다.

---

# 5. Existing Code Reuse

## 5.1 DirectAStage

기존 책임:

- exact channel scan
- exact FRLG room identification
- advertisement validation
- station association
- Nintendo control port
- participant state
- data plane

재사용 원칙:

- 내부 algorithm 변경 금지
- one-shot/no-retry 유지
- retry는 outer driver가 새 object 생성
- failure code/gate 보존
- StageSession으로 sustained context 유지

## 5.2 DirectBStage

기존 책임:

- advertisement validation
- selected PHY reset
- network construction
- AP/monitor/TAP
- data plane
- over-air advertisement
- Switch association
- Nintendo control
- teardown

재사용 원칙:

- proven `ldn.create_network()` 유지
- hostapd/nl80211 experimental 경로로 교체 금지
- one-shot/no-retry 유지
- 실패 후 새 object 생성
- exact selected resource만 cleanup

## 5.3 StageSession

- Direct stage thread owner
- sustained local context
- `wait_ready()`
- `stop()` sole exit owner

Core driver가 ownership을 침범하지 않는다.

## 5.4 TunnelSim

장점:

- game command를 해석하지 않음
- local Pia/Reliable 종단
- opaque application/RFU bytes
- optional observer
- 작은 tunnel surface

필요 surface:

```text
connected
connection_generation
send_rfu(payload, flags)
poll()
```

Phase B transport를 여기에 맞추는 `CoreTunnelAdapter`를 만든다.

---

# 6. SwitchLdnEndpointDriver

## 6.1 Capabilities

```text
endpoint_kind: switch_ldn
runtime_kind: managed_wsl
protocols:
  - switchtrade.gba-frame.v1
generation_roles:
  - origin
  - mirror
```

실제 composition에서는 host=origin, guest=mirror다.

## 6.2 Prepare

Prepare 확인:

- explicit selected adapter/USB ID
- hardware profile
- runtime-provided PHY
- installed keys absolute path
- required `ldn` version
- no active owned endpoint
- no unresolved cleanup

C에서 WSL Provisioner를 재작성하지 않는다.

## 6.3 Discover — Leader Side

```text
while not canceled:
    create fresh DirectAStage
    wrap in StageSession
    start
    if no room / scan timeout:
        stop or confirm terminal stage
        verify cleanup
        bounded backoff
        continue
    if fatal hardware/policy:
        fail
    if ready:
        retain StageSession
        create GenerationOffer(advertisement)
        return LeaderGeneration
```

Retryable 후보:

- no room observed
- scan timeout

Non-retryable/user-action 후보:

- keys invalid
- dependency/version mismatch
- adapter/PHY missing
- policy invalid
- repeated cleanup failure
- ambiguous exact room

Ambiguous room을 임의 선택하지 않는다.

## 6.4 Accept — Mirror Side

```text
validate protocol
validate advertisement through existing DirectB path
create fresh DirectBStage(application_data=offer.setup_payload)
wrap in StageSession
start
wait AP/data-plane/association readiness
retain StageSession
return MirrorGeneration
```

AP는 advertisement 전에는 만들지 않는다.

---

# 7. Connection and Tunnel Composition

## Leader

DirectA resources로 생성:

- `pia_connect.ConnectionManager`
- random local variable ID
- `PiaCrypto`
- `CoreTunnelAdapter`
- `TunnelSim(parent=False)`

## Mirror

DirectB resources로 생성:

- `pia_connect.HostConnectionManager`
- random local variable ID
- `PiaCrypto`
- `CoreTunnelAdapter`
- `TunnelSim(parent=True)`

## Tick Loop

```text
while generation active:
    simulation.tick()
    core tunnel pump
    observe cancel/failure
    sleep to next VBlank deadline
```

unbounded drift와 busy loop 금지.
Party observer는 Core acceptance에서 기본 비활성화한다.

---

# 8. Automatic Readiness

사용자 Ready는 제거하지만 내부 readiness는 유지한다.

1. Pair authenticated
2. peer socket ready
3. bidirectional probe
4. generation offer accepted
5. local Direct A/B ready
6. both generation identities match
7. data admission enabled
8. optional traffic status

WebSocket connect만으로 bridge ready 선언 금지.

---

# 9. CLI Design

## Commands

```console
python -m switchtrade.core_cli host
python -m switchtrade.core_cli join 381742
```

최소 options:

```text
--relay URL
--usb-id VID:PID
--channel 1|6|11
--verbose
--log-dir PATH
```

Room name, trainer name, visibility, Ready, role choice, Continue 없음.

## Development Wrapper

```console
.\dev.ps1 run host
.\dev.ps1 run join 381742
```

## User-facing States

Host:

```text
Starting SwitchTrade...
Pair code: 381742
Waiting for peer...
Peer connected.
Waiting for a Group Leader room...
Group Leader room detected.
Preparing remote mirror...
Remote mirror ready.
Bridge active.
```

Guest:

```text
Starting SwitchTrade...
Connecting with code 381742...
Peer connected.
Waiting for the host's Switch...
Preparing the mirror access point...
Mirror access point ready.
Choose Join Group on the Switch at any time.
Bridge active.
```

기술 로그는 `--verbose` 또는 file에 분리한다.

## Cancellation

`Ctrl+C`:

- expected cancellation traceback 없음
- stopping 상태
- generation cleanup
- transport close
- endpoint cleanup
- final stopped
- cleanup/unexpected failure만 nonzero

---

# 10. Cleanup Ownership

## Generation Close Order

1. generation closing
2. local packet admission stop
3. remote DATA admission stop
4. bounded drain/discard accounting
5. `TunnelSim` close
6. `StageSession` stop
7. Direct context release 확인
8. owned AP/monitor/TAP/interface 확인
9. Core generation transport close
10. CleanupReport publish
11. generation clear

## Failure Rules

- first functional failure primary
- cleanup failure secondary
- unknown cleanup blocks next generation
- unrelated PHY/interface 삭제 금지
- exact owner가 아닌 layer의 USB detach 금지
- prior StageSession thread 종료 전 retry 금지

---

# 11. Retry Policy

## Leader Discovery

- no-room/scan-timeout: 0.5–2초 bounded backoff
- retry 전 cleanup
- cancellation check
- tight loop 금지

## Mirror

- Pair가 살아 있으면 offer 대기
- one DirectB per offer
- AP timeout closes generation
- extensive repeated-generation qualification은 D

## Pair Reconnect

Core transport가 short reconnect와 re-probe를 처리한다.
진행 중 physical game generation 보존은 C에서 보장하지 않는다.

---

# 12. Error Mapping

기존 Direct A/B code를 보존한다.

추가 adapter code 후보:

| Code | Meaning |
|---|---|
| `SWITCH_ENDPOINT_POLICY_INVALID` | config/policy invalid |
| `SWITCH_ENDPOINT_BUSY` | prior resource owner active |
| `SWITCH_ENDPOINT_PROTOCOL_MISMATCH` | unsupported offer |
| `SWITCH_ENDPOINT_TUNNEL_FAILED` | adapter failure |
| `SWITCH_ENDPOINT_TICK_FAILED` | simulation failure |
| `SWITCH_ENDPOINT_CLEANUP_FAILED` | cleanup unverified |
| `SWITCH_GENERATION_CANCELED` | expected cancellation |

`A_*`, `B_*`, transport error를 generic failure로 flatten하지 않는다.

---

# 13. Tests

## Import Boundary

- Core does not import Switch driver
- Relay does not import Switch driver
- Switch driver boundary owns new `ldn`/FRLG imports
- composition root selects driver

## Driver Unit

Injected fake Direct stages/StageSession/resources:

- leader no-room retry
- fresh object per retry
- cancellation
- fatal/ambiguous error preservation
- advertisement offer
- mirror validation/readiness
- StageSession ownership
- cleanup order/failure

## Tunnel Adapter

- send RFU payload/flags
- poll remote frames
- connection generation
- disconnected queue reset
- bounds/stale/backpressure

## Composition

- fake Direct A/B resources
- two supervisors
- offer/accept
- TunnelSim-compatible adapter
- tick start/stop
- first failure
- no user checkpoint

## CLI

- host code output
- join validation
- minimal options
- Ctrl+C no traceback
- stable errors
- verbose separation

## Regression

- Direct A/B
- StageSession
- TunnelSim/Reliable/Pia
- Phase B
- existing Room/production
- Phase A hot-deploy

---

# 14. Acceptance Criteria

1. Host equivalent produces 6-digit code
2. Guest joins
3. new path uses no Room/Lobby/Ready/Continue
4. leader scan starts automatically
5. retry uses fresh DirectAStage
6. advertisement becomes GenerationOffer
7. mirror AP starts automatically after offer
8. TunnelSim uses CoreTunnelAdapter
9. both local sides ready before DATA
10. CLI cancellation cleans up
11. no hostapd substitution
12. existing full product intact
13. software tests pass
14. physical stability deferred to D

---

# 15. Phase C Handoff

- role mapping
- final endpoint interface
- reused modules
- changed modules/reasons
- CLI commands
- retry policy
- cleanup order
- stable errors
- tests
- D에 남은 unproven items
