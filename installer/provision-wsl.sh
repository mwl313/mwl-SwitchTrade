#!/usr/bin/env bash
# Stage, validate, commit, and compensate one isolated SwitchTrade WSL runtime.
set -euo pipefail

SOURCE=""
TARGET=/opt/switchtrade
CANDIDATE=/opt/switchtrade.candidate
MODE=stage
RELEASE_ID=""
PRIOR_RELEASE_ID=""
INTEGRITY_SHA256=""
PRIOR_INTEGRITY_SHA256=""
LOCATION=""

die() { printf 'switchtrade provision: %s\n' "$*" >&2; exit 1; }
release_of() {
    local root=$1
    [[ -f $root/.switchtrade-release.json ]] || return 1
    python3 - "$root/.switchtrade-release.json" <<'PY'
import json, re, sys
value = json.load(open(sys.argv[1], encoding="utf-8"))
release = value.get("release_id", "")
if value.get("schema") != 1 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", release):
    raise SystemExit(1)
print(release)
PY
}
require_release() {
    local root=$1 expected=$2 actual
    actual=$(release_of "$root") || die "RUNTIME_RELEASE_MARKER_INVALID: $root"
    [[ $actual == "$expected" ]] || die "RUNTIME_RELEASE_MISMATCH: expected $expected, found $actual"
}
write_integrity() {
    python3 - "$1" "$RELEASE_ID" <<'PY'
import hashlib, json, os, pathlib, stat, sys
root = pathlib.Path(sys.argv[1])
artifacts = {}
for path in sorted(root.rglob("*")):
    if path.name == ".switchtrade-integrity.json":
        continue
    if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
        continue
    if path.is_symlink():
        artifacts[path.relative_to(root).as_posix()] = "symlink:" + os.readlink(path)
    elif path.is_file():
        artifacts[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
value = {"schema": 1, "release_id": sys.argv[2], "artifact_hashes": artifacts}
(root / ".switchtrade-integrity.json").write_text(
    json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
PY
}
require_integrity() {
    local root=$1 expected=$2
    [[ $expected =~ ^[0-9a-f]{64}$ ]] || die "RUNTIME_INTEGRITY_ANCHOR_INVALID"
    python3 - "$root" "$expected" <<'PY'
import hashlib, json, os, pathlib, sys
root = pathlib.Path(sys.argv[1])
manifest = root / ".switchtrade-integrity.json"
if not manifest.is_file() or hashlib.sha256(manifest.read_bytes()).hexdigest() != sys.argv[2]:
    raise SystemExit("RUNTIME_INTEGRITY_MANIFEST_MISMATCH")
value = json.loads(manifest.read_text(encoding="utf-8"))
if value.get("schema") != 1 or not isinstance(value.get("artifact_hashes"), dict):
    raise SystemExit("RUNTIME_INTEGRITY_MANIFEST_INVALID")
actual = {}
for path in sorted(root.rglob("*")):
    if path == manifest:
        continue
    if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
        continue
    if path.is_symlink():
        actual[path.relative_to(root).as_posix()] = "symlink:" + os.readlink(path)
    elif path.is_file():
        actual[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
if actual != value["artifact_hashes"]:
    raise SystemExit("RUNTIME_INTEGRITY_ARTIFACT_SET_OR_HASH_MISMATCH")
PY
}
require_self_integrity() {
    local root=$1 digest
    [[ -f $root/.switchtrade-integrity.json ]] || die "RUNTIME_INTEGRITY_MANIFEST_MISSING"
    digest=$(sha256sum "$root/.switchtrade-integrity.json" | cut -d' ' -f1)
    require_integrity "$root" "$digest"
}

while (($#)); do
    case $1 in
        --source) [[ $# -ge 2 ]] || die "--source requires a directory"; SOURCE=$2; shift 2 ;;
        --release-id) [[ $# -ge 2 ]] || die "--release-id requires a value"; RELEASE_ID=$2; shift 2 ;;
        --prior-release-id) [[ $# -ge 2 ]] || die "--prior-release-id requires a value"; PRIOR_RELEASE_ID=$2; shift 2 ;;
        --integrity-sha256) [[ $# -ge 2 ]] || die "--integrity-sha256 requires a value"; INTEGRITY_SHA256=$2; shift 2 ;;
        --prior-integrity-sha256) [[ $# -ge 2 ]] || die "--prior-integrity-sha256 requires a value"; PRIOR_INTEGRITY_SHA256=$2; shift 2 ;;
        --location) [[ $# -ge 2 ]] || die "--location requires a value"; LOCATION=$2; shift 2 ;;
        --stage|--validate|--validate-candidate|--validate-active|--validate-location|--commit|--abort|--rollback|--compensate|--validate-retained|--recover-interrupted|--cleanup-staging)
            MODE=${1#--}; shift ;;
        *) die "unknown argument: $1" ;;
    esac
done

((EUID == 0)) || die "run as root inside the SwitchTrade distribution"
[[ $TARGET == /opt/switchtrade && $CANDIDATE == /opt/switchtrade.candidate ]] || die "unsafe runtime paths"
[[ $RELEASE_ID =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]] || die "RUNTIME_RELEASE_ID_INVALID"
if [[ $MODE == recover-interrupted ]]; then
    [[ $PRIOR_RELEASE_ID =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]] || die "RUNTIME_PRIOR_RELEASE_ID_INVALID"
fi

case $MODE in
    validate-location)
        case $LOCATION in
            active) location_path=$TARGET ;;
            candidate) location_path=$CANDIDATE ;;
            previous) location_path=${TARGET}.previous ;;
            commit_swap) location_path=${TARGET}.commit-swap ;;
            rollback_swap) location_path=${TARGET}.rollback-swap ;;
            *) die "RUNTIME_INTEGRITY_LOCATION_INVALID" ;;
        esac
        require_release "$location_path" "$RELEASE_ID"
        require_integrity "$location_path" "$INTEGRITY_SHA256"
        printf '[wsl] runtime location integrity validated location=%s release=%s\n' "$LOCATION" "$RELEASE_ID"
        exit 0 ;;
    cleanup-staging)
        find /opt -maxdepth 1 -type d -name 'switchtrade.new.*' -exec rm -rf -- {} +
        printf '[wsl] incomplete runtime staging directories removed\n'
        exit 0 ;;
    validate)
        require_release "$CANDIDATE" "$RELEASE_ID"
        [[ -x $CANDIDATE/bridge/.venv/bin/python ]] || die "RUNTIME_CANDIDATE_INCOMPLETE"
        (cd "$CANDIDATE" && "$CANDIDATE/bridge/.venv/bin/python" -m switchtrade.endpoint \
            --role host --session-id PROBE1 --relay-url http://127.0.0.1:9 --dry-run)
        printf '[wsl] candidate validated release=%s\n' "$RELEASE_ID"
        exit 0 ;;
    validate-candidate)
        require_release "$CANDIDATE" "$RELEASE_ID"
        if [[ -n $INTEGRITY_SHA256 ]]; then
            require_integrity "$CANDIDATE" "$INTEGRITY_SHA256"
        else
            require_self_integrity "$CANDIDATE"
        fi
        printf '[wsl] candidate marker validated release=%s\n' "$RELEASE_ID"
        exit 0 ;;
    validate-active)
        require_release "$TARGET" "$RELEASE_ID"
        [[ -z $INTEGRITY_SHA256 ]] || require_integrity "$TARGET" "$INTEGRITY_SHA256"
        printf '[wsl] active runtime validated release=%s\n' "$RELEASE_ID"
        exit 0 ;;
    abort)
        [[ ! -e $CANDIDATE || -d $CANDIDATE ]] || die "RUNTIME_CANDIDATE_UNSAFE"
        rm -rf -- "$CANDIDATE"
        printf '[wsl] candidate removed\n'
        exit 0 ;;
    validate-retained)
        require_release "${TARGET}.previous" "$RELEASE_ID"
        [[ -z $INTEGRITY_SHA256 ]] || require_integrity "${TARGET}.previous" "$INTEGRITY_SHA256"
        [[ -x ${TARGET}.previous/bridge/.venv/bin/python ]] || die "ROLLBACK_RUNTIME_INCOMPLETE"
        printf '[wsl] retained runtime validated release=%s\n' "$RELEASE_ID"
        exit 0 ;;
    rollback|compensate)
        previous=${TARGET}.previous
        swap=${TARGET}.rollback-swap
        if [[ -e $swap ]]; then
            require_release "$swap" "$PRIOR_RELEASE_ID"
            require_integrity "$swap" "$PRIOR_INTEGRITY_SHA256"
            if [[ ! -e $TARGET ]]; then
                require_release "$previous" "$RELEASE_ID"
                require_integrity "$previous" "$INTEGRITY_SHA256"
                mv -- "$previous" "$TARGET"
            fi
            if [[ ! -e $previous ]]; then
                require_release "$TARGET" "$RELEASE_ID"
                require_integrity "$TARGET" "$INTEGRITY_SHA256"
                mv -- "$swap" "$previous"
            fi
            [[ ! -e $swap ]] || die "RUNTIME_ROLLBACK_SWAP_STALE"
            printf '[wsl] interrupted %s recovered release=%s\n' "$MODE" "$RELEASE_ID"
            exit 0
        fi
        require_release "$previous" "$RELEASE_ID"
        [[ -z $INTEGRITY_SHA256 ]] || require_integrity "$previous" "$INTEGRITY_SHA256"
        [[ -d $TARGET && ! -e $swap ]] || die "one active runtime and a clean swap path are required"
        current_release=$(release_of "$TARGET") || die "RUNTIME_RELEASE_MARKER_INVALID: $TARGET"
        recover_rollback() {
            if [[ -d $swap ]]; then
                if [[ -d $TARGET && ! -e $previous ]]; then mv -- "$TARGET" "$previous" || true; fi
                if [[ ! -e $TARGET ]]; then mv -- "$swap" "$TARGET" || true; fi
            fi
        }
        trap recover_rollback EXIT
        mv -- "$TARGET" "$swap"
        if ! mv -- "$previous" "$TARGET"; then
            mv -- "$swap" "$TARGET"
            die "could not activate the retained WSL runtime"
        fi
        mv -- "$swap" "$previous"
        require_release "$TARGET" "$RELEASE_ID"
        trap - EXIT
        printf '[wsl] runtime %s completed release=%s previous=%s\n' "$MODE" "$RELEASE_ID" "$current_release"
        exit 0 ;;
    commit)
        require_release "$CANDIDATE" "$RELEASE_ID"
        [[ -z $INTEGRITY_SHA256 ]] || require_integrity "$CANDIDATE" "$INTEGRITY_SHA256"
        previous=${TARGET}.previous
        swap=${TARGET}.commit-swap
        [[ ! -e $swap ]] || die "RUNTIME_COMMIT_SWAP_STALE"
        if [[ -e $TARGET ]]; then
            current_release=$(release_of "$TARGET") || die "RUNTIME_ACTIVE_UNOWNED"
            [[ ! -e $previous || -d $previous ]] || die "RUNTIME_PREVIOUS_UNSAFE"
            rm -rf -- "$previous"
            recover_commit() {
                if [[ -d $swap ]]; then
                    if [[ -d $TARGET && ! -e $CANDIDATE ]]; then mv -- "$TARGET" "$CANDIDATE" || true; fi
                    if [[ ! -e $TARGET ]]; then mv -- "$swap" "$TARGET" || true; fi
                fi
            }
            trap recover_commit EXIT
            mv -- "$TARGET" "$swap"
            if ! mv -- "$CANDIDATE" "$TARGET"; then
                mv -- "$swap" "$TARGET"
                die "could not activate the staged runtime"
            fi
            mv -- "$swap" "$previous"
            trap - EXIT
            printf '[wsl] previous runtime retained release=%s\n' "$current_release"
        else
            mv -- "$CANDIDATE" "$TARGET"
        fi
        require_release "$TARGET" "$RELEASE_ID"
        printf '[wsl] runtime committed release=%s\n' "$RELEASE_ID"
        exit 0 ;;
    recover-interrupted)
        previous=${TARGET}.previous
        swap=${TARGET}.commit-swap
        require_release "$swap" "$PRIOR_RELEASE_ID"
        require_integrity "$swap" "$PRIOR_INTEGRITY_SHA256"
        [[ ! -e $previous ]] || die "RUNTIME_INTERRUPTED_PREVIOUS_UNSAFE"
        if [[ -e $CANDIDATE ]]; then
            require_release "$CANDIDATE" "$RELEASE_ID"
            require_integrity "$CANDIDATE" "$INTEGRITY_SHA256"
        fi
        if [[ -e $TARGET ]]; then
            require_release "$TARGET" "$RELEASE_ID"
            require_integrity "$TARGET" "$INTEGRITY_SHA256"
            [[ ! -e $CANDIDATE ]] || die "RUNTIME_INTERRUPTED_CANDIDATE_CONFLICT"
            mv -- "$TARGET" "$CANDIDATE"
        fi
        mv -- "$swap" "$TARGET"
        rm -rf -- "$CANDIDATE"
        require_release "$TARGET" "$PRIOR_RELEASE_ID"
        printf '[wsl] interrupted commit compensated release=%s\n' "$PRIOR_RELEASE_ID"
        exit 0 ;;
esac

[[ $MODE == stage ]] || die "unsupported mode: $MODE"
[[ -d $SOURCE && -f $SOURCE/requirements.txt ]] || die "invalid packaged source: $SOURCE"
[[ ! -e $CANDIDATE ]] || die "RUNTIME_CANDIDATE_EXISTS: repair the interrupted setup transaction"

for command in ethtool ip iw modinfo python3 rfkill sudo tcpdump lsusb; do
    command -v "$command" >/dev/null 2>&1 || die "RUNTIME_OS_DEPENDENCY_MISSING: $command; rebuild the pinned rootfs"
done
python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' || \
    die "Python 3.12 or newer is required by the pinned LDN runtime"

stage=$(mktemp -d /opt/switchtrade.new.XXXXXX)
cleanup() { rm -rf -- "$stage"; }
trap cleanup EXIT
cp -a "$SOURCE/." "$stage/"
[[ -f $stage/bridge/wheelhouse-manifest.json && -d $stage/bridge/wheelhouse ]] || \
    die "OFFLINE_WHEELHOUSE_MISSING: package must contain verified Python dependency artifacts"
python3 - "$stage" <<'PY'
import hashlib, json, pathlib, sys
root = pathlib.Path(sys.argv[1])
manifest = json.loads((root / "bridge/wheelhouse-manifest.json").read_text(encoding="utf-8-sig"))
requirements = root / "bridge/requirements.txt"
digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
if manifest.get("schema") != 1 or digest(requirements) != manifest.get("requirements_sha256"):
    raise SystemExit("wheelhouse requirements digest mismatch")
wheelhouse = root / "bridge/wheelhouse"
actual = {path.name for path in wheelhouse.iterdir() if path.is_file()}
expected = set(manifest.get("wheels", {}))
if actual != expected or not expected:
    raise SystemExit("wheelhouse artifact set mismatch")
for name, expected_hash in manifest["wheels"].items():
    if digest(wheelhouse / name) != expected_hash:
        raise SystemExit(f"wheelhouse hash mismatch: {name}")
PY
python3 -m venv "$stage/bridge/.venv"
"$stage/bridge/.venv/bin/python" -m pip install --disable-pip-version-check \
    --no-index --find-links "$stage/bridge/wheelhouse" \
    --requirement "$stage/bridge/requirements.txt"
"$stage/bridge/.venv/bin/python" - "$stage/bridge/requirements.txt" <<'PY'
from importlib.metadata import version
import pathlib, sys
for line in pathlib.Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    name, expected = line.split("==", 1)
    if version(name) != expected:
        raise SystemExit(f"installed dependency mismatch: {name}")
PY
find "$stage/scripts" -type f -name '*.sh' -exec chmod 0755 {} +
printf '{"schema":1,"release_id":"%s"}\n' "$RELEASE_ID" >"$stage/.switchtrade-release.json"
chmod 0644 "$stage/.switchtrade-release.json"
write_integrity "$stage"
mv -- "$stage" "$CANDIDATE"
trap - EXIT
printf '[wsl] runtime staged release=%s\n' "$RELEASE_ID"
