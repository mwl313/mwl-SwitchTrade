# MWL-SwitchTrade

> **순정 Nintendo Switch의 공식 Game Boy 서비스 포켓몬 게임을 인터넷으로 연결하는 트레이딩 시스템.**

> **WSL kernel warning:** the beta distribution will select the SwitchTrade custom kernel globally
> while it is installed. This overrides the active kernel selection for every WSL 2 distribution;
> setup must back up the existing `.wslconfig`, require explicit consent, and provide rollback.

스위치는 인터넷에 연결된 기기인데, 게임보이 포켓몬(FRLG 등)은 로컬 통신만 된다.
그 로컬 통신(LDN)을 PC 브리지가 가로채서 인터넷으로 연결한다. **홈브류/커펌 없이, 순정 그대로.**

## 한눈에 보기

```
[Switch A] ──LDN 무선──> [PC 브리지 A] ──인터넷 터널/릴레이──> [PC 브리지 B] <──LDN 무선── [Switch B]
```

- **기반 기술** (이미 존재, 검증됨): kinnay/LDN (로컬 무선 계층) + tornadus/frlg-ldn-trade (FRLG 게임 계층)
- **현재 구현**: 서버 권위 2인 private room + credentialed opaque RFU relay + native Windows/WSL client
- **출시 전 잔여**: relay 운영 검증, unsigned package/clean-machine 및 two-PC/two-Switch qualification
- **참고 아키텍처**: GB-Link/Celio 생태계 (실기 GBA를 인터넷에 연결한 형제 프로젝트)

## 문서

| 문서 | 내용 |
|---|---|
| [docs/00-project-brief.md](docs/00-project-brief.md) | 프로젝트 개요 — 목적/제약/범위/이름 후보 |
| [docs/01-assessment.md](docs/01-assessment.md) | 기술 스택 평가 — 툴체인 조합, 미싱 링크, 리스크 |
| [docs/02-roadmap.md](docs/02-roadmap.md) | 로드맵 — Phase 0~4 |
| [docs/03-vm-setup-guide.md](docs/03-vm-setup-guide.md) | 외장하드 VM 셋업 가이드 (Ubuntu Server, 최소 오버헤드) |
| [docs/04-trade-workflow.md](docs/04-trade-workflow.md) | 트레이드 워크플로우 v1 (검증된 절차) |
| [docs/05-phase2-design.md](docs/05-phase2-design.md) | Phase 2 상세 설계 — PC↔PC 인터넷 브리지 |
| [docs/06-distribution.md](docs/06-distribution.md) | 배포 전략 — 리눅스 레이어 분석, WSL2/ESP32 경로 |
| [docs/24-wsl-radio-validation-20260824.md](docs/24-wsl-radio-validation-20260824.md) | WSL/VM 카드별 G2~G4 검증과 RTL8188EU 진단 |
| [docs/50-current-product-demo-todo-20260825.md](docs/50-current-product-demo-todo-20260825.md) | **현재 제품 데모 즉시/백로그 TODO와 화면 흐름 (권위 문서)** |
| [docs/49-production-beta-priorities-20260825.md](docs/49-production-beta-priorities-20260825.md) | 프로덕션 베타의 기술적 근거와 출시 게이트 |
| [docs/51-windows-installer-bootstrap-design-20260825.md](docs/51-windows-installer-bootstrap-design-20260825.md) | Windows 설치·WSL 구성·재부팅 재개·롤백 설계 |
| [docs/54-native-ui-flow-and-runtime-structure-20260825.md](docs/54-native-ui-flow-and-runtime-structure-20260825.md) | Native UI 화면 흐름, 기능표, 런타임 계층과 용어 정의 |
| [docs/55-beta-distribution-preflight-checklist-20260825.md](docs/55-beta-distribution-preflight-checklist-20260825.md) | Beta 단일 설치·실행 패키지 구현 및 출시 전 체크리스트 |
| [docs/58-authoritative-room-control-event-contract-v1-20260825.md](docs/58-authoritative-room-control-event-contract-v1-20260825.md) | 서버 권위 Trade Room, 역할, 복구, UI 이벤트 계약 v1 |
| [docs/59-party-snapshot-and-trade-commit-contract-v1-20260825.md](docs/59-party-snapshot-and-trade-commit-contract-v1-20260825.md) | 수동 디코더 party snapshot 및 fail-closed trade commit 계약 v1 |
| [docs/60-external-consent-and-statistics-contract-v1-20260825.md](docs/60-external-consent-and-statistics-contract-v1-20260825.md) | 외부 동의, 최소 통계 수집, 보존·삭제 계약 v1 |
| [docs/61-private-beta-release-baseline-20260825.md](docs/61-private-beta-release-baseline-20260825.md) | Private beta 플랫폼, RTL8192EU, 기능·버전 기준선 |
| [docs/62-final-ui-overhaul-gpt-handoff-20260825.md](docs/62-final-ui-overhaul-gpt-handoff-20260825.md) | 최종 GPT/owner WPF UI overhaul 입력 및 Gate 0 승인 기준 |
| [docs/63-second-native-ui-overhaul-codex-handoff-20260825.md](docs/63-second-native-ui-overhaul-codex-handoff-20260825.md) | GPT의 두 번째 native UI audit 및 Codex 구현 지침 |
| [docs/64-second-native-ui-overhaul-implementation-report-20260825.md](docs/64-second-native-ui-overhaul-implementation-report-20260825.md) | 두 번째 native WPF audit 구현 결과, C1–C12 결정, 검증 기록 |
| [docs/67-hardware-support-expansion-20260826.md](docs/67-hardware-support-expansion-20260826.md) | WSL USB 카드 매트릭스, host engine 정책, 자동 진단과 실기 승격 게이트 |
| [docs/69-repository-preflight-completion-and-relay-handoff-20260826.md](docs/69-repository-preflight-completion-and-relay-handoff-20260826.md) | Repository preflight 완료 범위, relay hosting 인계, 남은 외부 gate |
| [docs/70-private-beta-support-and-recovery-guide-20260826.md](docs/70-private-beta-support-and-recovery-guide-20260826.md) | Private-beta 지원 범위와 안전한 복구 가이드 |
| [docs/75-visual-overhaul-3-installer-candidate-20260826.md](docs/75-visual-overhaul-3-installer-candidate-20260826.md) | Visual Overhaul 3가 포함된 최신 unsigned 설치 후보와 검증 기록 |
| [docs/76-wsl-custom-kernel-unicode-path-fix-20260826.md](docs/76-wsl-custom-kernel-unicode-path-fix-20260826.md) | 한글 Windows 사용자 경로의 WSL 커스텀 커널 시작 실패와 설치기 수정 |
| [relay/DEPLOYMENT.md](relay/DEPLOYMENT.md) | 별도 hosting agent용 production relay 배포·smoke runbook |
| [docs/30-native-fixed-handshake-20260824.md](docs/30-native-fixed-handshake-20260824.md) | Native two-Switch fixed-channel gold, PC-host root cause, and byte-verified Session fix |
| [handoff/HANDOFF-20260824-wsl-dual-radio.md](handoff/HANDOFF-20260824-wsl-dual-radio.md) | WSL 두 카드 최종 상태, 확장 구조, 다음 G5/G6 절차 |
| [handoff/HANDOFF-20260824-native-host-session.md](handoff/HANDOFF-20260824-native-host-session.md) | Next-agent gate for PC-host Pia and host/parent Reliable work |
| [docs/research/01-frlg-ldn-trade.md](docs/research/01-frlg-ldn-trade.md) | Tornadus 프로젝트 리서치 |
| [docs/research/02-gb-link-celio.md](docs/research/02-gb-link-celio.md) | GB-Link/Celio 생태계 리서치 |
| [docs/research/03-kinnay-ldn.md](docs/research/03-kinnay-ldn.md) | LDN 프로토콜 리서치 |
| [docs/research/04-youtube-videos.md](docs/research/04-youtube-videos.md) | YouTube 영상 2건 정리 |

WSL 무선 실행은 Windows에서 `scripts/windows/wsl-radio-preflight.ps1 -Prepare -AutoAttach`를 먼저 실행하고,
Linux에서는 `scripts/wsl-radio-prepare.sh --usb-id VID:PID --role ROLE -- COMMAND...`를 사용한다.
지원 카드와 driver/role 정책은 `config/wsl-radio-hardware.tsv`에 있다.
새 카드의 read-only 진단은 `python -m switchtrade.hardware_diagnostics --usb-id VID:PID`로 실행한다.
research/driver candidate는 명시적으로 선택할 수 있지만 실험용이며 작동이 보장되지 않는다.
quarantined 카드는 실행할 수 없다. 모든 카드의 기본 host engine은 `ldn.create_network()`이다.

## 상태

- [x] 리서치 1차 완료 (2026-08-20)
- [x] 킥오프 문서화
- [x] **Phase 0**: 환경 준비 + PoC 재현 — ✅ 트레이드 2세션 연속 성공 (2026-08-21, 마일스톤 M0 달성)
- [x] Phase 1: 코드 분석 + 트랜스포트 확장 지점 식별 (~90% — RemoteTransport 확장점 확정·구현)
- [x] Phase 2a: 릴레이 인프라 완성 (RemoteTransport + relay/server.py + FSM 훅, 테스트 9건 통과)
- [ ] Phase 2b: LAN 2브리지 실기 테스트 (진행 중 — `docs/07-2b-테스트-실측-20260821.md`)
- [ ] Phase 2c: 인터넷 (relay code hosting-ready; public TLS/two-NAT 실증 대기)
- [x] Phase 3: authoritative private session + native client 내부 구현
- [ ] Phase 4: 확장 (배틀, Gen 2)

## 리포 구조 (2026-08-25)

- `bridge/`: LDN/Pia/RFU/프레임 릴레이 런타임과 테스트. 과거 별도 emulator 리포의 전체 이력을
  subtree로 통합했다.
- `relay/`: 인터넷 세션 릴레이.
- `scripts/`, `config/`: Windows/WSL 무선 준비와 하드웨어 정책.
- `tools/`, `tests/`: 캡처/Pokémon payload 분석과 회귀 테스트.
- `apps/desktop/`: browser engine 없이 동작하는 self-contained WPF Windows 애플리케이션.
- `apps/web/`: UI Kit의 240×160 Canvas 프리미티브를 사용한 optional web/debug frontend.
- `assets/ui/`: 제품 UI 디자인 reference 원본.
- `switchtrade/`: 공유 하드웨어 프로필 reader, 진단/지원 bundle, RFU tunnel envelope, 로컬 control API.
- `installer/`: isolated SwitchTrade WSL distro bootstrap, launcher, provisioning, and package builder.
- `archive/`: 이전 VM 백업, Pokémon fixtures/results, agent 계획, 외부 reference checkout.
- `docs/`, `handoff/`: 실측 증거, 결정, 다음 작업.
- WSL kernel build는 별도 `mwl313/wsl2-kernel-build` 리포에 유지한다.

통합 브랜치는 `production-beta`다. 이전 `golden-capture-re`, `pokemon-payload-re`, `gptsolreview`와
별도 emulator 리포는 `archive/references/`에 증거 보존용으로 유지하며 새 프로덕션 작업의
기준이 아니다.

## 무선 캡처 안전 규칙

raw 802.11 캡처와 framerelay 실행은 반드시 `scripts/radio-health-gate.sh`를 먼저 통과한다.
이 게이트는 1/6/11에서 실제 RX를 확인하고, 수신 사망이면 해당 USB 장치만 한 번 리셋한 뒤
재검증한다. 직접 `tcpdump`를 백그라운드로 띄우는 절차는 사용하지 않는다.
1/6/11은 LDN 구현의 후보 채널이며, 전체 2.4GHz 진단이 필요하면
`--health-channels 1,2,3,4,5,6,7,8,9,10,11,12,13`으로 확장할 수 있다.

## 0.2.0-beta.1 repository candidate

Authoritative private rooms, the attempt-bound feature-neutral RFU tunnel, real control API, native
Windows frontend, passive decoder observer, isolated WSL lifecycle, native setup UI, signed-package
verification, and hosting-ready relay are implemented. The pinned Linux/WSL runtime suite passes
without Switch hardware. See [`docs/69-repository-preflight-completion-and-relay-handoff-20260826.md`](docs/69-repository-preflight-completion-and-relay-handoff-20260826.md).

`production-beta` commit `1e8b4bd` includes Visual Overhaul 3 and the Unicode-profile, minimal-rootfs,
and same-release Repair corrections. The matching locally built unsigned installer candidate is
`SwitchTrade-unsigned-private-beta-1e8b4bd.zip`; its reproducible inputs and checksums are recorded in
[`docs/75`](docs/75-visual-overhaul-3-installer-candidate-20260826.md).

This is an internal beta candidate, not a signed user release. Two physical RTL8192EU endpoints,
Switch-to-Switch validation, WAN/recovery soak, external clean-machine/reboot qualification, and
artifact signing remain release gates. The lifecycle manages only the named SwitchTrade distro and
backs up/restores the user's complete `.wslconfig`; when a verified custom-kernel bundle is supplied,
its kernel selection is global to WSL 2 and requires explicit consent.

## Support

Create a redacted support bundle from **Settings → Support**, then report reproducible problems at
https://github.com/mwl313/mwl-SwitchTrade/issues. Do not upload room credentials, packet captures, or
other private data outside the generated redacted bundle.

## 핵심 원칙

1. Switch는 **절대 건드리지 않는다** — 모든 마법은 PC 브리지에서
2. "똑바로 작동" 우선, 최적화는 마지막
3. 개인 사용/연구 목적 — 닌텐도 정책 리스크는 상시 재평가
