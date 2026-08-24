#!/usr/bin/env bash
#
# run_trade.sh v7 — frlgtrade.py 실행 래퍼 (CRITICAL-2 / WP-G, docs/plan/2026-08-22-audit-fix-plan.md)
#
# v5(VM 전용 ~/frlg-ldn-trade/run_trade.sh — **폐기**) 대비 변경점:
#   1. emu 탐색을 SCRIPT_DIR 기준으로 변경: $SCRIPT_DIR/../emu/frlgtrade.py 우선.
#      v5는 구 클론 경로 /home/aria/frlg-ldn-trade/frlgtrade.py 하드코딩 → 최신 패치 무시.
#      EMU_DIR 환경변수 오버라이드 지원 — 클론/배포 위치 무관 동작.
#   2. radio-health-gate.sh가 실제 RX를 먼저 확인하고, RX 0일 때만 USB 리셋한다.
#      정상 카드를 매 실행마다 리셋하지 않는다(WSL2 USB/IP detach 및 재열거 리스크 방지).
#   3. --phy 강제 전달 제거 — frlgtrade의 C-2 USB ID 자동감지에 위임.
#      사용자가 --phy를 인자로 직접 넘기면 "$@" 경유로 그대로 전달됨.
#      (v5의 phy0 폴백은 금지된 폴백 — 틀린 phy로 조인 시도하면 아무것도 잡히지 않음)
#   4. 실행 전 stale frlgtrade.py 프로세스 정리 (docs/09-testing-audit D-9).
#   5. 본체 워치독: timeout 900 — VM hang 최후 방어 (아래 [run] 주석의 근거 참조).
#   6. 종료 후 카드 인터페이스 up 복구 유지.
#   7. --dry-run: 카드 감지 / emu 경로 / phy 상태만 출력하고 실행하지 않음
#      (Mac 오프라인 검증용 — Mac엔 카드가 없으므로 "미감지"가 정상 출력).
#   8. radio-health-gate.sh로 실제 RX를 확인한 뒤에만 frlgtrade 시작.
#
# *** 적용은 VM 배포 후 ***: 이 스크립트는 프로젝트 리포에서 관리되며 tar+scp로 VM에
# 배포해야 실제 트레이드에 쓰인다 (plan §5.0). VM에 남은 구 v5 래퍼는 폐기 — 사용 금지.
#
# 사용법 (VM, root):
#   sudo PYTHON_BIN=/home/aria/ldnvenv/bin/python bash ~/scripts/run_trade.sh \
#        --live --verbose --keys /root/.switch/prod.keys --trades 3 --slots 0,1,2 \
#        -o /home/aria/mons/received_trade.pk3 /home/aria/mons/*.pk3
#   검증:  sudo bash ~/scripts/run_trade.sh --dry-run
# 환경변수:
#   EMU_DIR     emu 디렉터리 (기본: 스크립트 위치 기준 ../emu)
#   PYTHON_BIN  실행 파이썬 (기본: $EMU_DIR/.venv/bin/python, 없으면 python3)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
if [[ -z ${EMU_DIR:-} ]]; then
    if [[ -f "$SCRIPT_DIR/../emu/frlgtrade.py" ]]; then
        EMU_DIR="$SCRIPT_DIR/../emu"
    elif [[ -f "/home/aria/emu/frlgtrade.py" ]]; then
        EMU_DIR="/home/aria/emu"          # VM 표준 배포 위치 (~/에 래퍼를 놓을 때)
    else
        echo "ERROR: emu/frlgtrade.py not found — set EMU_DIR" >&2; exit 2
    fi
fi
readonly EMU_DIR
readonly EMU_PY="$EMU_DIR/frlgtrade.py"
readonly HEALTH_GATE="$SCRIPT_DIR/radio-health-gate.sh"
readonly WSL_RADIO_PREP="$SCRIPT_DIR/wsl-radio-prepare.sh"
readonly WATCHDOG_TIMEOUT=900                  # 15분 — 트레이드 1세션 실측 러닝타임의 충분한 상한

msg() { printf '%s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

usage() {
    cat <<EOF
run_trade.sh v7 — frlgtrade.py 실행 래퍼 (CRITICAL-2)

사용법:
  sudo bash run_trade.sh [--live ...] [frlgtrade.py 인자...]   # 트레이드 실행 (root 필수)
  sudo bash run_trade.sh --radio-usb-id 0bda:818b [--live ...] # WSL에서 카드 2개 이상일 때
  run_trade.sh --dry-run                                      # 상태만 출력, 실행 안 함
  run_trade.sh --help

환경변수:
  EMU_DIR     emu 디렉터리 (기본: $SCRIPT_DIR/../emu)
  PYTHON_BIN  실행 파이썬 (기본: \$EMU_DIR/.venv/bin/python, 없으면 python3)
  RADIO_USB_ID WSL 카드 선택 VID:PID (--radio-usb-id와 동일)
EOF
}

# --- 카드 감지 -------------------------------------------------------------------------------

find_card_dev() {
    # sysfs 역탐색: idVendor/idProduct로 USB 장치 디렉터리를 찾아 출력 (lsusb 부재/무검칠 때의 폴백).
    local f d id
    [[ -d /sys/bus/usb/devices ]] || return 1
    for f in /sys/bus/usb/devices/*/idVendor; do
        [[ -r $f ]] || continue
        d="$(dirname "$f")"
        [[ -r $d/idProduct ]] || continue
        id="$(<"$f"):$(<"$d/idProduct")"
        if [[ -n ${RADIO_USB_ID:-} ]]; then
            [[ $id == "${RADIO_USB_ID,,}" ]] || continue
            printf '%s\n' "$d"
            return 0
        fi
        case "$id" in
            0bda:8179|0bda:818b)
                printf '%s\n' "$d"; return 0
                ;;
        esac
    done
    return 1
}

detect_card_phy() {
    # frlgtrade C-2 detect_phy의 bash 미러: USB ID로 현재 wiphy를 찾아 "phyN usbid" 출력.
    # USB 리셋마다 wiphy 번호가 증가하므로(phy0→1→2…) 절대 하드코딩하지 않는다.
    local link phy usbid
    [[ -d /sys/class/ieee80211 ]] || return 1
    for link in /sys/class/ieee80211/*/device; do
        [[ -e $link ]] || continue
        phy="$(basename "$(dirname "$link")")"
        usbid="$(usb_id_of_syspath "$link")" || continue
        if [[ -n ${RADIO_USB_ID:-} ]]; then
            [[ $usbid == "${RADIO_USB_ID,,}" ]] || continue
            printf '%s %s\n' "$phy" "$usbid"
            return 0
        fi
        case "$usbid" in
            0bda:8179|0bda:818b)
                printf '%s %s\n' "$phy" "$usbid"; return 0
                ;;
        esac
    done
    return 1
}

usb_id_of_syspath() {
    # sysfs 경로의 vendor:product. device 링크는 USB *인터페이스*를 가리키므로
    # idVendor/idProduct가 나올 때까지 상위로 거슬러 올라간다 (frlgtrade._phy_usb_id 동일).
    local p
    p="$(readlink -f "$1" 2>/dev/null)" || return 1
    while [[ $p == /sys/* ]]; do
        if [[ -r $p/idVendor && -r $p/idProduct ]]; then
            printf '%s:%s\n' "$(<"$p/idVendor")" "$(<"$p/idProduct")"
            return 0
        fi
        p="$(dirname "$p")"
    done
    return 1
}

restore_ifaces_up() {
    # 종료 후 카드 인터페이스 up 복구 유지 (best-effort — 실패해도 스크립트는 계속).
    local dev n found=0
    command -v ip >/dev/null 2>&1 || return 0
    dev="$(find_card_dev)" || { msg "[restore] 카드 미감지 — up 복구 생략"; return 0; }
    for n in "$dev"/*/net/*; do
        [[ -d $n ]] || continue
        n="$(basename "$n")"
        if ip link set "$n" up 2>/dev/null; then
            msg "[restore] $n up"
        else
            msg "[restore] $n up 실패 (무시)"
        fi
        found=1
    done
    [[ $found -eq 1 ]] || msg "[restore] 카드 netdev 미발견 — up 복구 생략"
    return 0
}

# --- 실행 ------------------------------------------------------------------------------------

cleanup_stale() {
    # D-9: 실패/중단 후 잔류한 이전 frlgtrade.py가 다음 실행을 간섭한다 (docs/09 D-9).
    # 패턴을 'python* <토큰>frlgtrade.py'로 한정 — 본 스크립트(bash run_trade.sh)의 커맨드라인과
    # 절대 매칭되지 않게 하기 위함 (pkill -f frlgtrade.py 단독은 인자로 경로를 넘기는
    # 호출에서 자기 자신/부모를 쏠 위험이 있다). [pP]ython은 python3/python3.N,
    # /path/bin/python 및 macOS 프레임워크 "…/MacOS/Python"까지 커버.
    local pat='[pP]ython[^ ]* +[^ ]*frlgtrade\.py'
    if pkill -INT -f "$pat" 2>/dev/null; then
        msg "[cleanup] stale frlgtrade.py에 SIGINT — 종료 대기"
        sleep 3
        pkill -KILL -f "$pat" 2>/dev/null || true
        sleep 1
    fi
}

resolve_python() {
    if [[ -z ${PYTHON_BIN:-} ]]; then
        if [[ -x $EMU_DIR/.venv/bin/python ]]; then
            PYTHON_BIN="$EMU_DIR/.venv/bin/python"
        else
            PYTHON_BIN="python3"
        fi
    fi
}

dry_run_report() {
    local dev phy
    msg "== run_trade.sh v7 --dry-run (실행하지 않음) =="
    msg "emu 경로   : $EMU_PY"
    if [[ -f $EMU_PY ]]; then
        msg "             존재 ✓"
    else
        msg "             없음 ✗ — EMU_DIR 오버라이드 확인 필요"
    fi
    msg "python     : $PYTHON_BIN"
    if command -v "$PYTHON_BIN" >/dev/null 2>&1; then
        msg "             찾음 ✓"
    else
        msg "             PATH에 없음 ✗"
    fi
    if dev="$(find_card_dev)"; then
        msg "카드(sysfs): $dev 감지 ✓"
    else
        msg "카드(sysfs): 미감지 — Mac 오프라인 검증이라면 정상 출력"
    fi
    if phy="$(detect_card_phy)"; then
        msg "phy 상태   : $phy ← frlgtrade C-2 자동감지 대상"
    else
        msg "phy 상태   : 감지 불가 (/sys/class/ieee80211 없음 또는 카드 없음)"
    fi
    msg "전달 인자  : $*"
    msg "dry-run 완료 — 리셋/실행 모두 수행하지 않음"
}

main() {
    local dry_run=0
    local radio_role=guest
    local args=()
    while [[ $# -gt 0 ]]; do
        case $1 in
            --dry-run) dry_run=1 ;;
            --radio-usb-id)
                [[ $# -ge 2 ]] || die "--radio-usb-id에 VID:PID가 필요"
                RADIO_USB_ID="${2,,}"
                shift
                ;;
            --mode)
                [[ $# -ge 2 ]] || die "--mode에 값이 필요"
                [[ $2 == host ]] && radio_role=host
                args+=("$1" "$2")
                shift
                ;;
            --mode=host) radio_role=host; args+=("$1") ;;
            -h|--help) usage; exit 0 ;;
            *) args+=("$1") ;;          # --phy 포함 나머지는 모두 frlgtrade에 그대로 전달
        esac
        shift
    done

    resolve_python

    if [[ $dry_run -eq 1 ]]; then
        dry_run_report ${args[@]+"${args[@]}"}
        return 0
    fi

    [[ ${EUID} -eq 0 ]] || die "root 권한 필요 — sudo bash $SCRIPT_DIR/run_trade.sh ..."
    [[ -f $EMU_PY ]] || die "frlgtrade.py 미발견: $EMU_PY (EMU_DIR 환경변수로 오버라이드 가능)"
    command -v timeout >/dev/null 2>&1 || die "timeout(GNU coreutils) 필요 — VM에서 실행하세요"

    cleanup_stale

    trap restore_ifaces_up EXIT

    # 본체 워치독 — VM hang 최후 방어.
    # 근거: ldn.scan 커널 레벨 hang으로 VM 전체 먹통 4회 실측 (docs/04 #5), 그리고
    # docs/09 D-1 — fail_after는 checkpoint에서만 발동해 커널 blocking hang에는 무력.
    # -k 15: hang한 런이 SIGTERM을 무시할 수 있어 15초 후 SIGKILL로 마무리.
    local gate=()
    if [[ $(uname -r) == *microsoft* ]]; then
        # WSL does not reliably autoload these modular dependencies from the nl80211/TAP
        # call sites. Without them LDN fails late with NEW_KEY ENOENT or missing /dev/net/tun.
        modprobe ccm || die "WSL CCMP module(ccm) load failed"
        modprobe cmac || die "WSL CMAC module load failed"
        modprobe tun || die "WSL TUN/TAP module load failed"
        [[ -c /dev/net/tun ]] || die "WSL TUN/TAP device missing after modprobe tun"
        [[ -x $WSL_RADIO_PREP ]] || die "WSL radio selector 미발견/실행불가: $WSL_RADIO_PREP"
        gate=("$WSL_RADIO_PREP")
        [[ -z ${RADIO_USB_ID:-} ]] || gate+=(--usb-id "$RADIO_USB_ID")
        gate+=(--role "$radio_role")
    else
        [[ -x $HEALTH_GATE ]] || die "RX health gate 미발견/실행불가: $HEALTH_GATE"
        gate=("$HEALTH_GATE")
    fi
    gate+=(--target-channel "${RADIO_TARGET_CHANNEL:-6}" --)

    msg "[run] ${gate[*]} timeout --foreground ${WATCHDOG_TIMEOUT}s $PYTHON_BIN $EMU_PY ${args[*]+"${args[*]}"}"
    set +e
    # Keep the live process in the terminal foreground group so Ctrl-C reaches it.  Plain GNU timeout
    # creates a separate process group here; bash then consumes the terminal SIGINT while waiting and
    # the radio process continues until the 900s watchdog (reproduced in the parent-NI live run).
    "${gate[@]}" timeout --foreground -k 15 "$WATCHDOG_TIMEOUT" "$PYTHON_BIN" "$EMU_PY" ${args[@]+"${args[@]}"}
    local rc=$?
    set -e
    if (( rc == 124 || rc == 137 )); then
        msg "[watchdog] 종료코드 $rc — 본체 워치독(${WATCHDOG_TIMEOUT}s)이 hang 런을 강제 종료했다"
    fi
    return "$rc"
}

main "$@"
