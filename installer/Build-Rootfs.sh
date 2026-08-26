#!/usr/bin/env bash
# Build a minimal, architecture-specific WSL rootfs. Kernel selection is intentionally external.
set -euo pipefail

SUITE=${SWITCHTRADE_ROOTFS_SUITE:-resolute}
MIRROR=${SWITCHTRADE_ROOTFS_MIRROR:-http://archive.ubuntu.com/ubuntu}
ARCH=${SWITCHTRADE_ROOTFS_ARCH:-amd64}
OUTPUT=${1:-}
SOURCE_EPOCH=${SOURCE_DATE_EPOCH:-}

die() { printf 'switchtrade rootfs: %s\n' "$*" >&2; exit 1; }

((EUID == 0)) || die "run as root in a Linux build environment"
[[ -n $OUTPUT ]] || die "usage: sudo Build-Rootfs.sh OUTPUT.tar.gz"
[[ $SOURCE_EPOCH =~ ^[0-9]{9,}$ ]] || die "SOURCE_DATE_EPOCH is required for a reproducible rootfs"
[[ ! -e $OUTPUT ]] || die "output already exists: $OUTPUT"
command -v debootstrap >/dev/null 2>&1 || die "install debootstrap first"
command -v tar >/dev/null 2>&1 || die "tar is required"

stage=$(mktemp -d /var/tmp/switchtrade-rootfs.XXXXXX)
case $stage in /var/tmp/switchtrade-rootfs.*) ;; *) die "unsafe build stage: $stage" ;; esac
cleanup() { rm -rf -- "$stage"; }
trap cleanup EXIT

debootstrap --arch="$ARCH" --variant=minbase --components=main,universe \
    --include=ca-certificates,ethtool,iproute2,iw,kmod,libpcap0.8,python3,python3-pip,python3-venv,rfkill,sudo,tcpdump,usbutils \
    "$SUITE" "$stage" "$MIRROR"

cat >"$stage/etc/wsl.conf" <<'EOF'
[boot]
systemd=false

[automount]
enabled=true

[interop]
enabled=true
EOF
cat >"$stage/etc/switchtrade-distro.json" <<'EOF'
{"schema":1,"owner":"switchtrade-installer","product":"SwitchTrade"}
EOF
chmod 0644 "$stage/etc/switchtrade-distro.json"

chroot "$stage" apt-get clean
rm -rf -- "$stage/var/lib/apt/lists/"*
rm -f -- "$stage/etc/machine-id" "$stage/var/lib/dbus/machine-id" "$stage/etc/resolv.conf"
mkdir -p "$stage/etc"
: >"$stage/etc/machine-id"

mkdir -p "$(dirname "$OUTPUT")"
find "$stage" -xdev -print0 | xargs -0 touch --no-dereference --date="@$SOURCE_EPOCH"
tar --sort=name --mtime="@$SOURCE_EPOCH" --clamp-mtime --numeric-owner --owner=0 --group=0 \
    --pax-option=delete=atime,delete=ctime --xattrs --acls -C "$stage" -cf - . | gzip -n >"$OUTPUT"
printf 'switchtrade rootfs suite=%s arch=%s output=%s\n' "$SUITE" "$ARCH" "$OUTPUT"
