#!/usr/bin/env bash
# Build a minimal, architecture-specific WSL rootfs. Kernel selection is intentionally external.
set -euo pipefail

SUITE=${SWITCHTRADE_ROOTFS_SUITE:-resolute}
MIRROR=${SWITCHTRADE_ROOTFS_MIRROR:-http://archive.ubuntu.com/ubuntu}
ARCH=${SWITCHTRADE_ROOTFS_ARCH:-amd64}
OUTPUT=${1:-}

die() { printf 'switchtrade rootfs: %s\n' "$*" >&2; exit 1; }

((EUID == 0)) || die "run as root in a Linux build environment"
[[ -n $OUTPUT ]] || die "usage: sudo Build-Rootfs.sh OUTPUT.tar.gz"
[[ ! -e $OUTPUT ]] || die "output already exists: $OUTPUT"
command -v debootstrap >/dev/null 2>&1 || die "install debootstrap first"
command -v tar >/dev/null 2>&1 || die "tar is required"

stage=$(mktemp -d /var/tmp/switchtrade-rootfs.XXXXXX)
case $stage in /var/tmp/switchtrade-rootfs.*) ;; *) die "unsafe build stage: $stage" ;; esac
cleanup() { rm -rf -- "$stage"; }
trap cleanup EXIT

debootstrap --arch="$ARCH" --variant=minbase --components=main,universe \
    --include=ca-certificates "$SUITE" "$stage" "$MIRROR"

cat >"$stage/etc/wsl.conf" <<'EOF'
[boot]
systemd=false

[automount]
enabled=true

[interop]
enabled=true
EOF

chroot "$stage" apt-get clean
rm -rf -- "$stage/var/lib/apt/lists/"*
rm -f -- "$stage/etc/machine-id" "$stage/var/lib/dbus/machine-id" "$stage/etc/resolv.conf"
mkdir -p "$stage/etc"
: >"$stage/etc/machine-id"

mkdir -p "$(dirname "$OUTPUT")"
tar --numeric-owner --xattrs --acls -C "$stage" -czf "$OUTPUT" .
printf 'switchtrade rootfs suite=%s arch=%s output=%s\n' "$SUITE" "$ARCH" "$OUTPUT"
