# 리서치 노트: kinnay/LDN — Switch 로컬 무선 프로토콜

> 분석일: 2026-08-20 | 소스: GitHub README + 프로젝트 위키 링크

## 개요

- **URL**: https://github.com/kinnay/LDN | `pip install ldn`
- **정체**: Python 패키지 — PC의 Wi-Fi 카드로 Switch의 LDN(Local Domain Network)을 **스캔/참가/호스트**
- **라이선스**: GPL-3.0 | 63⭐ | 2022-03 생성, 2026-04 마지막 push — **성숙한 라이브러리**
- **제약**: Linux + Python 3.12+, 모니터 모드 가능한 무선 하드웨어, `CAP_NET_ADMIN` (sudo), NetworkManager 중지 필요 (사용 중 인터넷 불가 — 유선이면 생략 가능)

## LDN 프로토콜의 성격 (README 핵심)

- LDN은 ad-hoc도 infrastructure도 아닌 **중간 형태**
- 스테이션이 참가할 때 AP에 인증·연관(associate) 먼저 수행
- 인증 후 **모든 노드가 서로 직접 통신** (P2P 메시)
- 호스트 프레임은 FromDS 플래그, 다른 스테이션 프레임은 FromDS/ToDS 둘 다 없음

## 구현 방식 (이 프로젝트가 푼 난제)

1. **AP 모드 단독**: 브로드캐스트(`ff:ff:ff:ff:ff:ff`) 프레임 수신 불가 → 실패
2. **IBSS(ad-hoc) 단독**: association 요청이 전부 드랍 → 실패
3. **현재 방식 (성공)**: **AP 모드 + 모니터 모드 조합**
   - AP 인터페이스: probe/association 등 관리 프레임 처리
   - 모니터 인터페이스: 데이터 프레임 (브로드캐스트 포함) 수신/송신
   - 데이터 프레임을 파싱·복호화하여 **TAP 인터페이스에 주입** → Linux가 일반 네트워크처럼 취급

## 코드 구조

```
ldn/
  __init__.py
  queue.py      # 패킷 큐
  streams.py    # 신뢰성 있는 스트림
  util.py       # 유틸
  wlan.py       # 무선 하드웨어 제어 (핵심)
examples/
  scan.py       # 주변 LDN 네트워크 스캔
  join.py       # 네트워크 참가
  host.py       # 네트워크 호스트
```

## 우리 프로젝트와의 관계 — 중요 포인트

1. **호스트 모드 지원**: PC가 LDN 네트워크를 **호스트**할 수 있음 — 두 Switch를 하나의 가상 LDN 네트워크에 참가시키는 시나리오 가능
2. **데이터 프레임 레벨 접근**: 모니터 모드로 모든 데이터 프레임(스테이션 간 포함) 캡처 가능 → **인터넷 중계를 위한 캡처 지점**
3. **frlg-ldn-trade의 기반**: Tornadus가 이 라이브러리 위에 RFU 시뮬레이션을 얹음 (README 크레딧 명시)
4. **한계**: Linux 전용, 카드 의존성 (Intel AX200 등 비호환), sudo/NetworkManager 중지 필요 — **실사용 환경 구성이 관건**

## 열린 질문

- prod.keys가 LDN 통신에 필요한가? (frlg-ldn-trade 요구사항 — kinnay/LDN 문서에는 명시 안 됨. LDN 프레임 암호화 키인지, 게임 데이터 암호화인지 확인 필요)
- 두 Switch 간 직접 통신을 PC가 가로채서 릴레이할 때, LDN 세션 계층에서 재전송/타임아웃이 어떻게 동작하는지 — 코드 레벨 확인 필요
