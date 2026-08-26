#!/usr/bin/env bash
# Verify that a Realtek LDN radio can receive before starting a capture command.
# Usage: sudo radio-health-gate.sh [--iface IFACE] [--target-channel N] [-- COMMAND...]

set -euo pipefail

SYSFS_ROOT="${SWITCHTRADE_SYSFS_ROOT:-/sys}"
HEALTH_CHANNELS="${RADIO_HEALTH_CHANNELS:-1,6,11}"
TARGET_CHANNEL="${RADIO_TARGET_CHANNEL:-6}"
RX_TIMEOUT="${RADIO_HEALTH_TIMEOUT:-2}"
IFACE=""
EXPECTED_USB_ID=""
DRY_RUN=0
RESET_ON_RX_FAILURE=0

msg() { printf '%s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

usage() {
    cat <<'EOF'
Usage:
  sudo radio-health-gate.sh [options] [-- COMMAND...]

Options:
  --iface IFACE          Realtek radio interface (required when multiple cards exist)
  --usb-id VID:PID       Exact USB ID expected on IFACE (enables profile-added cards)
  --health-channels CSV  Receive-test channels (default: 1,6,11)
  --target-channel N     Channel left configured for COMMAND (default: 6)
  --timeout SECONDS      Per-channel receive timeout (default: 2)
  --reset-on-rx-failure  Explicit recovery: USB-reset once after an RX timeout
  --dry-run              Detect and report only; do not change the radio
  -h, --help             Show this help

The selected interface, USB ID, and PHY are exported to COMMAND as
SWITCHTRADE_IFACE, SWITCHTRADE_USB_ID, and SWITCHTRADE_PHY.
EOF
}

usb_id_of_iface() {
    local p
    p="$(readlink -f "$SYSFS_ROOT/class/net/$1/device" 2>/dev/null)" || return 1
    while [[ $p == "$SYSFS_ROOT"/* ]]; do
        if [[ -r $p/idVendor && -r $p/idProduct ]]; then
            printf '%s:%s\n' "$(<"$p/idVendor")" "$(<"$p/idProduct")"
            return 0
        fi
        p="$(dirname "$p")"
    done
    return 1
}

find_card_ifaces() {
    local name id
    for name in "$SYSFS_ROOT"/class/net/*; do
        name="$(basename "$name")"
        id="$(usb_id_of_iface "$name")" || continue
        if [[ -n $EXPECTED_USB_ID ]]; then
            [[ $id == "$EXPECTED_USB_ID" ]] && printf '%s\n' "$name"
        else
            case $id in
                0bda:8179|0bda:818b) printf '%s\n' "$name" ;;
            esac
        fi
    done
}

select_iface() {
    local id cards=()
    if [[ -n $IFACE ]]; then
        [[ -d $SYSFS_ROOT/class/net/$IFACE ]] || die "interface not found: $IFACE"
        id="$(usb_id_of_iface "$IFACE" || true)"
        if [[ -n $EXPECTED_USB_ID ]]; then
            [[ $id == "$EXPECTED_USB_ID" ]] || die "$IFACE USB ID $id != expected $EXPECTED_USB_ID"
        else
            case $id in
                0bda:8179|0bda:818b) ;;
                *) die "$IFACE is not a supported Realtek radio" ;;
            esac
        fi
        return 0
    fi
    mapfile -t cards < <(find_card_ifaces)
    (( ${#cards[@]} > 0 )) || die "no Realtek 0bda:8179/818b radio found"
    (( ${#cards[@]} == 1 )) || die "multiple radios found; pass --iface (${cards[*]})"
    IFACE="${cards[0]}"
}

card_busdev() {
    local p
    p="$(readlink -f "$SYSFS_ROOT/class/net/$IFACE/device")"
    while [[ $p == "$SYSFS_ROOT"/* ]]; do
        if [[ -r $p/busnum && -r $p/devnum ]]; then
            printf '%03d/%03d\n' "$((10#$(<"$p/busnum")))" "$((10#$(<"$p/devnum")))"
            return 0
        fi
        p="$(dirname "$p")"
    done
    return 1
}

reject_stale_capture() {
    local pid cmd
    command -v pgrep >/dev/null 2>&1 || return 0
    while read -r pid; do
        [[ -r /proc/$pid/cmdline ]] || continue
        cmd="$(tr '\0' ' ' < "/proc/$pid/cmdline")"
        [[ " $cmd " == *" -i $IFACE "* ]] && die "tcpdump already owns $IFACE (pid $pid): $cmd"
    done < <(pgrep -x tcpdump || true)
    return 0
}

configure_monitor() {
    local type
    type="$(iw dev "$IFACE" info 2>/dev/null | awk '$1=="type"{print $2; exit}')"
    if [[ $type != monitor ]]; then
        ip link set "$IFACE" down
        iw dev "$IFACE" set type monitor
    fi
    ip link set "$IFACE" up
}

has_rx() {
    local channel
    IFS=',' read -ra channels <<< "$HEALTH_CHANNELS"
    for channel in "${channels[@]}"; do
        iw dev "$IFACE" set channel "$channel"
        if timeout -s INT "$RX_TIMEOUT" tcpdump -q -i "$IFACE" -n -s 96 -c 1 \
                -w /dev/null >/dev/null 2>&1; then
            msg "[health] RX alive on channel $channel"
            return 0
        fi
    done
    return 1
}

reset_card() {
    local mac busdev
    command -v usbreset >/dev/null 2>&1 || die "usbreset is required to recover a dead radio"
    mac="$(<"$SYSFS_ROOT/class/net/$IFACE/address")"
    busdev="$(card_busdev)" || die "cannot resolve USB bus/device for $IFACE"
    msg "[health] RX dead; resetting $IFACE at $busdev"
    if ! usbreset "$busdev"; then
        if [[ $(uname -r) == *microsoft* ]]; then
            die "USB reset detached the WSL device; in elevated PowerShell re-run: usbipd attach --wsl --busid <BUSID>"
        fi
        die "USB reset failed for $IFACE at $busdev"
    fi
    for _ in {1..20}; do
        IFACE="$(find_card_ifaces | while read -r name; do
            [[ $(<"$SYSFS_ROOT/class/net/$name/address") == "$mac" ]] && { printf '%s\n' "$name"; break; }
        done)"
        [[ -n $IFACE ]] && return 0
        sleep 1
    done
    if [[ $(uname -r) == *microsoft* ]]; then
        die "radio detached from WSL USB/IP after reset; in elevated PowerShell re-run: usbipd attach --wsl --busid <BUSID>"
    fi
    die "radio did not reappear after USB reset"
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --iface) [[ $# -ge 2 ]] || die "--iface needs a value"; IFACE=$2; shift 2 ;;
        --usb-id) [[ $# -ge 2 ]] || die "--usb-id needs a value"; EXPECTED_USB_ID="${2,,}"; shift 2 ;;
        --health-channels) [[ $# -ge 2 ]] || die "--health-channels needs a value"; HEALTH_CHANNELS=$2; shift 2 ;;
        --target-channel) [[ $# -ge 2 ]] || die "--target-channel needs a value"; TARGET_CHANNEL=$2; shift 2 ;;
        --timeout) [[ $# -ge 2 ]] || die "--timeout needs a value"; RX_TIMEOUT=$2; shift 2 ;;
        --reset-on-rx-failure) RESET_ON_RX_FAILURE=1; shift ;;
        --dry-run) DRY_RUN=1; shift ;;
        -h|--help) usage; exit 0 ;;
        --) shift; break ;;
        *) die "unknown argument: $1" ;;
    esac
done

select_iface
CARD_ID="$(usb_id_of_iface "$IFACE")"
msg "[health] interface=$IFACE usb=$CARD_ID health=$HEALTH_CHANNELS target=$TARGET_CHANNEL"

if (( DRY_RUN )); then
    iw dev "$IFACE" info | awk '$1=="type" || $1=="channel"'
    exit 0
fi

(( EUID == 0 )) || [[ $SYSFS_ROOT != /sys ]] || die "run as root"
[[ $TARGET_CHANNEL =~ ^[0-9]+$ ]] || die "invalid target channel: $TARGET_CHANNEL"
(( TARGET_CHANNEL >= 1 && TARGET_CHANNEL <= 196 )) || die "target channel out of range: $TARGET_CHANNEL"
[[ $RX_TIMEOUT =~ ^[0-9]+([.][0-9]+)?$ ]] || die "invalid timeout: $RX_TIMEOUT"
[[ $HEALTH_CHANNELS =~ ^([0-9]+,)*[0-9]+$ ]] || die "invalid --health-channels: $HEALTH_CHANNELS"
command -v iw >/dev/null 2>&1 || die "iw is required"
command -v tcpdump >/dev/null 2>&1 || die "tcpdump is required"

reject_stale_capture
configure_monitor
if ! has_rx; then
    if (( RESET_ON_RX_FAILURE )); then
        reset_card
        configure_monitor
        has_rx || die "RX_UNHEALTHY: radio still receives zero frames after explicit USB recovery"
    else
        die "RX_INCONCLUSIVE: no packets were observed; retry near an active 2.4 GHz source or run explicit adapter recovery"
    fi
fi
iw dev "$IFACE" set channel "$TARGET_CHANNEL"
msg "[health] PASS; $IFACE restored to channel $TARGET_CHANNEL"

PHY="$(basename "$(readlink -f "$SYSFS_ROOT/class/net/$IFACE/phy80211" 2>/dev/null)")"
[[ $PHY =~ ^phy[0-9]+$ ]] || die "PHY_UNRESOLVED: could not resolve the radio PHY for $IFACE"
export SWITCHTRADE_IFACE="$IFACE"
export SWITCHTRADE_USB_ID="$CARD_ID"
export SWITCHTRADE_PHY="$PHY"
(( $# == 0 )) || exec "$@"
