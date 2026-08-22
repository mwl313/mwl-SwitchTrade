#!/usr/bin/env bash
# ============================================================
# WSL2 커스텀 커널 빌드 — MWL-SwitchTrade 배포 트랙 α (A-2)
# 실행 위치: 주인님 Windows PC의 WSL2(Ubuntu) 안
# 사용법:   bash build_kernel.sh   (sudo 암호 1회 물어봄)
# 소요:     20~60분 (PC 사양 따라) · 디스크 12GB+ 필요
# 검증 문서: docs/12-wsl2-poc-windows.md (G1~G2 게이트)
# ============================================================
set -euo pipefail
say() { echo -e "\n\033[1;36m== $* ==\033[0m"; }

# ---------- 사전 확인 ----------
if [[ "$(uname -r)" != *microsoft* ]]; then
  echo "[오류] WSL2 안에서 실행해야 해요. (현재 커널: $(uname -r))"
  exit 1
fi

FREE_GB=$(df --output=avail -BG / | tail -1 | tr -dc '0-9')
if (( FREE_GB < 12 )); then
  echo "[오류] 디스크 여유 ${FREE_GB}GB — 최소 12GB 필요. WSL 디스크 정리 후 재실행."
  exit 1
fi

# Windows 사용자 이름 감지 (interop 꺼져 있으면 직접 입력)
WINUSER="$(cmd.exe /C 'echo %USERNAME%' 2>/dev/null | tr -d '\r' || true)"
if [[ -z "$WINUSER" ]]; then
  read -rp "Windows 사용자 이름 입력: " WINUSER
fi
WINHOME="/mnt/c/Users/${WINUSER}"
if [[ ! -d "$WINHOME" ]]; then
  echo "[오류] ${WINHOME} 폴더가 없어요. Windows 사용자 이름을 확인하세요."
  exit 1
fi

say "1/6 의존성 설치"
sudo apt-get update -y
sudo apt-get install -y build-essential flex bison libssl-dev libelf-dev bc dwarves git wget kmod cpio

say "2/6 커널 소스 받기"
cd "$HOME"
if [[ ! -d WSL2-Linux-Kernel ]]; then
  git clone --depth 1 https://github.com/microsoft/WSL2-Linux-Kernel.git
fi
cd WSL2-Linux-Kernel
git pull --ff-only 2>/dev/null || true

say "3/6 설정 — Wi-Fi 드라이버 + 펌웨어 내장 + usbip 클라이언트"
cp Microsoft/config-wsl .config
mkdir -p firmware/rtlwifi
# RTL8188EU 펌웨어 (커널 이미지에 내장 — 배포 시 펌웨어 파일 불필요)
if [[ ! -s firmware/rtlwifi/rtl8188eufw.bin ]]; then
  wget -q "https://git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git/plain/rtlwifi/rtl8188eufw.bin" \
       -O firmware/rtlwifi/rtl8188eufw.bin
fi
# 8192EU도 쓰려면 아래 주석 해제:
# wget -q "https://git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git/plain/rtlwifi/rtl8192eu_nic.bin" \
#      -O firmware/rtlwifi/rtl8192eu_nic.bin

scripts/config \
  --enable CONFIG_EXTRA_FIRMWARE \
  --set-str CONFIG_EXTRA_FIRMWARE_DIR "$(pwd)/firmware" \
  --set-str CONFIG_EXTRA_FIRMWARE "rtlwifi/rtl8188eufw.bin" \
  --module CONFIG_CFG80211 \
  --module CONFIG_MAC80211 \
  --module CONFIG_RTL8XXXU \
  --enable CONFIG_RTL8XXXU_UNTESTED \
  --module CONFIG_USBIP_CORE \
  --module CONFIG_USBIP_VHCI_HCD
make olddefconfig

say "4/6 빌드 시작 ($(nproc)코어 — 여기가 제일 오래 걸려요, 놔두세요)"
make -j"$(nproc)"

say "5/6 모듈 번들링 (WSL 시스템 오염 없음 — 격리 폴더에)"
KVER=$(make kernelrelease)
rm -rf modout
make modules_install INSTALL_MOD_PATH="$PWD/modout"
tar -C modout/lib/modules -czf "${WINHOME}/modules-${KVER}.tar.gz" .

say "6/6 Windows로 결과 복사"
cp arch/x86/boot/bzImage "${WINHOME}/bzImage-wsl-st"

cat <<EOF

============================================================
✅ 완료! 생성된 파일:
   C:\\Users\\${WINUSER}\\bzImage-wsl-st          (커널)
   C:\\Users\\${WINUSER}\\modules-${KVER}.tar.gz  (모듈)

다음 단계 (PowerShell에서):
1) C:\\Users\\${WINUSER}\\.wslconfig 파일을 만들고 내용:
     [wsl2]
     kernel=C:\\\\Users\\\\${WINUSER}\\\\bzImage-wsl-st
2) wsl --shutdown  →  WSL 다시 열기
3) uname -a 로 커널 버전 확인 (PoC 게이트 G1 통과 확인)

확인되면 아리아에게 출력 붙여넣기!
============================================================
EOF
