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
| [docs/research/01-frlg-ldn-trade.md](docs/research/01-frlg-ldn-trade.md) | Tornadus 프로젝트 리서치 |
| [docs/research/02-gb-link-celio.md](docs/research/02-gb-link-celio.md) | GB-Link/Celio 생태계 리서치 |
| [docs/research/03-kinnay-ldn.md](docs/research/03-kinnay-ldn.md) | LDN 프로토콜 리서치 |
| [docs/research/04-youtube-videos.md](docs/research/04-youtube-videos.md) | YouTube 영상 2건 정리 |

## 상태

- [x] 리서치 1차 완료 (2026-08-20)
- [x] 킥오프 문서화
- [ ] **Phase 0**: 환경 준비 + PoC 재현 (frlg-ldn-trade 로컬 데모)
- [ ] Phase 1: 코드 분석 + 트랜스포트 확장 지점 식별
- [ ] Phase 2: PC↔PC 브리지 프로토타입 (LAN → 인터넷)
- [ ] Phase 3: 세션 시스템 + 클라이언트
- [ ] Phase 4: 확장 (배틀, Gen 2)

## 핵심 원칙

1. Switch는 **절대 건드리지 않는다** — 모든 마법은 PC 브리지에서
2. "똑바로 작동" 우선, 최적화는 마지막
3. 개인 사용/연구 목적 — 닌텐도 정책 리스크는 상시 재평가
