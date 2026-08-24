# 28 — Pia PC-host acquisition gate 구현 (2026-08-24)

> **Resolved by the fixed-channel native gold.** The missing NetStation table and Session
> type `2`/`5` bytes were captured and implemented. Continue with
> `docs/30-native-fixed-handshake-20260824.md`.

## 1. 현재 결론

실기 Switch가 PC의 `CODEX` 방을 보고 LDN participant 1로 join한 뒤 약 8초마다 나간 원인은
사용자 입력 속도가 아니었다. PC는 LDN host/participant 0이지만 기존 Pia와 게임 코드는
joiner/RIGHT/Follower 전용이어서 host의 첫 메시지인 Net `0x11`을 전혀 보내지 않았다.

이번 변경은 다음 실기에서 필요한 첫 host-owned gate를 구현한다.

1. PC가 약 500 ms마다 Pia Net `0x11` connection-status를 broadcast한다.
2. Switch의 Net `0x12`가 같은 sequence id를 echo하는지 검증한다.
3. 이어지는 Session type 0 join을 해석해 constant id, variable id, IP/port, player name을 보존한다.
4. Session accept의 native bytes를 얻기 전에는 `connected=False`를 유지해 기존 Follower 게임
   트래픽이 절대 송출되지 않게 한다.

즉 이번 단계의 성공 기준은 “트레이드 완료”가 아니라 **zero Pia TX를 해소하고 Switch의 실제
join request를 byte-exact로 확보하는 것**이다.

## 2. 기존 gold의 추가 복호화 결과

`logs/golden/discovery_20260824_081253/rtl8192eu_allch.pcap`의 CH1 room을 다시 해석했다.

```text
SSID                  e7908f7c3fd2bbf992815f63225afc9c
server random         e6863955335520eb4c32ac655f586b03
derived CCMP key      4356d28cb7fcb24f8e3fb6f70c42bbad
Pia packets decrypted 3,512 (failure 0)
host IP / var         169.254.120.1 / 0x348e
joiner IP / var       169.254.120.2 / 0x4a2b
```

이 gold에는 양방향 RTT, Reliable trade stream, Net `0x50`/`0x51`이 존재한다. 특히 Net `0x50`의
inner size `0x007a`는 전체 160-byte 메시지 크기가 아니라 뒤의 122-byte application data 크기와
일치한다. 따라서 기존 `parse_net()`이 inner size만큼 `payload[4:]`를 잘라 fixed field를 버린
것은 버그였다. Net `0x12`도 size가 0이지만 뒤에 4-byte sequence id가 있으므로 이전 parser는
정상 ACK의 body를 빈 값으로 만들었다. 이번에 fixed body 전체를 반환하도록 교정했다.

다만 CH1~13 hopping 중 association 직후 채널을 떠나 초기 Net `0x11`, Net `0x12`, Session join,
Session accept 구간은 캡처되지 않았다. 그래서 공개 Pia 6.x 구조로 확정 가능한 `0x11`과 join
parser까지만 구현하고, type-5/type-2 accept bytes는 다음 고정 채널 캡처 뒤 구현한다.

## 3. 코드 변경

`frlg-ldn-trade-emu`의 `gptsolreview`:

- `frlgsim/pia_connect.py`
  - Net fixed-field parser 수정
  - `build_net_request()` 추가
  - `parse_session_join()` 추가
  - `HostConnectionManager` 추가
- `frlgsim/sim.py`
  - connection manager의 host `poll()`을 VBlank마다 호출
- `frlgtrade.py`
  - `--mode host`에서 fresh variable id와 host manager 사용
  - host acquisition 중 기존 Follower engine을 명시적으로 gate
- `tests/test_pia_host.py`
  - Net wire fixture, join parser, 500 ms retransmission, encrypted broadcast 통합 검증

## 4. 검증

```text
tests.test_pia_host: 4/4 PASS
py_compile: PASS
all non-relay suites: 123/123 PASS
full discovery known setup error: relay offline suite의 uvicorn 미설치 1건
```

relay error는 이번 Pia 변경의 회귀가 아니며 2026-08-24 이전부터 존재한 requirements/venv 문제다.

## 5. 다음 실기 gate

1. 두 radio 모두 actual-RX health gate 통과
2. RTL8192EU로 PC room 시작, RTL8188EU를 같은 채널 observer로 고정
3. 사용자에게 Switch를 join-room 화면에 두도록 요청
4. PC capture에 OUT Net `0x11`이 500 ms 간격으로 존재하는지 먼저 확인
5. 사용자에게 `CODEX` 선택 요청
6. 로그에서 `Switch acked host Net 0x11`과 `Switch Session join captured` 확인
7. 즉시 안전 종료하고 capture/observer pcap 보존
8. captured native join을 기준으로 Session type-5 accept/type-2 follow-up을 구현

이 실험에서도 Switch 화면의 “other trainer appears unavailable”는 예상 가능하다. 이번 gate는 그
메시지 전에 Switch의 native Session join을 확보해 다음 byte-exact host accept 구현을 여는 단계다.
