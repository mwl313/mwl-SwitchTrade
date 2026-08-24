# 14 — 하드웨어 호환성 매트릭스 & 확장 가능한 카드 지원 구조 (2026-08-24)

> 결정: 주인님 — "rtl8188eus AP 실험(🅑안) 폐기. 대신 UI에서 하드웨어 체크로 호스트/게스트 가능 여부를 표시하고, 호환 안 되면 둘 다 불가 표시. 여러 하드웨어 추가 가능한 확장 구조로."
> 최종 빌드: WSL2 프로그램 (docs/06-distribution.md 길 A, docs/12-wsl2-poc-windows.md)
> 배경 실측: VMware에서는 8192EU=AP 노출 ✅ / 8188EU=AP 미노출 ❌. WSL USB/IP 호환성은
> 별도 축이며 2026-08-24 현재 8192EU G2~G4+30분 soak ✅ / 8188EU mainline G2 ❌,
> patched pinned vendor driver guest/relay G2~G4 + 5분 soak ✅이다.

> **2026-08-25 production correction:** later real guest tests showed that the patched 8188EU can
> receive/decode the room but cannot complete Nintendo's custom nl80211 control-port association
> (`EINVAL`), and AP+monitor can deadlock. It is quarantined from every beta role. RTL8192EU is the
> sole beta candidate; a second matching card will be used for symmetric testing on 2026-08-26.

---

## 1. 역할 정의

| 역할 | 무엇을 하는가 | 필요 무선 기능 |
|---|---|---|
| **HOST** (방 개설) | 브리지가 LDN 방을 직접 브로드캐스트 → 스위치가 검색해서 조인 | **AP 모드** + monitor |
| **GUEST** (조인) | 스위치가 연 방에 브리지가 EMU로 조인 (트랙 A) 또는 프레임 중계 (트랙 B) | station(조인 시) or monitor만(트랙 B) |
| **불가** | 두 역할 모두 불가 — 해당 하드웨어 미지원 | — |

## 2. 카드 매트릭스 v1 (실측 기반)

| USB ID | 칩셋 | 백엔드/드라이버 | HOST | GUEST | 근거 |
|---|---|---|---|---|---|
| `0bda:818b` | RTL8192EU | VMware/rtl8xxxu | ✅ | ✅ | AP 노출, LDN join 실증(T1/T3) |
| `0bda:818b` | RTL8192EU | WSL USB-IP/rtl8xxxu | ✅ room-open | ✅ | monitor RX/TX G4 + AP/monitor/TAP/FRLG room-ready. 실제 Switch join은 G6 잔여 |
| `0bda:8179` | RTL8188EU | VMware/rtl8xxxu | ❌ | ✅ | AP 미노출, LDN join·monitor RX 실증(T3) |
| `0bda:8179` | RTL8188EU | WSL USB-IP/rtl8xxxu | ❌ | ❌ | firmware MCU start `-11`, interface 생성 전 G2 FAIL |
| `0bda:8179` | RTL8188EU | WSL USB-IP/patched vendor 8188eu | ❌ | ❌ beta quarantine | room RX/decode PASS; custom control-port connect `EINVAL`; AP+monitor deadlock |
| `0e8d:7610` 등 | MT7610U | mt76x0u (인커널) | 🔍 후보 | 🔍 후보 | upstream ALFA AWUS036ACHM reliability high; WSL/role 미실측 |
| PCIe ID varies | RTL8821CE | rtw88_8821ce | 🔍 후보 | 🔍 후보 | upstream reliability high; PCIe evidence는 WSL USB-IP 증거가 아님 |
| PCIe ID varies | AMD RZ616 | mt7921e | ❓ | ❓ | upstream reliability low; 진단 후보 only |
| `0bda:c811` 등 | RTL8821CU | rtw88_8821cu | ❓ 미확인 | ❓ 미확인 | USB 변형 및 USB-IP 별도 검증 필요 |
| Intel AX 계열 | — | iwlwifi | ❌ | ❌ | 원작자 README: 동작 안 함 (공식 기록) |
| Atheros AR9271 | — | ath9k_htc | ❓ | ❌ 대체로 불가 | 원작자 README |

**원칙**: 같은 USB ID라도 VMware/native/WSL USB-IP 결과는 합치지 않는다. 해당 backend에서
검증된 것만 ✅로 표시하고, 추정은 🔍/❓로 명시한다.

## 3. 구현된 확장 구조

단일 runtime 진실 공급원은 `config/wsl-radio-hardware.tsv`다. 각 행은 USB ID, driver 전략,
모듈 파일, 허용 driver, 역할, 검증 상태를 가진다. `scripts/wsl-radio-prepare.sh`는 다음을 한 번에
fail-closed로 수행한다.

1. 둘 이상의 지원 카드가 있으면 `--usb-id` 없이는 선택하지 않는다.
2. vanilla interface를 우선 확인하고, profile이 허용할 때만 exact-kernel 외부 모듈을 로드한다.
3. 외부 모듈의 `vermagic`와 선택적 SHA256 sidecar를 검사한다.
4. 실제 bound driver가 profile 허용 목록에 있는지, 요청 역할(`host/guest/relay`)이 허용되는지 검사한다.
5. `radio-health-gate.sh`로 실제 802.11 RX를 확인한 뒤에만 command를 `exec`한다.
6. 선택한 interface와 USB ID를 `SWITCHTRADE_IFACE`, `SWITCHTRADE_USB_ID`로 앱에 전달한다.

`frlgtrade.py`도 이 선택값을 우선하므로 새 profile USB ID를 추가할 때 Python 상수까지 다시
편집할 필요가 없다. `run_trade.sh v7`은 WSL에서 selector를 자동 사용하며 8188EU를 host로 요청하면
실행 전에 거부한다.

### 새 카드 추가 절차

1. USB ID/driver를 확인하고 profile 행을 `candidate`로 추가한다.
2. in-kernel driver면 kernel build의 `extra_kernel_config`와 필요 시 `extra_firmware`를 지정한다.
3. out-of-tree driver면 source commit+local patch를 고정해 exact kernel module을 재현 빌드한다.
4. G2 interface, G3 actual RX, G4 외부 RX/TX, 30분 soak, 역할별 실기를 통과시킨다.
5. 통과한 역할만 profile에 열고 상태를 `verified`로 올린다.

## 4. UI 표시 규격 (WSL2 프로그램용 — 최종 빌드 요구사항)

```
[카드 감지됨] Realtek RTL8192EU (0bda:818b) / WSL USB-IP
  ├─ 방 개설(HOST): ✅ 가능
  └─ 참가(GUEST):   ✅ 가능

[카드 감지됨] Realtek RTL8188EU (0bda:8179) / WSL USB-IP / vendor 8188eu
  ├─ 방 개설(HOST): ❌ 불가
  └─ 참가/중계(GUEST/RELAY): ❌ beta 불가
  ℹ 관찰용 RX/decode만 허용됩니다.
  ℹ Nintendo custom control-port association이 실패하고 AP+monitor가 deadlock할 수 있습니다.

[알 수 없는 카드] (0bda:xxxx)
  ⚠ 이 카드는 아직 검증 목록에 없습니다 — 호스트/참가 모두 불가로 표시됩니다.
```

규칙:
- host_capable=False → HOST 버튼 비활성화 + 안내 문구 (대안 카드 제시)
- 둘 다 False 또는 미등록 → "이 하드웨어는 지원되지 않습니다" 표시
- WSL runtime 판정은 TSV profile이 단일 진실 공급원 — UI는 같은 profile을 읽는다

## 5. 관련 결정 이력

| 날짜 | 결정 |
|---|---|
| 2026-08-24 | patched 8188EU warning-free guest/relay 검증. 단독 AP는 PASS지만 AP+monitor cfg80211 deadlock 실측으로 host 차단 근거 갱신 |
| 2026-08-24 | 실제 TSV profile+selector 구현. driver/vermagic/SHA/RX/role 검사를 command 앞에 강제 |
| 2026-08-24 | 8188EU vendor driver를 WSL guest/relay로 승격 |
| 2026-08-24 | 호환성 key를 USB ID만이 아니라 backend+driver까지 확장. 8188EU는 VM guest ✅지만 WSL mainline ❌ |
| 2026-08-22 | 🅑안(rtl8188eus out-of-tree AP 실험) **폐기** — 과거 hang 4회 이력 + 🅐 역할 재배치로 충분 + 최종 빌드는 WSL2라 드라이버 실험의 이득이 제한적 |
| 2026-08-22 | 대신 **하드웨어 체크 UI + 확장 레지스트리** 채택 (본 문서) |
| 2026-08-21 | 카드 교체 제안 금지 유지 (주인님 강경 지시) — 본 구조는 교체가 아니라 "보유 카드로 무엇이 가능한지 알려주는" 기능 |

## 6. 구현 상태

CLI/runtime selector는 구현·실기 통과했다. UI는 STEP 13+에서 TSV profile을 그대로 읽어 같은
역할/검증 상태를 표시하면 된다. WSL 실제 Switch G5/G6 전에는 `production-verified` 표기를 쓰지 않는다.

---
*작성: 아리아 | WSL/USB-IP 실측 갱신: Codex 2026-08-24*
