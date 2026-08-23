# 22 — LDN 골든 캡처 플레이북: 스위치↔스위치 무선 세션 전 과정 캡처 가이드

> 작성: 아리아 (2026-08-23)
> 용도: MWL-SwitchTrade의 STEP 10 디버깅뿐 아니라, 향후 모든 닌텐도 LDN/무선 프로토콜
>       분석 작업에 재사용 가능한 표준 절차서.
> 근거 기술: 코덱스 "native Switch-to-Switch golden capture + one-field differential replay" 제안,
>           Kinnay NintendoClients/LDN 문서, 본 프로젝트 실측 노하우 (docs/15~20)

---

## 0. 이 문서로 할 수 있는 것

- 스위치 2대가 주고받는 **모든 무선 프레임을 raw 바이트로 보존** (나중에 언제든 재분석)
- 방 검색 → 조인 → 인증 → 데이터 교환 → 트레이드까지 **단계별 경계를 시간축으로 대조**
- PC(EMU/브리지)가 만든 신호와 **실기 신호를 바이트 단위 diff** → 원인 필드 특정
- 한 번 캡처해두면 코드 수정 후 **재현 실험의 참조基准(reference)**으로 영구 사용

## 1. 하드웨어·소프트웨어 준비물

| 항목 | 사양 | 비고 |
|---|---|---|
| 수신 카드 | RTL8188EU 또는 RTL8192EU | monitor 모드 지원 필수. VM2 배치 |
| 호스트 카드 | RTL8192EU (HOST 가능) | VM1 배치 — PC가 AP 역할 시 |
| 스위치 A/B | FRLG(NSO GBA 앱) 설치, 로컬 통신 허용 | |
| VM2 OS | Ubuntu + ldn 0.0.17 venv + prod.keys | advert_check 실행 환경 |
| 캡처 도구 | tcpdump (pcap), tshark (오프라인 분석) | |
| 화면 기록 | 스마트폰 카메라 또는 캡처카드 | 타임라인 정렬용 |

⚠️ 카드 수신 사망(8188EU 특유) 대비: `authorized` 토글 스크립트 상시 준비.

## 2. 캡처 정보 체크리스트 (빠짐없이)

### A. 물리 계층 (radiotap 헤더 자동 포함)
- [ ] 타임스탬프 (μs 정밀도) — 나중에 화면 녹화와 정렬
- [ ] 수신 채널 / 주파수
- [ ] 신호 강도 dBm, 전송 속도, 안테나 정보
- [ ] FCS 오류 여부 (손상 프레임 구분)

### B. 802.11 관리 프레임
- [ ] **Beacon**: BSSID, SSID(32자 hex), capability, RSN IE, TIM, 전체 IE 체인 hexdump
- [ ] **Probe Request**: 요청 SSID 목록 (스위치가 찾는 방 이름 = 우리 SSID와 일치하는지)
- [ ] **Probe Response**: 위 Beacon과 동일 필드
- [ ] **Auth** (open-system): seq 번호, status code
- [ ] **Assoc Request/Response**: 지원 속도, capability, AID

### C. Nintendo Vendor Action 광고 ⭐ (방 리스트의 본체)
- [ ] 전체 raw hex (radiotap 제외한 802.11 부분)
- [ ] 디코딩 필드:
  - OUI/type/version 헤더 (`7f 00 22 aa 04 00 01 01`)
  - comm_id (16진 16B)
  - scene_id (FRLG=22287)
  - LDN 버전 / security_level
  - accept_policy
  - participants (현재/최대 — FRLG는 1/6)
  - application_data 122B 전체
    - Pia prefix `00 5c 16 00 58`
    - RFU payload (base85): TID, name, session_id, partner_info, tradeSpecies
- [ ] Action 광고 **주기** (100ms 간격 확인) 및 채널별 관측 분포

### D. 보안/암호화 관련
- [ ] RSN IE 상세 (cipher suite, AKM, capabilities)
- [ ] EAPOL 4-way handshake 유무 (LDN은 없어야 정상 — static CCMP)
- [ ] CCMP 데이터 프레임: PN(Packet Number) 초기값과 증가 패턴
- [ ] wlan_key 파생 재료: server_random (광고에서 추출)

### E. 데이터 교환 단계
- [ ] Assoc 이후 최초 Data 프레임 (LDN custom auth 시작점)
- [ ] TAP 인터페이스에서 본 IP/UDP 패킷 (169.254.x.x 대역)
- [ ] RFU 세션 handshake (Pia connect)
- [ ] Union Room 진입 후 좌석 배정 프레임
- [ ] 트레이드 제안/승인/완료 시점의 프레임 마커

### F. 컨텍스트 (수동 기록 — 매우 중요)
- [ ] 스위치 화면 동영상 (시작~종료 전체)
- [ ] 조작 타임라인 메모: `HH:MM:SS 리더 그룹 생성`, `HH:MM:SS 팔로워 조인` 등
- [ ] 각 스위치의 MAC 주소 미리 기록 (A/B 구분용)

## 3. 캡처 절차 (순서 엄수)

```
[사전] VM2 부팅 → 카드 생존 확인 → monitor 모드 CH6 고정
[1] tcpdump 시작 (pcap 저장) ← 반드시 스위치 조작 '전'에
[2] advert_check 병행 실행 (실시간 디코딩 확인용)
[3] 주인님: 스위치 A 리더 그룹 생성
[4] 주인님: 스위치 B 조인 → 트레이드 완주
[5] 주인님: "끝" 신호
[6] tcpdump 종료 → pcap 파일 보관 (logs/YYYY-MM-DD/golden/)
[7] 분석: tshark + advert_check 디코더 + 수동 hexdiff
```

### 명령어 스니펫

```bash
# VM2 — 캡처 시작 (raw pcap)
sudo tcpdump -i <IFACE> -I -e -s 0 -w /tmp/golden_$(date +%H%M%S).pcap 'type mgt or type data' &

# VM2 — 실시간 광고 디코딩 (별도 터미널)
sudo timeout --signal=INT 60s .venv/bin/python -m frlgsim.advert_check \
  --keys /root/.switch/prod.keys --phy <PHY> --channel 6 --dwell 55

# 종료 후 분석
tshark -r /tmp/golden_HHMMSS.pcap -Y "wlan.fc.type_subtype==8" -T fields \
  -e frame.number -e wlan.sa -e wlan.ssid -e frame.time_relative | head
```

## 4. 골든 캡처 이후: 차등 분석 (one-field differential)

1. **골든 광고 vs EMU 광고 hexdiff**
   - 같은 위치, 같은 시간대에 둘 다 캡처해서 나란히 놓고 비교
   - 다른 바이트 = 후보 필드. 같은 바이트 = 배제
2. **한 번에 하나만 수정**하고 스위치 검색 재시험
   - 방이 보임 → 그 필드가 결정적 원인
   - 안 보임 → 다음 후보로
3. **Replay 진단** (선택): 골든 캡처의 Action 프레임을 그대로 재주입
   - 재송출 방은 리스트에 보이는데 EMU 방은 안 보임 → 무선 OK, 페이로드 문제 확정
   - 재송출 방도 안 보임 → 무선/채널/타이밍 문제
   - ⚠️ 암호 세션이 낡아 조인은 불가할 수 있음 — "리스트 표시" 판정용으로만

## 5. 과거 실수 방지 체크 (본 프로젝트 교훈)

| 함정 | 예방책 |
|---|---|
| 같은 카드 모니터로 자기 TX 캡처 = 루프백 없어 안 잡힘 | **반드시 물리적으로 다른 수신기** 사용 |
| ldn.scan 호출 시 VM hang (3회 재발) | 외부 `timeout --signal=INT` 필수, trio timeout만 믿지 않기 |
| 8188EU 시작 직후 수신 사망 | authorized 토글 스크립트 선준비 |
| beacon head에 IEs 누락 → rtl8xxxu beaconing 안 함 | hostapd-style IEs 유지 (docs/16) |
| application_data 추측 필드 | 골든 캡처로 실측값 대체 (D1/D2/D3 교훈) |
| Probe Request 대기를 "발견 판정"으로 오용 | LDN 발견은 Action 광고 기반 — Auth는 리스트 등록 '후'에 옴 |

## 6. 산출물 보관 규칙

```
logs/YYYY-MM-DD/golden/
├── golden_HHMMSS.pcap      # raw 전체
├── advert_decode.log       # advert_check 출력
├── timeline.md             # 수동 조작 타임라인
└── switch_macs.txt         # A/B MAC 메모
```

git에는 pcap 넣지 말 것(.gitignore). 분석 결과(md/json)만 커밋.

## 7. 응용 시나리오 (향후 재사용)

- 새 카드 드라이버 검증 (V-1 대체·보강)
- 게임 버전 업데이트 후 프로토콜 변경 감지
- 다른 타이틀(Pokémon LGPE, SwSh 등)의 LDN 변형 분석
- 릴레이 왕복 지연이 끼는 framerelay 환경의 ACK 유실률 측정 베이스라인
