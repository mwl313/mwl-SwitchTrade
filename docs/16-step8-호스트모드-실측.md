# STEP 8 — 호스트 모드 브로드캐스트 검증 실측 (2026-08-22)

> 환경: VM1(8192EU, HOST) + VM2(8188EU, 스캐너) | 스위치 불사용
> 목적: VM1의 HostTransport가 여는 FRLG 방이 실제로 공중에 뿌려지는지, VM2 카드가 볼 수 있는지

## 결과: **부분 성공 — 핵심 발견 1건 포함**

### ✅ 성공한 것

| # | 항목 | 증거 |
|---|---|---|
| 1 | **HostTransport 방 개설 완주** | `Room is open - waiting for the Switch to scan and join...` |
|   | | hosting ssid=e7a6c903...(16B 랜덤) us=169.254.61.1 comm_id=0x01006fa0233f8000 scene=22287 ch=6 |
| 2 | **RFU 비콘(application_data) 인코더 실동작** | beacon decoded: **host name='EMU' TID=0xeb64 RFU-session-id=0xc1a1** |
|   | | → STEP 2에서 만든 인코더가 실기에서 처음으로 자기 광고를 생성·디코딩 왕복함 |
| 3 | **AP + monitor + TAP 3 vif 동시 생성** (STEP 7 재확인) | ldn-mon(monitor) / wlx(type AP) / ldn-tap(TUN) |
| 4 | **자기 프레임 무선 송출 확인** | ldn-mon에서 SA=a0:47:d7:b0:2b:39 프레임 161개 캡처 (Vendor Action 158 + Data 2) |

### ⚠️ 미해결

| # | 항목 | 상세 |
|---|---|---|
| 1 | **Beacon 프레임이 공중에 관측되지 않음** | ldn-mon에 잡히는 자기 프레임은 Action(Vendor-specific)뿐, Beacon(subtype 8) 0개 |
| 2 | VM2 스캔 found 0 | 1차 원인은 8188EU 수신 사망(토글로 복구 후 CH1 31패킷 정상). 복구 후 CH6에서 주변 공유기(SWING/SK) 비콘은 수신했으나 EMU Beacon은 여전히 0 |
| 3 | 8188EU CH6 수신 시 간헐 -83dBm 저신호 관측 | 거리/안테나 이슈 가능성. 단 TP-Link_67E8(CH2)은 -11dBm으로 강하게 잡힘 |

## 🔍 원인 분석

**"자기 프레임은 잡히는데 Beacon만 없다"** 는 점이 핵심 단서:

- Vendor Action 프레임 158개가 ldn-mon에 보인다 = **카드가 실제로 무선 송출 중**이고 소프트웨어적으로도 TX가 일어남
- 그러나 START_AP로 등록한 Beacon(head+tail)이 공중에 안 나옴
- iw CLI의 "malformed beacon head"(STEP 7)와 동일한 계열 문제로 추정: **rtl8xxxu 드라이버가 nl80211 CMD_START_AP의 BEACON_HEAD/TAIL을 받아들이지만, 실제 beaconing을 시작하지 않았을 가능성**
  - hostapd 없이 순 netlink START_AP는 커널 mac80211 경유 시 beaconing이 시작되지만,
    rtl8xxxu의 펌웨어 기반 beacon 구현은 추가 조건(beacon interval 설정 타이밍, 인터페이스 UP 상태, BSS 등록)이 있을 수 있음
- 대조: STEP 7에서도 동일 패턴(START_AP 성공 + mon0에서 자기 비콘 0)

## 다음 액션

1. **hostapd 크로스체크**: 같은 ap0 vif에서 hostapd로 SSID=MWLTEST AP 기동 → VM2 스캔에서 보이면
   = "드라이버 beaconing은 되는데 ldn의 START_AP 파라미터 세팅에 빠진 것이 있다"로 특정됨
   → ldn create_network 호출에 빠진 attr(NL80211_ATTR_CONTROL_PORT_OVER_NL80211 등) 역탐색
2. **VM2를 CH6 모니터로 고정하고 VM1 host를 몇 회 재기동**하며 Beacon 프레임 유무 재확인 (타이밍 이슈 배제)
3. 그래도 안 되면 rtl8xxxu AP beaconing 한계로 판정하고, **호스트 모드는 hostapd 하이브리드**(방 개설만 hostapd, 게임 데이터는 ldn-tap)로 설계 변경 검토

## 교훈

- 8188EU는 실행 전 authorized 토글이 사실상 필수 (이번에도 시작 직후 수신 사망)
- "START_AP 성공 리턴" ≠ "beaconing 시작" — 반드시 공중 캡처로 검증할 것
