#!/usr/bin/env bash
set -euo pipefail

repo=${1:-}
wheelhouse=${2:-}
modules=${3:-}
firmware_directory=${4:-}
firmware_manifest=${5:-}
output=${6:-}
release_id=${7:-}
content_id=${8:-}
source_epoch=${9:-}
wheelhouse_manifest=${10:-}
base_rootfs=${11:-}
ubuntu_snapshot=https://snapshot.ubuntu.com/ubuntu/20260827T000000Z

die() { printf 'switchtrade appliance: %s\n' "$*" >&2; exit 1; }
((EUID == 0)) || die 'run as root in the disposable WSL builder'
[[ -d $repo/switchtrade && -d $repo/bridge && -d $wheelhouse ]] || die 'source or wheelhouse is missing'
[[ -f $modules && -d $firmware_directory && -f $firmware_manifest ]] || die 'kernel modules or firmware bundle is missing'
[[ -f $wheelhouse_manifest ]] || die 'wheelhouse manifest is missing'
[[ -f $base_rootfs ]] || die 'pinned Ubuntu base rootfs is missing'
[[ $release_id =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]] || die 'invalid release id'
[[ $content_id =~ ^[0-9a-f]{64}$ ]] || die 'invalid runtime content id'
[[ $source_epoch =~ ^[0-9]{9,}$ ]] || die 'invalid source epoch'
expected_wheels=$(mktemp)
actual_wheels=$(mktemp)
awk '{print $2}' "$wheelhouse_manifest" | LC_ALL=C sort >"$expected_wheels"
find "$wheelhouse" -maxdepth 1 -type f -printf '%f\n' | LC_ALL=C sort >"$actual_wheels"
cmp -s "$expected_wheels" "$actual_wheels" || die 'wheelhouse file set does not match its pinned manifest'
(cd "$wheelhouse" && sha256sum -c "$wheelhouse_manifest") >/dev/null || die 'wheelhouse hash verification failed'
rm -f -- "$expected_wheels" "$actual_wheels"

stage=$(mktemp -d /var/tmp/switchtrade-appliance.XXXXXX)
cleanup() { rm -rf -- "$stage"; }
trap cleanup EXIT
chmod 0755 "$stage"

tar -xzf "$base_rootfs" -C "$stage"
install -d -m 0755 "$stage/dev"
mknod -m 0666 "$stage/dev/null" c 1 3
mknod -m 0666 "$stage/dev/zero" c 1 5
mknod -m 0666 "$stage/dev/random" c 1 8
mknod -m 0666 "$stage/dev/urandom" c 1 9
cp -L /etc/resolv.conf "$stage/etc/resolv.conf"
install -d -m 0755 "$stage/etc/ssl/certs"
cp -L /etc/ssl/certs/ca-certificates.crt "$stage/etc/ssl/certs/ca-certificates.crt"
archive_keyring=/usr/share/keyrings/ubuntu-archive-keyring.gpg
[[ -f $stage$archive_keyring ]] || die 'Ubuntu archive signing key is missing from the pinned base image'
rm -f -- "$stage/etc/apt/sources.list.d/"*
printf 'deb [signed-by=%s] %s noble main universe restricted multiverse\n' \
  "$archive_keyring" "$ubuntu_snapshot" \
  >"$stage/etc/apt/sources.list"
cat >"$stage/usr/sbin/policy-rc.d" <<'EOF'
#!/bin/sh
exit 101
EOF
chmod 0755 "$stage/usr/sbin/policy-rc.d"
: >"$stage/etc/modules"
apt_options=(
  -o Acquire::Check-Valid-Until=false
  -o Acquire::Retries=5
  -o Acquire::http::Timeout=60
  -o Acquire::https::Timeout=60
)
chroot "$stage" apt-get "${apt_options[@]}" update
chroot "$stage" env DEBIAN_FRONTEND=noninteractive apt-get \
  "${apt_options[@]}" install -y --no-install-recommends \
  ca-certificates ethtool hostapd iproute2 iw kmod python3 python3-venv \
  rfkill tcpdump usbutils wireless-regdb
rm -f -- "$stage/usr/sbin/policy-rc.d"

rm -rf -- "$stage/opt/switchtrade" "$stage/usr/lib/modules"
install -d -m 0755 "$stage/opt/switchtrade" "$stage/opt/switchtrade/scripts" \
  "$stage/etc/switchtrade" "$stage/usr/lib/modules"
cp -a "$repo/switchtrade" "$stage/opt/switchtrade/"
cp -a "$repo/bridge" "$stage/opt/switchtrade/"
cp -a "$repo/tools" "$stage/opt/switchtrade/"
for script_name in run-beta-endpoint.sh wsl-radio-prepare.sh radio-health-gate.sh; do
  cp -a "$repo/scripts/$script_name" "$stage/opt/switchtrade/scripts/"
done
cp -a "$repo/config" "$stage/opt/switchtrade/"
cp -a "$repo/requirements.txt" "$stage/opt/switchtrade/"
cp -a "$repo/payload/release-config.json" "$stage/etc/switchtrade/release-config.json"
rm -rf -- "$stage/opt/switchtrade/bridge/.venv" "$stage/opt/switchtrade/bridge/wheelhouse"
rm -rf -- "$stage/opt/switchtrade/bridge/tests"
rm -f -- "$stage/opt/switchtrade/bridge/"*.md
install -d -m 0755 "$stage/opt/switchtrade/bridge/wheelhouse"
cp -a "$wheelhouse/." "$stage/opt/switchtrade/bridge/wheelhouse/"

tar -xzf "$modules" -C "$stage/usr/lib/modules"
kernel_release=$(tar -tzf "$modules" | awk -F/ 'NF >= 2 && $2 != "" {print $2; exit}')
[[ -n $kernel_release ]] || die 'kernel release is missing from modules archive'
chroot "$stage" /usr/sbin/depmod "$kernel_release"

cp -a "$firmware_directory/." "$stage/usr/lib/firmware/"
cp -a "$firmware_manifest" "$stage/etc/switchtrade/firmware-manifest.sha256"

while read -r expected relative; do
  [[ -n ${expected:-} && -n ${relative:-} ]] || continue
  candidate="$stage/usr/lib/$relative"
  [[ -f $candidate ]] || candidate="$stage/lib/$relative"
  [[ -f $candidate ]] || die "required firmware is missing: $relative"
  actual=$(sha256sum "$candidate" | cut -d' ' -f1)
  [[ $actual == "$expected" ]] || die "firmware hash mismatch: $relative"
done <"$firmware_manifest"

cat >"$stage/etc/wsl.conf" <<'EOF'
[boot]
systemd=false

[automount]
enabled=true

[interop]
enabled=true

[user]
default=root
EOF
cat >"$stage/etc/wsl-distribution.conf" <<'EOF'
[oobe]
defaultUid=0
defaultName=SwitchTrade

[shortcut]
enabled=false

[windowsterminal]
enabled=false
EOF
printf '{"schema":1,"owner":"switchtrade-provisioner","product":"SwitchTrade","release_id":"%s","payload_sha256":"%s"}\n' \
  "$release_id" "$content_id" >"$stage/etc/switchtrade-distro.json"
printf '{"schema":1,"release_id":"%s"}\n' "$release_id" >"$stage/opt/switchtrade/.switchtrade-release.json"
printf '{"schema":1,"ubuntu_snapshot":"%s"}\n' "$ubuntu_snapshot" >"$stage/etc/switchtrade/build-source.json"
chroot "$stage" dpkg-query -W -f='${Package}=${Version}\n' | LC_ALL=C sort \
  >"$stage/etc/switchtrade/package-lock.txt"
chmod 0644 "$stage/etc/wsl.conf" "$stage/etc/wsl-distribution.conf" \
  "$stage/etc/switchtrade-distro.json" "$stage/opt/switchtrade/.switchtrade-release.json"
chmod 0600 "$stage/opt/switchtrade/config/prod.keys"

chroot "$stage" /usr/bin/python3 - <<'PY'
import hashlib, json, pathlib
root = pathlib.Path('/opt/switchtrade/bridge')
requirements = root / 'requirements.txt'
wheelhouse = root / 'wheelhouse'
value = {
    'schema': 1,
    'requirements_sha256': hashlib.sha256(requirements.read_bytes()).hexdigest(),
    'wheels': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
               for p in sorted(wheelhouse.glob('*.whl'))},
}
(root / 'wheelhouse-manifest.json').write_text(json.dumps(value, sort_keys=True) + '\n', encoding='utf-8')
PY
chroot "$stage" /usr/bin/python3 -m venv /opt/switchtrade/bridge/.venv
chroot "$stage" /opt/switchtrade/bridge/.venv/bin/python -m pip install \
  --disable-pip-version-check --no-index --find-links /opt/switchtrade/bridge/wheelhouse \
  --requirement /opt/switchtrade/bridge/requirements.txt
chroot "$stage" /opt/switchtrade/bridge/.venv/bin/python - <<'PY'
from importlib.metadata import version
import pathlib
for raw in pathlib.Path('/opt/switchtrade/bridge/requirements.txt').read_text().splitlines():
    line = raw.strip()
    if line and not line.startswith('#'):
        name, expected = line.split('==', 1)
        if version(name) != expected:
            raise SystemExit(f'dependency mismatch: {name}')
import fastapi, ldn, uvicorn, websockets, zstandard  # noqa: F401
PY
rm -rf -- "$stage/opt/switchtrade/bridge/wheelhouse" \
  "$stage/opt/switchtrade/bridge/.venv"/lib/python*/site-packages/pip* \
  "$stage/var/lib/apt/lists/"* "$stage/var/cache/apt/"* \
  "$stage/var/log/"* "$stage/tmp/"* "$stage/var/tmp/"*
rm -f -- "$stage/var/cache/ldconfig/aux-cache"
find "$stage/opt/switchtrade" -type d -name __pycache__ -prune -exec rm -rf -- {} +
find "$stage/opt/switchtrade/scripts" -type f -name '*.sh' -exec chmod 0755 {} +
rm -f -- "$stage/etc/resolv.conf" "$stage/var/lib/dbus/machine-id"
rm -f -- "$stage/dev/null" "$stage/dev/zero" "$stage/dev/random" "$stage/dev/urandom"
: >"$stage/etc/machine-id"

chroot "$stage" /usr/bin/python3 - "$release_id" <<'PY'
import hashlib, json, os, pathlib, sys
root = pathlib.Path('/opt/switchtrade')
artifacts = {}
for path in sorted(root.rglob('*')):
    if path.name == '.switchtrade-integrity.json' or '__pycache__' in path.parts:
        continue
    relative = path.relative_to(root).as_posix()
    if path.is_symlink(): artifacts[relative] = 'symlink:' + os.readlink(path)
    elif path.is_file(): artifacts[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
value = {'schema': 1, 'release_id': sys.argv[1], 'artifact_hashes': artifacts}
(root / '.switchtrade-integrity.json').write_text(
    json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n', encoding='utf-8')
PY

find "$stage" -xdev -print0 | xargs -0 touch --no-dereference --date="@$source_epoch"
mkdir -p "$(dirname "$output")"
tar --sort=name --mtime="@$source_epoch" --clamp-mtime --numeric-owner --owner=0 --group=0 \
  --pax-option=delete=atime,delete=ctime --xattrs --acls -C "$stage" -cf - . | gzip -n >"$output"
printf 'SwitchTrade immutable appliance created: %s\n' "$output"
