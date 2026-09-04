# Phase A Design Document
## Development Foundation: Agent Context Diet + WSL Source Hot-Deploy

- Phase: A
- 선행 조건: clean baseline과 보존용 tag/branch
- 후속 Phase: B — Core Foundation
- 하드웨어 요구: 없음
- production behavior 변경: 금지
- installer architecture 변경: 금지
- 핵심 결과:
  1. 에이전트가 거대한 incident history를 기본으로 읽지 않는다.
  2. Python/source 변경 후 installer 없이 설치된 WSL에서 실행한다.

---

# 1. 문제 정의

## 1.1 Agent context 문제

현재 루트 `AGENTS.md`는 구현·테스트·빌드·설치·배포·복구·삭제·handoff 전
`docs/MISTAKES_TO_AVOID.md`를 완전히 읽도록 요구한다.

해당 문서는 약 187KB이며 다음이 혼합되어 있다.

- 항상 지켜야 하는 안전 규칙
- 특정 날짜와 test run의 상세 경위
- 폐기된 architecture의 incident
- 당시 commit 및 process identity
- operator action history
- 아직 조사 중인 가설

이 정책은 작은 작업에도 과거 history 전체를 컨텍스트에 넣게 하며, 현재 코드를 읽을 여유를
줄이고 outdated detail을 새 요구사항으로 오해하게 만든다.

## 1.2 개발 배포 문제

현재 immutable WSL appliance와 replacement installer는 release에는 적합하지만,
개발 중 Python/source 변경을 확인할 때마다 새 installer를 만드는 것은 비효율적이다.

source만 바뀐 경우 이미 설치된 다음 환경을 재사용할 수 있다.

- verified WSL runtime
- custom kernel
- modules/firmware
- Python interpreter
- virtual environment
- pinned dependencies
- installed keys/config
- radio tooling

---

# 2. Design Goals

## Agent Context

- 역사적 evidence 무손실 보존
- active instructions를 짧고 task-routed하게 유지
- archive 전체 기본 읽기 금지
- error code/path/subsystem 일치 시에만 관련 incident 조회
- 안전 invariant는 active 문서에 유지
- 재발 방지는 prose보다 test/lint로 승격
- context policy 자체를 테스트

## Hot-Deploy

- installer 없이 개발 source 배포
- installed runtime/dependencies 재사용
- production runtime 불변
- dirty working tree 포함
- deterministic content ID
- atomic current switch
- dependency mismatch fail-closed
- explicit WSL distro/user/cwd/executable
- 공백·비ASCII Windows 경로 지원
- secret/machine state 제외
- 한 명령으로 sync + run

---

# 3. Non-Goals

Phase A에서는 다음을 하지 않는다.

- Room 기능 제거
- Pair Relay 구현
- Core Supervisor 구현
- CLI 제품 기능 구현
- Direct A/B 변경
- `relay/server.py` 변경
- WPF 변경
- WSL 포터블화
- WSL distro import/unregister 정책 변경
- replacement Provisioner 재작성
- kernel/driver/dependency 변경
- production installer build 변경
- `MISTAKES_TO_AVOID` 본문 요약·수정·재해석

---

# 4. Agent Context Architecture

## 4.1 Target File Layout

```text
AGENTS.md
docs/
├── MISTAKES_TO_AVOID.md
├── agent/
│   ├── INVARIANTS.md
│   └── CONTEXT_MAP.md
└── incidents/
    ├── INDEX.md
    ├── ARCHIVE_MANIFEST.json
    └── archive/
        └── MISTAKES_TO_AVOID-legacy-20260901.md

tools/
└── build_incident_index.py

tests/
└── test_agent_context_policy.py
```

파일명은 실제 repository convention에 맞춰 작게 조정할 수 있지만 다음 경계는 유지한다.

- active policy
- distilled invariants
- routing map
- generated index
- immutable archive

## 4.2 Migration Method

기존 incident body를 모델이 다시 작성하면 안 된다.

1. 원본 SHA-256 계산
2. `git mv` 또는 byte-for-byte copy
3. archive SHA-256 재계산
4. 두 hash 동일 확인
5. `ARCHIVE_MANIFEST.json`에 path, size, sha256 기록
6. 기존 경로에 짧은 routing stub
7. heading index를 script로 생성
8. active instruction 변경
9. test 실행

Archive는 historical evidence이며 formatting correction도 금지한다.

## 4.3 Root AGENTS Responsibilities

루트 `AGENTS.md`는 다음만 포함한다.

1. exact branch/base/status 확인
2. nearest applicable instructions 확인
3. one work packet / one conceptual boundary
4. relevant docs만 읽기
5. incident archive 전체 기본 읽기 금지
6. incident lookup trigger
7. global non-negotiable invariants
8. test/acceptance/handoff 규칙

권장 제한:

- 120 lines 이하
- 8KB 이하

## 4.4 Incident Lookup Triggers

다음 경우에만 `docs/incidents/INDEX.md`를 검색한다.

- recovery/cleanup 작업
- 기존 stable error code가 관찰됨
- 해당 subsystem의 ownership/lifecycle 변경
- 동일 failure 재발
- 사용자가 historical analysis를 명시적으로 요청

다음은 trigger가 아니다.

- 일반 구현
- 단위 테스트 추가
- typo 수정
- unrelated module 추가
- “안전을 위해 일단 전체 읽기”

## 4.5 Incident Promotion Policy

```text
Observed failure
→ run artifact/log

Cause unknown
→ investigating; global invariant 승격 금지

Reproduced/source-confirmed
→ 개별 incident 문서 또는 archive entry

General prevention found
→ INVARIANTS에 짧게 승격
→ 가능한 경우 test/lint 추가
```

## 4.6 Required Global Invariants

- first functional failure 보존
- cleanup failure는 secondary
- unknown은 absent가 아님
- one run owns one endpoint and one hardware lease
- polling/status read는 launch/revive 금지
- cleanup 확인 전 새 generation 금지
- exact source/runtime/process/device identity
- secret/MAC/capture/private path commit 금지
- unit test scope 과대해석 금지
- source/identity/hardware/protocol/privacy/cleanup gate 우회 금지

---

# 5. Hot-Deploy Architecture

## 5.1 Storage Model

### Installed Base

```text
/opt/switchtrade/
├── bridge/.venv/bin/python
├── requirements.txt
├── bridge/requirements.txt
├── switchtrade/
├── bridge/
├── config/prod.keys
└── scripts/
```

Phase A hot-deploy는 이 경로를 수정하지 않는다.

### Development Overlay

```text
/opt/switchtrade-dev/
├── releases/
│   ├── <content-id-1>/
│   └── <content-id-2>/
├── current -> releases/<content-id-2>
├── manifests/
└── .lock
```

`releases/<content-id>`는 immutable하게 취급한다.

## 5.2 Host File Layout

```text
dev.ps1
scripts/dev/
├── DevOverlay.psm1
├── install-overlay.sh
├── dev-source-allowlist.txt
└── README.md

tests/
└── test_dev_hot_deploy_contract.py
```

root `dev.ps1`은 얇은 command dispatcher다.

## 5.3 Commands

### Doctor

```console
.\dev.ps1 doctor
```

확인:

- Windows
- Store WSL availability
- `%LOCALAPPDATA%\SwitchTrade\state\active-runtime.json`
- schema와 `active_runtime`
- 해당 distro 등록
- `/etc/switchtrade-distro.json`
- `/opt/switchtrade/bridge/.venv/bin/python`
- Python version
- installed/local requirements hash
- overlay root ownership/permission

Doctor는 installer/repair를 자동 실행하지 않는다.

### Sync

```console
.\dev.ps1 sync
```

동작:

1. source allowlist 산출
2. secret/denylist 검사
3. relative path + file hash manifest
4. content ID 계산
5. temporary tar 생성
6. exact WSL distro로 전달
7. staging directory extract
8. manifest 재검증
9. release directory atomic commit
10. `current` symlink atomic switch
11. 오래된 overlay bounded cleanup

### Run

```console
.\dev.ps1 run -- <module-or-core-arguments>
```

Phase C 이후 목표 UX:

```console
.\dev.ps1 run host
.\dev.ps1 run join 381742
```

중요 환경:

```text
PYTHONNOUSERSITE=1
PYTHONPATH=/opt/switchtrade-dev/current
SWITCHTRADE_SOURCE_ROOT=/opt/switchtrade-dev/current
SWITCHTRADE_INSTALLED_ROOT=/opt/switchtrade
```

실행 경계:

- exact distro
- explicit user
- `--cd /opt/switchtrade-dev/current`
- `/opt/switchtrade/bridge/.venv/bin/python`
- explicit module
- no inherited Windows cwd

### Test

```console
.\dev.ps1 test
```

- overlay sync
- production venv
- overlay cwd/PYTHONPATH
- 선택한 pytest target
- test output/exit code 전달
- USB 또는 실물 radio 자동 획득 금지

### Clean

```console
.\dev.ps1 clean
```

삭제 가능:

```text
/opt/switchtrade-dev/**
```

삭제 금지:

```text
/opt/switchtrade/**
installed WSL registration
kernel files
.wslconfig
USB bind/share state
production logs/state
```

## 5.4 Source Allowlist

기본 포함 후보:

```text
switchtrade/**/*.py
bridge/**/*.py
bridge/**/*.sh
scripts/**/*.sh
tests/**/*.py
pytest.ini
requirements.txt
bridge/requirements.txt
config/wsl-radio-hardware.tsv
```

향후 포함:

```text
switchtrade/core/**
switchtrade/transport/**
switchtrade/endpoints/**
relay/core_*.py
```

기본 제외:

```text
.git/**
**/.venv/**
**/__pycache__/**
artifacts/**
runs/**
captures/**
support bundles
*.pcap
*.pcapng
*.zip
config/prod.keys
token/credential files
installer payloads
kernel artifacts
```

새 untracked source 파일도 allowlist 내부이고 ignore/forbidden 대상이 아니면 포함한다.

## 5.5 Content Identity

Git SHA만 사용하면 dirty 변경을 구분하지 못한다.

```text
content_id = SHA-256(
  sorted(relative_path + NUL + file_sha256 + LF)
)
```

Manifest:

```json
{
  "schema": 1,
  "git_head": "...",
  "dirty": true,
  "content_id": "...",
  "files": {
    "switchtrade/example.py": "..."
  }
}
```

## 5.6 Dependency Compatibility Gate

Local과 installed runtime의 다음 hash를 비교한다.

```text
requirements.txt
bridge/requirements.txt
```

불일치 시:

```text
DEV_DEPENDENCY_MISMATCH
The installed WSL runtime does not match this checkout.
Build/install a matching runtime once before using hot-deploy.
```

자동 `pip install` 금지.

## 5.7 Atomicity and Recovery

Deploy states:

```text
packing
→ copied
→ extracted
→ verified
→ committed
```

원칙:

- staging failure는 current 변경 금지
- existing release 덮어쓰기 금지
- current switch atomic
- interrupted staging은 ownership 확인 후 제거
- concurrent sync는 lock으로 거부
- run 중 release를 즉시 삭제하지 않음
- current와 previous 등 최소 2~3개 retention

---

# 6. Stable Error Contract

| Code | Meaning |
|---|---|
| `DEV_ACTIVE_RUNTIME_MISSING` | active runtime state 없음 |
| `DEV_ACTIVE_RUNTIME_INVALID` | state schema/path invalid |
| `DEV_WSL_RUNTIME_NOT_REGISTERED` | active distro 없음 |
| `DEV_RUNTIME_OWNERSHIP_INVALID` | marker mismatch |
| `DEV_PYTHON_MISSING` | installed interpreter 없음 |
| `DEV_DEPENDENCY_MISMATCH` | local/installed lock mismatch |
| `DEV_SOURCE_ALLOWLIST_EMPTY` | deploy source 없음 |
| `DEV_SOURCE_FORBIDDEN` | secret/forbidden file 포함 |
| `DEV_DEPLOY_BUSY` | concurrent operation |
| `DEV_ARCHIVE_FAILED` | tar 생성 실패 |
| `DEV_EXTRACT_FAILED` | WSL extract 실패 |
| `DEV_MANIFEST_MISMATCH` | copy 후 hash mismatch |
| `DEV_COMMIT_FAILED` | current switch 실패 |
| `DEV_RUN_FAILED` | child process nonzero |
| `DEV_CLEAN_REFUSED` | dev root 밖 삭제 시도 |

---

# 7. Tests

## Document Policy

- archive hash matches manifest
- index generator deterministic
- root AGENTS line/size limit
- no active instruction mandates full archive read
- active stub points to index
- runtime source untouched by A1

## Hot-Deploy Unit/Static

- allowlist intended source 포함
- denylist secret/capture 거부
- dirty edit로 content ID 변경
- manifest deterministic
- active runtime JSON validation
- dependency mismatch
- exact WSL cwd/executable construction
- production write/delete path 없음
- clean containment
- PowerShell parser
- shell syntax

## Live Development Smoke

- doctor against installed runtime
- sync from ASCII path
- sync from path containing spaces/non-ASCII
- overlay-only marker import
- Python line 변경 후 resync
- new content ID
- production sample hash 불변
- clean removes overlay only
- installer invocation 없음

---

# 8. Acceptance Criteria

1. Legacy body byte hash 보존
2. Root AGENTS가 archive 전체 읽기를 요구하지 않음
3. task-relevant docs만 routing
4. `dev.ps1 doctor`가 active runtime 식별
5. `dev.ps1 sync`가 dirty source 배포
6. `run/test`가 installed venv + overlay source 사용
7. requirements mismatch 차단
8. `/opt/switchtrade` 불변
9. installer/kernel/registration/USB ownership 불변
10. 관련 테스트 통과

---

# 9. Phase A Handoff

- base/final commits
- archived file hash
- active context 문서
- hot-deploy command examples
- live runtime
- dependency fingerprints
- production path invariance evidence
- test outputs
- known limitations
- B 시작 전 제약
