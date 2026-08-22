#!/usr/bin/env bash
#
# run_trade.sh v6 — frlgtrade.py 실행 래퍼 (CRITICAL-2 / WP-G, docs/plan/2026-08-22-audit-fix-plan.md)
#
# v5(VM 전용 ~/frlg-ldn-trade/run_trade.sh — **폐기**) 대비 변경점:
#   1. emu 탐색을 SCRIPT_DIR 기준으로 변경: $SCRIPT_DIR/../emu/frlgtrade.py 우선.
#      v5는 구 클론 경로 /home/aria/frlg-ldn-trade/frlgtrade.py 하드코딩 → 최신 패치 무시.
#      EMU_DIR 환경변수 오버라이드 지원 — 클론/배포 위치 무관 동작.
#   2. 카드 리셋 자동 감지: lsusb에서 0bda:8179(RTL8188EU) / 0bda:818b(RTL8192EU)를
#      찾아 감지된 ID로 usbreset. 못 찾으면 sysfs idVendor/idProduct 역탐색 후
#      authorized 토글(0 → 2초 → 1). v5는 0bda:8179 하드코딩(현재 카드는 818b와 불일치).
#   3. --phy 강제 전달 제거 — frlgtrade의 C-2 USB ID 자동감지에 위임.
#      사용자가 --phy를 인자로 직접 넘기면 "$@" 경유로 그대로 전달됨.
#      (v5의 phy0 폴백은 금지된 폴백 — 틀린 phy로 조인 시도하면 아무것도 잡히지 않음)
#   4. 실행 전 stale frlgtrade.py 프로세스 정리 (docs/09-testing-audit D-9).
#   5. 본체 워치독: timeout 900 — VM hang 최후 방어 (아래 [run] 주석의 근거 참조).
#   6. 종료 후 카드 인터페이스 up 복구 유지.
#   7. --dry-run: 카드 감지 / emu 경로 / phy 상태만 출력하고 실행하지 않음
#      (Mac 오프라인 검증용 — Mac엔 카드가 없으므로 "미감지"가 정상 출력).
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

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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
readonly WATCHDOG_TIMEOUT=900                  # 15분 — 트레이드 1세션 실측 러닝타임의 충분한 상한

msg() { printf '%s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

usage() {
    cat <<EOF
run_trade.sh v6 — frlgtrade.py 실행 래퍼 (CRITICAL-2)

사용법:
  sudo bash run_trade.sh [--live ...] [frlgtrade.py 인자...]   # 트레이드 실행 (root 필수)
  run_trade.sh --dry-run                                      # 상태만 출력, 실행 안 함
  run_trade.sh --help

환경변수:
  EMU_DIR     emu 디렉터리 (기본: $SCRIPT_DIR/../emu)
  PYTHON_BIN  실행 파이썬 (기본: \$EMU_DIR/.venv/bin/python, 없으면 python3)
EOF
}

# --- 카드 감지 -------------------------------------------------------------------------------

lsusb_card_id() {
    # lsusb에서 Realtek LDN 카드 ID(0bda:8179 | 0bda:818b)를 찾으면 출력, 없으면 실패.
    command -v lsusb >/dev/null 2>&1 || return 1
    local id
    id="$(lsusb 2>/dev/null | awk '/0bda:(8179|818b)/{print $6; exit}')" || true
    [[ -n $id ]] && printf '%s\n' "$id"
}

find_card_dev() {
    # sysfs 역탐색: idVendor/idProduct로 USB 장치 디렉터리를 찾아 출력 (lsusb 부재/무검칠 때의 폴백).
    local f d
    [[ -d /sys/bus/usb/devices ]] || return 1
    for f in /sys/bus/usb/devices/*/idVendor; do
        [[ -r $f ]] || continue
        [[ $(<"$f") == 0bda ]] || continue
        d="$(dirname "$f")"
        [[ -r $d/idProduct ]] || continue
        case "$(<"$d/idProduct")" in
            8179|818b) printf '%s\n' "$d"; return 0 ;;
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
        case "$usbid" in
            0bda:8179|0bda:818b) printf '%s %s\n' "$phy" "$usbid"; return 0 ;;
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

# --- 카드 리셋 -------------------------------------------------------------------------------

reset_card() {
    # *** modprobe -r rtl8xxxu 등 드라이버 재로드는 절대 금지 ***
    #   드라이버 재로드는 카드 "수신"을 사망시킨다 (2026-08-21 2회 실측, docs/04-trade-workflow #4).
    #   유일한 즉시 복구는 USB 레벨 리셋(usbreset 또는 sysfs authorized 토글)이다.
    local id dev
    if id="$(lsusb_card_id)"; then
        if command -v usbreset >/dev/null 2>&1; then
            msg "[reset] lsusb 감지: $id → usbreset"
            usbreset "$id"
            sleep 3                       # v5 실측: 리셋 후 재열거 안정화 대기 (docs/04 §4-1)
            return 0
        fi
        msg "[reset] usbreset 미설치 — sysfs authorized 토글로 대체"
    fi
    if dev="$(find_card_dev)"; then
        msg "[reset] sysfs 역탐색 감지: $dev → authorized 토글 (0 → 2s → 1)"
        echo 0 > "$dev/authorized"
        sleep 2
        echo 1 > "$dev/authorized"
        sleep 3                           # 재열거 안정화
        return 0
    fi
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
    local id dev phy
    msg "== run_trade.sh v6 --dry-run (실행하지 않음) =="
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
    if id="$(lsusb_card_id)"; then
        msg "카드(lsusb): $id 감지 ✓"
    else
        if command -v lsusb >/dev/null 2>&1; then
            msg "카드(lsusb): 미감지 — 카드 미연결이면 정상"
        else
            msg "카드(lsusb): lsusb 없음(비-Linux) — Mac 오프라인 검증이라면 정상 출력"
        fi
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
    local args=()
    while [[ $# -gt 0 ]]; do
        case $1 in
            --dry-run) dry_run=1 ;;
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

    reset_card || die "Realtek USB 카드(0bda:8179/0bda:818b) 미감지 — 연결 상태 확인 후 재시도"

    trap restore_ifaces_up EXIT

    # 본체 워치독 — VM hang 최후 방어.
    # 근거: ldn.scan 커널 레벨 hang으로 VM 전체 먹통 4회 실측 (docs/04 #5), 그리고
    # docs/09 D-1 — fail_after는 checkpoint에서만 발동해 커널 blocking hang에는 무력.
    # -k 15: hang한 런이 SIGTERM을 무시할 수 있어 15초 후 SIGKILL로 마무리.
    msg "[run] timeout ${WATCHDOG_TIMEOUT}s $PYTHON_BIN $EMU_PY ${args[*]+"${args[*]}"}"
    set +e
    timeout -k 15 "$WATCHDOG_TIMEOUT" "$PYTHON_BIN" "$EMU_PY" ${args[@]+"${args[@]}"}
    local rc=$?
    set -e
    if (( rc == 124 || rc == 137 )); then
        msg "[watchdog] 종료코드 $rc — 본체 워치독(${WATCHDOG_TIMEOUT}s)이 hang 런을 강제 종료했다"
    fi
    return "$rc"
}

main "$@"
