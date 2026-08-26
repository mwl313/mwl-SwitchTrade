#!/usr/bin/env bash
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PREP="$REPO/scripts/wsl-radio-prepare.sh"
TEST_ROOT="$(mktemp -d)"
trap 'case $TEST_ROOT in "${TMPDIR:-/tmp}"/*|/tmp/*) rm -rf -- "$TEST_ROOT" ;; esac' EXIT

fail() { printf 'radio workflow test: %s\n' "$*" >&2; exit 1; }
assert_contains() { grep -Fq -- "$2" "$1" || fail "expected '$2' in $1"; }

new_case() {
    local case_root="$TEST_ROOT/$1" fake
    mkdir -p "$case_root/sys/bus/usb/devices/1-1/1-1:1.0" \
        "$case_root/sys/class/net" "$case_root/sys/class/ieee80211" \
        "$case_root/sys/drivers/rtl8xxxu" "$case_root/bin" "$case_root/locks"
    printf '0bda\n' > "$case_root/sys/bus/usb/devices/1-1/idVendor"
    printf '818b\n' > "$case_root/sys/bus/usb/devices/1-1/idProduct"
    printf '00\n' > "$case_root/sys/bus/usb/devices/1-1/bDeviceClass"
    printf '1\n' > "$case_root/sys/bus/usb/devices/1-1/busnum"
    printf '2\n' > "$case_root/sys/bus/usb/devices/1-1/devnum"
    : > "$case_root/dmesg.log"
    : > "$case_root/timeout.count"

    fake="$case_root/bin/uname"
    printf '%s\n' '#!/usr/bin/env bash' 'printf "6.18.0-microsoft-standard-WSL2\\n"' > "$fake"
    fake="$case_root/bin/modprobe"
    cat > "$fake" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[[ $1 == rtl8xxxu ]]
sys=$SWITCHTRADE_SYSFS_ROOT
dev="$sys/bus/usb/devices/1-1"
mkdir -p "$sys/class/net/wlan7" "$sys/class/ieee80211/phy7"
ln -sfn "$dev/1-1:1.0" "$sys/class/net/wlan7/device"
ln -sfn "$sys/class/ieee80211/phy7" "$sys/class/net/wlan7/phy80211"
ln -sfn "$dev/1-1:1.0" "$sys/class/ieee80211/phy7/device"
ln -sfn "$sys/drivers/rtl8xxxu" "$dev/1-1:1.0/driver"
printf '02:00:00:00:00:07\n' > "$sys/class/net/wlan7/address"
touch "$SWITCHTRADE_TEST_STATE/module-loaded"
if [[ ${MODPROBE_WARNING:-0} == 1 ]]; then
  printf 'rtl8xxxu 1-1:1.0: Firmware failed to start\n' >> "$SWITCHTRADE_TEST_STATE/dmesg.log"
fi
EOF
    fake="$case_root/bin/lsmod"
    cat > "$fake" <<'EOF'
#!/usr/bin/env bash
printf 'Module Size Used by\n'
[[ -e $SWITCHTRADE_TEST_STATE/module-loaded ]] && printf 'rtl8xxxu 1 0\n'
EOF
    fake="$case_root/bin/dmesg"
    cat > "$fake" <<'EOF'
#!/usr/bin/env bash
cat "$SWITCHTRADE_TEST_STATE/dmesg.log"
EOF
    fake="$case_root/bin/iw"
    cat > "$fake" <<'EOF'
#!/usr/bin/env bash
if [[ ${1:-} == dev && ${3:-} == info ]]; then
  printf 'Interface %s\n\ttype monitor\n' "$2"
fi
exit 0
EOF
    for command in ip tcpdump; do
        printf '%s\n' '#!/usr/bin/env bash' 'exit 0' > "$case_root/bin/$command"
    done
    fake="$case_root/bin/pgrep"
    printf '%s\n' '#!/usr/bin/env bash' 'exit 1' > "$fake"
    fake="$case_root/bin/timeout"
    cat > "$fake" <<'EOF'
#!/usr/bin/env bash
count=$(<"$SWITCHTRADE_TEST_STATE/timeout.count")
count=$((count + 1))
printf '%s\n' "$count" > "$SWITCHTRADE_TEST_STATE/timeout.count"
case ${RX_MODE:-pass} in
  pass) exit 0 ;;
  fail) exit 1 ;;
  recover) (( count > 3 )) ;;
esac
EOF
    fake="$case_root/bin/usbreset"
    cat > "$fake" <<'EOF'
#!/usr/bin/env bash
touch "$SWITCHTRADE_TEST_STATE/usbreset-called"
exit 0
EOF
    chmod +x "$case_root/bin"/*
    printf '%s\n' "$case_root"
}

run_prepare() {
    local case_root=$1; shift
    env PATH="$case_root/bin:$PATH" \
        SWITCHTRADE_SYSFS_ROOT="$case_root/sys" \
        SWITCHTRADE_LOCK_ROOT="$case_root/locks" \
        SWITCHTRADE_TEST_STATE="$case_root" \
        SWITCHTRADE_RADIO_PROFILES="$REPO/config/wsl-radio-hardware.tsv" \
        "$PREP" --usb-id 0bda:818b --timeout 0.01 "$@"
}

cold="$(new_case cold)"
# shellcheck disable=SC2016 # Variables intentionally expand inside the child shell.
run_prepare "$cold" -- bash -c \
    'printf "%s %s %s\n" "$SWITCHTRADE_IFACE" "$SWITCHTRADE_USB_ID" "$SWITCHTRADE_PHY"' \
    > "$cold/output" 2>&1
assert_contains "$cold/output" "cold-loading in-tree module rtl8xxxu"
assert_contains "$cold/output" "wlan7 0bda:818b phy7"

quiet="$(new_case quiet)"
if RX_MODE=fail run_prepare "$quiet" -- true > "$quiet/output" 2>&1; then
    fail "packetless normal launch unexpectedly passed"
fi
assert_contains "$quiet/output" "RX_INCONCLUSIVE"
[[ ! -e $quiet/usbreset-called ]] || fail "normal launch reset a packetless radio"

recover="$(new_case recover)"
RX_MODE=recover run_prepare "$recover" --reset-on-rx-failure -- true \
    > "$recover/output" 2>&1
[[ -e $recover/usbreset-called ]] || fail "explicit recovery did not reset the radio"
assert_contains "$recover/output" "[health] PASS"

warning="$(new_case warning)"
if MODPROBE_WARNING=1 run_prepare "$warning" -- true > "$warning/output" 2>&1; then
    fail "fatal module warning unexpectedly reached the workload"
fi
assert_contains "$warning/output" "fatal compatibility warning"

locked="$(new_case locked)"
# shellcheck disable=SC2016 # Variables intentionally expand inside the child shell.
run_prepare "$locked" -- bash -c 'touch "$SWITCHTRADE_TEST_STATE/owner-ready"; sleep 2' \
    > "$locked/owner-output" 2>&1 &
owner_pid=$!
for _ in {1..40}; do [[ -e $locked/owner-ready ]] && break; sleep 0.05; done
[[ -e $locked/owner-ready ]] || fail "lock owner did not start"
if run_prepare "$locked" -- true > "$locked/contender-output" 2>&1; then
    fail "concurrent radio owner unexpectedly passed"
fi
assert_contains "$locked/contender-output" "RADIO_BUSY"
wait "$owner_pid"

printf 'radio workflow simulation PASS\n'
