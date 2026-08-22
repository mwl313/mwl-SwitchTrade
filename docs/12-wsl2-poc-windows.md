# 12 — Windows 배포 PoC 절차서 (WSL2 커스텀 커널)

> 작성: 2026-08-22 | 상태: [확정] PoC 절차 v1 — 코드 수정 없음, 실기 실행 대기
> 상위 문서: `docs/06-distribution.md` (배포 전략 전체)

## 0. [확정] 결정 사항 (2026-08-22)

| 항목 | 결정 |
|---|---|
| 웹앱 배포 | ❌ **포기** — 브라우저 무선 제어 불가 + LDN 근접성(물리 벽) |
| 1차 배포 | **Windows — WSL2 커스텀 커널** (본 문서의 PoC로 검증) |
| 2차 배포 | **macOS** — Windows 성공 시에만 착수 (UTM/Fusion 헤드리스 VM 이미지) |
| 폴백 | VirtualBox OVA (WSL2 No-Go 시) |

## 1. PoC 목표와 판정 기준

**목표**: 일반 Windows PC에서 "설치 스크립트 1번 + 동글 꽂기"로 LDN 브리지가 동작함을 증명.

| 게이트 | 검증 내용 | 통과 기준 | 실패 시 |
|---|---|---|---|
| G1 | 커스텀 커널 부팅 | `uname -a`가 빌드한 커널 표시 | 빌드 재시도 (난이도 낮음) |
| G2 | 카드 인식 + 모니터 지원 | `lsusb` 0bda:8179 + `iw phy` monitor 목록에 존재 | 펌웨어/CONFIG 재점검 |
| G3 | 스캔 성공 | 스위치 리더 광고 found ≥ 1 (**timeout 래핑 필수**) | ⚠️ 이후 게이트 전면 재평가 |
| G4 | assoc + 트레이드 1회 | 트랙 A 워크플로우 v1 완주, received .pk3 생성 | 환경 변수 분리 분석 후 재시도 |

**Go/No-Go**: G4까지 통과 = WSL2 배포 1차안 확정. G2까지 되고 G3~G4 실패 = 원인 분석 1회 후 OVA 폴백 판단.

## 2. 사전 요구사항

| 항목 | 요구 | 확인 방법 |
|---|---|---|
| Windows | 10 (22H2+) / 11 — 관리자 권한 가능 | — |
| 가상화 | BIOS에서 VT-x/SVM 활성 | 작업관리자 > 성능 > CPU "가상화: 사용" |
| RTL8188EU 동글 | 0bda:8179 (8192EU 0bda:818b도 가능 — rtl8xxxu 공용) | `usbipd list` |
| 디스크 | 커널 빌드용 ~15GB (WSL2 내) | — |
| ⚠️ VMware 공존 | **주인님 PC에는 VMware VM(V1/V2)이 있음** — WSL2 활성(Hyper-V 플랫폼) 시 VMware 15.5+는 공존 가능하지만 성능 저하(Ultra-light 모드) 발생 가능 | PoC 중 VM 성능 변화 관찰 필요 |

**Windows 절전 예방 (PoC 전 필수 — 카드 수신 사망 예방, VM 실측과 동일):**
```powershell
# 관리자 PowerShell
powercfg /SETACVALUEINDEX SCHEME_CURRENT 2a737441-1930-4402-8d77-b2bebba308a3 48e6b7a6-50f5-4782-a5d4-53bb8f07e226 0
powercfg /SETACTIVE SCHEME_CURRENT
```

## 3. 절차

### Step 1 — WSL2 + Ubuntu 설치 (약 15분)
```powershell
# 관리자 PowerShell
wsl --install          # 기본 Ubuntu, 자동으로 Hyper-V 플랫폼 활성
# 재부팅 1회 (최초 1회만) → Ubuntu 초기 계정 설정
wsl --version          # WSL 버전 확인 (2.x)
```

### Step 2 — usbipd-win + 카드 attach (기본 커널로 lsusb까지만, 약 10분)
```powershell
winget install usbipd
usbipd list                      # 동글 BUSID 확인 (예: 2-3)
usbipd bind --hardware-id <BUSID>        # 구버전은 --busid
usbipd attach --wsl --hardware-id <BUSID>
```
```bash
# WSL2 안에서
lsusb                            # 0bda:8179 보이면 OK (드라이버 없어도 lsusb엔 보임)
sudo apt install linux-tools-generic hwdata usbutils wireless-tools iw
```
> 참고: 기본 WSL2 커널엔 Wi-Fi 드라이버가 없어서 wlan 인터페이스는 안 생김 — 정상.

### Step 3 — 커스텀 커널 빌드 (약 30분~1시간, WSL2 안에서)
```bash
sudo apt install build-essential flex bison libssl-dev libelf-dev dwarves bc git
git clone https://github.com/microsoft/WSL2-Linux-Kernel.git
cd WSL2-Linux-Kernel
git checkout $(git describe --tags $(git rev-list --tags --max-count=1))  # 최신 안정 태그
cp Microsoft/config-wsl .config

# 펌웨어 준비 (커널에 내장 — 배포 시 펌웨어 파일 따로 안 줘도 되게 하는 트릭)
mkdir -p firmware/rtlwifi
wget https://git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git/plain/rtlwifi/rtl8188eufw.bin \
     -O firmware/rtlwifi/rtl8188eufw.bin
scripts/config --enable CONFIG_EXTRA_FIRMWARE \
               --set-str CONFIG_EXTRA_FIRMWARE_DIR "$(pwd)/firmware" \
               --set-str CONFIG_EXTRA_FIRMWARE "rtlwifi/rtl8188eufw.bin"
# 8192EU도 함께면: rtl8192eu_nic.bin 추가

scripts/config --module CONFIG_CFG80211 --module CONFIG_MAC80211 \
               --module CONFIG_RTL8XXXU --module CONFIG_TUN \
               --enable CONFIG_RTL8XXXU_UNTESTED
make olddefconfig
make -j$(nproc) && make modules_install
cp arch/x86/boot/bzImage /mnt/c/Users/<윈도우계정>/bzImage-wsl-st
```
> ⚠️ `CONFIG_EXTRA_FIRMWARE_DIR`은 절대경로 문자열로 커널에 새겨짐 — 빌드 머신 경로여도 무방(빌드 시 번들링).
> ⚠️ 알려진 리스크: usbipd-win #1022 — usbip 경유 펌웨어 다운로드 타이밍 실패 사례. G2에서 dmesg로 확인.

### Step 4 — 커널 교체 + 부팅 (G1, 약 5분)
```powershell
# C:\Users\<계정>\.wslconfig 생성
[wsl2]
kernel=C:\\Users\\<계정>\\bzImage-wsl-st
```
```powershell
wsl --shutdown; wsl   # 재시작 후
```
```bash
uname -a              # 빌드한 커널 버전이면 G1 통과
```

### Step 5 — 모듈 로드 + 모니터 확인 (G2)
```bash
# usbipd re-attach 필요할 수 있음 (PowerShell: usbipd attach --wsl ...)
sudo modprobe cfg80211 mac80211 rtl8xxxu
lsmod | grep -E 'rtl8xxxu|mac80211|cfg80211'
dmesg | tail -20      # "RTL8188EU ... Loading firmware rtlwifi/rtl8188eufw.bin" 확인
iw phy                # "monitor: supported" 있으면 G2 통과
```

### Step 6 — 스캔 PoC (G3) — ⚠️ timeout 래핑 필수
- VM 실측교훈(D-1): ldn.scan이 커널 레벨 hang을 일으킬 수 있음 → **반드시 외부 `timeout 60` + 백그라운드**로 실행
- 스위치: 디렉트 코너 → 트레이드 → 리더 진입
- `scan_phy.py` 템플릿(switch-ldn-trade 스킬) 사용, phy 이름은 `iw phy` 출력 기준으로
- WSL2에는 NM(NetworkManager)이 기본 없음 → EBUSY/unmanaged 문제 클래스가 애초에 없을 것 (장점)
- udev rename(wlx<MAC>)은 동일 발생 — iface 이름은 `iw dev`로 직접 확인

### Step 7 — 트랙 A 트레이드 1회 (G4)
- 릴레이: Mac mini(`relay/server.py`) 또는 같은 PC의 두 번째 WSL 인스턴스
- `emu/frlgtrade.py --relay-url http://<릴레이IP>:8788 --role host --session-id <SID> ...` — VM 워크플로우 v1 그대로
- 몬 파일/키는 VM 백업(`backup-vm-20260821/`)에서 복사
- **run_trade.sh v6는 VMware 의존 부분(카드 리셋 sysfs 경로 등)이 있어 그대로 안 먹힐 수 있음** → 첫 트레이드는 래퍼 없이 직접 실행하고, 성공 후 WSL2용 래퍼 변형을 별도로 만들 것

### Step 8 — 세션 유지성 확인 (배포 전제)
```powershell
usbipd bind --hardware-id <BUSID>   # 1회
usbipd attach --wsl --hardware-id <BUSID> --auto-attach   # 재부팅 후 자동 재연결
```
- Windows 재부팅 → auto-attach로 카드 복귀되는지 확인
- 카드 수신 사망(IQK) 발생 시: PowerShell detach/attach 사이클 스크립트가 VM의 usbreset 대체품 (배포 패키징 때 자동화)

## 4. 성공 후 배포 패키징 계획 (PoC 다음 단계)

| 구성요소 | 형태 |
|---|---|
| installer.ps1 | 사전 진단(가상화 활성·Windows 버전) → WSL 설치 → usbipd 설치 → 커널/모듈/펌웨어 배치 → .wslconfig → auto-attach 등록 |
| 커널 번들 | bzImage + 모듈 tar (버전 고정, GitHub Release 첨부) |
| WSL2 래퍼 | run_trade.sh v6의 WSL2 변형 (카드 리셋 = usbipd 사이클 호출) |
| 제거 스크립트 | 원상복구 보장 (주인님 원칙: 설치물은 깨끗이 지워져야 함) |

## 5. macOS 2차 게이트 (조건부)

Windows G4 통과 시에만 착수. 방식: UTM 또는 VMware Fusion(개인 무료) 헤드리스 VM + ARM64 Ubuntu + rtl8xxxu(메인라인 ARM 지원) + USB 패스스루.
미검증 리스크: Apple Silicon USB 패스스루 품질(QEMU 흔들림) × 8188EU 민감성 조합. Intel Mac은 Windows와 거의 동일 구조.
