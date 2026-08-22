# B2 — hostapd vs ldn START_AP nl80211 attrs gap 분석 (2026-08-22 밤)

> 방법: hostapd -dd 로그(207줄)와 ldn wlan.py:1573-1590 소스 비교
> 목표: rtl8xxxu에서 beaconing이 시작 안 되는 원인 특정

---

## 발견된 차이 4건

### GAP-1: NL80211_ATTR_BEACON_IES 누락 ⭐ 유력

hostapd가 보내는 값:
```
nl80211: beacon_ies - hexdump(len=10): 7f 08 04 00 00 02 00 00 00 40
```
- IE 0x7F (Extended Capabilities) — **필수 필드로, 커널 mac80211이 beacon에 삽입함**
- 이게 없으면 일부 드라이버/커널 조합에서 beacon 업데이트 실패 가능

ldn은 이 attr 자체를 전송하지 않음.

### GAP-2: NL80211_ATTR_PROBERESP_IES 누락
- hostapd: `7f 08 04 00 00 02 00 00 00 40` (같은 Extended Capabilities)
- probe response에도 이 IE를 넣어야 함. ldn은 미전송.

### GAP-3: NL80211_ATTR_ASSOCRESP_IES 누락
- 동일한 Extended Capabilities. assoc response에 포함됨. ldn 미전송.

### GAP-4: HIDDEN_SSID 모드 차이
| | ldn | hostapd |
|---|---|---|
| attr | `NL80211_HIDDEN_SSID_ZERO_CONTENTS` (=2) | `not in use` (=0) |
| 의미 | SSID를 beacon에서 숨김 (길이 0으로 표시하되 내용 제거) | SSID 정상 노출 |
| 영향 | **스위치의 passive scan에서 SSID 매칭 실패 가능** ⭐ | SSID 정상 수신 |

⭐ GAP-4는 스위치가 방을 못 찾는 직접적 원인일 수 있음:
- 스위치 LDN 스캔은 SSID를 파싱해서 comm_id/application_data를 식별하는데,
  HIDDEN_SSID=ZERO_CONTENTS면 SSID가 빈 값으로만 전달됨
- 단, 우리 SSID는 16B hex 랜덤이라 스위치가 "특정 SSID를 검색"하는 게 아니라
  application_data를 파싱하는 구조 → hidden이어도 괜찮을 수도 있음
- 그러나 rtl8xxxu 드라이버가 ZERO_CONTENTS + BEACON_HEAD 조합에서 beacon 생성을
  스킵했을 가능성은 있음

## 추가 관찰: beacon head/tail 차이

| | ldn (패치 후) | hostapd |
|---|---|---|
| head len | ~36B+IEs | 58B |
| capability | 0x0401 | 0x0104 ← **바이트 순서 주의! hostapd=0104(BE), ldn 패치=0401(LE)** |
| tail | b"" | 23B (extended rates + extended capabilities 등) |

**capability 바이트 순서**: hostapd 로그 `01 04` = LE u16으로 읽으면 0x0401.
우리 패치도 `struct.pack("<H", 0x0401)` = `01 04` → ✅ 일치 확인.

tail이 23B vs 0B 차이: extended rates(32 04 30 48 60 6c) + extended capabilities(7f...) +
RM enabled(3b 02 51 00). 이것들 없이도 기본 beaconing은 가능해야 하지만, 일부 클라이언트가
호환성 체크에서 걸릴 수 있음.

---

## 결론: 우선순위

1. **GAP-4 수정** (HIDDEN_SSID → NOT_IN_USE): 가장 간단하고 영향 큼
2. **GAP-1~3 수정** (beacon_ies/proberesp_ies/assocresp_ies 추가): Extended Capabilities IE
3. tail에 extended rates 추가 (선택)

## 다음: B3 gap 분석 완료 → B4 패치 구현
