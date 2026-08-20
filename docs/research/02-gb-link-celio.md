# 리서치 노트: GB-Link / Celio 생태계

> 분석일: 2026-08-20 | 소스: GitHub org (21개 리포) + 데모 영상 (ej2fjM4zJuo)

## 조직 개요

- **URL**: https://github.com/GB-Link | 웹: https://gblink.io
- **슬로건**: "Building the internet for original gameboy games."
- **생성**: 2026-06-08 | 공개 리포 21개
- **정체**: 실기 게임보이 하드웨어(GBA 등)를 인터넷에 연결하는 **완전한 생태계** — 펌웨어 + DIY 하드웨어 + 웹 클라이언트 + 서버

## 아키텍처 3층

### 1. 하드웨어/펌웨어

| 리포 | 설명 |
|---|---|
| **GBLink-Firmware** (⭐41) | RP2040을 USB↔게임보이 링크 어댑터로. Celio-Link(Gen3 온라인) + GBLink(테트리스/프린터/멀티부트/어드밴스워즈) 병합. **6가지 모드**: GBA Trade Emu(0x00), GBA Link 브리지(0x01), GB Link SPI(0x02), GB Printer(0x03), Advance Wars(0x04), e-Reader(0x05). WebUSB 명령 프로토콜 + WS2812 LED 상태 |
| **GB-Link-USB-DIY** | Pico + BOB-12009 레벨시프터 기반 오픈소스 PCB. gerber 공개, JLCPCB 주문 가능 (1.2mm, ENIG 권장). 3D 프린트 케이스 공개 |
| **gblink-pro** | Raspberry Pi Zero 2W를 어댑터로 — PC 불필요 독립 실행. SPI + 레벨시프터. Gen1/2 트레이드 + Gen3(멀티부트) + 테트리스 지원 |

### 2. 웹 클라이언트 (WebUSB)

| 리포 | 설명 |
|---|---|
| **Celio-Client** | **Gen 3 온라인 링크** (배틀/트레이드/레코드믹스) + **트레이드 에뮬레이션 모드** (.pk3/.ek3 최대 6마리 업로드). celi0.link. WebUSB(Chromium) / WebSerial(Firefox 151+) |
| **gb-pokemon-web** (⭐11) | RBY/GSC 온라인 트레이드 (Pool/2-Player). Python 원본(Lorenzooone)의 JS 포팅. Gen3 미구현 |
| **gblink-launcher** | launcher.gblink.io — 전 서브프로젝트 통합 런처 |
| **gb-tetris-web** (+server) | 실기 테트리스 온라인 멀티 |
| **gb-printer-web** | GB 프린터 에뮬레이터 (GB 카메라 사진 → PNG) |
| **gba-multiboot-web** | 링크 케이블로 GBA ROM 전송 (플래시카트 불필요) |
| **gblink-distributor** | 이벤트 포켓몬 배포 (Gen1/2 카트리지) |
| **gblink-ereader** | e-Reader 에뮬레이션 |
| **gb-cart-doctor-web** | GBC 모드 전환 → 카트리지 덤프 |

### 3. 서버/브리지

| 리포 | 설명 |
|---|---|
| **Celio-Server** | Socket.IO 릴레이 서버. 세션 관리 + 패킷 중계만 (게임 데이터 해석 안 함). TLS는 리버스 프록시. **우리 릴레이 서버의 직접적인 설계 참고** |
| **gblink-netplay-bridge** | 실기 GBA ↔ RetroArch netplay (에뮬레이터 유저와 대전). Electron 앱. 네트워크에 RetroArch+gpsp로 보임. 펌웨어 2.2.2+ 필요 |

## 데모 영상 핵심 (ej2fjM4zJuo — "They Said Online Gen 3 Pokémon Was Impossible...")

- GB-Link USB v2(프리프로덕션) + 실기 GBA 2대 (하나는 GC+GB Player) → **인터넷 더블배틀 실시간 성공**
- 세션 ID 공유 → 게임 내 배틀 룸 입장 → 자동 링크
- 지연 체감 거의 없음 (턴제 특성) — "link standby → 상대 선택 → 즉시 진행"
- **RSEFRLG 전부 지원** (링크 케이블 에뮬레이션)
- 구입: Crowd Supply (gblink-usb-v2)

## 우리 프로젝트와의 관계

- **아키텍처 참고 대상**: Celio의 세션 ID 매칭 + 릴레이 서버 + 클라이언트 분리가 우리 설계의 템플릿
- **대상 하드웨어는 다름**: GB-Link는 실기 GBA 링크 케이블용, 우리는 Switch NSO(에뮬레이터) + LDN 무선 — 즉 **같은 문제를 다른 물리 계층에서 푸는 형제 프로젝트**
- frlg-ldn-trade와 달리 **배틀 실시간성까지 검증됨** — Phase 4 배틀 확장의 근거
