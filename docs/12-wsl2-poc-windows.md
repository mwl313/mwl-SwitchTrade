# 12 — Windows 배포 PoC 절차서 (WSL2 × framerelay)

> 작성: 2026-08-22 | 개정: 2026-08-24 — **실기 G1~G4 + 카드별 WSL 호환성 반영**
> 상위 문서: `docs/06-distribution.md` (전략), `docs/12-framerelay-구조와-로드맵.md` (framerelay 로드맵 — 이 문서는 그 STEP 16의 실행 절차서)

### 2026-08-24 현재 실측 상태

- G1 통과: `6.6.123.2`와 `6.18.35.2-microsoft-standard-WSL2+` 빌드·부팅·모듈 검증 완료.
  두 빌드 모두 Realtek firmware와 regulatory DB/signature가 내장돼 기존 `-2` 오류가 없다.
- **RTL8188EU(0bda:8179)는 WSL G2 실패**: 6.6.87.2, 6.6.123.2, 6.18.35.2에서 USB 열거와
  firmware 파일 로드는 성공하지만 약 3.6초 후 MCU ready handshake가 `-11`로 끝난다. `iw`
  interface가 생기기 전 실패하므로 NetworkManager, monitor mode, RX death 문제가 아니다.
- **RTL8192EU(0bda:818b)는 같은 WSL/USB-IP에서 G2, ambient G3, 외부 RF G4 통과**: monitor mode,
  1~13 전체 채널 설정, health gate 통과. CH1/6/11 5초 pcap에서 각각 109/53/3 frames,
  kernel drop 0을 확인했다(`logs/wsl/g3-8192eu-ch*.pcap`).
- G4는 VM2/RTL8188EU 외부 수신기로 WSL/RTL8192EU 주입을 재캡처했다. CH6 10 Hz 표본에서
  30개 중 28개(93.3%), 100개 중 90개(90.0%)를 unique frame으로 수신했고, 재캡처된 802.11
  payload는 전부 byte-exact였다. 단일 카드 self-capture가 아니라 실제 RF 송신을 증명했다.
- 결론: WSL 경로 자체는 동작한다. **mainline `rtl8xxxu` + USB/IP에서 8188EU만 비호환**이지만
  pinned vendor `8188eu`는 monitor RX와 양방향 외부 TX G4를 통과했다. 8192EU는 전 역할,
  8188EU는 guest/relay profile로 사용한다. 실제 Switch G5/G6 전에는 production 완료로 부르지 않는다.

## 0. [확정] 결정 사항

| 항목 | 결정 |
|---|---|
| 프로덕션 트랙 | **framerelay (트랙 B, 투명 중계)** — 2026-08-22 방향 전환. EMU는 검증·폴백 트랙으로 유지 |
| 웹앱 배포 | ❌ 포기 — 브라우저 무선 제어 불가 + LDN 근접성 물리 벽 |
| 1차 배포 | **Windows — WSL2 커스텀 커널** (본 문서) |
| 2차 배포 | **macOS** — Windows 성공 시에만 착수 (UTM/Fusion 헤드리스 VM) |
| 폴백 | VirtualBox OVA |

### framerelay가 배포에 미치는 차이 (EMU 대비)

| 요소 | EMU (구 플랜) | framerelay (본 플랜) | 배포 영향 |
|---|---|---|---|
| 무선 동작 | 모니터 RX + AP 조인 + TAP 주입 | 모니터 RX + **TX 인젝션(radiotap)** | 조인 단계 자체가 없음 → assoc 타이밍 리스크 소멸 |
| TAP/TUN | 필수 (UDP 데이터 플레인) | **불필요** (AF_PACKET만 사용) | 커널 CONFIG 단순화 |
| 최대 리스크 | assoc 타이밍 | **SIFS ACK × 인터넷 왕복** + usbipd 지연 가산 | G6의 핵심 관찰 항목 |
| 카드 요구 | 8188EU OK | 베이스 = **WSL은 8192EU**, VMware는 8188EU/8192EU / **호스트 모드 = 8192EU 필수** | 8188EU는 WSL USB/IP firmware start 실패 |
| 게임 해석 | frlgsim 필요 | 불필요 (프레임 통째 중계, 암호화도 스위치끼리) | 배포 번들에서 frlgsim 제외 가능 |

## 1. PoC 게이트 (framerelay 기준)

**목표**: 일반 Windows PC에서 "설치 스크립트 1번 + 동글 꽂기"로 framerelay 브리지가 동작함을 증명.

| 게이트 | 검증 내용 | 통과 기준 | 필요 하드웨어 | 실패 시 |
|---|---|---|---|---|
| G1 | 커스텀 커널 부팅 | `uname -a`가 빌드 커널 표시 | — | 빌드 재시도 (난이도 낮음) |
| G2 | 카드 인식 + 모니터 지원 | `lsusb` 0bda:8179/818b + `iw phy` monitor | 동글 1개 | 펌웨어/CONFIG 재점검 |
| G3 | **RX 캡처** | 스위치 리더 광고 비콘 캡처 (**timeout 래핑 필수** — VM hang 교훈 D-1) | 동글 1개 + 스위치 | 이후 게이트 재평가 |
| G4 | **TX 인젝션** ⭐ | WSL 송신 frame을 별도 VM/카드에서 재캡처 → 바이트 동등성 (V-1 방식, radiotap 8B 헤더) | 동글 2개 | 드라이버/헤더 분석 |
| G5 | framerelay 루프 | `bridge.py` × 2 + 릴레이 MWLB 왕복이 실무선에서 동작 | **동글 2개** (같은 PC에 attach) 또는 동글1+스위치1 | — |
| G6 | **framerelay E2E** 🏆 | 로드맵 STEP 12와 동일 게이트: B 화면에 "A의 방" 표시 + 조인. **ACK 유실률 관찰 필수** | 동글 2개 + 스위치 2대 | 플랜 B (관리프레임만 중계 + 데이터 Pia 우회 — 07-framerelay-design §4) |

**Go/No-Go**:
- G4 통과 = **WSL2 무선 기반(RX+TX) 확정** → 배포 패키징 착수 가능 (framerelay 앱 코드 완성과 독립)
- G5/G6 = framerelay 개발 진행(로드맵 STEP 6~12)에 종속 — WSL2가 "그저 또 하나의 무선 백엔드"로 흡수되는지 확인하는 게이트
- G2까지만 되고 G3~G4 실패 = 원인 분석 1회 후 OVA 폴백 판단

**WSL2 PoC의 전략적 위치**: 로드맵 STEP 16이지만, **G1~G4는 framerelay 앱 개발과 독립이라 선행 실행 가능**.
VM(검증)과 WSL2(배포)의 무선 결과를 조기에 대조해두면 STEP 10~13(스위치 실기)을 VM/WSL2 어느 쪽으로든 유연하게 돌릴 수 있어요.

## 2. 사전 요구사항

| 항목 | 요구 | 비고 |
|---|---|---|
| Windows | 10 (22H2+) / 11 — 관리자 권한 | 가상화(VT-x/SVM) 활성 확인 |
| 동글 (베이스 모드) | WSL: **8192EU(0bda:818b)**. VMware: 8188EU 또는 8192EU | 8188EU는 VM 실측 OK, WSL G2 FAIL |
| 동글 (호스트 모드, 선택) | **8192EU만** — AP 지원 (8188EU는 AP 없음, 8/22 실측) | 브리지가 방을 여는 모드(로드맵 H-2/STEP 8~10)를 쓸 경우 |
| 동글 수량 | **2개 권장** — G5를 스위치 없이 같은 PC에서 루프백 검증 | +1만 원 수준 |
| 디스크 | 커널 빌드 ~15GB (WSL2 내) | |
| ⚠️ VMware 공존 | 주인님 PC에 VMware VM(V1/V2) 존재 — Hyper-V 플랫폼 활성 시 공존 가능하나 성능 저하 가능 | PoC 중 V1/V2 성능 관찰 |

**Windows 절전 예방 (PoC 전 필수 — 카드 수신 사망 예방):**
```powershell
# 관리자 PowerShell
powercfg /SETACVALUEINDEX SCHEME_CURRENT 2a737441-1930-4402-8d77-b2bebba308a3 48e6b7a6-50f5-4782-a5d4-53bb8f07e226 0
powercfg /SETACTIVE SCHEME_CURRENT
```

## 3. 절차

### Step 1 — WSL2 + Ubuntu 설치 (약 15분)
```powershell
# 관리자 PowerShell
wsl --install          # 기본 Ubuntu + Hyper-V 플랫폼 활성
# 재부팅 1회 (최초 1회만) → Ubuntu 초기 계정 설정
wsl --version
```

### Step 2 — usbipd-win + 카드 attach (기본 커널로 lsusb까지만, 약 10분)
```powershell
winget install usbipd
usbipd list                      # 동글 BUSID 확인 (예: 2-3)
usbipd bind --busid <BUSID>
usbipd attach --wsl --busid <BUSID>
```

이 저장소에서는 elevated PowerShell에서 다음 preflight를 표준 진입점으로 쓴다. VMware USB
Arbitrator 충돌을 막고 profile에 있는 두 카드를 attach한 뒤 WSL `lsusb`까지 확인한다.

```powershell
.\scripts\windows\wsl-radio-preflight.ps1 -Prepare -AutoAttach
```

`-AutoAttach`는 USB reset/재연결 뒤 같은 BUSID를 WSL에 다시 붙이는 hidden watcher를 카드별로
유지한다. Linux command는 `scripts/wsl-radio-prepare.sh --usb-id VID:PID --role host|guest|relay -- COMMAND...`
형태로 시작한다. driver/module/vermagic/SHA/role와 actual RX 중 하나라도 실패하면 COMMAND는 실행되지
않는다. `run_trade.sh v7`은 WSL에서 이 selector를 자동 적용한다.
```bash
# WSL2 안
lsusb                            # 0bda:8179 / 0bda:818b 확인
sudo apt install linux-tools-generic hwdata usbutils iw tcpdump wireless-regdb
```
> 기본 WSL2 커널엔 Wi-Fi 드라이버가 없어 wlan 인터페이스는 안 생김 — 정상. G2는 Step 5에서.

### Step 3 — 커널 확보: GitHub Actions 원격 빌드 ⭐ (주인님 PC 디스크 1GB 이하)
- 로컬 빌드(12GB 필요)는 주인님 PC 용량 문제로 폐기 → **원격 빌드로 전환** (2026-08-22 결정)
- 리포: **github.com/mwl313/wsl2-kernel-build** (공개, 아리아 운영) — Actions가 microsoft/WSL2-Linux-Kernel을 받아
  rtl8xxxu 모듈 + 펌웨어/규제 DB 내장(CONFIG_EXTRA_FIRMWARE: rtl8188eufw.bin/rtl8192eu_nic.bin,
  regulatory.db/.p7s) + usbip 클라이언트 모듈까지 빌드
- 실행: `gh workflow run build-kernel.yml` (아리아) → 소요 ~20분 → Artifacts에서 다운로드
  - 산출물: `bzImage-wsl-st` + `modules-<KVER>.tar.gz` + `README-install.txt`
- 주인님 PC 필요 용량: **결과 파일 ~300MB만**
- 워크플로우 소스: `scripts/wsl2/github-build/.github/workflows/build-kernel.yml` (MWL-SwitchTrade 리포 내 관리)
- (참고) 로컬 빌드 대안 스크립트도 유지: `scripts/wsl2/build_kernel.sh` — 용량 여유 생기면 사용 가능
- ⚠️ 알려진 리스크: usbipd-win #1022 — usbip 경유 펌웨어 다운로드 타이밍 실패 사례. Step 5 dmesg로 확인.

### Step 4 — 커널 교체 + 부팅 (G1)
다운로드한 모듈 archive는 `<KVER>/...` 구조이므로 `/lib/modules` 아래에 푼다. 기존
커널 모듈은 삭제하지 않는다.

```bash
sudo mkdir -p /lib/modules
sudo tar -xzf /mnt/c/wsl-kernel/modules-<KVER>.tar.gz -C /lib/modules
sudo depmod -a <KVER>
```

```powershell
# C:\Users\<계정>\.wslconfig
[wsl2]
kernel=C:\\Users\\<계정>\\bzImage-wsl-st
```
```powershell
wsl --shutdown; wsl
```
```bash
uname -a    # 빌드 커널이면 G1 통과
```

### Step 5 — 모듈 로드 + 모니터 확인 (G2)
```bash
# PowerShell에서 re-attach 필요할 수 있음
sudo modprobe cfg80211 mac80211 rtl8xxxu
lsmod | grep -E 'rtl8xxxu|mac80211|cfg80211'
dmesg | tail -30      # IQK 에러 및 regulatory.db load 실패가 없는지 확인
iw phy                # "monitor" 지원 확인 → G2 통과
```
> WSL2에는 NetworkManager 기본 부재 → EBUSY/unmanaged 문제 클래스가 애초에 없음 (VM 대비 장점).
> udev rename(wlx<MAC>)은 동일 발생 — iface 이름은 `iw dev`로 확인.
> WSL의 rootfs firmware 로딩은 `-2`로 실패할 수 있어 규제 DB도 커널에 내장한다. 실패가 남으면
> world domain에서 1~11 RX 검증은 가능하지만 배포 빌드로 승인하지 않는다.

### Step 6 — RX 캡처 PoC (G3) — ⚠️ timeout 래핑 필수
- 스위치: 디렉트 코너 → 트레이드 → 리더 진입 (LDN 광고)
- 모든 tcpdump/AF_PACKET/framerelay 실행은 먼저 `scripts/radio-health-gate.sh`를 통과한다.
- 모니터 iface를 ch 1/6/11 순회하며 비콘 캡처 → `--host-mac`(스위치 MAC) 확인
- **반드시 외부 `timeout 60` 사용** (ldn.scan 커널 hang 교훈 — VM 3회 실측)
- 성공 기준: 스위치 비콘 수신 + comm_id 디코드(선택)

```bash
IFACE=$(iw dev | awk '$1=="Interface"{print $2; exit}')
for CH in 1 6 11; do
  sudo ./scripts/radio-health-gate.sh --iface "$IFACE" --target-channel "$CH" -- \
    timeout -s INT 20 tcpdump -i "$IFACE" -e -s 0 -w "g3-ch${CH}.pcap"
done
```

### Step 7 — TX 인젝션 PoC (G4) ⭐ framerelay 핵심 게이트
- V-1 방식(VM 실측 절차) 동일 적용: **캡처한 실제 프레임 1개를 그대로 재주입 → 재캡처 → 바이트 동등성 대조**
- radiotap 8B 헤더(`00 00 08 00 00 00 00 00`) 부착 필수 — VM 실측에서 헤더 없으면 드라이버가 조용히 폐기
- 2026-08-24 WSL/8192EU 단일 카드에서는 `send()` 성공 frame이 같은 카드 pcap에 echo되지 않았다.
  그러므로 자기 재캡처를 성공 기준으로 쓰지 않고 별도 monitor 카드/VM에서 RF 재캡처한다.
- **실측 PASS**: VM2/8188EU 외부 카드가 CH6에서 10 Hz 주입 30개 중 28개, 100개 중 90개를
  unique로 재캡처했다. 수신 radiotap 26바이트를 제외한 frame은 모두 송신본과 byte-exact였고
  FCS/padding 차이가 없었다(`logs/wsl/g4-wsl8192-to-vm8188*.pcap`).
- 이 90~93.3%는 ACK 없는 broadcast Probe Request 표본이다. 반복 beacon 또는 ACK/retry가 있는
  실제 LDN unicast의 신뢰도나 SIFS 인터넷 중계 가능성으로 그대로 환산하지 않는다.

### Step 8 — framerelay 루프 (G5) — 동글 2개 구성
- PowerShell에서 동글 2개 각각 bind/attach (같은 WSL2 인스턴스)
- 릴레이: Mac mini(`relay/server.py:8788`) 또는 같은 PC
- 각 카드별로 `radio-health-gate.sh --iface <IFACE> -- <framerelay 명령>`을 사용해
  `framerelay/__main__.py` × 2 실행 (`--role host/guest`, `--host-mac`은 테스트용 더미 MAC)
- 성공 기준: A→릴레이→B 프레임 왕복 + BeaconReplayer 재주입 관찰 (스위치 없이 파이프라인 검증)

### Step 9 — framerelay E2E (G6) 🏆 — 로드맵 STEP 12와 동일 게이트
- 스위치 A(리더) + 스위치 B(참가) + 동글 2개
- 성공 기준: B 화면에 "A의 방" 표시 → 조인 → 트레이드
- **ACK 유실률 관찰이 1차 관찰 포인트**: SIFS ACK가 인터넷 왕복(릴레이가 같은 PC면 로컬 왕복) + usbipd 지연을 견디는지
- 릴레이를 같은 PC에서 돌리면 "usbipd 지연만" 분리 측정 가능 → Mac mini 릴레이로 바꾸면 "인터넷 왕복 가산" 분리 측정 (2단계 측정 권장)

### Step 10 — 세션 유지성 (배포 전제)
background systemd service만으로는 WSL instance/VM idle 종료를 막지 못할 수 있다. relay daemon
배포에서는 다음 설정을 kernel 항목과 함께 사용하고 `wsl --shutdown` 후 재시작한다.

```ini
[general]
instanceIdleTimeout=-1

[wsl2]
kernel=C:\\wsl-kernel\\bzImage-wsl-st-6.18.35.2
vmIdleTimeout=-1
```

```powershell
usbipd bind --busid <BUSID>                               # 관리자, 최초 1회
usbipd attach --wsl --busid <BUSID> --auto-attach         # 이 프로세스가 실행 중일 때 재연결 감시
```
- attach 상태는 Windows 재부팅·장치 리셋 후 영구 유지되지 않는다. 런처가 `usbipd list`를 확인하고
  필요 시 elevated PowerShell에서 attach를 다시 실행해야 한다.
- WSL 안 `usbreset` 뒤 iface가 돌아오지 않으면 health gate는 실패 종료한다. 이때 Windows에서
  `usbipd attach --wsl --busid <BUSID>`를 다시 실행한 뒤 워크플로우를 재시작한다.

## 4. 성공 후 배포 패키징 계획 (framerelay 기준)

| 구성요소 | 형태 |
|---|---|
| installer.ps1 | 사전 진단(가상화·Windows 버전) → WSL/usbipd 설치 → 커널 번들 배치 → .wslconfig → attach 런처 등록 |
| 커널 번들 | bzImage + 모듈 tar + 내장 펌웨어 (버전 고정, GitHub Release) |
| 브리지 런처 | `framerelay/__main__.py` 래퍼 — **스위치 MAC 자동 감지**(비콘 캐시에서 추출, 수동 `--host-mac` 폴백), 카드 자동 감지(8179/818b), 릴레이 URL/세션 입력 |
| 카드 사망 자동복구 | RX 카운터 감시 → PowerShell usbipd detach/attach 사이클 (VM의 C-6에 상응) |
| 제거 스크립트 | 원상복구 보장 (설치물은 깨끗이 지워져야 함) |
| 호스트 모드 옵션 | 8192EU 사용자 한정 — 브리지가 방 개설(로드맵 H-2). 설치기가 카드 AP 지원 여부를 감지해 노출 |

## 5. macOS 2차 게이트 (조건부)

Windows G6 통과 시에만 착수. UTM/Fusion(개인 무료) 헤드리스 VM + ARM64 Ubuntu + rtl8xxxu(메인라인 ARM 지원).
미검증 리스크: Apple Silicon USB 패스스루 품질 × 8188EU 민감성. Intel Mac은 Windows와 거의 동일 구조.
framerelay는 TX 인젝션이 필수라, USB 패스스루 품질이 EMU 때보다 더 결정적 — 2차 게이트에서 G4(인젝션)부터 재검증.
