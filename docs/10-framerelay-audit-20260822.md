# 10 — framerelay(트랙 B) 사이클 2 Audit 결과 (2026-08-22)

> 작성: 옥스 알파(opencode) 적대적 코드 리뷰 | 대상: 커밋 1622751 (사이클 1 framerelay 코어)
> 상태: 읽기 전용 리뷰 — 코드 수정 없음. 발견 이슈는 다음 세션 수정 백로그.
> 베이스라인: tests/test_framerelay.py 23케이스 전부 통과 확인됨.

---

## CRITICAL

**C-1. EchoGuard 바이트 동등성 전제 미검증 — 실패 시 양단 무한 ping-pong 증폭**
- 위치: `framerelay/bridge.py:79-104`, `radio.py:63-74`, `radio.py:24`
- 문제: EchoGuard는 "주입 프레임 == 재캡처 프레임"의 sha1 일치 가정. 그러나 (a) 주입 시 드라이버가 FCS 덧붙이면 캡처 측 payload에 FCS 포함 → 해시 어긋남. radiotap Flags(present bit 0x10)에 FCS 포함 여부가 실리지만 strip_radiotap은 길이로만 자르고 플래그 폐기. (b) 드라이버별 헤더 패딩 변형도 해시를 깸. `PACKET_IGNORE_OUTGOING` 미지원 커널(<4.20)에선 이 경로가 루프 방지의 유일 방어선 — 미스매치 1회면 양방향 증폭 루프.
- 근거: docs/07 §3은 TX 헤더 8B만 실측, RX 캡처의 FCS/padding 거동은 실측 기록 없음. 스텁 라디오 테스트는 바이트 불변을 전제 — 이 전제 검증 테스트 없음.
- 수정 방향: (1) 캡처 시 radiotap Flags 파싱 후 FCS 4B 절단 (2) EchoGuard를 전체-바이트 해시 대신 (type, addr1..3, seq_ctrl) 튜플 등 변형 내성 키로 전환 (3) 안전망으로 초당 중계 상한/루프 카운터 도입.
- 선행 실기 검증: **V-1 (아래)**

## HIGH

**H-1. HEARTBEAT_INTERVAL(30s) == 릴레이 HEARTBEAT_TIMEOUT(30s) 타임아웃 경합**
- 릴레이는 "마지막 수신 후 30.0s"로 끊는데 브리지도 30.0s 간격 송신 → 침묵 구간에서 수신 간격 >30.0s 되기 쉬움 → 4408 close 반복. 트래픽 흐르는 동안엔 덮이지만 광고 시작 전/종료 후엔 접속 churn.
- Track A RemoteTransport도 동일 값 (우발적 복제).
- 수정: HEARTBEAT_INTERVAL을 TIMEOUT의 1/3(예: 10s)으로. 공용 상수화 고려.

**H-2. `_outbox` 무한 성장 + 재접속 시 스테일 프레임 일제 방출**
- WS 단절 중에도 라디오 루프가 계속 큐잉(비콘 ~10fps). 재접속 시 수 분 치 오래된 ACK/응답이 순서대로 주입되어 진행 중 교환을 더 꼬게 함. 메모리 무한.
- 수정: 단절 중 큐잉 중단 or cap+drop-oldest / 재접속 직후 age N프레임 이상 폐기.

**H-3. 재접속 3회(~3초) 포기 후 조용한 좀비 상태**
- 릴레이 재시작 같은 수 초 장애면 WS 스레드 영구 종료인데 메인 루프는 살아 있고 큐만 불어남 ("겉보기 건강" — 현장 디버깅 비용 급증).
- 수정: 무한/지수 백오프 재접속, 또는 포기 시 명시적 process exit.

**H-4. 비콘 캐시 TTL 부재 — 유령 룸**
- Switch A가 방을 닫으면 마지막 비콘 4개가 영원히 100ms 재생됨 → B 화면에 죽은 방이 계속 보이고 조인 시도가 공허한 곳으로. guest 하프는 원격 비콘까지 재캐시. 호스트 하프는 A의 비콘을 A 에어에 되돌려 재생(airtime 낭비).
- 수정: 캐시 엔트리 TTL(1~2s), 재생은 guest 역할(or 원격 발신) 한정.

## MEDIUM

| ID | 내용 | 수정 방향 |
|---|---|---|
| M-1 | `EchoGuard.prune()` 프로덕션 미호출 — `_seen` 무한 성장 (느린 누수) | record()/duplicate()에서 주기 prune 또는 상한+drop-oldest |
| M-2 | `MonitorRadio.recv` 모든 OSError→None 처리 — USB 분리(ENODEV)·드라이버 웨지 시 무음 좀비 | errno 분류(EAGAIN/EINTR=계속, 나머지=로그+종료) |
| M-3 | CLI bind 실패(OSError ENODEV/EPERM) 미처리 — raw traceback, 주석과 불일치 | open()에서 RuntimeError 래핑 또는 __main__에서 OSError 수집 |
| M-4 | 비콘 재생 폭주: 캐시 4개×10Hz=최대 40주입/s + 스테일 timestamp(TSF 점프 위험) + 신선/재생 이중 주입 | capacity 1~2 축소, 최신 1개만 재생, 조인 성립 후 감속 검토 |
| M-5 | `websockets` requirements.txt 누락 — 부재 시 WS 스레드 조용히 즉사(H-3 좀비 결합) | requirements 추가 또는 start() 사전 import 검사 |
| M-6 | MWLB trailing-bytes 계약 vs 소비자 불일치 — 연결 프레임 시 두 번째 무음 폐기 (현재는 릴레이 메시지 경계 보존으로 안전하나 암묵적 의존) | 잔여 바이트 루프 처리 or "WS 메시지당 1프레임" 명시 |

## LOW
L-1 stats 3스레드 동시 += (표시용 경미) / L-2 pinned URL role 쿼리 누락 시 4409 가능 / L-3 memoryview 입력 계약 불일치 / L-4 SIGTERM 미처리(cleanup 생략) / L-5 --host-mac 오류 시 zero-match 무음 no-op / L-6 테스트 공백(WireStub이 릴레이 의미 우회, parity 2 msg_type뿐)

## 긍정 확인
- BSSID 필터: QoS 데이터 서브타입도 주소 배치 동일해 커버됨. ff:ff 와일드카드도 FromDS(addr2/3)/ToDS(addr1=BSSID)로 커버 — 유의미한 빈틈 없음 (남는 건 L-5의 BSSID≠MAC 전제뿐).

## 실기 검증 필요 (코드 리뷰만으로 판정 불가)

| # | 항목 | 방법 |
|---|---|---|
| V-1 | ⭐ **주입↔재캡처 바이트 동등성(FCS/padding/radiotap Flags)** — C-1의 진위 | `radio-health-gate.sh -- <tcpdump...>` 통과 후 카드 A 주입→모니터 재캡처 hexdump 대조 (`-y IEEE802_11_RADIO`) |
| V-2 | 대상 커널 PACKET_IGNORE_OUTGOING 실제 효과 (echo 경로 자체 발생 여부) | 커널 버전 확인 + 주입 시 셀프 캡처 관측 |
| V-3 | 100ms 스테일 비콘 재생의 스위치 해석: 스캔 표시·TSF 동기·조인 후 전력관리 이상 | 2대 실측 (방 안/밖 분리) — cadence 100ms vs 실측 LDN 비콘 간격 비교 |
| V-4 | 릴레이 RTT(50~200ms) 하 유니캐스트 ACK/SIFS 리스크 — 조인 핸드셰이크 통과 여부 | §7 절차 5~6 관찰 + 재전송률 캡처 분석 |
| V-5 | Switch LDN softAP BSSID == 콘솔 MAC 전제 (--host-mac 유효성) | 광고 비콘 addr2/addr3 대조 |
| V-6 | LDN 최대 프레임/A-MSDU 사용 여부 (MAX_PAYLOAD 대비) | 모니터 캡처 프레임 길이 분포 |

## 다음 세션 실행 권장 순서
1. **V-1 먼저** (카드 1개로 가능, 스위치 불필요) → C-1 수정 방향 확정
2. H-1~H-4 + M-1~M-6 일괄 수정 (독립 커밋, 오프라인 테스트 보강)
3. V-3/V-4/V-5 = 2대 실기 검증 체크리스트에 통합 (docs/07 §7 절차와 병행)
