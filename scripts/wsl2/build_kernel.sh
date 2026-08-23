#!/usr/bin/env bash
# ============================================================
# WSL2 커스텀 커널 빌드 — MWL-SwitchTrade 배포 트랙 α (A-2)
# 실행 위치: 주인님 Windows PC의 WSL2(Ubuntu) 안
# 사용법:   bash build_kernel.sh   (sudo 암호 1회 물어봄)
# 신규 in-kernel 카드 예:
#   EXTRA_KERNEL_CONFIG='CONFIG_MT76_USB=m CONFIG_MT76x2U=m' \
#   EXTRA_FIRMWARE_SPECS='mediatek/file.bin=https://pinned.example/file.bin' bash build_kernel.sh
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
KERNEL_REF="${KERNEL_REF:-linux-msft-wsl-6.6.123.2}"
if [[ ! -d WSL2-Linux-Kernel ]]; then
  git clone --depth 1 --branch "$KERNEL_REF" https://github.com/microsoft/WSL2-Linux-Kernel.git
fi
cd WSL2-Linux-Kernel
git fetch --depth 1 origin "$KERNEL_REF"
git checkout --detach FETCH_HEAD

say "3/6 설정 — Wi-Fi 드라이버 + 펌웨어 내장 + usbip 클라이언트"
cp Microsoft/config-wsl .config
mkdir -p firmware/rtlwifi
FW_BASE="https://git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git/plain"
REGDB_BASE="https://git.kernel.org/pub/scm/linux/kernel/git/wens/wireless-regdb.git/plain"
EXTRA_KERNEL_CONFIG="${EXTRA_KERNEL_CONFIG:-}"
EXTRA_FIRMWARE_SPECS="${EXTRA_FIRMWARE_SPECS:-}"
# RTL8188EU/RTL8192EU 펌웨어 (커널 이미지에 내장 — 배포 시 펌웨어 파일 불필요)
if [[ ! -s firmware/rtlwifi/rtl8188eufw.bin ]]; then
  wget -q "$FW_BASE/rtlwifi/rtl8188eufw.bin" \
       -O firmware/rtlwifi/rtl8188eufw.bin
fi
if [[ ! -s firmware/rtlwifi/rtl8192eu_nic.bin ]]; then
  wget -q "$FW_BASE/rtlwifi/rtl8192eu_nic.bin" \
       -O firmware/rtlwifi/rtl8192eu_nic.bin
fi
for REGDB in regulatory.db regulatory.db.p7s; do
  [[ -s firmware/$REGDB ]] || wget -q "$REGDB_BASE/$REGDB" -O "firmware/$REGDB"
done
FW_LIST="rtlwifi/rtl8188eufw.bin rtlwifi/rtl8192eu_nic.bin regulatory.db regulatory.db.p7s"
for SPEC in $EXTRA_FIRMWARE_SPECS; do
  PATH_PART="${SPEC%%=*}"
  URL_PART="${SPEC#*=}"
  [[ "$SPEC" == *=* && -n "$PATH_PART" && -n "$URL_PART" ]] || {
    echo "[오류] 잘못된 EXTRA_FIRMWARE_SPECS 항목: $SPEC"; exit 1;
  }
  [[ "$PATH_PART" != /* && "$PATH_PART" != *..* ]] || {
    echo "[오류] 안전하지 않은 firmware 상대경로: $PATH_PART"; exit 1;
  }
  mkdir -p "firmware/$(dirname "$PATH_PART")"
  wget -q "$URL_PART" -O "firmware/$PATH_PART"
  [[ -s firmware/$PATH_PART ]] || { echo "[오류] firmware 다운로드 실패: $PATH_PART"; exit 1; }
  FW_LIST="$FW_LIST $PATH_PART"
done

scripts/config \
  --enable CONFIG_USB_SUPPORT \
  --enable CONFIG_USB_COMMON \
  --enable CONFIG_USB \
  --enable CONFIG_EXTRA_FIRMWARE \
  --set-str CONFIG_EXTRA_FIRMWARE_DIR "$(pwd)/firmware" \
  --set-str CONFIG_EXTRA_FIRMWARE "$FW_LIST" \
  --module CONFIG_CFG80211 \
  --module CONFIG_MAC80211 \
  --module CONFIG_RTL8XXXU \
  --enable CONFIG_RTL8XXXU_UNTESTED \
  --module CONFIG_USBIP_CORE \
  --module CONFIG_USBIP_VHCI_HCD
for SPEC in $EXTRA_KERNEL_CONFIG; do
  KEY="${SPEC%%=*}"
  VALUE="${SPEC#*=}"
  [[ "$KEY" =~ ^CONFIG_[A-Z0-9_]+$ ]] || { echo "[오류] 잘못된 config symbol: $KEY"; exit 1; }
  case "$VALUE" in
    y) scripts/config --enable "$KEY" ;;
    m) scripts/config --module "$KEY" ;;
    n) scripts/config --disable "$KEY" ;;
    *) echo "[오류] 잘못된 config 값: $SPEC"; exit 1 ;;
  esac
done
make olddefconfig

for SPEC in $EXTRA_KERNEL_CONFIG; do
  KEY="${SPEC%%=*}"
  VALUE="${SPEC#*=}"
  if [[ "$VALUE" == n ]]; then
    grep -q "^# ${KEY} is not set" .config
  else
    grep -q "^${KEY}=${VALUE}" .config
  fi || { echo "[오류] olddefconfig가 $SPEC 요청을 변경했습니다."; exit 1; }
done

for OPT in CONFIG_USB CONFIG_USB_COMMON CONFIG_CFG80211 CONFIG_MAC80211 CONFIG_RTL8XXXU CONFIG_USBIP_CORE CONFIG_USBIP_VHCI_HCD; do
  grep -qE "^${OPT}=(y|m)" .config || { echo "[오류] olddefconfig가 ${OPT}를 제거했습니다."; exit 1; }
done

say "4/6 빌드 시작 ($(nproc)코어 — 여기가 제일 오래 걸려요, 놔두세요)"
make -j"$(nproc)"

say "5/6 모듈 번들링 (WSL 시스템 오염 없음 — 격리 폴더에)"
KVER=$(make kernelrelease)
rm -rf modout
make modules_install INSTALL_MOD_PATH="$PWD/modout" INSTALL_MOD_STRIP=1
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
