# 14 — 하드웨어 호환성 매트릭스 & 확장 가능한 카드 지원 구조 (2026-08-22)

> 결정: 주인님 — "rtl8188eus AP 실험(🅑안) 폐기. 대신 UI에서 하드웨어 체크로 호스트/게스트 가능 여부를 표시하고, 호환 안 되면 둘 다 불가 표시. 여러 하드웨어 추가 가능한 확장 구조로."
> 최종 빌드: WSL2 프로그램 (docs/06-distribution.md 길 A, docs/12-wsl2-poc-windows.md)
> 배경 실측: rtl8xxxu 드라이버 기준 8192EU=AP 노출 ✅ / 8188EU=AP 미노출 ❌ (2026-08-22 iw phy 실측)

---

## 1. 역할 정의

| 역할 | 무엇을 하는가 | 필요 무선 기능 |
|---|---|---|
| **HOST** (방 개설) | 브리지가 LDN 방을 직접 브로드캐스트 → 스위치가 검색해서 조인 | **AP 모드** + monitor |
| **GUEST** (조인) | 스위치가 연 방에 브리지가 EMU로 조인 (트랙 A) 또는 프레임 중계 (트랙 B) | station(조인 시) or monitor만(트랙 B) |
| **불가** | 두 역할 모두 불가 — 해당 하드웨어 미지원 | — |

## 2. 카드 매트릭스 v1 (실측 기반)

| USB ID | 칩셋 | 드라이버 | HOST | GUEST | 근거 |
|---|---|---|---|---|---|
| `0bda:818b` | RTL8192EU | rtl8xxxu (인커널) | ✅ | ✅ | iw phy에 AP 노출 (2026-08-22 VM1 실측), LDN join 실증(T1/T3) |
| `0bda:8179` | RTL8188EU | rtl8xxxu (인커널) | ❌ | ✅ | iw phy AP 미노출 (VM2 실측). LDN join·모니터 실증(T3) |
| `0e8d:7612` 등 | MT7612U | mt76 (인커널) | 🔍 예상 ✅ | 🔍 예상 ✅ | 원작자 README: AWUS036ACHM(mt7921e)=높음 신뢰. 미실측 — 입수 시 검증 후 갱신 |
| `0bda:c811` 등 | RTL8821CU | rtw88_8821cu | ❓ 미확인 | ❓ 미확인 | 원작자 README: RTL8821CE(PCIe)=높음. USB 변형 별도 검증 필요 |
| Intel AX 계열 | — | iwlwifi | ❌ | ❌ | 원작자 README: 동작 안 함 (공식 기록) |
| Atheros AR9271 | — | ath9k_htc | ❓ | ❌ 대체로 불가 | 원작자 README |

**원칙**: 이 표는 "검증된 것만 ✅". 추정은 🔍/❓로 명시하고, 실제 유저 하드웨어 입수 시 5분 스크립트로 검증 후 갱신한다.

## 3. 확장 가능한 구조 설계 — `hardware.py` (단일 진실 공급원)

### 3.1 데이터 구조
```python
# emu/frlgsim/hardware.py (신규 제안)

@dataclass(frozen=True)
class CardProfile:
    usb_id: str            # "0bda:818b"
    chip: str              # "RTL8192EU"
    driver_hint: str       # "rtl8xxxu"
    host_capable: bool     # AP 모드 지원 = 방 개설 가능
    guest_capable: bool    # join / frame-relay 가능
    notes: str = ""
    verified: bool = False # 실측 검증 여부 (False면 추정)

CARD_REGISTRY: dict[str, CardProfile] = {
    "0bda:818b": CardProfile("0bda:818b", "RTL8192EU", "rtl8xxxu",
                             host_capable=True, guest_capable=True,
                             notes="iw phy AP 노출 실측 2026-08-22", verified=True),
    "0bda:8179": CardProfile("0bda:8179", "RTL8188EU", "rtl8xxxu",
                             host_capable=False, guest_capable=True,
                             notes="AP 미노출; join/monitor는 실증", verified=True),
    # ... 신규 카드 = 딕셔너리 엔트리 하나 추가로 끝
}
```

### 3.2 판정 함수 (UI와 CLI 양쪽에서 사용)
```python
def detect_card() -> CardProfile | None:
    """현재 꽂힌 카드를 lsusb/sysfs에서 감지 → CardProfile 반환. 미등록이면 None."""

def capabilities(card: CardProfile) -> dict:
    """{host: bool, guest: bool} — UI 표시용. 미등록 카드는 {host: False, guest: False}
    + 'unknown' 플래그 (호환 안 됨 표시 조건)."""

def runtime_ap_check(profile: CardProfile) -> bool:
    """매트릭스가 True여도 현재 커널/드라이버 상태에서 실제 AP 가능한지 이중 확인
    (iw phy 출력 파싱). 드라이버 업데이트로 매트릭스가 바뀐 경우 잡아내는 안전망."""
```

### 3.3 새 카드 추가 절차 (확장성 핵심)
1. 카드 입수 → VM 꽂기 → `lsusb`, `iw phy`
2. `scripts/check-card.sh`(신규 제안) 실행 → 자동 리포트(AP 노출? monitor? 조인 스캔?)
3. 결과를 CARD_REGISTRY에 한 줄 추가 + verified=True 갱신
4. 끝 — UI/CLI/문서는 자동 반영

## 4. UI 표시 규격 (WSL2 프로그램용 — 최종 빌드 요구사항)

```
[카드 감지됨] Realtek RTL8192EU (0bda:818b)
  ├─ 방 개설(HOST): ✅ 가능
  └─ 참가(GUEST):   ✅ 가능

[카드 감지됨] Realtek RTL8188EU (0bda:8179)
  ├─ 방 개설(HOST): ❌ 불가 (이 카드는 참가 전용입니다)
  └─ 참가(GUEST):   ✅ 가능
  ℹ 방 개설이 필요하면 RTL8192EU 카드를 사용하세요.

[알 수 없는 카드] (0bda:xxxx)
  ⚠ 이 카드는 아직 검증 목록에 없습니다 — 호스트/참가 모두 불가로 표시됩니다.
```

규칙:
- host_capable=False → HOST 버튼 비활성화 + 안내 문구 (대안 카드 제시)
- 둘 다 False 또는 미등록 → "이 하드웨어는 지원되지 않습니다" 표시
- 매트릭스는 코드 내 레지스트리가 단일 진실 공급원 — 문서는 자동 생성 가능

## 5. 관련 결정 이력

| 날짜 | 결정 |
|---|---|
| 2026-08-22 | 🅑안(rtl8188eus out-of-tree AP 실험) **폐기** — 과거 hang 4회 이력 + 🅐 역할 재배치로 충분 + 최종 빌드는 WSL2라 드라이버 실험의 이득이 제한적 |
| 2026-08-22 | 대신 **하드웨어 체크 UI + 확장 레지스트리** 채택 (본 문서) |
| 2026-08-21 | 카드 교체 제안 금지 유지 (주인님 강경 지시) — 본 구조는 교체가 아니라 "보유 카드로 무엇이 가능한지 알려주는" 기능 |

## 6. 구현 착수 시점

STEP 13+ 프로덕션 트랙(WSL2 빌드) 진입 시 `frlgsim/hardware.py` + UI로 구현.
그 전에는 본 문서가 매트릭스의 단일 진실 공급원.

---
*작성: 아리아 | 실측: VM1(8192EU)/VM2(8188EU) iw phy 2026-08-22*
