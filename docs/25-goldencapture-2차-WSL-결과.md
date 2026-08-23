# 25 — 골든캡처 2차: WSL 듀얼 라디오 실기 성공 및 프로토콜 교정 (2026-08-24)

## 1. 결론

이번 캡처는 세 가지를 확정했다.

1. FireRed/LeafGreen의 두 Switch는 공유기를 경유하지 않고 **Nintendo LDN으로 직접 통신**했다.
2. WSL의 RTL8192EU와 patched RTL8188EU는 둘 다 이 통신을 실제 RF에서 수신했다. RTL8188EU의
   receive path도 이번 세션 동안 정상 동작했다.
3. 현재 EMU 구현에는 실기 광고와 다른 두 필드가 있었다. 실기는 **LDN protocol 3 / application
   version 88**인데 코드는 기본 protocol 1 / application version 1이었다.

따라서 1차 캡처의 “인터넷 통신만 했다”는 결론은 폐기한다. 1차 캡처는 CH6만 관측했기 때문에
CH11/CH1에서 일어난 LDN 세션을 놓친 것이다.

## 2. 실험 조건과 무결성

| 항목 | 값 |
|---|---|
| 환경 | WSL2, `6.18.35.2-microsoft-standard-WSL2+` |
| Radio A | RTL8192EU (`0bda:818b`), in-kernel `rtl8xxxu` |
| Radio B | RTL8188EU (`0bda:8179`), pinned vendor `8188eu` |
| 수집 방식 | 두 라디오 CH1~13 staggered hopping, dwell 0.4초 |
| PCAP 시간 | 08:14:08.52 ~ 08:18:23.43 KST |
| RTL8192EU | 13,341 frames, 2,506,764 bytes, kernel drop 0 |
| RTL8188EU | 7,061 frames, 1,581,242 bytes, kernel drop 0 |

SHA-256:

```text
9cc0bcf18a09f0620e63e05849d8b9c7135150b7ac421510ce3e78d48d4eb712  rtl8192eu_allch.pcap
677f5535680754222393df19a9dd2ccB823C5582BAC0A8D0BB8365290B562EC4  rtl8188eu_allch.pcap
```

두 라디오 모두 캡처 전·후 health gate의 실제 RX 검증을 통과했다. 캡처 종료 뒤 hopper/tcpdump
프로세스가 남지 않은 것도 확인했다.

## 3. 인터넷 트래픽과 로컬 트레이드의 분리

Switch A는 라이선스 제한 때문에 게임 부팅 시 인터넷 접속이 필요했다. 따라서 TP-Link BSSID
`68:ff:7b:ef:67:e8`와의 Auth/Assoc/EAPOL 및 그 BSS의 protected data는 **라이선스/bootstrap
트래픽**으로 분류한다.

트레이드 LDN은 아래의 별도 BSS이다.

| 역할 | MAC | 근거 |
|---|---|---|
| Switch A / LDN host BSSID | `a4:c1:e8:66:73:25` | Nintendo OUI, LDN 광고 participant 0 |
| Switch B / LDN participant 1 | `98:41:5c:79:41:38` | Nintendo OUI, join 뒤 광고 participant 1 |

LDN 광고의 IP는 `169.254.120.1`과 `169.254.120.2`였고, 두 MAC 사이에 직접 802.11 unicast가
있었다. 공유기 BSSID는 이 프레임들의 transmitter/receiver/BSSID가 아니다. 그러므로 Switch A가
부팅 전에 인터넷을 썼다는 사실과 트레이드가 로컬 LDN이었다는 사실은 동시에 참이다.

## 4. 실측 세션 타임라인

RTL8192EU 캡처의 암호화된 Nintendo Vendor Action을 `ldn 0.0.17`과 검증된 prod.keys로 해독했다.

| 시각 | 관측 |
|---|---|
| 08:15:48.360 | CH11, 1/6 방 광고. host=`Min`, game name=`DESTROY` |
| 08:16:05.868 | 새 SSID/server-random/challenge의 CH1, 1/6 방 광고 |
| 08:16:10.052 | CH1 광고가 2/6으로 갱신. `mwl`/`98:41:5c:79:41:38` 참가 |
| 08:16:10.047~08:17:45.922 | 두 Switch 사이 직접 protected unicast |
| 08:16:13.837 | RFU partner word가 `0x1584`에서 `0x9584`로 변함 |
| 08:17:47.654 | 마지막 LDN broadcast 관측 |

CH11과 CH1 광고는 SSID, server random, challenge, RFU session id가 모두 다르다. 따라서 한 방이
단순히 채널만 이동했다기보다 **연속된 두 LDN room instance**로 해석하는 것이 안전하다.

## 5. 실기 광고의 확정 필드

```text
LDN protocol          3
LDN version           4
advertise format      3 (AES-GCM)
local comm id         0x01006fa0233f8000
scene id              22287
application version   88 (0x58)
security mode         1
accept policy         0
max participants      6
application_data      122 bytes
band/channel           2.4 GHz / CH11, then CH1
```

첫 CH11 1-player 광고의 `application_data`는 현재 `beacon.build_application_data()`가 같은
TID/name/session/header/partner word를 입력받았을 때 **122/122 byte exact**로 일치했다. 즉 현재
RFU beacon encoder와 Pia header는 초기 방 검색 단계에서 맞다.

참가 뒤 header의 player count는 1에서 2로 바뀌었고, 트레이드 진행 중 partner word의 상위 비트가
`0x1584 -> 0x9584`로 바뀌었다. 이 동적 비트의 정확한 상태 의미는 fixed-channel 전체 스트림에서
추가로 매핑해야 한다. 그러나 초기 방 검출을 막는 원인은 아니다.

## 6. 프레임 증거와 두 카드 평가

RTL8192EU가 같은 LDN BSS에서 잡은 주요 수:

| 방향/종류 | 수 |
|---|---:|
| Switch B -> Switch A direct data | 1,622 |
| Switch A -> Switch B direct data | 1,540 |
| Switch A local broadcast data | 183 |
| Nintendo Vendor Action | 280 |
| LDN beacon | 271 |

RTL8188EU도 독립적으로 direct A->B 316, B->A 307, Vendor Action 62, beacon 69를 잡았다. 따라서
“카드가 Switch 통신을 못 듣는다” 또는 “8188EU가 현재 receive-dead 상태다”라는 가설은 이번
실험과 양립하지 않는다.

다만 hopping 중 각 카드는 한 순간에 한 채널만 들었으므로 두 카드의 수신율을 위 숫자로 비교하면
안 된다. RTL8188EU의 AP/host capability까지 증명된 것도 아니다. 이번에 증명된 것은 monitor RX와
채널 변경, Nintendo 관리 프레임 해독, 양방향 protected data 관측이다.

## 7. 코드 감사 결과와 적용한 교정

### 실기와 이미 맞았던 부분

- comm id `0x01006fa0233f8000`
- scene id `22287`
- max participants 6, security 1, accept 0
- LDN version 4
- Pia/RFU `application_data` 122-byte 초기 광고 encoder
- GBA/Pia app version 내부 값 `0x0058`

### 실기와 달랐던 부분

| 위치 | 기존 | 실기/교정 |
|---|---:|---:|
| `HostTransport.APPLICATION_VERSION` | 1 | 88 |
| `LiveTransport.APPLICATION_VERSION` | 1 | 88 |
| `LiveTransport` 기본 comm/scene | placeholder | 실측 comm/scene |
| `CreateNetworkParam.protocol` | 미설정, library default 1 | 명시적 3 |
| `advert_check` | app 1, protocol 미검사 | app 88, protocol 3 검사 |
| wire regression test | protocol 1/AES-CTR | protocol 3/AES-GCM |

LDN protocol 1과 3은 단순 표기 차이가 아니다. Kinnay는 protocol 1에 AES-CTR/master_key_00을,
protocol 3에 AES-GCM/master_key_12를 사용한다. 기존 host 광고/인증은 실기와 cryptographic
protocol 자체가 달랐다.

### 별도 잔존 blocker: hostapd hybrid

현재 `use_ap_engine=True` 경로는 generic hostapd AP만 만들고 Nintendo Vendor Action 광고,
LDN authentication, participant table, `ldn-tap` 생성을 수행하지 않는다. 그런데 같은 경로가
곧바로 `ldn-tap` 존재를 요구한다. 또한 async context 진입이 이미 `start()`를 호출한 뒤 body에서
다시 `start()`를 호출하고, 요청한 PHY가 아니라 첫 `wlx*`/`wlan*`를 고른다. 따라서 이 경로는
현재 production host 구현이 아니며, CLI 기본값이 `False`라 dormant 상태인 것뿐이다.

실제 host 모드는 현재 stock `ldn.create_network()` fallback을 사용한다. protocol/app 교정은 그
경로의 필수 수정이지만, rtl8xxxu에서 periodic beacon이 안정적으로 나오는지는 별도 실기 gate다.

## 8. 이번 캡처의 한계와 다음 실기 절차

CH1~13 hopping은 “어느 채널에서 LDN이 존재하는가”를 찾는 데 성공했지만 dwell 0.4초라 association,
authentication, trade payload의 연속 스트림을 보존하지 못한다. 따라서 이번 PCAP을 완전한 패킷
replay gold로 취급하면 안 된다.

다음 실험은 다음처럼 분리한다.

1. 사용자에게 두 Switch를 실제 연결시키기 전 방 검색 화면에서 대기하도록 요청한다.
2. Radio A는 CH1~13 discovery를 수행해 Vendor Action을 해독하고 payload channel을 결정한다.
3. Radio B를 그 채널에 즉시 고정하고 연속 캡처 시작을 확인한 뒤 사용자에게 연결 시작을 알린다.
4. 가능하면 Radio A도 같은 채널에 고정해 이중 독립 수집한다.
5. 입장, 의자 접근, 거래 시작, Pokémon 1마리 교환, 종료, 퇴장마다 사용자 채팅 marker를 받는다.
6. 이 fixed-channel gold로 LDN auth, Pia session, RFU 상태 bit, 실제 trade payload를 매핑한다.

그 전에 교정된 EMU guest가 Switch-host CH1/11 방에 join하는 짧은 실기 smoke test를 먼저 하면
protocol 3/app 88 수정의 효과를 가장 빠르게 분리 검증할 수 있다.

## 9. 테스트 결과

- golden beacon/advertisement 집중 테스트: **20/20 PASS**
- 전체 EMU discovery: **119 tests 실행, 기존 relay suite setup error 1건**
- 중단 원인: WSL `.venv`에 `uvicorn`이 없음. radio/protocol 코드 회귀가 아니라 기존 relay
  packaging/dependency 누락이며, 배포 준비 전에 별도로 고쳐야 한다.
