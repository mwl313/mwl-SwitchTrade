# MWL-SwitchTrade — VM 셋업 가이드 (외장하드, 최소 오버헤드)

> 목적: Windows 데스크탑의 VMware Workstation Pro + 외장하드에 Ubuntu Server 24.04 VM을 설치,
> RTL8188EU를 USB 패스스루로 넘겨 LDN 브리지(리눅스 프론트엔드)로 사용.
> 아리아(Mac mini)는 Tailscale + SSH로 원격 접속해 작업.
>
> 업데이트: 2026-08-20

---

## 0. 전체 그림

```
[Switch] ⇄무선⇄ [RTL8188EU]
                   │ USB
[Windows 데스크탑] ─ VMware Workstation Pro
                   └─ [Ubuntu Server 24.04 VM]  ← 외장하드에 저장
                        ├─ RTL8188EU (USB 패스스루)
                        ├─ LDN + frlgsim + 브리지 데몬 (이후 단계)
                        └─ Tailscale + SSH (아리아 원격 접속)
[Mac mini (아리아)] ──Tailscale──> ssh aria@<VM IP>
```

---

## 1. 사전 준비 — 외장하드 조건 (중요)

| 항목 | 권장 | 비고 |
|---|---|---|
| 인터페이스 | **USB 3.2 Gen 2 (10Gbps)** 이상 | USB 3.0(5Gbps)도 동작하나 VM I/O가 느림. 반드시 PC의 파란 포트(USB 3.x)에 연결 |
| 매체 | **외장 SSD 권장** | HDD면 부팅/설치/패키지 설치가 현저히 느림. (HDD로 해도 동작은 함) |
| 파일 시스템 | **NTFS** | VMware에서 최고 호환. exFAT도 되지만 NTFS 권장 |
| 여유 공간 | 30GB 이상 | VM 디스크 20GB + 스왑/메모리 여유 |
| 전원 | 전원 공급형이면 안전 | 버스파워드 HDD는 VM 중 전압 강하로 분리 위험 → VM 손상 |

**외장하드 분리 주의**: VM 실행 중엔 절대 분리하지 말 것. 사용 후 VMware에서 VM 종료 → "안전하게 제거" 순서.

---

## 2. VMware Workstation Pro 설치 (개인 무료)

1. https://www.vmware.com/products/desktop-hypervisor/workstation-and-fusion 에서 **Workstation Pro for Windows** 다운로드
2. 브로드컴 계정 생성 → **Personal Use (개인용 무료) 라이선스 키** 발급
3. 설치 후: `Help → Enter License Key`에 개인용 키 입력
4. 설치 완료 확인 후 재부팅 권장 (USB 드라이버 정착)

---

## 3. VM 생성 (외장하드에, 최소 스펙)

### 3-1. ISO 다운로드
- **Ubuntu Server 24.04 LTS**: https://ubuntu.com/download/server
- (데스크톱 버전 아님! 서버 = GUI 없음 = 최소 오버헤드)

### 3-2. 새 VM 생성 (Custom 경로)
```
File → New Virtual Machine → Custom (advanced)
  1. Hardware compatibility: 기본값 유지
  2. Installer disc image: Ubuntu Server ISO 선택
  3. Guest OS: Linux → Ubuntu 64-bit
  4. Virtual machine name: MWL-Bridge
  5. Location: <외장하드 경로> (예: E:\VMs\MWL-Bridge)
  6. Firmware: BIOS (기본 유지)
  7. CPU: 2 프로세서 코어
  8. Memory: 2048 MB (2GB) ← 최소. 부족하면 나중에 4GB로
  9. Network: NAT
  10. I/O controller: LSI Logic SAS (기본)
  11. Disk type: NVMe ← 가상 NVMe가 SATA보다 빠름
  12. Disk: Create a new virtual disk, 20GB
      → "Store virtual disk as a single file" 대신
      → "Split virtual disk into multiple files" 선택 ← 외장하드 이동/백업에 유리
  13. Finish (전원 켜지 않게, Customize Hardware로)
```

### 3-3. Customize Hardware (생성 전)
- **USB Controller: USB 3.1** 추가/확인
- CD/DVD: ISO 연결 확인
- 완료 후 **"Power on" 하지 말고 Finish** → 아래 설치 단계로

---

## 4. Ubuntu Server 24.04 설치 (최소화)

1. VM 전원 ON → 설치 시작
2. 언어: English (기본 유지 — CLI라 한국어 불필요)
3. **Minimized** 설치 선택 ← 핵심! 기본 설치보다 패키지 수가 크게 적음
4. 네트워크: DHCP 그대로 (NAT)
5. 계정:
   - 이름: `aria` / 사용자명: `aria`
   - 비밀번호: 강한 비밀번호 (나중에 SSH 키로 교체)
6. **OpenSSH server 체크** ← 필수
7. 설치 완료 → 재부팅 → 로그인 확인

### 설치 직후 최소화 (루트 또는 sudo로)
```bash
# 1) 기본 업데이트
sudo apt update && sudo apt upgrade -y

# 2) snap 제거 (불필요한 백그라운드 부담)
sudo systemctl disable --now snapd
sudo apt purge -y snapd
sudo rm -rf /var/cache/snapd /snap /var/snap

# 3) cloud-init 제거 (서버 설치 시 기본 포함 — VM에선 불필요)
sudo apt purge -y cloud-init
sudo rm -rf /etc/cloud /var/lib/cloud

# 4) open-vm-tools 설치 (VM 성능/클립보드/시간 동기화 — 오버헤드 거의 없음)
sudo apt install -y open-vm-tools

# 5) 확인: 메모리/프로세스
free -h
ps aux | wc -l   # 최소 설치 + purge 후엔 100개 안팎이면 정상
```

---

## 5. 오버헤드 추가 튜닝 (외장하드 필수)

### 5-1. .vmx 파일 편집 (VM 종료 후)
외장하드의 VM 폴더에서 `MWL-Bridge.vmx`를 메모장으로 열고 맨 아래 추가:

```
mainMem.useNamedFile = "FALSE"
```

- **효과**: VM 메모리 백업 파일(.vmem)이 외장하드에 생성되는 것을 방지 → 외장하드 I/O 대폭 감소
- **대가**: VM suspend(일시 중지) 불가. 대신 shutdown/start 사용 (우린 데몬 서버니까 무관)
- VM 재시작으로 적용

### 5-2. Windows USB 선택적 절전 끄기 (중요!)
```
제어판 → 전원 옵션 → 선택한 요금제 설정 변경
→ 고급 전원 설정 변경 → USB 설정 → USB 선택적 절전 모드 설정 → 사용 안 함
```
패스스루한 Wi-Fi 카드가 절전으로 들어가면 LDN 연결이 끊김.

### 5-3. 외장하드 절전 끄기
```
제어판 → 전원 옵션 → 고급 전원 설정
→ 하드 디스크 → 다음 시간 후 하드 디스크 끄기 → "0" (안 함)
```
USB HDD/SSD가 절전 들어가면 VM 디스크 I/O가 멈추며 프리즈 현상 발생.

### 5-4. Windows 부팅 시 VM 자동 시작 (선택)
```
VMware Workstation → VM → Power → Open Power-On Options
→ "Power on this virtual machine when the computer starts" 체크
```
상시 브리지로 쓰려면 추천. (백그라운드 실행: Workstation 종료 시 트레이로 최소화)

---

## 6. USB 패스스루 — RTL8188EU 연결

1. **VM 전원을 켜기 전에** RTL8188EU를 Windows에 꽂아 둔다
2. VM 전원 ON
3. VMware 메뉴: `VM → Removable Devices → [Realtek RTL8188EU] → Connect`
4. 게스트에서 확인:
```bash
lsusb | grep -i realtek
# Bus 003 Device 005: ID 0bda:8179 Realtek Semiconductor Corp. RTL8188EUS 802.11n Wireless Network Adapter
```
5. **드라이버: 메인라인 rtl8xxxu로 충분 (커스텀 빌드 불필요 — 2026-08-20 실측)**
   - Ubuntu 26.04 커널 7.0에서 RTL8188EUS는 자동으로 `rtl8xxxu`가 잡음
   - `iw list` → Supported interface modes: **managed, monitor** 확인됨 (AP는 없지만 불필요)
   - rtl8188eus 커스텀 빌드는 필요 시에만 (모니터 인젝션 문제 발생 시)
6. **모니터 모드 실측 (성공 확인됨)**:
```bash
sudo apt install -y iw tcpdump
sudo /home/aria/scripts/radio-health-gate.sh \
  --iface wlx00ada7117309 --target-channel 1 -- \
  timeout -s INT 10 tcpdump -i wlx00ada7117309 -c 15
# → Beacon/Probe Request 수신 확인 (0 dropped). VM+패스스루에서 모니터 모드 실동작 검증됨
```
7. LDN 파이썬 환경:
```bash
# Ubuntu 26.04 = Python 3.14 → python3.14-venv 패키지 사용
sudo apt install -y python3-pip python3.14-venv
python3 -m venv ~/ldnvenv && ~/ldnvenv/bin/pip install ldn trio
```
8. **스캔 테스트는 prod.keys 필요** (아래 11장 참고)

---

## 7. 아리아 원격 접속 (Tailscale + SSH)

### 7-1. VM에 Tailscale 설치
```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
# 출력되는 URL을 브라우저로 열어 로그인 (Windows/Mac과 같은 계정)
tailscale ip -4   # 예: 100.x.x.x
```

### 7-2. SSH 키 인증 (아리아가 비밀번호 없이 접속)
아리아(Mac mini)에서:
```bash
ssh-keygen -t ed25519 -f ~/.ssh/aria_bridge -N ""
ssh-copy-id -i ~/.ssh/aria_bridge aria@<VM테일넷IP>
```
VM에서 키 로그인 확인:
```bash
ssh -i ~/.ssh/aria_bridge aria@<VM테일넷IP> "echo OK && uname -a"
```

### 7-3. SSH 보안 (선택)
```bash
sudo sed -i 's/^#PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo systemctl restart ssh
```

---

## 8. 검증 체크리스트

- [ ] `lsusb`에 RTL8188EU 표시 (패스스루 성공)
- [ ] `iw list`에 monitor 모드 표시
- [ ] `tailscale status`에 VM IP 표시 (Windows/Mac에서 ping 가능)
- [ ] Mac mini에서 `ssh aria@<IP>` 키 로그인 성공
- [ ] `free -h` — 2GB 중 300MB 이하 사용 (최소 설치 기준)
- [ ] snap/cloud-init 제거 확인 (`snap list` 에러, `/etc/cloud` 없음)

---

## 9. 함정 & 문제 해결

| 증상 | 원인/해결 |
|---|---|
| 패스스루가 계속 끊김 | Windows USB 선택적 절전 확인 (5-2) |
| VM이 멈춤/디스크 에러 | 외장하드 절전 (5-3), USB 케이블/포트 품질 확인 |
| .vmem이 외장하드에 생김 | mainMem.useNamedFile = "FALSE" (5-1) |
| 패스스루 시 호스트에서 카드 안 보임 | 정상 — VM이 독점. 해제는 VM → Removable Devices → Disconnect |
| Ubuntu 설치 중 ISO 안 보임 | CD/DVD 연결 확인 (3-3) |
| iw list에 AP만 있고 monitor 없음 | 드라이버 문제 — rtl8188eus 재빌드 (6-5), `sudo modprobe -r rtl8xxxu` |
| 메모리 부족 (OOM) | VM 메모리 4096MB로 상향 (VM 종료 → Edit settings) |

---

## 10. 다음 단계 (VM 완성 후)

1. **prod.keys 확보** (11장) — 순정 스위치에서 직접 추출 불가 (Lockpick=커펌). PC에서 사용하는 키 파일은 스위치를 건드리지 않으므로 순정 원칙 유지.
2. ldn 스캔 테스트 → Switch가 만든 LDN 네트워크가 잡히는지
3. 성공 → frlg-ldn-trade 클론, PoC 재현 (Switch↔PC 트레이드)
4. 성공 → 브리지 데몬 + 릴레이 설계 (Phase 2)

## 11. prod.keys 문제 (실측으로 확인된 유일한 장애물)

**상황 (2026-08-20 실측)**:
- LDN 스캔에는 advertise 프레임 해독 키가 필요 → `ldn.load_keys('~/.switch/prod.keys')` 필수
- 파생에 필요한 것: `master_key_00/12`, `aes_kek_generation_source`, `aes_key_generation_source` — **전부 Lockpick으로만 추출 가능 (커펌 필요)**
- 순정 스위치에서 직접 얻는 경로는 없음

**완화 요소 (리서치 확인)**:
- FRLG 패스프레이즈: 공개 상수 (위키 LDN-Passphrases, frlgsim에 하드코딩) ✓
- 데이터 프레임: 보안 레벨 1에서 **평문** — 트레이드 데이터 암호화 없음 ✓
- advertise/data input key: 공개 상수 (`191884743e24c77d87c69e4207d0c438`, `f1e7018419a84f711da714c2cf919c9c`) ✓
- kinnay/LDN에 `override_advertise_key`/`override_data_key` 파라미터 존재 → **파생 키 값이 알려지면 prod.keys 불필요 경로 가능**

**해법 옵션**:
| 옵션 | 설명 | 순정 유지 |
|---|---|---|
| A. 커뮤니티 공유 키 | frlg-ldn-trade Discord 등에서 공유된 prod.keys를 PC에 두고 사용 | ✓ (스위치 무관) |
| B. override 키 대기 | FRLG용 파생 advertise/data 키가 공개되면 직접 주입 | ✓ |
| C. (미권장) Lockpick | 스위치 커펌 필요 — 순정 원칙 위반 | ✗ |

**✅ 해결됨 (2026-08-20)**: GitHub 공개 리포 `THZoria/NX_Firmware`의 prod.keys 사용 (에뮬레이터 커뮤니티 표준 아카이브).
- `master_key_00/12`, `aes_kek/key_generation_source` 포함 확인 (LDN 파생에 필요한 키 전부)
- VM의 `/root/.switch/prod.keys`에 배치 (sudo 실행 시 root 홈 참조 — `~/.switch`는 aria 홈과 별개라 둘 다 복사 필요)
- `ldn.load_keys()` + `ldn.scan()` **실측 성공** (키 유효 확인, 0 networks는 스위치 미기동이 원인)
- 참고 백업: `Abdess/retrobios` (bios/Nintendo/Switch/prod.keys) — 동일 키 세트

## 12. PoC 준비 상태 (2026-08-20)

VM에 준비 완료된 것:
- [x] RTL8188EUS 패스스루 + 모니터 모드 실측 (0 dropped)
- [x] `~/ldnvenv` — ldn 0.0.17, trio, pycryptodome, zstandard
- [x] prod.keys (공개 리포, /root/.switch/)
- [x] `~/frlg-ldn-trade` 클론 + 의존성 설치, `frlgtrade.py --help` 동작
- [ ] **Switch 측 준비** (주인님): NSO GB 앱 FRLG → 디렉트 코너 해금 (~20~40분 플레이)
- [ ] **.pk3 2개 준비** (주인님): PKHeX for Web (https://pkhex-web.github.io/)에서 생성
- [ ] 실제 트레이드 테스트: `sudo ~/ldnvenv/bin/python frlgtrade.py --live --keys /root/.switch/prod.keys -o output.pk3 PARTY1.pk3 PARTY2.pk3`

---

*작성: 2026-08-20 | 프로젝트: MWL-SwitchTrade*
