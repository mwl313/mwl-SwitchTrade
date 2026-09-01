#!/usr/bin/env bash
# Select a supported WSL USB radio, ensure its driver, then require actual RX before COMMAND.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSFS_ROOT="${SWITCHTRADE_SYSFS_ROOT:-/sys}"
DEV_ROOT="${SWITCHTRADE_DEV_ROOT:-/dev}"
LOG_FD="${SWITCHTRADE_LOG_FD:-1}"
LOCK_ROOT="${SWITCHTRADE_LOCK_ROOT:-/run/lock}"
PROFILE_FILE="${SWITCHTRADE_RADIO_PROFILES:-$SCRIPT_DIR/../config/wsl-radio-hardware.tsv}"
HEALTH_GATE="$SCRIPT_DIR/radio-health-gate.sh"
USB_ID="${RADIO_USB_ID:-}"
USB_DEVICE="${RADIO_USB_DEVICE:-}"
MODULE_DIR="${SWITCHTRADE_MODULE_DIR:-}"
HEALTH_CHANNELS="${RADIO_HEALTH_CHANNELS:-1,6,11}"
TARGET_CHANNEL="${RADIO_TARGET_CHANNEL:-6}"
RX_TIMEOUT="${RADIO_HEALTH_TIMEOUT:-2}"
DRIVER_PROBE_TIMEOUT="${RADIO_DRIVER_PROBE_TIMEOUT:-30}"
REQUIRED_ROLE="${RADIO_ROLE:-}"
RESET_ON_RX_FAILURE=0
MODE=ensure

msg() { printf '%s\n' "$*" >&"$LOG_FD"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

usage() {
    cat <<'EOF'
Usage:
  sudo wsl-radio-prepare.sh [options] [-- COMMAND...]
  wsl-radio-prepare.sh --list-profiles
  wsl-radio-prepare.sh --status

Options:
  --usb-id VID:PID       Select a card when more than one supported radio is attached
  --device-path PATH     Select the exact attached sysfs USB device (dual-radio diagnostics)
  --profile-file PATH    Hardware profile table override
  --module-dir PATH      Directory containing profile module + optional .sha256
  --health-channels CSV  Actual-RX channels (default: 1,6,11)
  --target-channel N     Channel left configured for COMMAND (default: 6)
  --timeout SECONDS      Per-channel health timeout (default: 2)
  --role ROLE            Require a profile role: host, guest, or relay
  --reset-on-rx-failure  Explicit recovery: USB-reset once after an RX timeout
  --allow-experimental-hardware
                         Deprecated compatibility flag; candidates no longer require confirmation
  --driver-only          Prepare and validate the profile driver, then exit before RX health
  --status               Report attached USB devices/drivers without mutation
  --list-profiles        Print supported profiles without mutation
EOF
}

normalize_usb_id() {
    printf '%s\n' "${1,,}"
}

profile_for() {
    local wanted=$1
    awk -F '\t' -v wanted="$wanted" '
        $0 !~ /^#/ && NF >= 8 && tolower($1) == wanted { print; found=1; exit }
        END { if (!found) exit 1 }
    ' "$PROFILE_FILE"
}

list_profiles() {
    awk -F '\t' '
        BEGIN { printf "%-10s %-20s %-20s %-18s %-20s %-5s %-24s\n", "USB_ID", "STRATEGY", "DRIVERS", "ROLES", "STATUS", "AUTO", "ENGINE" }
        $0 !~ /^#/ && NF >= 8 { printf "%-10s %-20s %-20s %-18s %-20s %-5s %-24s\n", $1, $2, $4, $5, $6, $7, (NF >= 11 ? $11 : "ldn") }
    ' "$PROFILE_FILE"
}

usb_id_of_device() {
    local dev=$1
    [[ -r $dev/idVendor && -r $dev/idProduct ]] || return 1
    printf '%s:%s\n' "$(<"$dev/idVendor")" "$(<"$dev/idProduct")" | tr '[:upper:]' '[:lower:]'
}

attached_usb_devices() {
    local f dev id
    for f in "$SYSFS_ROOT"/bus/usb/devices/*/idVendor; do
        [[ -r $f ]] || continue
        dev="$(dirname "$f")"
        [[ ! -r $dev/bDeviceClass || $(<"$dev/bDeviceClass") != 09 ]] || continue
        id="$(usb_id_of_device "$dev")" || continue
        printf '%s\t%s\n' "$id" "$dev"
    done
}

ifaces_for_device() {
    local dev_real name path
    dev_real="$(readlink -f "$1")"
    for name in "$SYSFS_ROOT"/class/net/*; do
        [[ -e $name/device ]] || continue
        path="$(readlink -f "$name/device")"
        case $path in
            "$dev_real"/*|"$dev_real":*) basename "$name" ;;
        esac
    done
}

preferred_iface_for_device() {
    local device=$1 iface first="" type
    while read -r iface; do
        [[ -n $first ]] || first=$iface
        type="$(iw dev "$iface" info 2>/dev/null | awk '$1 == "type" { print $2; exit }')"
        if [[ $type == monitor ]]; then
            printf '%s\n' "$iface"
            return 0
        fi
    done < <(ifaces_for_device "$device")
    [[ -n $first ]] || return 1
    printf '%s\n' "$first"
}

phy_for_device() {
    local dev_real link path
    dev_real="$(readlink -f "$1")"
    for link in "$SYSFS_ROOT"/class/ieee80211/*/device; do
        [[ -e $link ]] || continue
        path="$(readlink -f "$link")"
        case $path in
            "$dev_real"/*|"$dev_real":*) basename "$(dirname "$link")"; return 0 ;;
        esac
    done
    return 1
}

recreate_monitor_iface() {
    local device=$1 phy candidate iface
    phy="$(phy_for_device "$device")" || return 1
    candidate="stmon${phy#phy}"
    if ip link show "$candidate" >/dev/null 2>&1; then
        candidate="st${phy#phy}mon"
    fi
    printf '%s\n' "[driver] $phy has no netdev; recreating monitor interface $candidate" >&2
    iw phy "$phy" interface add "$candidate" type monitor || return 1
    for _ in {1..20}; do
        iface="$(preferred_iface_for_device "$device" 2>/dev/null || true)"
        [[ -n $iface ]] && { printf '%s\n' "$iface"; return 0; }
        sleep 0.1
    done
    return 1
}

remove_extra_ifaces() {
    local device=$1 keep=$2 iface
    while read -r iface; do
        [[ $iface == "$keep" ]] && continue
        msg "[driver] removing stale extra interface $iface"
        ip link set "$iface" down 2>/dev/null || true
        iw dev "$iface" del || die "could not remove stale interface $iface"
        [[ ! -e $SYSFS_ROOT/class/net/$iface ]] || die "stale interface still exists after delete: $iface"
    done < <(ifaces_for_device "$device")
}

driver_for_device() {
    local dev_real intf link
    dev_real="$(readlink -f "$1")"
    for intf in "$dev_real"/*:*; do
        [[ -L $intf/driver ]] || continue
        link="$(readlink -f "$intf/driver")"
        basename "$link"
        return 0
    done
    return 1
}

driver_allowed() {
    local driver=$1 allowed=$2 item
    IFS=',' read -ra items <<< "$allowed"
    for item in "${items[@]}"; do
        [[ $driver == "$item" ]] && return 0
    done
    return 1
}

wait_for_bound_iface() {
    local device=$1 expected_driver=$2 iface observed_driver
    local deadline=$((SECONDS + DRIVER_PROBE_TIMEOUT))
    # usbipd exposes the USB sysfs device before an already-loaded Wi-Fi driver has
    # finished probing it.  RTL8192EU commonly needs several seconds to read EFuse,
    # load firmware, register its PHY, and finally create the netdev.  Treat that as
    # an in-progress probe, not as a missing interface that needs recreation.
    while ((SECONDS < deadline)); do
        iface="$(preferred_iface_for_device "$device" 2>/dev/null || true)"
        if [[ -n $iface ]]; then
            printf '%s\n' "$iface"
            return 0
        fi
        observed_driver="$(driver_for_device "$device" 2>/dev/null || true)"
        [[ $observed_driver == "$expected_driver" ]] || return 1
        sleep 0.2
    done
    return 1
}

role_allowed() {
    local role=$1 allowed=$2 item
    IFS=',' read -ra items <<< "$allowed"
    for item in "${items[@]}"; do
        [[ $role == "$item" ]] && return 0
    done
    return 1
}

resolve_module() {
    local filename=$1 candidate
    if [[ -n $MODULE_DIR ]]; then
        candidate="$MODULE_DIR/$filename"
        [[ -s $candidate ]] && { printf '%s\n' "$candidate"; return 0; }
    fi
    for candidate in \
        "/lib/modules/$(uname -r)/extra/$filename" \
        "/mnt/c/wsl-kernel/modules/$(uname -r)/$filename" \
        "/mnt/c/wsl-kernel/$filename"; do
        [[ -s $candidate ]] && { printf '%s\n' "$candidate"; return 0; }
    done
    return 1
}

verify_module() {
    local module=$1 expected actual vermagic
    command -v modinfo >/dev/null 2>&1 || die "modinfo is required"
    vermagic="$(modinfo -F vermagic "$module" | awk '{print $1}')"
    [[ $vermagic == "$(uname -r)" ]] || die "module kernel mismatch: $vermagic != $(uname -r)"
    if [[ -s $module.sha256 ]]; then
        expected="$(awk 'NR==1 {print tolower($1)}' "$module.sha256")"
        actual="$(sha256sum "$module" | awk '{print tolower($1)}')"
        [[ $expected == "$actual" ]] || die "module checksum mismatch: $module"
    else
        msg "[driver] warning: no checksum sidecar for $module"
    fi
}

verify_loaded_module() {
    local module=$1 driver=$2 expected_name expected_src loaded_src
    verify_module "$module"
    expected_name="$(modinfo -F name "$module")"
    [[ $driver == "$expected_name" ]] || die "profile module $expected_name does not match loaded driver $driver"
    expected_src="$(modinfo -F srcversion "$module")"
    loaded_src="$(cat "$SYSFS_ROOT/module/$driver/srcversion" 2>/dev/null || true)"
    [[ -n $expected_src && $loaded_src == "$expected_src" ]] || \
        die "loaded $driver is not the profiled module artifact (srcversion mismatch)"
}

loaded_module_name() {
    # modprobe accepts dashes while sysfs/lsmod normally expose underscores.
    printf '%s\n' "${1//-/_}"
}

load_prerequisite_module() {
    local requested=$1 loaded module_path vermagic
    loaded="$(loaded_module_name "$requested")"
    msg "[prerequisite] loading $requested"
    modprobe "$requested" || die "MODULE_LOAD_FAILED: could not load $requested"
    [[ -d $SYSFS_ROOT/module/$loaded ]] || \
        die "MODULE_NOT_LOADED: $requested has no loaded sysfs module"
    module_path="$(modinfo -n "$requested" 2>/dev/null || true)"
    if [[ -n $module_path && $module_path != '(builtin)' ]]; then
        vermagic="$(modinfo -F vermagic "$requested" 2>/dev/null | awk '{print $1}')"
        [[ $vermagic == "$(uname -r)" ]] || \
            die "MODULE_VERMAGIC_MISMATCH: $requested $vermagic != $(uname -r)"
    fi
}

select_device() {
    local id dev dev_real requested_real profile auto_select candidates=()
    if [[ -n $USB_DEVICE ]]; then
        requested_real="$(readlink -f "$USB_DEVICE" 2>/dev/null || true)"
        [[ -n $requested_real && -d $requested_real ]] || \
            die "exact USB device path is unavailable"
    fi
    while IFS=$'\t' read -r id dev; do
        profile="$(profile_for "$id" 2>/dev/null)" || continue
        if [[ -n $USB_ID && $id != "$USB_ID" ]]; then
            continue
        fi
        if [[ -n $USB_DEVICE ]]; then
            dev_real="$(readlink -f "$dev" 2>/dev/null || true)"
            [[ $dev_real == "$requested_real" ]] || continue
        fi
        IFS=$'\t' read -r _ _ _ _ _ _ auto_select _ <<< "$profile"
        if [[ -z $USB_ID && $auto_select != yes ]]; then
            continue
        fi
        candidates+=("$id"$'\t'"$dev")
    done < <(attached_usb_devices)
    ((${#candidates[@]} > 0)) || die "no auto-selectable attached USB radio${USB_ID:+ matching $USB_ID}${USB_DEVICE:+ at the exact device path}"
    ((${#candidates[@]} == 1)) || die "multiple eligible radios attached; attach one radio per WSL endpoint (VID:PID cannot distinguish identical adapters)"
    printf '%s\n' "${candidates[0]}"
}

status_report() {
    local id dev iface driver support
    while IFS=$'\t' read -r id dev; do
        if profile_for "$id" >/dev/null 2>&1; then support=supported; else support=unknown; fi
        iface="$(ifaces_for_device "$dev" | paste -sd, -)"
        driver="$(driver_for_device "$dev" 2>/dev/null || true)"
        printf '%s dev=%s support=%s driver=%s iface=%s\n' \
            "$id" "$(basename "$dev")" "$support" "${driver:-unbound}" "${iface:-none}"
    done < <(attached_usb_devices)
}

while (($#)); do
    case $1 in
        --usb-id) [[ $# -ge 2 ]] || die "--usb-id needs a value"; USB_ID="$(normalize_usb_id "$2")"; shift 2 ;;
        --device-path) [[ $# -ge 2 ]] || die "--device-path needs a value"; USB_DEVICE=$2; shift 2 ;;
        --profile-file) [[ $# -ge 2 ]] || die "--profile-file needs a value"; PROFILE_FILE=$2; shift 2 ;;
        --module-dir) [[ $# -ge 2 ]] || die "--module-dir needs a value"; MODULE_DIR=$2; shift 2 ;;
        --health-channels) [[ $# -ge 2 ]] || die "--health-channels needs a value"; HEALTH_CHANNELS=$2; shift 2 ;;
        --target-channel) [[ $# -ge 2 ]] || die "--target-channel needs a value"; TARGET_CHANNEL=$2; shift 2 ;;
        --timeout) [[ $# -ge 2 ]] || die "--timeout needs a value"; RX_TIMEOUT=$2; shift 2 ;;
        --role) [[ $# -ge 2 ]] || die "--role needs a value"; REQUIRED_ROLE=$2; shift 2 ;;
        --reset-on-rx-failure) RESET_ON_RX_FAILURE=1; shift ;;
        --allow-experimental-hardware) shift ;;
        --driver-only) MODE=driver; shift ;;
        --status) MODE=status; shift ;;
        --list-profiles) MODE=profiles; shift ;;
        -h|--help) usage; exit 0 ;;
        --) shift; break ;;
        *) die "unknown argument: $1" ;;
    esac
done

[[ -r $PROFILE_FILE ]] || die "profile table not found: $PROFILE_FILE"
[[ $(uname -r) == *microsoft* ]] || die "this driver selector is for WSL2"

case $MODE in
    profiles) list_profiles; exit 0 ;;
    status) status_report; exit 0 ;;
esac

((EUID == 0)) || [[ $SYSFS_ROOT != /sys ]] || die "run as root"
[[ $DRIVER_PROBE_TIMEOUT =~ ^[1-9][0-9]*$ ]] || \
    die "RADIO_DRIVER_PROBE_TIMEOUT must be a positive integer"
[[ -x $HEALTH_GATE ]] || die "health gate not executable: $HEALTH_GATE"

selection="$(select_device)"
IFS=$'\t' read -r USB_ID DEVICE <<< "$selection"
command -v flock >/dev/null 2>&1 || die "flock is required for exclusive radio ownership"
mkdir -p "$LOCK_ROOT"
LOCK_PATH="$LOCK_ROOT/switchtrade-radio-${USB_ID//:/-}.lock"
if [[ -n $USB_DEVICE ]]; then
    device_lock_id="$(printf '%s' "$(readlink -f "$DEVICE")" | sha256sum | awk '{print $1}')"
    LOCK_PATH="$LOCK_ROOT/switchtrade-radio-$device_lock_id.lock"
fi
exec 9>"$LOCK_PATH"
flock -n 9 || die "RADIO_BUSY: another SwitchTrade endpoint, diagnostic, or repair owns $USB_ID"
profile="$(profile_for "$USB_ID")"
IFS=$'\t' read -r _ strategy module_file allowed_drivers roles status auto_select _notes _model _chipset host_engine _evidence <<< "$profile"
host_engine=${host_engine:-ldn}
case $status in
    production-verified|beta-candidate) ;;
    upstream-candidate|driver-candidate) ;;
    quarantined) die "HARDWARE_QUARANTINED: $USB_ID cannot be used for a trading attempt" ;;
    *) die "HARDWARE_STATUS_BLOCKED: unknown profile status $status for $USB_ID" ;;
esac
[[ $host_engine == ldn ]] || die \
    "HOST_ENGINE_IN_DEVELOPMENT: $host_engine cannot be selected; use ldn"
if [[ -n $REQUIRED_ROLE ]]; then
    case $REQUIRED_ROLE in host|guest|relay) ;; *) die "invalid role: $REQUIRED_ROLE" ;; esac
    role_allowed "$REQUIRED_ROLE" "$roles" || die "$USB_ID does not support role $REQUIRED_ROLE (roles=$roles)"
fi

# P0b has a single, explicit dependency order. Do not rely on call-site autoloading:
# the packaged WSL kernel has previously exposed missing crypto/TUN modules only after
# ldn.connect() or ldn.create_network() had already started.
load_prerequisite_module usbip-core
load_prerequisite_module vhci-hcd
load_prerequisite_module cfg80211
load_prerequisite_module libarc4
load_prerequisite_module mac80211
load_prerequisite_module led-class
iface="$(preferred_iface_for_device "$DEVICE" 2>/dev/null || true)"
driver="$(driver_for_device "$DEVICE" 2>/dev/null || true)"

if [[ -z $iface && -n $driver ]]; then
    msg "[driver] waiting for in-progress $driver probe to create its interface"
    iface="$(wait_for_bound_iface "$DEVICE" "$driver" 2>/dev/null || true)"
    driver="$(driver_for_device "$DEVICE" 2>/dev/null || true)"
    if [[ -z $iface && -n $driver ]] && ! phy_for_device "$DEVICE" >/dev/null 2>&1; then
        die "DRIVER_PROBE_TIMEOUT: $driver did not create a PHY or interface within ${DRIVER_PROBE_TIMEOUT}s"
    fi
fi

if [[ -z $iface && -n $driver ]]; then
    iface="$(recreate_monitor_iface "$DEVICE")" || \
        die "$USB_ID is bound to $driver but its missing monitor interface could not be recreated"
fi

if [[ -z $iface ]]; then
    before="$(dmesg | wc -l)"
    if [[ $strategy == vanilla ]]; then
        module_name="${allowed_drivers%%,*}"
        msg "[driver] cold-loading in-tree module $module_name for $USB_ID"
        modprobe "$module_name" || die "could not load in-tree module $module_name for $USB_ID"
    else
        [[ $strategy == vanilla-then-module ]] || die "unsupported driver strategy $strategy for $USB_ID"
        module="$(resolve_module "$module_file")" || die "module not found for $USB_ID: $module_file"
        verify_module "$module"
        module_name="$(modinfo -F name "$module")"
    fi
    if [[ $strategy == vanilla-then-module ]] && ! lsmod | awk '{print $1}' | grep -qx "$module_name"; then
        msg "[driver] loading $module_name for $USB_ID from $module"
        insmod "$module"
    fi
    for _ in {1..30}; do
        iface="$(preferred_iface_for_device "$DEVICE" 2>/dev/null || true)"
        [[ -n $iface ]] && break
        sleep 0.5
    done
    [[ -n $iface ]] || die "$module_name loaded but $USB_ID produced no interface"
    # Several modern-kernel compatibility faults are deferred until ndo_open.
    # Exercise that boundary before the actual-RX gate can exec the workload.
    if ! ip link set "$iface" up; then
        rmmod "$module_name" 2>/dev/null || true
        die "$module_name created $iface but failed its first interface open; rolled back"
    fi
    ip link set "$iface" down
    new_log="$(dmesg | tail -n "+$((before + 1))")"
    if grep -Eq 'Incorrect netdev->dev_addr|Firmware failed to start|probe with driver .* failed' <<< "$new_log"; then
        ip link set "$iface" down 2>/dev/null || true
        rmmod "$module_name" 2>/dev/null || true
        die "$module_name emitted a fatal compatibility warning; rolled back"
    fi
    driver="$(driver_for_device "$DEVICE" 2>/dev/null || true)"
fi

remove_extra_ifaces "$DEVICE" "$iface"

[[ -n $driver ]] || die "$USB_ID has interface $iface but no bound driver"
driver_allowed "$driver" "$allowed_drivers" || die "$USB_ID bound unexpected driver: $driver"
if [[ $module_file != - ]]; then
    profile_module="$(resolve_module "$module_file" 2>/dev/null || true)"
    if [[ -n $profile_module && $driver == "$(modinfo -F name "$profile_module")" ]]; then
        verify_loaded_module "$profile_module" "$driver"
    elif [[ $driver != rtl8xxxu ]]; then
        die "$USB_ID uses $driver but its profiled artifact $module_file is unavailable"
    fi
fi
msg "[driver] PASS usb=$USB_ID strategy=$strategy driver=$driver iface=$iface roles=$roles status=$status auto_select=$auto_select engine=$host_engine${REQUIRED_ROLE:+ required_role=$REQUIRED_ROLE}"
export SWITCHTRADE_USB_DEVICE="$(readlink -f "$DEVICE")"

load_prerequisite_module ccm
load_prerequisite_module cmac
load_prerequisite_module tun
if [[ $SYSFS_ROOT == /sys ]]; then
    [[ -c $DEV_ROOT/net/tun ]] || die "TUN_DEVICE_MISSING: $DEV_ROOT/net/tun is not a character device"
else
    [[ -e $DEV_ROOT/net/tun ]] || die "TUN_DEVICE_MISSING: $DEV_ROOT/net/tun is missing"
fi
msg "[prerequisite] PASS crypto=ccm,cmac tun=$DEV_ROOT/net/tun"

[[ $MODE != driver ]] || exit 0

health_args=()
(( RESET_ON_RX_FAILURE == 0 )) || health_args+=(--reset-on-rx-failure)
exec "$HEALTH_GATE" --iface "$iface" --usb-id "$USB_ID" \
    --health-channels "$HEALTH_CHANNELS" --target-channel "$TARGET_CHANNEL" \
    --timeout "$RX_TIMEOUT" "${health_args[@]}" -- "$@"
