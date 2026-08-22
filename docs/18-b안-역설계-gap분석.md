# 18 — B안 역설계: hostapd nl80211 시퀀스 분석 & ldn 패치 설계 (2026-08-22)

> 작성: 아리아 | B1 로그: logs/2026-08-22/b1_hostapd_full.log (197줄, -dd 전체 덤프)
> 목적: ldn create_network의 START_AP가 beaconing을 시작하지 않는 원인을
>        hostapd의 실제 nl80211 시퀀스와 바이트 단위 비교로 특정하고 패치

---

## 1. B1 실측 결과 — 결정적 발견

hostapd는 같은 카드(8192EU)에서 **정상적으로 Beacon을 송출**함:
- VM2 passive 캡처: MWLTEST Beacon **142개/20초** (=100ms 간격 정상)
- signal -31~-33dBm

ldn START_AP 후:
- VM2 스캔: BSS a047이 **Probe Response로만** 나타남 (Beacon frame 0)
- mon0 캡처: 자기 Beacon **0개**
- 스위치 A 방 검색 리스트: ❌ 못 찾음 (passive scan이라 Beacon 필요)

→ **START_AP는 성공하지만 rtl8xxxu 드라이버가 periodic beaconing을 시작하지 않음**

## 2. GAP 분석 — ldn _start_ap vs hostapd 차이

### 🔴 CRITICAL GAP (원인으로 유력)

| # | 항목 | hostapd | ldn | 영향 |
|---|---|---|---|---|
| **G1** | BEACON_HEAD IEs | ✅ SSID IE + rates IE + DS IE 포함 (58B) | ❌ **IEs 전부 없음** (36B) | 커널/driver가 beacon frame을 불완전하다고 판단해 송출 안 함 |
| **G2** | HIDDEN_SSID | `not in use` | `NL80211_HIDDEN_SSID_ZERO_CONTENTS` ← **hidden 모드!** | hidden SSID = probe response에만 SSID 포함, beacon에는 SSID 필드 생략 → 스위치가 SSID 매칭 실패 |
| **G3** | BEACON_TAIL | 23B (extended rates + extended capabilities) | `b""` 빈 값 | tail 없이는 HT capability 등이 누락되어 일부 클라이언트가 거부 |
| **G4** | beacon_ies/proberesp_ies | 10B Extended Capabilities IE | ❌ 없음 | probe response에 확장 기능 정보 없음 |

### 🟡 HIGH GAP (동작에 영향 가능)

| # | 항목 | hostapd | ldn |
|---|---|---|---|
| H1 | 실행 순서 | Set freq → flush → Set beacon | START_AP 한 번에 모든 것 포함 |
| H2 | DEL_STATION flush | ✅ 시작 전 flush | ❌ 없음 |
| H3 | operstate UP 명시 설정 | ✅ | ❌ (인터페이스 up은 하지만 operstate 설정 안 함) |

## 3. 패치 설계 — `_start_ap` 수정

### 수정 대상: ldn wlan.py `_start_ap` 메서드 (wlan.py:1572)

패치를 frlgsim/transport.py의 monkey-patch로 구현 (ldn 원본 수정 없음):

```python
# install_beacon_head_override() 확장 버전
def install_start_ap_fix(log=print) -> bool:
    """AccessPoint._start_ap를 래핑해서:
    1. BEACON_HEAD에 SSID IE + rates IE + DS params IE 추가
    2. BEACON_TAIL에 extended rates + ext capabilities 추가  
    3. HIDDEN_SSID를 NOT_IN_USE로 변경
    4. beacon_ies/proberesp_ies/assocresp_ies attrs 추가"""
```

### 구체적 수정 내용

```python
# 1. BEACON_HEAD 재조립 (기존 install_beacon_head_override에서 이미 구현)
head = _build_host_beacon_head(ssid, channel, bssid)

# 2. BEACON_TAIL 생성 (hostapd와 동일한 extended rates + capabilities)
tail = bytes.fromhex("2a010432043048606c3b0251" + "00" + "7f08040000020000000040")

# 3. HIDDEN_SSID 제거
attrs.pop(nl80211.NL80211_ATTR_HIDDEN_SSID, None)

# 4. IEs 추가
ext_cap_ie = bytes.fromhex("7f08040000020000000040")
attrs[nl80211.NL80211_ATTR_BEACON_IES] = ext_cap_ie
attrs[nl80211.NL80211_ATTR_PROBE_RESP_IEs] = ext_cap_ie  # 이름 확인 필요
attrs[nl80211.NL80211_ATTR_ASSOC_RESP_IEs] = ext_cap_ie  # 이름 확인 필요
```

## 4. 구현 계획

| 순서 | 작업 | 파일 |
|---|---|---|
| 1 | `install_start_ap_fix()` 함수 작성 — `_start_ap` 래핑 | transport.py |
| 2 | 기존 `install_beacon_head_override` 통합 (중복 제거) | transport.py |
| 3 | 오프라인 테스트 (스텁으로 attrs 검증) | test_beacon_head.py 확장 |
| 4 | VM1 배포 → host 기동 → mon0에서 Beacon 수신 확인 | VM1 |
| 5 | VM2 스캔 found ≥1 확인 | VM2 |

## 5. 리스크

- NL80211_ATTR_PROBE_RESP_IEs / ASSOC_RESP_IEs의 정확한 상수명 확인 필요
- HIDDEN_SSID 제거 시 스위치의 hidden SSID 처리 동작 변화 가능성 (낮음)
- BEACON_TAIL 형식이 hostapd와 완전히 동일해야 하는지 (일부 IE만으로도 충분할 수 있음)
