# 26 — PC host 실기 gate: 방 표시·LDN join 성공, Pia host-role 미구현 확인 (2026-08-24)

## 1. 결론

protocol 3 / application version 88 교정 뒤 WSL RTL8192EU가 만든 `CODEX` 방이 실제 Switch의
방 목록에 표시되었고, Switch는 해당 방에 LDN participant 1로 여러 번 정상 join했다. 따라서
다음 gate는 통과했다.

- periodic beacon 외부 RF 송신
- encrypted Nintendo Vendor Action 외부 RF 송신/해독
- 실기 Switch room discovery
- open authentication/association
- protocol 3 LDN custom authentication
- participant table `1/6 -> 2/6`

실패는 더 위의 Pia/game session layer다. PC 프로그램은 LDN host/participant 0이면서도 기존
joiner 전용 코드를 그대로 실행해 `RIGHT / Follower / mpId=1`로 설정되고 Switch host가 보낼
`Net 0x11`을 기다렸다. 실제 Switch는 participant 1이므로 PC host가 먼저 Pia 연결을 시작하기를
기다렸다. 양쪽 모두 기다린 뒤 Switch가 약 8초 후 “the other trainer appears unavailable”로
나갔다. 사용자 입력 속도 문제는 아니다.

## 2. 실험 구성

| 역할 | 장치 | 구성 |
|---|---|---|
| PC LDN host | RTL8192EU `0bda:818b`, `rtl8xxxu` | WSL, CH6, `HostTransport`, protocol 3/app 88 |
| 외부 observer | RTL8188EU `0bda:8179`, patched `8188eu` | WSL, monitor CH6, continuous pcap |
| Switch joiner | `98:41:5c:79:41:38` | FRLG join-room 화면에서 `CODEX` 선택 |

두 카드 모두 실험 전 actual-RX health gate를 통과했다. 종료 뒤 두 카드도 다시 health gate를
통과했고, 잔류 `frlgtrade`/`tcpdump` 프로세스는 없다.

## 3. 외부 RF 검증

RTL8188EU가 RTL8192EU host `a0:47:d7:b0:2b:39`에서 다음을 수신했다.

```text
LDN protocol          3
frequency/channel     2437 MHz / CH6
comm id               0x01006fa0233f8000
scene id              22287
application version   88
security/accept       1 / 0
participants          1/6 <-> 2/6
application_data      122 bytes
```

- decoded Vendor Action: 1,098
- beacon: 1,098
- participant transitions: 11 states, 즉 5회의 `1/6 -> 2/6 -> 1/6` join/timeout cycle
- standard association request/response도 외부 캡처에 존재
- CCMP를 실측 server-random과 built-in GBA passphrase로 외부 해독하면 protocol 3 LDN custom
  authentication request/response와 ARP가 정상이다.

따라서 “방 광고가 여전히 틀려서 Switch가 거부했다”는 가설은 폐기한다.

## 4. Pia blocker의 직접 증거

Host 로그:

```text
hosting ... participants=1/6
PEER JOINED our room ... (2/6)
awaiting host connection ... host_var=unseen rx_ok=0 tx=0
peer left the room
```

`host_pia.jsonl`에는 session metadata 한 줄만 있고 `pkt` record가 0개다. 즉 Pia UDP datagram은
양방향 모두 시작되지 않았다.

현재 코드의 모순:

- host mode에서도 `--self-id`는 `1`만 허용한다.
- trade engine은 항상 `RIGHT (Follower / mpId=1)`이다.
- `PiaConnect`는 host의 `Net 0x11`에 응답하는 joiner state machine만 구현한다.
- host mode 로그도 “awaiting the host's Pia connection handshake”라고 출력한다.

LDN host transport만 추가하고 그 위의 Pia/game 역할을 전환하지 않은 것이 근본 원인이다.

## 5. 다음 구현 gate

다음 실기 전에 최소한 다음 host 역할이 필요하다.

1. PC participant 0 / LEFT / Leader state
2. Switch participant 1을 향한 Pia Net `0x11` 시작 및 재전송
3. Switch의 Net `0x12` 처리
4. joiner Session request 수신·accept/update 응답
5. host-side constant/variable ID와 packet-id 수명
6. 연결 성립 뒤에만 overworld/link-state host flow 시작

이 동작은 기존 joiner `PiaConnect`에 조건문을 흩뿌리지 말고, wire builder/decoder는 공유하되
별도 host state machine으로 분리하는 것이 안전하다. 다음 fixed-channel Switch-host gold에서
Net/Session 초기 handshake를 연속 수집해 byte-exact fixture로 만든 뒤 실기에 재투입한다.

## 6. 보존 파일

```text
bd71f3c1081a2fa114eaccde9ef86e83a3a25794d1db896f1bd5219a58d681fd  host_pia.jsonl
cd0f4c1264208aa65dd640656815c931ee565c19fe8b48fb43a8a205278eb8a0  observer_session.pcap
c80fe5e06087b0eefcf460e2f9d4cbd10c50d1be770c2ffc62b73f45181cc9c6  observer_startup.pcap
```

경로: `logs/golden/pc_host_20260824_085514/`

> **2026-08-24 implementation update:** Net `0x11` host outreach and Session-join capture are now
> implemented as a gated acquisition step. See `docs/28-pia-host-acquisition-20260824.md`.
