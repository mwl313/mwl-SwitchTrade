#!/usr/bin/env bash
# ============================================================
# WSL2 커스텀 커널 빌드 — MWL-SwitchTrade 배포 트랙 α (A-2)
# 실행 위치: 주인님 Windows PC의 WSL2(Ubuntu) 안
# 사용법:   bash build_kernel.sh   (sudo 암호 1회 물어봄)
# 추가 실험 카드만 EXTRA_KERNEL_CONFIG/EXTRA_FIRMWARE_SPECS로 전달한다.
# production matrix의 드라이버와 firmware는 이 스크립트가 항상 포함하고 검증한다.
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
mkdir -p firmware/mediatek firmware/rtw88
LINUX_FIRMWARE_COMMIT="01205307636157a12c29e6a774bf83b218732050"
REGULATORY_COMMIT="74cb99ff3853e0092d909a8b8afeadea88dfd16b"
LINUX_FIRMWARE_BASE="https://kernel.googlesource.com/pub/scm/linux/kernel/git/firmware/linux-firmware/+/$LINUX_FIRMWARE_COMMIT"
REGULATORY_BASE="https://kernel.googlesource.com/pub/scm/linux/kernel/git/wens/wireless-regdb/+/$REGULATORY_COMMIT"
EXTRA_KERNEL_CONFIG="${EXTRA_KERNEL_CONFIG:-}"
EXTRA_FIRMWARE_SPECS="${EXTRA_FIRMWARE_SPECS:-}"

fetch_pinned() {
  local target=$1 url=$2 expected=$3 actual
  mkdir -p "firmware/$(dirname "$target")"
  wget -qO- "$url?format=TEXT" | base64 -d >"firmware/$target"
  [[ -s firmware/$target ]] || { echo "[오류] firmware 다운로드 실패: $target"; exit 1; }
  actual="$(sha256sum "firmware/$target" | awk '{print $1}')"
  [[ $actual == "$expected" ]] || { echo "[오류] firmware 해시 불일치: $target"; exit 1; }
}

fetch_pinned regulatory.db "$REGULATORY_BASE/regulatory.db" \
  2fb33ca0074db573e05ef7dd50bb45b63c0ff98b7e852e1105ebad536fae8e6b
fetch_pinned regulatory.db.p7s "$REGULATORY_BASE/regulatory.db.p7s" \
  c941c08f51c93e46722293b85631604c3740d86c3de0c75f79aef50d2e919179
fetch_pinned rtlwifi/rtl8188eufw.bin "$LINUX_FIRMWARE_BASE/rtlwifi/rtl8188eufw.bin" \
  2ff74315287529dec2e50eb57d6e0c97d2116f28ae166773ccdf93b6360000c4
fetch_pinned rtlwifi/rtl8192eu_nic.bin "$LINUX_FIRMWARE_BASE/rtlwifi/rtl8192eu_nic.bin" \
  b15bc955fba2fc3abc093affe62c9f7284a0b84d4f13f8ce55366488dc9aad8b
fetch_pinned mediatek/mt7610u.bin "$LINUX_FIRMWARE_BASE/mediatek/mt7610u.bin" \
  5a4268e9021bb587426ba624b425f1e660bfc82cd63b36ad3ce6fb9ce6751760
fetch_pinned mt7662.bin "$LINUX_FIRMWARE_BASE/mediatek/mt7662.bin" \
  f7e52492f58088cae50e51a54cca68e4abc5b74f7d0b6b731dbb4c04465a94b6
fetch_pinned mt7662_rom_patch.bin "$LINUX_FIRMWARE_BASE/mediatek/mt7662_rom_patch.bin" \
  6f0e871268f6e4d99196d90d89bcc09fe493d010366260a2cfcaa5dd66095f8c
fetch_pinned rt2870.bin "$LINUX_FIRMWARE_BASE/rt2870.bin" \
  251b8918391eac6415d60dca239e415aad0177e885376f2a17782e64fcbbe317
fetch_pinned rtw88/rtw8821c_fw.bin "$LINUX_FIRMWARE_BASE/rtw88/rtw8821c_fw.bin" \
  2ef409bc418549fcf294061dd0cae1fc22fd9da79b60524950b25de18732f3f0
FW_LIST="regulatory.db regulatory.db.p7s rtlwifi/rtl8188eufw.bin rtlwifi/rtl8192eu_nic.bin mediatek/mt7610u.bin mt7662.bin mt7662_rom_patch.bin rt2870.bin rtw88/rtw8821c_fw.bin"
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
  --module CONFIG_MT76x0U \
  --module CONFIG_MT76x2U \
  --module CONFIG_RT2800USB \
  --enable CONFIG_RT2800USB_RT35XX \
  --module CONFIG_RTW88_8821CU \
  --module CONFIG_USBIP_CORE \
  --module CONFIG_USBIP_VHCI_HCD
for SPEC in $EXTRA_KERNEL_CONFIG; do
  KEY="${SPEC%%=*}"
  VALUE="${SPEC#*=}"
  [[ "$KEY" =~ ^CONFIG_[A-Za-z0-9_]+$ ]] || { echo "[오류] 잘못된 config symbol: $KEY"; exit 1; }
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

for OPT in CONFIG_USB CONFIG_USB_COMMON CONFIG_CFG80211 CONFIG_MAC80211 CONFIG_RTL8XXXU CONFIG_MT76x0U CONFIG_MT76x2U CONFIG_RT2800USB CONFIG_RT2800USB_RT35XX CONFIG_RTW88_8821CU CONFIG_USBIP_CORE CONFIG_USBIP_VHCI_HCD; do
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
