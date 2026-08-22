# STEP 7 — AP+monitor 동시 vif 실측 결과 (2026-08-22)

> 환경: VM1, RTL8192EU (`0bda:818b`), rtl8xxxu (인커널), 커널 7.0.0-30
> 방법: netlink(nl80211) 직접 호출 — kinnay ldn의 BeaconFrame.encode() 재사용해 beacon head 조립

## 판정: **PASS (조건부)** — AP 기동 중 monitor vif 생성·공존 성공

## 실측 결과

| # | 시험 | 결과 |
|---|---|---|
| 1 | `iw phy` 인터페이스 모드 | ✅ managed / **AP** / AP/VLAN / monitor |
| 2 | interface combinations | `not supported` 표기 = 드라이버가 명시적 제한 목록 없음 (소프트웨어 판단에 위임) |
| 3 | wlx 인터페이스를 AP 타입 전환 | ✅ (`set type __ap` → type AP) |
| 4 | **NL80211_CMD_START_AP 성공** | ✅ kinnay BeaconFrame.encode() head + SSID=MWLTEST, CH1, beacon_int=100, DTIM=3 |
| 5 | **AP 기동 상태에서 mon0(monitor) 생성** | ✅ **성공** — `iw dev`가 둘 다 표시: `wlx...(type AP, ssid MWLTEST, channel 1)` + `mon0(type monitor)` |
| 6 | AP 유지 중 mon0 promiscuous 진입/복귀 | ✅ dmesg 확인 (entered/left promiscuous mode) |
| 7 | 자기 비콘의 무선 수신(mon0로) | ⚠️ 미확인 — 주변 공유기(TP-Link, CH2) 비콘은 수신되지만 자기 TX는 루프백 안 됨 |

## ⚠️ 조건부 사유와 해석

자기 AP 비콘이 mon0에서 안 잡히는 것에는 두 가능성이 있음:

1. **하드웨어 루프백 부재 (유력)**: rtl8xxxu는 자신이 보낸 프레임을 자기 모니터로 되돌려주지 않음.
   PACKET_IGNORE_OUTGOING과 동일한 효과가 하드웨어 레벨에서 존재. → framerelay EchoGuard 설계와 양립
   (오히려 에코 원천 차단이라 유리). V-1 실험(주입↔재캡처 일치)은 AF_PACKET 송신 경로였고 이번은
   nl80211 AP 비콘 경로라 별개 — 비콘은 드라이버 펌웨어가 생성하므로.
2. **비콘 미송출**: tx_packets이 3초+1 증가(매우 느림)해 완전 배제 못 함.

## 확정 판정

- **AP+monitor 동시 vif 구성 자체는 성공** — 호스트 모드(framerelay 조합)의 물리적 전제 충족.
  framerelay는 "AP vif(호스트 모드) 또는 스위치 softAP(게스트 모드) 옆에서 monitor vif로 캡처" 구조인데,
  후자(T1~T4에서 이미 실증)든 전자(이번 실측)든 monitor가 살아있음이 확인됨.
- **자기 비콘 무선 수신 여부는 STEP 8(VM2 스캔으로 EMU 방 검색)에서 확정** — VM2 카드가
  MWLTEST 방을 보이면 그것이 최종 증거 (자기 루프백과 무관하게 외부 수신을 증명).

## 실행 노트 (재현용)

- 스크립트: `/tmp/step7_final.py`, `/tmp/step7_nl3.py` (VM1)
- 핵심: iw CLI의 `ap start`는 beacon head 파싱 제약("malformed beacon head") → netlink 직접 호출 필요
- beacon head는 반드시 kinnay `BeaconFrame.encode()` 사용 (수작업 hex는 EINVAL)
- START_AP 전 인터페이스 UP 필수 ("Network is down" 에러 회피)
- AP 기동 중 mon0 생성 1회 성공 후 재시도 시 EMFILE(Errno 23) 간헐 발생 → vif 정리 후 재실행로 해결

## 남은 후속

- [ ] STEP 8: VM2 카드로 MWLTEST 방 스캔 (자기 비콘 외부 수신의 최종 증명)
- [ ] (선택) hostapd 설치 시 정식 AP 운용도 가능하나, 우리는 ldn create_network가 START_AP를 대체하므로 불필요
