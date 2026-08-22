# 배포 전략 — 리눅스 레이어 분석과 사용자 배포 경로

> 상태: [방향] 초안 — 2026-08-21
> 상태 태그: [확정] = 결정됨 / [방향] = 검토 필요 / [미결] = 결정 필요
>
> 이 문서는 "사용자에게 어떻게 배포할 것인가"를 다룬다. 개발/검증 환경(VMware VM + RTL8188EU 패스스루)과
> 사용자 배포 환경은 다르다 — 사용자는 VM을 받아서 쓸 수 없다는 전제에서 출발한다.

---

## 1. [확정] 사용자 배포 요구사항

| 요구사항 | 내용 |
|---|---|
| 기존 OS 유지 | 사용자가 쓰는 Windows/macOS를 끄거나 교체하지 않는다 |
| 재부팅 없음 | 최초 1회 설정 이후, 사용 중 OS를 재부팅하지 않는다 |
| 준비물 최소화 | 하드웨어 준비물은 **Wi-Fi 카드(USB 동글) 1개**만 |
| 설치 간소화 | 리눅스 콘솔/명령 입력 없이 동작해야 한다 |

---

## 2. [확정] 리눅스 의존성 분석 — 왜 리눅스가 필요한가

LDN 브리지가 사용하는 계층을 분해하면:

```
┌────────────────────────────────────────────────┐
│ ③ Python 앱 (ldn 라이브러리 + frlgsim)          │ ← OS 무관 (어디서든 실행 가능)
├────────────────────────────────────────────────┤
│ ② TAP 인터페이스 (패킷 주입)                    │ ← 리눅스 커널 전용 (CAP_NET_ADMIN)
├────────────────────────────────────────────────┤
│ ① nl80211 (모니터 모드 / AP·스테이션 조인)      │ ← 리눅스 커널 전용 (mac80211/cfg80211)
│    + Wi-Fi 드라이버 (rtl8xxxu)                 │
└────────────────────────────────────────────────┘
```

| 레이어 | 용도 | Windows/macOS 대체 |
|---|---|---|
| ① nl80211 모니터 모드 | 스위치의 raw 802.11 프레임(관리+데이터) 수신 | ❌ 없음 — Windows Native Wi-Fi API에 모니터 모드 없음 (Npcap도 미지원) |
| ① nl80211 AP/조인 | LDN 네트워크에 스테이션으로 참가 | ❌ 없음 — macOS Airport 드라이버 비공개 |
| ② TAP 인터페이스 | 복호화된 패킷 주입 | ❌ 없음 — Windows TAP은 수동 설치+드라이버 서명 문제 |
| ③ Python 앱 | ldn + frlgsim | ✅ 가능 — 단 ①②가 없으면 무선 제어 불가 |

**결론: ①과 ②가 리눅스 커널 전유물이다. "리눅스 OS 전체"가 아니라 "①+② 계층"이 필수다.**

---

## 3. [확정] "리눅스 레이어 제거" 판정

- **Windows/macOS 네이티브 앱으로 실행: 불가능.** raw 802.11 프레임 접근 자체가 OS에 없음.
- **WSL2 기본 상태: 불가능.** WSL2 커널에 Wi-Fi 드라이버(rtl8xxxu) 미포함, 가상 NIC만 노출.
- **Docker Desktop: 불가능.** 가상 NIC만 노출, raw 프레임 접근 없음.
- **가능한 유일한 방향: "리눅스의 필요한 계층만 가져오기"** — 아래 4절.

---

## 4. [방향] "리눅스 레이어만 가져오는" 3가지 길

### 길 A: WSL2 커스텀 커널 — 커널 레이어만 (현실적, PoC 대상) ⭐

WSL2는 "리눅스 OS가 아니라 **리눅스 커널만** Windows 위에서" 실행하는 기술.
Windows는 그대로 유지, 최초 1회 재부팅(기능 활성화)만 필요.

**필요한 것 2가지 (둘 다 우리가 패키징):**

1. **USB 패스스루**: `usbipd-win`으로 RTL8188EU 동글을 WSL2에 attach
   → 리눅스 커널이 카드를 직접 제어 (우리 VM의 USB 패스스루와 같은 원리)
2. **커스텀 WSL2 커널**: 기본 커널에 rtl8xxxu/cfg80211/mac80211 없음
   → **우리가 rtl8xxxu 포함 커널 빌드** 후 배포 (사용자는 파일 1개 교체 + .wslconfig)

**성공 시 사용자 플로우:**
```
스크립트 1번 실행(설치) → 동글 꽂기 → 실행
```
준비물 = Wi-Fi 카드 1개. Windows 앱처럼 보임.

**리스크:**
- Hyper-V 활성화 필요 — 일부 가상화 도구(VMware/VirtualBox)와 충돌 가능 (VMware 15.5+는 공존 가능, 성능 패널티)
- WSL2 커널은 우리 검증 환경(VMware VM)과 다른 경로 → **PoC 실기 검증 필수**
- 커스텀 커널 빌드 유지보수 부담 (우리 관리)

**검증 포인트 (PoC 체크리스트):**
- [ ] WSL2 커스텀 커널 빌드 (rtl8xxxu + cfg80211 + mac80211 + tun 포함)
- [ ] usbipd-win으로 RTL8188EU attach → `lsusb`/`dmesg`에서 카드 인식
- [ ] `iw dev` / `iw phy`에서 모니터 모드 지원 확인
- [ ] ldn 스캔 → 스위치 광고 검출 (found 1)
- [ ] assoc 성공 → 트레이드 1회 (워크플로우 v1 재현)

### 길 B: 사용자 공간 드라이버 포팅 — 이론 가능, 비현실적

RTL8188EU는 USB 칩이라 libusb로 직접 제어하는 사용자 공간 드라이버를 만들면
리눅스 커널 없이도 카드를 제어할 수 있음 (macOS Nexmon이 유사 접근).
단, 802.11 MAC 처리 + AES 암호화 + 펌웨어 로딩을 전부 재구현해야 함.

| 항목 | 평가 |
|---|---|
| 리눅스 잔존 | 0 (완전 제거) |
| 개발 노력 | 수개월 ~ 1년+ |
| 판정 | ❌ 프로젝트 규모 대비 비현실적 |

### 길 C: 무선 계층을 MCU로 대체 (ESP32) — 궁극의 리눅스 제거 (장기)

ESP32 (Wi-Fi 내장 MCU, ~5천원)에 LDN 무선 계층을 펌웨어로 이식:

```
[Switch] ←무선→ [ESP32 동글] ←USB→ [PC 앱 (Windows/macOS 그대로)]
```

- 리눅스가 **완전히 제거**됨
- PC 앱 = frlgsim 게임 로직만 (Python, OS 무관)
- ESP32는 2.4GHz promiscuous/AP/STA 모드 지원 — LDN(고정 패스프레이즈 + AES-CCMP) 처리 가능성 있음
- 단, LDN 프로토콜 펌웨어 재구현 = **수개월 작업** → 장기 목표

---

## 5. [방향] 배포 경로 비교

| 길 | 리눅스 잔존 | 개발 노력 | 사용자 준비물 | 사용자 OS 영향 | 시기 |
|---|---|---|---|---|---|
| **A. WSL2 커스텀 커널** ⭐ | 커널만 | 1~2주 (빌드+PoC) | 카드 1개 | Windows 유지, 최초 1회 재부팅 | **지금 PoC 가능** |
| B. 사용자 공간 드라이버 | 0 | 수개월~1년+ | 카드 1개 | 영향 없음 | 비현실적 |
| C. ESP32 펌웨어 | **0** | 수개월 | ESP32(카드 대체) | 영향 없음 | 장기 목표 |
| (참고) VirtualBox OVA | 전체 VM | 낮음 | 카드 1개 + VirtualBox | Windows/macOS 유지 | 가능하나 "VM 받기" 부담 |
| (참고) RPi 브리지 박스 | 전체 OS (은닉) | 중 | 박스 1개 | 영향 없음 | 카드 1개 조건 불충족 |

**권장 경로: A(WSL2 커스텀 커널)를 PoC로 검증 → 성공 시 배포 1차안으로 채택.
C(ESP32)는 중장기 목표로 유지 — A가 동작하는 동안 병행 리서치.**

---

## 6. [확정] 리서치 결과 — WSL2 경로 실증 선례 확인 (2026-08-22)

### 6.1 결정적 발견: WSL2 + rtl8xxxu 모니터 모드 동작 선례 존재

**출처**: seanhungtw/usb-wifi_monitor-mode_on_WSL2 (GitHub, 2024) + usbipd-win issue #390

| 검증 항목 | 결과 | 우리 프로젝트와의 관계 |
|---|---|---|
| **rtl8192eu → rtl8xxxu 드라이버 → WSL2 모니터 모드** | ✅ 동작 (dmesg 실측 로그 포함) | **우리 8188EU와 동일 드라이버 경로** — 8188EU도 rtl8xxxu가 담당 |
| MT7921au (mt7921u) | ✅ 동작 (5.18에서 드라이버 포팅 필요) | 원작자 README 테스트 카드 RZ616과 같은 계열 |
| 커스텀 커널 빌드 절차 | 문서화 완료 (Microsoft/config-wsl 기반 menuconfig) | CONFIG_MAC80211=m / CFG80211=m / RTL8XXXU=m |
| 펌웨어 로딩 트릭 | ✅ 확보 — 커널 소스에 펌웨어 복사 + `CONFIG_EXTRA_FIRMWARE` 내장 (usbipd-win #390 코멘트) | rtl8xxxu는 펌웨어를 커널 빌드에 내장 가능 → 배포 이미지 단순화 |
| usbipd-win attach | ✅ Microsoft 공식 지원 (커널 ≥ 5.10.60.1) | Windows 측 설치 1회 |
| iw 모니터 전환 | ✅ `iw dev wlan0 set monitor none` + 채널 설정 | run_trade.sh의 down→set type monitor→up 순서와 동일 |

**해석**: "WSL2에서 무선 브리지"는 이론이 아니라 **이미 실증된 경로**. 우리의 미검증 부분은
①8188EU 특유의 수신 사망/IQK 이슈가 usbipd 경로에서 어떻게 나오는가 ②ldn 라이브러리의 AP join(스테이션 assoc)이
WSL2 가상화 환경에서 통과하는가 ③TX 인젝션(framerelay 필수)이다.

### 6.2 커널 구성 요구사항 (PoC 빌드 스펙)

| CONFIG | 값 | 용도 |
|---|---|---|
| CONFIG_CFG80211 / MAC80211 | =m | nl80211 스택 (ldn 라이브러리 의존) |
| CONFIG_RTL8XXXU | =m (+UNTESTED 옵션 확인) | 8188EU/8192EU 공용 드라이버 |
| CONFIG_TUN | =m | TAP 인터페이스 (LiveTransport 패킷 주입) — WSL2 기본 커널에 없음, 커스텀 빌드에서 추가 |
| CONFIG_USB_USBNET / USBIP_VHCI | =m/y | usbipd 클라이언트 측 |
| CONFIG_EXTRA_FIRMWARE | rtlwifi 펌웨어 내장 | 펌웨어 파일 배포 불필요하게 만드는 트릭 |

빌드 환경: microsoft/WSL2-Linux-Kernel 클론 → `cp Microsoft/config-wsl .config` → menuconfig → bzImage.
배포물 = bzImage 1개(+모듈) + .wslconfig 2줄. 사용자 설치는 스크립트 1번.

### 6.3 환경 차이 리스크 (VM 대비)

| 항목 | VMware VM (현재 검증됨) | WSL2 (PoC 대상) |
|---|---|---|
| USB 경로 | VMware 패스스루 (직접) | usbipd-win (TCP/IP-over-Hyper-V 소켓 — 지연·타이밍 다름) |
| NM | 있음 → unmanaged conf 필수 | 기본 없음(systemd on 시 설치 가능) — EBUSY 클래스 문제 자체가 안 생길 가능성 |
| udev rename | wlx<MAC> 발생 | 동일 발생 (커널 레벨) — vif 정리 로직 영향 없음 |
| 카드 수신 사망(IQK/절전) | Windows 절전이 원인 중 하나 | **Windows 호스트 그대로라 절전 변수 유지** — powercfg 예방 설정 여전히 필요 |
| ldn.scan hang | trio 타임아웃 무력화 실측 | 미지수 — PoC에서 timeout 래퍼(D-1) 선행 적용 후 테스트 |

---

## 7. [방향] 두 트랙과 배포 전략의 접점 (브레인스토밍)

### 7.1 트랙별 배포 요구사항 차이

| 요소 | 트랙 A (EMU 리더-리더) | 트랙 B (framerelay 자연 통신) |
|---|---|---|
| 필요한 무선 동작 | 모니터 RX + AP join (스테이션 assoc) + UDP 데이터 | 모니터 RX + **TX 인젝션(radiotap)** |
| 게임 해석 | frlgsim 필요 | 불필요 (프레임 통째 중계) |
| ACK 타이밍 민감도 | 낮음 (게임 레벨 재시도) | **높음 (SIFS ACK → 인터넷 왕복 문제, §4 실측 대상)** |
| WSL2 영향 | usbipd 지연이 assoc/데이터에 영향 가능 | usbipd 지연 + TX 인젝션 성공 여부가 **이중 리스크** |

**브레인스토밍 결론 1**: WSL2 PoC는 **트랙 A 기준으로 먼저** 하는 게 맞아요.
트랙 A는 이미 VM에서 실기 트레이드 성공 이력이 있어서 "WSL2 환경 차이"만 분리 측정 가능.
트랙 B는 ACK 타이밍이라는 독자 리스크가 있어서, VM 실측(2대 준비되면)과 WSL2 검증을 섞으면 원인 분리가 어려워져요.

**브레인스토밍 결론 2**: 배포 이미지는 **두 트랙 공통 하부**로 만든다.
커널(bzImage)+드라이버+펌웨어+usbipd 세팅은 동일하고, 위에 얹는 앱만 달라짐:
```
공통 하부: Windows + usbipd-win + WSL2(Ubuntu) + 커스텀 bzImage + ldnvenv
  ├─ 트랙 A 앱: emu/frlgtrade.py (--relay-url ...)
  └─ 트랙 B 앱: framerelay/bridge.py (나중)
```
즉 WSL2 PoC가 성공하면 **한 번의 검증으로 두 트랙 모두의 배포 기반이 완성**돼요.

**브레인스토밍 결론 3**: 릴레이 서버 위치와 무관.
relay/server.py는 어차피 Mac mini/클라우드에서 돌고, WSL2 브리지는 WSS 클라이언트만 하므로
배포 전략은 릴레이 아키텍처 변경을 유발하지 않아요.

### 7.2 PoC 실행 순서 제안 (코드 수정 전 문서 작업)

1. [문서] WSL2 PoC 절차 문서 작성 — 커널 빌드 스크립트 + usbipd 명령 + .wslconfig + 검증 체크리스트 (§6.2 스펙 기준)
2. [Windows] PoC-1: 커스텀 커널 부팅 확인 (uname -a)
3. [Windows] PoC-2: 8188EU attach → lsusb/dmesg → modprobe rtl8xxxu → iw phy (monitor 지원)
4. [Windows] PoC-3: 스캔 found 1 (스위치 리더 광고) — **timeout 래핑 필수**
5. [Windows] PoC-4: 트랙 A 트레이드 1회 (VM 워크플로우 v1 재현)
6. 판정: 성공 → 배포 1차안 = WSL2 확정 / 실패 → VirtualBox OVA 폴백 (§5 표)

> 참고: 이 문서의 "배포"는 Phase 2c(인터넷 브리지) 완료 이후 최종 사용자 대상. 현재는 설계 단계.
> 코드 수정/신규 작성 없음 — 본 섹션은 리서치·설계만 포함 (2026-08-22).

---

## 8. [확정] 배포 방향 최종 결정 (2026-08-22 업데이트 — 프로덕션 트랙 framerelay 기반)

| 항목 | 결정 |
|---|---|
| 프로덕션 트랙 | **framerelay (트랙 B, 투명 중계)** — 2026-08-22 방향 전환. EMU는 검증·폴백 트랙 |
| 웹앱 배포 | ❌ 포기 — 브라우저 무선 제어 불가 + LDN 근접성 물리 벽 |
| **1차** | **Windows — WSL2 커스텀 커널 경로** (framerelay 기준 게이트) |
| 2차 | macOS — **Windows PoC 성공 시에만 착수** (UTM/Fusion 헤드리스 VM) |
| 폴백 | VirtualBox OVA |

- PoC 실행 절차·게이트(G1~G6)·패키징 계획: **`docs/12-wsl2-poc-windows.md`** — framerelay 기준 개정판
- framerelay 구조/로드맵: `docs/12-framerelay-구조와-로드맵.md` (PoC는 그 STEP 16)
- **framerelay 배포 특이점**:
  - 무선 요구 = 모니터 RX + TX 인젝션(radiotap 8B) — AP 조인/TAP 불필요 → WSL2 커널 CONFIG 단순화
  - 최대 신규 리스크 = SIFS ACK × 릴레이 왕복 + usbipd 지연 가산 (EMU의 assoc 리스크와 대체)
  - 카드 매트릭스: 베이스 모드 = 8188EU/8192EU 모두 OK / 호스트 모드 = **8192EU 필수**(AP 지원, 8/22 실측)
  - 배포 번들에서 frlgsim 제외 가능 (게임 해석 없음 — 프레임 통째 중계)
