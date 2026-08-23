# HANDOFF 2 — STEP 10 LDN discovery 감사와 수정 (2026-08-23)

> 작성자: Codex GPT solution review
> 수신자: 다음 코딩/실기 검증 에이전트
> 목적: 순정 Switch의 FRLG 방 목록에 PC 호스트가 보이지 않는 STEP 10 문제의 감사 결과,
> 코드 수정, 그리고 다음 실기 판정 절차를 인계한다.

## 1. 저장소와 고정 지점

| 저장소 | 작업 브랜치 | 기반 | 이 인계의 변경 |
|---|---|---|---|
| `mwl313/mwl-SwitchTrade` | `gptsolreview` | `main` @ `6280543` | 감사 문서와 이 handoff |
| `mwl313/frlg-ldn-trade-emu` | `gptsolreview` | `framerelay-dev` @ `8ebe5dd` | `0a7b924` (`ldn: correct FRLG discovery advertisement`) |

두 저장소는 별도 Git 저장소다. 일반 배치에서는 메인 저장소의 `emu/`가 두 번째 저장소다.

## 2. 결론

지금까지 STEP 10은 주로 일반 802.11 beacon과 Switch의 Probe Request/Auth를 관찰했다.
그러나 LDN 방 발견 순서는 다음과 같다.

1. 호스트가 Nintendo Vendor Action advertisement를 100 ms마다 방송한다.
2. 클라이언트 Switch가 이 Action frame을 수동 스캔하고 복호화/필터링한다.
3. 방이 목록에 올라오고 사용자가 선택한 뒤에야 open-system Auth/Assoc가 시작된다.

따라서 방이 안 보이는 동안 Probe Request/Auth가 없는 것은 정상이며, 그것으로 "Switch가 못
봤다"와 "봤지만 버렸다"를 구분할 수 없다. 일반 beacon 수신 성공도 LDN advertisement의
외부 RF 수신을 증명하지 않는다.

근거:

- <https://github.com/kinnay/NintendoClients/wiki/LDN-Protocol>
- <https://github.com/kinnay/LDN/pull/8#issuecomment-3938931613>
- Kinnay `Scanner.receive()`는 Vendor Action frame만 LDN 광고로 해석한다.

## 3. 확인한 결함과 수정

### Critical — Wi-Fi SSID가 서로 다른 값이었다

`ldn.create_network()`는 16-byte session SSID를 `param.ssid.hex()`로 바꾼 32자리 ASCII 문자열을
AP에 전달한다. 기존 beacon monkey-patch는 다시 `bytes.fromhex(ssid)`를 호출해 16 raw bytes를
beacon에 넣었다. Action advertisement/probe response와 beacon의 BSS identity가 달랐다.

수정: 문자열을 ASCII 32 bytes로 보존한다. beacon SSID IE는 LDN 규격대로 길이 32와 zero
contents를 사용하고, 실제 ASCII SSID는 `NL80211_ATTR_SSID`와 probe response에 남는다.

### Critical — FRLG 참가자 수가 `1/8`이었다

프로젝트 캡처의 실제 FRLG 광고는 모두 `1/6`이다. 기존 값 8은 Kinnay 라이브러리 기본값일
뿐 실측값이 아니다. 수정: `HostTransport.MAX_PARTICIPANTS = 6`.

### High — hidden SSID를 visible로 강제했다

LDN 규격은 beacon SSID 내용을 zero로 만든다. 기존 START_AP patch는
`HIDDEN_SSID_ZERO_CONTENTS`를 `NOT_IN_USE`로 덮어썼다. 이 patch와 잘못된 동작만 검증하던
`tests/test_start_ap_attrs.py`를 삭제했다. rtl8xxxu에서 주기 beacon을 발생시킨 complete
beacon-head override 자체는 유지했다.

### High — BSS capability 불일치

커스텀 beacon의 `0x0431`을 Kinnay encrypted probe response와 같은 `0x0511`로 맞추고 기존
RSN/CCMP IE를 유지했다.

### Medium — Pia 6.x header 오해

기존 코드는 offset `0x15` 이후를 추정 flags/TLV로 취급했다. 공식 구조는 big-endian fixed
header다: size `0x5C`, system communication version 22, application communication version
`0x58`, player-limit fields, u32 name length, encoding byte, 64-byte player name.

근거: <https://github.com/kinnay/NintendoClients/wiki/LDN-Application-Data-(Pia)>

## 4. 변경 파일

- `emu/frlgsim/transport.py`: SSID, hidden beacon, capability, max participants, host metadata.
- `emu/frlgsim/beacon.py`: 문서화된 Pia 6.x header builder.
- `emu/frlgsim/advert_check.py`: 별도 수신 카드에서 encrypted Vendor Action 광고를 decode하고
  FRLG identity를 검사하는 결정적 진단 도구.
- `emu/tests/test_host_advertisement.py`: 실제 Kinnay APNetwork encode → decrypt → decode 회귀.
- `emu/tests/test_beacon_head.py`, `test_beacon_encoder.py`: 수정된 wire contract 회귀.
- `docs/20-step10-codex-beacon-audit.md`: 근거, 전체 감사, 실기 절차.
- `docs/19-step10-아웃라인과-픽스.md`: P0 진단의 오류를 알리는 정정문.

## 5. hostapd 제안 감사

추가 상담 내용의 우려는 타당하지만 현재 `use_ap_engine=True` 경로는 LDN hybrid가 아니다.

- `async with engine`이 이미 시작한 뒤 `engine.start()`를 다시 호출한다.
- `ldn.create_network()`를 우회하므로 Vendor Action 광고, Nintendo custom auth,
  participant/IP 할당, monitor/TAP CCMP 처리가 없다.
- 따라서 `ldn-tap`도 생성되지 않아 `_require_tap()`이 실패한다.
- 일반 WPA2 4-way handshake와 `AP-STA-CONNECTED`는 LDN 인증을 대체하지 않는다.
- 요청한 PHY가 아니라 첫 `wlx*`/`wlan*`를 고른다.

다음 실기에서는 `use_ap_engine`을 켜지 말고 수정된 pure Kinnay/nl80211 경로를 먼저 검증한다.

## 6. 완료한 검증

- Python 3.14 `compileall`: 통과.
- beacon/transport 비무선 unit test 108개: 통과.
- relay integration test 4개: 통과.
- 실제 Kinnay 광고 encode/decrypt/decode: 통과.
- `git diff --check`: 통과.

Windows에서는 Linux sysfs symlink fixture 이름의 `:` 제약 때문에 `test_detect_phy.py`를 제외했다.
광고 변경과 무관하지만 Linux VM에서 전체 suite를 다시 실행한다.

## 7. 다음 에이전트의 첫 실기 — 이것부터 한다

VM1과 VM2 모두 emulator `gptsolreview`를 checkout한다. VM1에서 channel 6으로 HostTransport를
실행한 상태에서, 반드시 물리적으로 다른 수신 카드인 VM2에서 실행한다.

```bash
sudo timeout --signal=INT 15s .venv/bin/python -m frlgsim.advert_check \
  --keys /root/.switch/prod.keys --phy <VM2_PHY> --channel 6
```

outer `timeout`은 유지한다. driver/kernel nl80211 호출이 uninterruptible 상태에 걸리면 Trio
timeout만으로는 프로세스를 회수할 수 없다.

판정:

- `no decodable ... advertisement`: blocker는 Action-frame RF injection/channel/radio state다.
  beacon 개수나 Probe/Auth를 더 분석하지 않는다.
- `MISMATCH=...`: Action frame은 VM2까지 도달했다. 표시된 NetworkInfo field부터 고친다.
- `PASS`: 이 상태에서 Switch를 FRLG 검색 화면에 둔다.
- `PASS`인데도 방이 안 보임: 같은 외부 카드로 PC 광고와 실제 Switch-host 광고를 각각
  캡처하고, decoded `NetworkInfo`와 application data 122 bytes 전체를 byte diff한다.
- 방은 보이지만 join 실패: 그때부터 Probe Response → open Auth → Assoc → static CCMP →
  LDN custom authentication 순서로 추적한다.

## 8. 아직 검증하지 못한 것

이 작업 환경에는 문서에 적힌 `~/.ssh/aria_bridge` private key가 없어 VM 로그인과 실제 RF
검증을 수행하지 못했다. 따라서 코드/wire format 수정은 검증됐지만 "Switch 방 목록 표시"는
아직 완료 판정하지 않는다.

## 9. 다음 에이전트가 피할 것

- 방이 안 보이는 단계에서 Probe Request/Auth를 기다리지 않는다.
- 송신 카드 자신의 monitor capture를 외부 RF 전달 증거로 취급하지 않는다.
- ordinary beacon scan 성공을 LDN discovery 성공으로 부르지 않는다.
- 현재 hostapd branch를 discovery 해결책으로 켜지 않는다.
- 하드웨어 실측 없이 "Switch가 이제 감지한다"고 완료 처리하지 않는다.
