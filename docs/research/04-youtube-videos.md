# 리서치 노트: YouTube 영상 정리 2건

> 분석일: 2026-08-20 | 두 영상 모두 "PC/컴퓨터 ↔ 게임보이 하드웨어 통신" 커뮤니티의 최신 성과

---

## 1. "Trading in Firered is about to get a whole lot cooler...."

- **URL**: https://www.youtube.com/watch?v=Ld2YphF-HVI
- **채널**: Professor Rex (@ProfessorRex) | 약 8분 30초

### 요약
PC(에뮬레이터/카트리지 덤프)의 3세대 포켓몬을 **무개조 Switch 2**의 NSO FRLG로 보내는 최초 데모.

### 핵심 내용
- PCNYC 001 피카츄 (GBA 사파이어 카트리지) → GBxCart 덤프 → PKHeX for Web 확인 → .pk3 → frlg-ldn-trade로 Switch 전송 성공
- **역방향도 가능**: Switch에서 PC로 보내면 .pk3 자동 저장 (무개조 스위치 포켓몬 백업 수단)
- 동작: PC Wi-Fi 카드(PCIe RTL8821CE)가 LDN 네트워크에 참가 → Switch가 "EMU"를 상대 플레이어로 인식
- 한계: 연결 재시도 필요, 트레이드 취소 버그 (프로그램 종료로 해결)
- 제작자 비전: 비공식 GTS, 온라인 배틀, 무선 미스터리 기프트, 뮤 머신 부활

### 타임라인
| 시간 | 내용 |
|---|---|
| 0:00 | PCNY 피카츄 → 무개조 Switch 2 전송 데모 시작 |
| 1:25 | 카트리지 덤프 → PKHeX 확인 |
| 3:57 | .pk3 로드, LDN 프로그램 실행 |
| 4:49 | Switch 인식 → 연결 → "EMU" 참가 |
| 5:52 | Switch→PC 역방향 전송 (찬시 .pk3 저장) |
| 7:10 | 취소 버그 → 프로그램 종료, 피카츄 도착 확인 |
| 7:50 | 마무리 — 프로젝트 잠재력 |

---

## 2. "They Said Online Gen 3 Pokémon Was Impossible..."

- **URL**: https://www.youtube.com/watch?v=ej2fjM4zJuo
- **채널**: GB-Link (@gblinkio) | 약 9분 45초

### 요약
GB-Link USB v2 (RP2040 어댑터)를 꽂은 실기 GBA 2대를 인터넷으로 연결, **실시간 더블배틀** 시연 성공.

### 핵심 내용
- 구성: GC+GB Player vs GBA+GB-Link USB v2 (프리프로덕션)
- 세션 ID 공유 → 게임 내 배틀 룸 입장 → 자동 링크
- **지연 체감 없음**: "link standby → 선택 전달 → 즉시 진행", "턴제라 지연이 안 느껴진다"
- 지원: Ruby/Sapphire/Emerald/FRLG 전부 (링크 케이블 에뮬레이션)
- 구입처: Crowd Supply (gblink-usb-v2)

### 타임라인
| 시간 | 내용 |
|---|---|
| 0:00 | 실기 GBA 온라인 더블배틀 시작 |
| 0:30 | 세션 ID 공유 → 링크 성공 |
| 1:15 | 배틀 진행 (더블배틀 실제 플레이) |
| 3:00 | 프로젝트 소개 (스타로드 = 하드웨어 제작자) |
| 8:00 | 실시간성 논의 — "턴제라 지연 무감각" |
| 9:20 | 지원 게임 + 구매 안내 |

---

## 두 영상의 관계 (프로젝트 관점)

| | 영상 1 (Professor Rex) | 영상 2 (GB-Link) |
|---|---|---|
| 대상 | Switch 2 NSO FRLG | 실기 GBA |
| 통신 | LDN 로컬 무선 (Wi-Fi 카드) | 링크 케이블 + RP2040 USB |
| 증명한 것 | **무개조 Switch와 PC 간 트레이드** | **실기 GBA 간 인터넷 배틀 (실시간)** |
| 우리에게 | L1/L2 계층의 근거 | L3/L4 (세션·릴레이·클라이언트)의 참고 |

**결론**: 영상 1이 우리 시스템의 "Switch 접근법"을, 영상 2가 "인터넷 연결 아키텍처"를 증명한다. 둘을 합치는 것이 MWL-SwitchTrade.
