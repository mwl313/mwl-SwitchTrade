# ldn 업스트림 기여 초안 — ConnectNetworkParam에 bssid 필드 추가 (2026-08-22)

> 작성: 옥스 알파 (opencode, WP-H) | 상태: **초안 — 네트워크 허용 시 PR용** (현 제약: push 금지)
> 대상: [kinnay/LDN](https://github.com/Kinnay/NintendoClients) 계열 ldn 패키지 **0.0.17**
> 로컬 참조 스냅샷: `docs/research/ldn-0.0.17-src/` (행 번호는 이 스냅샷 기준)
> 관련: Audit 이슈 I-7 (`docs/09-testing-audit-20260821.md`), C-4 재구현 (emu `e91c6ac`)

## 1. 동기 — I-7 오접속 (실측 근거)

FRLG 트레이드 브리지에서 스위치 2대가 **동일 SSID + 동일 채널**로 동시 광고되면, ldn의
스테이션 조인은 SSID+채널만 nl80211에 전달하므로 커널/cfg80211이 BSS를 자유 선택한다.
실측(docs/09 I-7): host가 "스위치 A 선택"을 지정해도 브리지가 스위치 B에 assoc 시도 →
거부(status 1). dmesg로 대상 MAC 불일치 확인. LDN 광고 프레임에는 이미 호스트 WLAN MAC이
들어 있으므로(=BSSID), 그 값을 CONNECT 요청에 `NL80211_ATTR_MAC`(BSSID 힌트)로 전달하면
된다.

## 2. 0.0.17 소스 분석 — 왜 라이브러리 밖에서 불가능한가

1. **attrs는 `_connect_network` 내부에서 로컬 생성** — `wlan.py:1289–1341`.
   `attrs` dict에 `NL80211_ATTR_SSID` / `NL80211_ATTR_WIPHY_FREQ` 등만 채우고
   `await self._wlan.request(nl80211.NL80211_CMD_CONNECT, attrs)`(`wlan.py:1336`)로 전달.
   호출자가 args/kwargs를 건드릴 진입점이 없음.
2. **스캔 결과에는 BSSID가 이미 있다** — `__init__.py:1206`(및 1329):
   `info.address = action.source` — 광고 액션 프레임의 발신 MAC = 호스트 AP의 BSSID.
   즉 `NetworkInfo.address`가 곧 BSSID인데,
3. **`connect()`가 그 값을 버린다** — `__init__.py:1943`:
   `factory.connect_network(param.phyname, param.ifname, network.ssid.hex(), network.channel, wlan_key)`
   — phy/ifname/ssid/channel/key만 전달, `network.address`는 wlan 계층까지 가지 않음.
4. `Factory.connect_network`(`wlan.py:1837`) → `Station.__init__`(`wlan.py:1214`)도
   ssid/channel/key만 저장. 조인 성공 후의 실제 BSSID는 `Station._host_address`
   (`wlan.py:1348`, CONNECT 응답의 `NL80211_ATTR_MAC`)로만 관찰 가능.

현재 워크어라운드: emu 쪽 런타임 몽키패치(emu 리포 `e91c6ac`) — `station._wlan`을 프록시로
교체해 CONNECT request에 `NL80211_ATTR_MAC`을 in-place 주입. site-packages 무수정이지만
비공개 속성 의존 + 버전 드리프트 취약. **업스트림에 필드 하나만 추가되면 패치 자체가
불필요**(transport에는 `ldn.__version__` 가드가 있어 반영 시 자동 무효화됨).

## 3. 제안 diff (0.0.17 기준)

방침: 옵트인(`bssid=None` 기본값)으로 현행 동작 완전 보존. 값은 `MACAddress | None`,
wlan 계층까지 raw bytes로만 전달해 wlan 모듈이 ldn 데이터모델을 몰라도 되게 한다.

```diff
--- a/ldn/__init__.py
+++ b/ldn/__init__.py
@@ class ConnectNetworkParam:
     network: NetworkInfo = field(default_factory=lambda: NetworkInfo(1))
     password: bytes = b""
+
+    # Optional BSSID pin for the underlying 802.11 association. When set, the
+    # NL80211 connect request carries NL80211_ATTR_MAC so the kernel associates
+    # with that exact AP instead of any BSS matching SSID+channel. Useful when
+    # multiple consoles advertise the same SSID on the same channel; the value
+    # is typically NetworkInfo.address of a scan result (= the host's WLAN MAC).
+    bssid: bytes | None = None

@@ async def connect():
     async with wlan.create_factory() as factory:
         async with factory.connect_network(
             param.phyname, param.ifname, network.ssid.hex(), network.channel,
-            wlan_key
+            wlan_key, param.bssid
         ) as interface:
```

```diff
--- a/ldn/wlan.py
+++ b/ldn/wlan.py
@@ class Factory:
     @contextlib.asynccontextmanager
     async def connect_network(
         self, phyname: str, ifname: str, ssid: str, channel: int,
-        key: bytes | None
+        key: bytes | None, bssid: bytes | None = None
     ) -> AsyncIterator[Station]:
         ...
             sta = Station(
                 self._wlan, self._router, ifname, index, address, ssid, channel,
-                key
+                key, bssid
             )

@@ class Station:
     def __init__(
         self, wlan: nl80211.NL80211, router: route.RouteController, name: str,
         index: int, address: MACAddress, ssid: str, channel: int,
-        key: bytes | None
+        key: bytes | None, bssid: bytes | None = None
     ):
         ...
         self._key = key
+        self._bssid = bssid

@@ Station._connect_network():
         attrs = {
             nl80211.NL80211_ATTR_IFINDEX: self.index(),
             nl80211.NL80211_ATTR_SSID: self._ssid.encode(),
             nl80211.NL80211_ATTR_WIPHY_FREQ: Channels[self._channel],
             ...
         }
+
+        if self._bssid is not None:
+            if len(self._bssid) != 6:
+                raise ValueError(f"Invalid BSSID: {self._bssid.hex()}")
+            attrs[nl80211.NL80211_ATTR_MAC] = self._bssid
 
         if self._key is not None:
```

### 설계 노트

- **타입**: `bytes | None`(6바이트). `MACAddress`로 받아 `bytes()` 변환하는 안도 가능하나,
  wlan 모듈이 이미 갖고 있는 타입만 쓰는 편이 의존이 얕음. `param.check()` 단계에서
  `NetworkInfo.address`와 비교 검증은 선택 사항.
- **`NL80211_ATTR_MAC` 의미**: cfg80211 connect에서 "연결 의도 BSSID" 힌트. 드라이버가
  미지원해도 SSID+채널 스캔 폴백으로 동작(cfg80211 표준 동작).
- **검증 훅**: 조인 후 `Station._host_address != self._bssid`면 즉시 예외 → 호출자 재시도,
  라는 b-lite 검증은 호출자(emulator) 쪽에 두는 것도 가능 — 응답 MAC은 이미
  `message.attributes[NL80211_ATTR_MAC]`로 공개(wlan.py:1348).
- **호환성**: 기본 `None` → attrs 변경 없음 → 기존 동작 100% 보존.

## 4. PR 전 체크리스트 (네트워크 허용 시)

1. 실기 재현·검증 먼저: 2스위치 동시 광고에서 `--target-bssid` 조인 성공 +
   dmesg assoc MAC == 대상 BSSID (플랜 §5 체크리스트 항목 5)
2. 업스트림 리포의 실제 HEAD에 rebase (본 초안은 0.0.17 스냅샷 기준 — 행 번호 drift 확인)
3. 스타일: 업스트림 코딩 컨벤션(docstring/typing) 맞춤, 테스트 추가 방식 확인
4. PR 본문: I-7 재현 절차(동일 SSID+채널 2콘솔, status 1 거부 dmesg) 첨부
