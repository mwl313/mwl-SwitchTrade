#!/usr/bin/env bash
# Profile-gated WSL entry point for the feature-neutral SwitchTrade endpoint.
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
PREP="$ROOT/scripts/wsl-radio-prepare.sh"
PYTHON_BIN=${SWITCHTRADE_PYTHON:-"$ROOT/bridge/.venv/bin/python"}
WATCHDOG=${SWITCHTRADE_ENDPOINT_TIMEOUT:-10800}

die() { printf 'switchtrade: %s\n' "$*" >&2; exit 1; }

role=""
usb_id=""
channel=6
args=("$@")
while [[ $# -gt 0 ]]; do
    case $1 in
        --role) [[ $# -ge 2 ]] || die "--role requires host|guest"; role=$2; shift ;;
        --role=*) role=${1#*=} ;;
        --usb-id) [[ $# -ge 2 ]] || die "--usb-id requires VID:PID"; usb_id=${2,,}; shift ;;
        --usb-id=*) usb_id=${1#*=}; usb_id=${usb_id,,} ;;
        --channel) [[ $# -ge 2 ]] || die "--channel requires 1..13"; channel=$2; shift ;;
        --channel=*) channel=${1#*=} ;;
    esac
    shift
done

[[ $role == host || $role == guest ]] || die "--role host|guest is required"
[[ $channel =~ ^([1-9]|1[0-3])$ ]] || die "channel must be 1..13"
[[ -x $PREP ]] || die "radio selector missing: $PREP"
[[ -x $PYTHON_BIN ]] || PYTHON_BIN=$(command -v python3 || true)
[[ -n $PYTHON_BIN ]] || die "Python runtime not found"
command -v timeout >/dev/null 2>&1 || die "GNU timeout is required"

# Online host sits beside the leader Switch and joins its room; online guest
# hosts the mirrored room beside the joining Switch.
radio_role=guest
[[ $role == guest ]] && radio_role=host

gate=("$PREP")
[[ -z $usb_id ]] || gate+=(--usb-id "$usb_id")
gate+=(--role "$radio_role" --target-channel "$channel" --)

export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
exec "${gate[@]}" timeout --foreground -k 15 "$WATCHDOG" \
    "$PYTHON_BIN" -m switchtrade.endpoint "${args[@]}"
