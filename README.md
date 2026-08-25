# MWL-SwitchTrade

> **순정 Nintendo Switch의 공식 Game Boy 서비스 포켓몬 게임을 인터넷으로 연결하는 트레이딩 시스템.**

스위치는 인터넷에 연결된 기기인데, 게임보이 포켓몬(FRLG 등)은 로컬 통신만 된다.
그 로컬 통신(LDN)을 PC 브리지가 가로채서 인터넷으로 연결한다. **홈브류/커펌 없이, 순정 그대로.**

## 한눈에 보기

```
[Switch A] ──LDN 무선──> [PC 브리지 A] ──인터넷 터널/릴레이──> [PC 브리지 B] <──LDN 무선── [Switch B]
```

- **기반 기술** (이미 존재, 검증됨): kinnay/LDN (로컬 무선 계층) + tornadus/frlg-ldn-trade (FRLG 게임 계층)
- **미싱 링크**: PC↔PC 인터넷 터널/릴레이 + 세션 매칭 (신규 개발)
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
| [docs/30-native-fixed-handshake-20260824.md](docs/30-native-fixed-handshake-20260824.md) | Native two-Switch fixed-channel gold, PC-host root cause, and byte-verified Session fix |
| [handoff/HANDOFF-20260824-wsl-dual-radio.md](handoff/HANDOFF-20260824-wsl-dual-radio.md) | WSL 두 카드 최종 상태, 확장 구조, 다음 G5/G6 절차 |
| [handoff/HANDOFF-20260824-native-host-session.md](handoff/HANDOFF-20260824-native-host-session.md) | Next-agent gate for PC-host Pia and host/parent Reliable work |
| [docs/research/01-frlg-ldn-trade.md](docs/research/01-frlg-ldn-trade.md) | Tornadus 프로젝트 리서치 |
| [docs/research/02-gb-link-celio.md](docs/research/02-gb-link-celio.md) | GB-Link/Celio 생태계 리서치 |
| [docs/research/03-kinnay-ldn.md](docs/research/03-kinnay-ldn.md) | LDN 프로토콜 리서치 |

WSL 무선 실행은 Windows에서 `scripts/windows/wsl-radio-preflight.ps1 -Prepare -AutoAttach`를 먼저 실행하고,
Linux에서는 `scripts/wsl-radio-prepare.sh --usb-id VID:PID --role ROLE -- COMMAND...`를 사용한다.
지원 카드와 driver/role 정책은 `config/wsl-radio-hardware.tsv`에 있다.
| [docs/research/04-youtube-videos.md](docs/research/04-youtube-videos.md) | YouTube 영상 2건 정리 |

## 상태

- [x] 리서치 1차 완료 (2026-08-20)
- [x] 킥오프 문서화
- [x] **Phase 0**: 환경 준비 + PoC 재현 — ✅ 트레이드 2세션 연속 성공 (2026-08-21, 마일스톤 M0 달성)
- [x] Phase 1: 코드 분석 + 트랜스포트 확장 지점 식별 (~90% — RemoteTransport 확장점 확정·구현)
- [x] Phase 2a: 릴레이 인프라 완성 (RemoteTransport + relay/server.py + FSM 훅, 테스트 9건 통과)
- [ ] Phase 2b: LAN 2브리지 실기 테스트 (진행 중 — `docs/07-2b-테스트-실측-20260821.md`)
- [ ] Phase 2c: 인터넷 (NAT 통과) 트레이드
- [ ] Phase 3: 세션 시스템 + 클라이언트
- [ ] Phase 4: 확장 (배틀, Gen 2)

## 리포 구조 (2026-08-25)

- `bridge/`: LDN/Pia/RFU/프레임 릴레이 런타임과 테스트. 과거 별도 emulator 리포의 전체 이력을
  subtree로 통합했다.
- `relay/`: 인터넷 세션 릴레이.
- `scripts/`, `config/`: Windows/WSL 무선 준비와 하드웨어 정책.
- `tools/`, `tests/`: 캡처/Pokémon payload 분석과 회귀 테스트.
- `SwitchTrade-UI-Kit.zip`: 제품 UI 디자인 reference 원본.
- `desktop/`: browser engine 없이 동작하는 self-contained WPF Windows 애플리케이션.
- `ui/`: UI Kit의 240×160 Canvas 프리미티브를 사용한 optional web/debug frontend.
- `switchtrade/`: 공유 하드웨어 프로필 reader, 진단/지원 bundle, RFU tunnel envelope, 로컬 control API.
- `installer/`: isolated SwitchTrade WSL distro bootstrap, launcher, provisioning, and package builder.
- `docs/`, `handoff/`: 실측 증거, 결정, 다음 작업.
- WSL kernel build는 별도 `mwl313/wsl2-kernel-build` 리포에 유지한다.

통합 브랜치는 `production-beta`다. 이전 `golden-capture-re`, `pokemon-payload-re`, `gptsolreview`와
별도 emulator 리포는 증거 보존용이며 새 프로덕션 작업의 기준이 아니다.

## 무선 캡처 안전 규칙

raw 802.11 캡처와 framerelay 실행은 반드시 `scripts/radio-health-gate.sh`를 먼저 통과한다.
이 게이트는 1/6/11에서 실제 RX를 확인하고, 수신 사망이면 해당 USB 장치만 한 번 리셋한 뒤
재검증한다. 직접 `tcpdump`를 백그라운드로 띄우는 절차는 사용하지 않는다.
1/6/11은 LDN 구현의 후보 채널이며, 전체 2.4GHz 진단이 필요하면
`--health-channels 1,2,3,4,5,6,7,8,9,10,11,12,13`으로 확장할 수 있다.

## 0.2.0-beta.0 internal build

Private relay sessions, the feature-neutral RFU endpoint tunnel, real control API integration, native
Windows frontend, optional static web frontend, and isolated-distro bootstrap source are implemented. The pinned Linux runtime test
suite passes without Switch hardware. See
[`docs/53-beta0-internal-build-20260825.md`](docs/53-beta0-internal-build-20260825.md).

This is an internal beta candidate, not a signed user release. Two physical RTL8192EU endpoints,
Switch-to-Switch validation, WAN/recovery soak, external clean-machine/reboot qualification, and
artifact signing remain release gates. A checksummed minimal rootfs and isolated install/repair/
uninstall cycle now pass internally. The bootstrap leaves the global/custom WSL kernel configuration
unchanged.

## 핵심 원칙

1. Switch는 **절대 건드리지 않는다** — 모든 마법은 PC 브리지에서
2. "똑바로 작동" 우선, 최적화는 마지막
3. 개인 사용/연구 목적 — 닌텐도 정책 리스크는 상시 재평가
