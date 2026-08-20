# 리서치 노트: tornadus/frlg-ldn-trade

> 분석일: 2026-08-20 | 소스: GitHub README + 코드 트리 + 데모 영상 (Ld2YphF-HVI)

## 개요

- **URL**: https://github.com/tornadus/frlg-ldn-trade
- **정체**: PoC — PC가 LDN(로컬 무선)으로 무개조 Switch/Switch 2의 FRLG와 직접 트레이드
- **언어/라이선스**: Python / AGPL-3.0
- **규모**: 95⭐ / 9 fork / 이슈 1 / 생성 2026-06-21 / 마지막 push 2026-07-17
- **개발 배경 (README)**: "된다는 걸 증명하기 위해" 존재. 비공식 GTS·온라인 배틀로 가는 첫걸음. **AI 툴(Claude) 대거 사용 명시** — 다만 스티어링이 많이 필요했다고.

## 코드 구조

```
frlgtrade.py          # 엔트리포인트 (CLI)
frlgsim/
  __init__.py
  barrier.py          # 동기화 배리어
  basestats.py        # 기본 스탯 계산
  block.py            # GBA 플래시 블록?
  charmap.py          # 문자 인코딩
  crypto.py           # 암호화 (게임 링크 암호화?)
  gbaframe.py         # GBA 링크 프레임
  linkplayer.py       # 링크 플레이어 상태 머신
  linkstate.py        # 링크 상태
  mon.py              # 포켓몬(.pk3) 처리
  ni.py               # ?
  pia_connect.py      # PIA (Nintendo의 온라인 인증 라이브러리?) 접속
  reliable.py         # 신뢰성 있는 전송
  rfu.py              # RFU (GBA 무선 어댑터) 프로토콜
  sim.py              # 시뮬레이션 코어
  stats.py            # 능력치
  trade.py            # 트레이드 로직
  transport.py        # 전송 계층
```

**핵심 이해**: frlgsim은 GBA 링크 케이블/RFU 프로토콜을 PC에서 재구현해서, 게임(NSO FRLG)이 PC를 "진짜 GBA"로 인식하게 만든다. LDN 계층(kinnay/LDN) 위에서 동작.

## 검증된 사실 (데모 영상 기준)

1. **무개조 Switch 2에서 동작** — NSO FRLG, 커펌 없음
2. **양방향 가능**: PC→Switch (피카츄 전송), Switch→PC (찬시 수신, .pk3 자동 저장)
3. **연결 플로우**: Switch 게임에서 디렉트 코너 → 트레이드 리더가 됨 → PC가 "EMU"로 참가 요청 → Switch에서 승인
4. **버그 존재**: 트레이드 취소 실패 시 프로그램 종료로 해결, 연결도 여러 번 시도 필요할 수 있음
5. PC의 Wi-Fi 카드가 LDN 네트워크에 참가 (영상: PCIe RTL8821CE 사용)

## 요구사항 (README)

- Linux, Python 3.12+
- 호환 Wi-Fi 카드 (아래 표)
- FRLG 디렉트 코너 해금 상태의 Switch (약 20~40분 플레이)
- .pk3 파일 최소 2개
- **Switch prod.keys** (기본 위치 ~/.switch/prod.keys) ← 순정 제약과 충돌 가능성 있음 (Open Question)

### Wi-Fi 카드 호환성

| 카드 | 타입 | 드라이버 | 신뢰성 |
|---|---|---|---|
| AMD RZ616 | 내장 M.2 | mt7921e | 낮음 (반속, 데드락) |
| ALFA AWUS036ACHM | 외장 USB | mt76x0u | 높음 (권장) |
| Realtek RTL8821CE | 내장 PCIe | rtw88_8821ce | 높음 |
| Intel AX200 | 내장 M.2 | iwlwifi | **동작 안 함** (IP 할당 불가) |
| Atheros AR9271 | 외장 USB | ath9k_htc | 대부분 동작 안 함 |

## 우리 프로젝트와의 관계

- **게임 레이어(L2)의 핵심 의존성** — 포크/확장 전제
- 트랜스포트를 원격 피어로 확장하는 것이 Phase 2의 핵심 작업
- prod.keys 의존성은 Phase 0에서 검증 필요
