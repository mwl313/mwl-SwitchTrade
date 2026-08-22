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

## 🔍 원인 분석 — **hostapd 크로스체크로 확정 완료 (같은 날 추가 실측)**

**크로스체크 결과: hostapd AP는 VM2 스캔에서 즉시 발견됨!**

| 시험 | 결과 |
|---|---|
| hostapd (SSID=MWLTEST, CH6, 같은 카드) | ✅ VM2 `iw scan`에서 **즉시 발견** — signal -37dBm, Probe Response로 SSID 응답 |
| ldn START_AP (SSID=16B hex, CH6, 같은 카드) | ❌ Beacon 미관측, 스캔 0 |

→ **드라이버(rtl8xxxu)의 beaconing 능력은 정상. 문제는 ldn 0.0.17의 START_AP 파라미터 세팅에 있음으로 특정 완료.**

### 차이 분석 (hostapd -dd 로그 vs ldn attrs)
- hostapd는 beacon head에 **완전한 IE 세트**(SSID IE+supported rates+DS params, capability 0x0411)를 넣고,
  beacon_ies(7f Extended capabilities)도 별도 전달
- kinnay BeaconFrame.encode()의 head는 timestamp 8B + capability만 있고 **SSID/rates/DS IEs가 없음**
  (원작자는 SSID를 BEACON_HEAD가 아니라 NL80211_ATTR_SSID 속성으로 전달 — 커널이 조립하려면
  특정 커널/드라이버 조합에서 hidden-ssid 처리 등 추가 조건 필요)
- hostapd는 CONTROL_PORT_OVER_NL80211 등 추가 attr도 세팅

### 결론 및 해결 경로
1. **ldn create_network의 BEACON_HEAD를 hostapd 스타일로 보강** (SSID IE + supported rates + DS params
   를 head에 직접 삽입) — frlgsim/beacon.py 또는 HostTransport에서 head를 재조립해 전달하는 패치로 해결 가능성 높음
2. 폴백: 호스트 모드의 방 개설만 hostapd 담당 + 게임 데이터는 기존 ldn-tap 경유 하이브리드

### 교훈

- 8188EU는 실행 전 authorized 토글이 사실상 필수 (이번에도 시작 직후 수신 사망)
- "START_AP 성공 리턴" ≠ "beaconing 시작" — 반드시 공중 캡처로 검증할 것
- **동일 카드에서 hostapd 비콘은 외부 수신 확인됨 → EchoGuard·모니터 캡처 설계 전체와 양립**

---

## ✅ 최종 해결 (같은 날 밤 — beacon head 패치 실기 검증 성공)

### 적용한 패치 3단계
1. `_build_host_beacon_head()` — hostapd -dd hexdump 역산 조립 (SSID IE + rates + DS params)
2. `install_beacon_head_override()` — `AccessPoint`(실제 소유 클래스; Station 아님!) 몽키패치,
   ldn에 __version__ 없어 importlib.metadata 폴백
3. **hex-string SSID 허용** — 최종 블로커. ldn이 param.ssid.hex()(문자열)를 Station._ssid에
   그대로 저장해서 bytes 타입체크에 걸려 매번 stock으로 폴백했었음

### 실기 검증 결과 (VM1 host + VM2 스캔)
```
BSS a0:47:d7:b0:2b:39          ← VM1의 EMU 방
  freq: 2437 (CH6 정확)
  beacon interval: 100 TUs
  capability: ESS ShortSlotTime (0x0401)   ← 우리가 만든 값 그대로!
  signal: -37.00 dBm
  SSID: \xd5xOO6\x91/\x1b<y\x8bDT\xcaPF     ← 실행마다 생성되는 16B 랜덤 SSID
  Supported rates: 1.0* 2.0* 5.5* 11.0* ...
  DS Parameter set: channel 6                ← 우리가 넣은 DS IE 그대로!
```

**호스트 모드(브리지가 FRLG 방을 직접 여는 것) 첫 실기 성공.**
커밋: 5a68eea(구현) → bf22a85(hex-string 수정). join 경로 무수정.

---

## ✅ STEP 9 — framerelay 무선 단독 흐름 실측 (같은 날 밤)

### 구성
- VM1: 호스트 모드(host_long.py, 180초 유지) + framerelay host 브리지(ldn-mon) + 릴레이(8788)
- 세션: WH60AB/DTV48F (role 충돌 시 재생성 — 403 처리 확인)

### 발견·수정
1. **URL 스킴 버그**: CLI가 `http://` 릴레이 URL을 그대로 websockets.connect에 전달 → 즉시 거부.
   `compose_relay_url`에 http(s)→ws(s) 자동 변환 추가 (+테스트 3건). 커밋 완료.
2. **stdout 버퍼링**: nohup 리다이렉션 시 로그 지연 → `-u` 플래그로 해결 (운영 노트)

### 성공 시퀀스 (운용 순서 — 재현용)
```
1. host 기동 (phy1 지정 필수): step8_host/host_long.py → AP CH6 + ldn-mon + ldn-tap 생성
2. ldn-mon up (AP 기동 후에 up해야 채널 공유됨 — 선업 시 CH1 하드고정 버그)
3. framerelay 기동:
   sudo .venv/bin/python -u -m framerelay --iface ldn-mon \
     --host-mac a0:47:d7:b0:2b:39 --relay-url http://127.0.0.1:8788 \
     --session-id <ID> --role host --verbose
4. [bridge] websocket connected → TX relay 프레임 다수 관찰
```

### 실측 결과
```
[bridge] websocket connected: ws://127.0.0.1:8788/session/.../ws?role=host
[bridge] TX relay 1388B d0000000ffffffffffffa047d7b02b39...   ← QoS Data, 우리 AP 송신 프레임
guest 브리지: 196프레임 처리 (rate limiter 조용히 통과, 에러 0)
```

**캡처→0x20 포장→WS 전송 파이프라인 첫 무선 실증 완료.**

### 운영 노트
- ldn-mon은 반드시 AP 기동 **후에** up (선업하면 CH1 고정 버그 — rtl8xxxu 멀티vif 채널 관리)
- role 충돌 시 릴레이가 403 반환 → 새 세션 생성으로 회피
- 자기 TX 루프백 부재(V-1 결론 재확인): EchoGuard 설계와 양립

### 남음
- guest 브리지의 RX inject 후 스위치B 화면 표시 확인 (=STEP 11 E2E, 스위치 필요)
