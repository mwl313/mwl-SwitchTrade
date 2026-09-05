# SwitchTrade Core Simplification Program
## 전체 상세 계획 — 기록용

- 작성일: 2026-09-05
- 프로젝트: `mwl313/mwl-SwitchTrade`
- 작성 시점 확인 기준: `main` commit `950aa778d9b1cc7a26168ea7b1e2348848cb45ee`
- 문서 성격: 의사결정·범위·진행 순서를 보존하는 기록 문서
- 구현 에이전트용 프롬프트: 별도 A/B/C Prompt 문서 참조
- 현재 상태: Phase A·B 완료, C1 시작 가능
- 실행 브랜치: `Simple-Architecture` (main 변경 금지)
- Phase B 종료 근거: `09f4eb0f3b59e2e40a040ae8e35aa5283a055f41`, CI run #33941204541 (Windows·Ubuntu green)
- 실행 원칙: **A → B → C → D → E 순차 진행**

> 이 문서의 commit 정보는 작성 시점의 기준점이다. 실제 작업을 시작할 때는 반드시
> `git rev-parse HEAD`, 현재 브랜치, working tree 상태를 다시 기록한다.

---

# 1. 프로그램의 목적

현재 SwitchTrade는 실물 Nintendo Switch의 FireRed/LeafGreen 로컬 통신을 인터넷으로
중계하기 위한 핵심 기술 외에도 다음 책임이 하나의 제품에 누적되어 있다.

- Windows WPF UI
- Public/Private Trade Room
- Room metadata와 public directory
- Ready 및 Switch 역할 선택
- authoritative room/attempt lifecycle
- 사용자 checkpoint와 Continue 절차
- P0/ABC+D qualification orchestration
- 설치·복구·업데이트·진단
- WSL appliance와 custom kernel
- USB Wi-Fi 소유권 관리
- Pokémon party 관찰
- 레거시와 신형 tunnel 경로
- 다수의 milestone, incident, handoff 문서

이 구조는 안정적인 제품을 만들기 위해 많은 안전장치를 추가한 결과지만, 현재 개발 목적에는
다음 문제가 있다.

1. 사용자가 프로젝트 전체를 이해하고 관리하기 어렵다.
2. 작은 변경도 Room, Control API, WPF, WSL, installer를 모두 거쳐야 한다.
3. 새 버전을 시험할 때마다 installer를 실행하는 비용이 너무 크다.
4. `MISTAKES_TO_AVOID.md` 전체 읽기 의무가 에이전트 컨텍스트를 잠식한다.
5. 코드 작성 모델의 잔량이 제한되어 있어 작은 작업 단위와 명확한 검증 경계가 필요하다.
6. 향후 RetroArch gpSP를 연결하려면 현재 Switch 전용 제품 lifecycle과 endpoint를 분리해야 한다.

이 프로그램의 목표는 현재 제품을 조금 축소하는 것이 아니다.

> **검증된 무선·Pia·Reliable·RFU 구현은 보존하면서, 1:1 연결만 담당하는 작고
> endpoint-neutral한 SwitchTrade Core 실행 경로를 새로 만든다.**

---

# 2. 최종 제품 목표

## Host

```console
switchtrade host
```

```text
Pair code: 381742
Waiting for peer...
Peer connected.
Waiting for the Group Leader Switch...
Local room detected.
Remote mirror ready.
Bridge active.
```

## Guest

```console
switchtrade join 381742
```

```text
Connecting with code 381742...
Peer connected.
Waiting for the host's Switch...
Mirror access point ready.
Choose Join Group on the Switch at any time.
Bridge active.
```

사용자에게 다음 개념은 노출하지 않는다.

- Public Room
- Private Room
- Room Browser
- Lobby
- Ready
- Attempt
- Role Lock
- Start Session
- Connection Test
- Continue checkpoint
- 수동 AP 시작
- 수동 scan 시작
- 두 PC의 타이밍 맞추기

단, 게임 안의 물리적 역할은 남는다.

- Host 측 Switch: **Group Leader**
- Guest 측 Switch: **Join Group**

Guest 측 미러 AP는 Host 측 실제 Switch 방의 advertisement가 존재한 뒤에만 만들 수 있다.
따라서 “프로그램 실행 즉시 영구 AP”가 아니라 다음이 정확한 목표다.

> **상시 준비 상태 + 실제 방을 감지하는 즉시 자동 미러 AP 생성**

---

# 3. 확정한 핵심 결정

## 3.1 A–E를 순차 진행한다

```text
A. 개발 기반 정리
   ↓
B. 하드웨어 독립 Core
   ↓
C. Switch LDN Core 연결
   ↓
D. 실기 안정화
   ↓
E. RetroArch gpSP 확장
```

- A가 끝나야 모든 후속 에이전트가 짧은 컨텍스트와 빠른 실행 경로를 사용한다.
- B가 끝나야 C가 Switch 전용 코드를 Core에 억지로 섞지 않는다.
- C가 끝나야 D에서 Core 결함과 실물 RF 결함을 구분할 수 있다.
- D에서 Switch↔Switch 기준선을 안정화한 뒤 E의 emulator 변수를 추가한다.

각 Phase 내부에서도 기본은 순차 작업 패킷이다. 계약이 동결된 뒤에만 독립 테스트나 문서 작업을
제한적으로 병렬화한다.

## 3.2 포터블 WSL은 목표에서 제외한다

포터블화의 실제 목적은 “개발 코드 변경마다 installer를 다시 돌리지 않기”였다.

따라서 해결책은 다음으로 축소한다.

> **기존 WSL appliance와 dependency는 한 번 설치해 두고, 개발 소스만 별도 overlay에
> hot-deploy하여 실행한다.**

하지 않을 일:

- 매 실행 시 WSL distro import/unregister
- custom portable WSL manager 신규 작성
- 설치된 Provisioner 재작성
- production `/opt/switchtrade` 덮어쓰기
- 개발 편의를 위한 자동 `apt`/`pip`

Installer/runtime rebuild가 필요한 변경:

- Python dependency lock
- `ldn` 버전
- WSL base appliance
- kernel/module
- driver/firmware

일반 Python, Relay, Core, CLI 변경은 hot-deploy로 시험한다.

## 3.3 기존 full product는 C 완료 전까지 삭제하지 않는다

```text
기존 경로
WPF → Control API → Room Authority → Production Runner → ABC+D

신규 경로
CLI → Pair Client → Core Supervisor → Endpoint Driver
```

C의 software acceptance와 첫 end-to-end 검증 전까지 다음을 유지한다.

- `apps/desktop/`
- 기존 `switchtrade/control.py`
- 기존 production room/attempt API
- 기존 installer/replacement
- 기존 ABC+D test suite
- 현재 published release/tag

## 3.4 Pair와 Generation을 분리한다

### Pair

6자리 코드로 두 PC가 만난 뒤 프로그램 종료 전까지 유지되는 인터넷 연결 관계다.

```text
Pair
├── pair_id
├── host credential
├── guest credential
├── peer presence
├── reconnect lease
└── protocol capabilities
```

### Generation

한 번 생성된 실제 Switch 방과 미러 AP의 수명이다.

```text
Generation
├── generation_id
├── protocol_id
├── opaque advertisement/setup payload
├── local endpoint session
├── remote endpoint session
├── data stream
└── cleanup result
```

Pair를 다시 만들지 않고 여러 Generation을 실행할 수 있는 구조를 처음부터 사용한다.
실제 반복·reconnect·soak acceptance는 D에서 수행한다.

## 3.5 Endpoint, Runtime, Protocol, Relay를 분리한다

```text
Core
├── Pair
├── Generation
├── Supervisor
└── Endpoint interface

Endpoint Drivers
├── Switch LDN
└── RetroArch gpSP (E)

Runtime Backends
├── Installed/Managed WSL
└── Native Windows (E)

Protocol Adapters
├── Switch GBA-frame/RFU
├── gpSP RFU1 (E)
└── mixed Switch↔gpSP adapter (E)

Relay
└── 인증된 두 socket 사이의 opaque forwarding
```

Relay는 FireRed, Switch, gpSP, Pokémon command를 알면 안 된다.

## 3.6 Terra/Luna가 구현하고 설계·검수는 별도로 관리한다

| 책임 | 담당 |
|---|---|
| 프로그램 전체 설계와 의사결정 | ChatGPT 오케스트레이션 |
| 각 작업 패킷과 프롬프트 작성 | ChatGPT 오케스트레이션 |
| 구현 diff, 호출 경로, 테스트 결과 검토 | ChatGPT 오케스트레이션 |
| 실제 코드 작성 | Terra 또는 Luna |
| 2차 실패 관점 리뷰 | 다른 한쪽 모델 |
| 희소한 Codex 사용 | C의 고위험 통합 또는 D/E 핵심 감사 |
| 실물 Wi-Fi/Switch 실행 | 사용자 |
| 로그와 failure 분석 | ChatGPT 오케스트레이션 |

Codex를 남겨둘 가치가 큰 지점:

1. Direct A/B lifecycle과 Core Supervisor 최종 결합 감사
2. USB·WSL·cleanup 소유권이 함께 걸리는 변경
3. Switch framing과 gpSP protocol 변환 검증

---

# 4. 현재 코드에서 보존할 가치가 높은 부분

## 거의 그대로 보존

```text
bridge/frlgsim/tunnel.py
bridge/frlgsim/sim.py
bridge/frlgsim/reliable.py
bridge/frlgsim/pia_connect.py
bridge/frlgsim/crypto.py

switchtrade/connection/a_stage.py
switchtrade/connection/b_stage.py
switchtrade/connection/stage_session.py
switchtrade/connection/data_plane.py

switchtrade/rfu_tunnel_v2.py의 epoch/sequence/probe 원칙
switchtrade/hardware.py
switchtrade/process_guard.py

scripts/wsl-radio-prepare.sh
scripts/radio-health-gate.sh
config/wsl-radio-hardware.tsv
```

## 원칙만 보존하고 Core에서는 직접 사용하지 않음

```text
switchtrade/connection/coordinator.py
switchtrade/connection/service.py
switchtrade/connection/production_run.py
switchtrade/connection/distributed_harness.py
switchtrade/control.py
relay/authority.py
apps/desktop/
```

보존할 원칙:

- 단일 owner
- bounded queue
- stale generation 거부
- 최초 failure 보존
- idempotent stop
- cleanup 검증
- 정확한 hardware identity

제외할 제품 개념:

- Room metadata
- owner/member room semantics
- Ready
- optimistic room version
- public listing
- trainer profile
- role selection UI
- user checkpoint
- party display

---

# 5. Target Architecture

```text
Windows Development Host
└── dev.ps1
    ├── doctor
    ├── sync
    ├── run
    ├── test
    └── clean
          │ source-only hot deploy
          ▼
Installed SwitchTrade WSL
├── /opt/switchtrade/       immutable installed base
│   ├── Python / venv
│   ├── dependencies
│   ├── config / keys
│   └── verified radio environment
└── /opt/switchtrade-dev/   disposable development overlay
    ├── releases/<content-id>/
    └── current
          │
          ▼
SwitchTrade Core
├── PairClient ↔ Core Relay
├── CoreSupervisor
│   ├── Pair lifetime
│   ├── Generation lifetime
│   ├── probe / sequence / backpressure
│   └── cleanup ownership
└── SwitchLdnEndpointDriver
    ├── leader_side → DirectAStage
    ├── mirror_side → DirectBStage
    ├── StageSession
    ├── TunnelSim
    └── Pia / Reliable / RFU
```

---

# 6. Phase Overview

| Phase | 이름 | 핵심 결과 | 실물 하드웨어 |
|---|---|---|---|
| A | Development Foundation | 문서 컨텍스트 축소 + source hot-deploy | 사용하지 않음 |
| B | Core Foundation | Pair Relay + Pair/Generation/Supervisor + fake endpoint | 사용하지 않음 |
| C | Switch Core Integration | Direct A/B/TunnelSim 연결 + 실제 CLI + 자동 scan/AP | software 중심 |
| D | Physical Stabilization | 반복 Generation, reconnect, soak, residue-free cleanup | 필수 |
| E | Emulator Expansion | RetroArch gpSP endpoint와 mixed protocol | emulator 및 선택적 Switch |

---

# 7. Phase A — Development Foundation

## 목표

1. 모든 작업 전에 187KB incident 문서를 읽는 정책 제거
2. 역사적 evidence 무손실 보존
3. 개발 코드 변경 시 installer를 재실행하지 않는 hot-deploy
4. 후속 Terra/Luna 작업의 컨텍스트와 반복 시간 감소

## A1. Agent Context Policy Migration

- 기존 `MISTAKES_TO_AVOID.md` 본문을 byte-preserving archive로 이동
- 기존 경로에는 짧은 routing stub
- incident heading을 기계적으로 추출한 index
- 루트 `AGENTS.md`를 짧은 invariant + context routing으로 교체
- archive 전체 기본 읽기 금지
- 관련 error code/path가 있을 때만 선택 조회
- 문서 정책 회귀 테스트

## A2. Development Hot-Deploy

- root `dev.ps1`
- `doctor`, `sync`, `run`, `test`, `clean`
- active WSL runtime 확인
- installed Python/dependency 재사용
- source allowlist만 `/opt/switchtrade-dev/releases/<content-id>`에 배포
- `current` atomic switch
- `/opt/switchtrade` 불변
- explicit distro/user/Linux cwd/executable
- requirements hash 불일치 차단
- secret/config key는 installed absolute path 사용
- dirty working tree도 content hash로 식별
- failed deploy는 current 변경 금지

## Phase A Exit Gate

- archive 전체를 읽지 않고 정상 agent 작업 가능
- installer 없이 `dev.ps1 sync/test/run`
- production runtime 불변
- dependency mismatch fail-closed

---

# 8. Phase B — Core Foundation

## 목표

Switch, WSL, Wi-Fi, `ldn`, WPF, 기존 Room Authority 없이 구현:

- 6자리 Pair
- Host/Guest credential
- endpoint-neutral WebSocket
- Pair lifetime
- Generation lifetime
- readiness/probe
- sequence/epoch
- bounded queue
- cleanup
- fake endpoint E2E

## 작업 패킷

1. B1 Core domain contracts + fake endpoint
2. B2 Minimal Pair Relay
3. B3 Generation-bound wire transport
4. B4 CoreSupervisor
5. B5 Software-only end-to-end

## Phase B Exit Gate

- Core/Relay에 `ldn`, WSL, WPF, FRLG import 없음
- fake endpoint 두 개가 실제 WebSocket Relay로 양방향 통신
- Pair와 Generation 수명 분리
- 기존 production Room API 회귀 없음

---

# 9. Phase C — Switch Core Integration

## 목표

Phase B Core에 현재 검증된 Switch LDN 경로 연결

## 역할

| 사용자 | Pair seat | Generation role | Switch | PC 무선 |
|---|---|---|---|---|
| Host | host | origin | Group Leader | 실제 방 scan/join |
| Guest | guest | mirror | Join Group | 미러 AP 생성 |

## 작업 패킷

1. C1 Switch endpoint boundary
2. C2 Direct A leader-side adapter
3. C3 Direct B mirror-side + TunnelSim adapter
4. C4 CLI + automatic lifecycle
5. C5 Software qualification

## Phase C Exit Gate

- Host CLI가 6자리 code 생성
- Guest CLI가 code로 pair
- Host 방 자동 scan
- advertisement 자동 전달
- Guest mirror AP 자동 시작
- TunnelSim이 Core transport 위에서 pump
- 한 Generation의 start/active/close
- `Ctrl+C` cleanup
- 기존 WPF/Room product 병렬 보존

---

# 10. Phase D — Physical Stabilization

ABC 완료 후 상세 문서와 프롬프트를 작성한다.

예정 범위:

- Switch↔Switch 첫 end-to-end
- Host/Guest 시작 순서 변형
- 늦은 Join Group
- 반복 Generation
- relay short disconnect
- peer process restart
- scan/AP timeout recovery
- 30분 idle 및 traffic soak
- 20-generation loop
- 모든 상태의 `Ctrl+C`
- AP/TAP/interface/PHY residue
- USB return
- WSL process absence
- first failure preservation

D는 새로운 기능 추가가 아니라 안정화와 acceptance다.

---

# 11. Phase E — RetroArch gpSP Expansion

D 완료 후 실제 gpSP branch/commit을 읽고 상세 문서와 프롬프트를 작성한다.

예정 조합:

| PC A | PC B | Runtime |
|---|---|---|
| Switch | Switch | WSL ↔ WSL |
| Switch | gpSP | WSL ↔ Native |
| gpSP | Switch | Native ↔ WSL |
| gpSP | gpSP | Native ↔ Native |

원칙:

- gpSP RFU1과 SwitchTrade GBA-frame이 동일하다고 가정하지 않음
- mixed path는 stateful ProtocolAdapter
- Relay는 protocol 변환 금지
- emulator-only 실행은 WSL 준비 금지

---

# 12. Branch, Commit, Handoff Strategy

## 권장 시작

1. `main` clean 확인
2. base commit과 release/tag 기록
3. 보존용 tag 제안: `pre-core-simplification`
4. branch 제안: `core-simplification`
5. 작은 numbered commit

예시:

```text
A1 docs: replace mandatory full incident reads
A2 dev: add source-only WSL hot deploy
A3 test: verify development foundation

B1 core: add domain contracts and fakes
B2 relay: add minimal pair service
B3 transport: add generation-bound wire client
B4 core: add endpoint-neutral supervisor
B5 test: qualify fake end-to-end core

C1 endpoint: add Switch LDN boundary
C2 endpoint: adapt Direct A leader side
C3 endpoint: adapt Direct B mirror side
C4 cli: add host and join commands
C5 test: qualify Switch Core composition
```

## 작업 패킷 필수 항목

- exact branch/base commit
- allowed files
- forbidden files
- one goal
- non-goals
- required interfaces
- invariants
- exact tests
- acceptance criteria
- required response format

## Handoff 필수 항목

- commit hash
- 변경 파일
- 실제 테스트 명령과 결과
- 새 error codes
- cleanup/migration 필요 여부
- 다음 작업 제약
- unresolved items

---

# 13. Cross-Phase Invariants

1. 최초 functional failure 보존
2. cleanup failure는 secondary
3. `unknown` ≠ `absent`
4. 한 Pair에는 host/guest 한 좌석
5. 6자리 code는 인증 토큰이 아님
6. credential로 seat 결정
7. 한 Generation은 하나의 generation ID
8. old generation/epoch frame 거부
9. bounded queue overflow는 명시적 failure
10. status read는 launch/revive 금지
11. 이전 cleanup 확인 후 다음 Generation
12. endpoint는 자신이 만든 local resource만 제거
13. dev hot-deploy는 `/opt/switchtrade` 수정 금지
14. dependency mismatch 자동 설치 금지
15. secret/token/MAC/capture/private path commit 금지
16. unit test를 실물 acceptance로 표현 금지
17. Core는 concrete endpoint/runtime import 금지
18. Relay는 endpoint protocol 해석 금지
19. 사용자 checkpoint 제거와 내부 probe 제거를 혼동하지 않음
20. proven code 동작 변경은 별도 commit과 regression test

---

# 14. 주요 위험

| 위험 | 예방 |
|---|---|
| incident evidence 손실 | byte-preserving archive + hash manifest |
| hot-deploy의 production 오염 | 별도 dev root + production write 금지 |
| dependency mismatch 오진 | local/installed lock hash 비교 |
| B가 Room server를 재사용 | 병렬 core relay path |
| Pair seat와 Switch role 혼동 | 별도 enum/명칭 |
| one-shot stage 재사용 | 매 retry 새 객체 |
| retry residue | cleanup barrier + backoff |
| Core가 ldn private API 인지 | Switch driver 내부 격리 |
| gpSP format 추측 | E 시작 시 실제 branch 감사 |
| 에이전트 범위 확장 | allowed/forbidden files |
| Codex 잔량 소모 | 고위험 통합 감사에만 사용 |
| C 전 legacy 삭제 | D 전까지 full product 보존 |

---

# 15. Completion Definition

## ABC 완료

- bounded Agent context
- installer 없는 source hot-deploy
- minimal Pair Relay
- endpoint-neutral CoreSupervisor
- fake endpoint E2E
- Switch LDN endpoint adapter
- host/join CLI
- 자동 scan 및 advertisement 전달
- 자동 mirror AP
- TunnelSim bridge composition
- deterministic local cleanup path
- 기존 product 경로 보존
- software tests 통과

## 전체 완료

- Switch↔Switch 실기 안정화
- 반복/reconnect/soak
- residue-free cleanup
- gpSP native endpoint
- gpSP↔gpSP
- Switch↔gpSP
- 최종 release/installer 경로 정리
- legacy archive/제거 결정

---

# 16. Immediate Next Action

다음 실행은 **Phase C1뿐**이다.

1. C Design을 승인 기준으로 사용
2. C Prompt의 C1만 실행
3. Switch LDN boundary와 import isolation을 검증
4. C1 commit을 검토·푸시
5. C2로 진행하기 전에 C1 acceptance를 별도 검수

C2 이후 작업은 각 선행 packet의 acceptance를 통과한 뒤에만 시작한다.
