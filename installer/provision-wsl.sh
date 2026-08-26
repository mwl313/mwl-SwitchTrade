#!/usr/bin/env bash
# Provision one isolated SwitchTrade WSL distribution from a packaged app tree.
set -euo pipefail

SOURCE=""
TARGET=/opt/switchtrade
MODE=install

die() { printf 'switchtrade provision: %s\n' "$*" >&2; exit 1; }

while (($#)); do
    case $1 in
        --source) [[ $# -ge 2 ]] || die "--source requires a directory"; SOURCE=$2; shift 2 ;;
        --rollback) MODE=rollback; shift ;;
        *) die "unknown argument: $1" ;;
    esac
done

((EUID == 0)) || die "run as root inside the SwitchTrade distribution"
[[ $TARGET == /opt/switchtrade ]] || die "unsafe target: $TARGET"

if [[ $MODE == rollback ]]; then
    previous=${TARGET}.previous
    swap=${TARGET}.rollback-swap
    [[ -d $TARGET && -d $previous && ! -e $swap ]] || \
        die "one retained WSL runtime and a clean swap path are required"
    mv -- "$TARGET" "$swap"
    if ! mv -- "$previous" "$TARGET"; then
        mv -- "$swap" "$TARGET"
        die "could not activate the retained WSL runtime"
    fi
    mv -- "$swap" "$previous"
    printf '[wsl] runtime rollback completed; one prior runtime remains available\n'
    exit 0
fi

[[ -d $SOURCE && -f $SOURCE/requirements.txt ]] || die "invalid packaged source: $SOURCE"

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
    ca-certificates ethtool iproute2 iw libpcap0.8 python3 python3-pip python3-venv \
    rfkill sudo tcpdump usbutils
rm -rf /var/lib/apt/lists/*
python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' || \
    die "Python 3.12 or newer is required by the pinned LDN runtime"

stage=$(mktemp -d /opt/switchtrade.new.XXXXXX)
cleanup() { rm -rf -- "$stage"; }
trap cleanup EXIT
cp -a "$SOURCE/." "$stage/"
python3 -m venv "$stage/bridge/.venv"
"$stage/bridge/.venv/bin/python" -m pip install --disable-pip-version-check \
    --requirement "$stage/bridge/requirements.txt"
find "$stage/scripts" -type f -name '*.sh' -exec chmod 0755 {} +

backup=""
if [[ -e $TARGET ]]; then
    backup="${TARGET}.previous"
    rm -rf -- "$backup"
    mv -- "$TARGET" "$backup"
    printf '[wsl] previous runtime retained at %s\n' "$backup"
fi
if ! mv -- "$stage" "$TARGET"; then
    [[ -z $backup || ! -d $backup ]] || mv -- "$backup" "$TARGET"
    die "could not activate the staged runtime; the previous runtime was restored"
fi
trap - EXIT

"$TARGET/bridge/.venv/bin/python" -m switchtrade.endpoint \
    --role host --session-id PROBE1 --relay-url http://127.0.0.1:9 --dry-run
printf '[wsl] SwitchTrade runtime provisioned at %s\n' "$TARGET"
