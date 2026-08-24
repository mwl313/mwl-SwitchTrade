# 08 — 드라이버 매니저 설계 (칩셋 자동 감지 → 적절한 드라이버 로드)

> **2026-08-25 정정:** 이 문서의 8188EU WSL guest 지원 주장은 후속 실기에서 기각됐다.
> patched vendor driver는 광고 수신/해석은 가능하지만 Nintendo custom control-port association이
> `EINVAL`로 실패하고 AP+monitor도 deadlock한다. 프로덕션 베타는 RTL8192EU만 후보이며 현재 계획은
> `docs/49-production-beta-priorities-20260825.md`가 우선한다.

> 작성: 2026-08-21 | 목표: **어떤 Wi-Fi 카드를 꽂든 자동으로 작동**하게 하는 배포용 호환 레이어
> 원칙: 원래 드라이버의 프로토콜을 덮어쓰지 않는다. 칩셋별 **올바른 드라이버**를 골라 로드한다.

## 배경

- rtl8xxxu(인커널)로 8188EU/8192EU **모두 LDN join 검증 완료**. 초기 8192EU 실패(assoc 성공 → 100ms 내 deauth)는 드라이버 문제가 아니라 **stale 상태 문제**였음 — 재부팅 후 깨끗한 상태에서 완전한 트레이드 세션 성공 (2026-08-21 재검증, `docs/07-2b-테스트-실측-20260821.md` ⭐ 섹션). out-of-tree 드라이버 불필요
- 칩셋마다 리눅스 드라이버 구현 상태가 다르므로, **칩셋 판별 → 올바른 드라이버**가 정답 (현재는 전부 rtl8xxxu 단일 경로)
- 사용자는 어떤 카드를 꽂아도 동작하기를 원함 (범용 배포 목적)

## 칩셋 매핑 테이블 (v1)

| USB ID | 칩셋 | 드라이버 | 출처 | 상태 |
|---|---|---|---|---|
| `0bda:8179` | RTL8188EU | `rtl8xxxu` | 인커널 | ✅ LDN join 검증 완료 |
| `0bda:818b` | RTL8192EU | `rtl8xxxu` | 인커널 | ✅ LDN join 검증 완료 (2026-08-21 재검증 — out-of-tree 불필요) |
| `0e8d:7610` 등 | MT7610U | `mt76x0u` | 인커널 | ✅ 원작자 검증 (ALFA AWUS036ACHM, high) |
| PCIe ID varies | RTL8821CE | `rtw88_8821ce` | 인커널 | ✅ 원작자 검증 (high; WSL USB-IP와 별개) |
| PCIe ID varies | AMD RZ616 | `mt7921e` | 인커널 | 🟡 원작자 low reliability |
| `0bda:c811` 등 | RTL8821CU | `rtw88` (usb) | 인커널 | ❓ 후보 |
| 그 외 | — | 인커널 드라이버 우선 → 실패 시 out-of-tree | — | — |

## 스크립트 구조 (install-driver.sh)

```
1. 감지: lsusb에서 Wi-Fi 어댑터 USB ID 수집 (Realtek 0bda / MediaTek 0e8d 등)
2. 판별: 매핑 테이블 조회 → 드라이버 결정
3. 준비: 
   - 충돌 드라이버 언로드/블랙리스트 (예: 8192EU 쓰려면 rtl8xxxu 언로드)
   - out-of-tree면 dkms 빌드 (커널 헤더 확인 → 실패 시 안내)
4. 로드: modprobe <드라이버> → 인터페이스 생성 확인 (iw dev)
5. 검증: 모니터 모드 전환 → 비콘 수신 확인 → (선택) LDN 스캔
6. 실패 시: 다음 후보 드라이버로 재시도 + 로그 저장
```

## LDN 실행 전 준비 (드라이버와 무관한 공통 절차 — 실측 확정)

1. **phy 감지**: `iw phy | grep Wiphy` — USB 리셋마다 번호 증가 (phy0→1→2)
2. **기존 wlx/ldn vif 삭제**: `iw dev <iface> del` — rtl8xxxu 계열은 phy당 vif 1개 제한 (실측: `Match already configured`/EBUSY 방지)
3. **NM에서 카드 제외**: `nmcli device set <iface> managed no` (즉시) 또는 unmanaged conf (재부팅) — EBUSY 방지
   - 영구화(카드 교체 면역): `sudo scripts/setup-nm-unmanaged.sh` 실행 후 **재부팅** — reload/restart 절대 금지 (VM 네트워크 사망)
4. **채널 고정**: 실행 전 스캔으로 스위치 광고 채널 확인 (1/6/11)

## 현재 검증 상태 (2026-08-21)

- [x] 8188EU + rtl8xxxu → host/guest LDN join 성공 (로컬 트레이드 2회 + 2b host)
- [ ] 8192EU + rtl8192eu-linux → 빌드 후 join 검증 (진행 중)
- [ ] 칩셋 감지 스크립트 자동화
- [ ] 2b 본 테스트 (릴레이 경유 양방향)

## 배포 관점

- 사용자 설치는 `install-driver.sh` 한 번 실행 → 카드 꽂으면 자동 인식
- 지원 칩셋 매트릭스를 README에 명시 (beta는 8192EU; 향후 MT7610U/RTL8821CE/RZ616 검증)
- 드라이버는 DKMS로 커널 업데이트에도 유지
