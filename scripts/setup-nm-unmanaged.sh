#!/usr/bin/env bash
#
# setup-nm-unmanaged.sh — NetworkManager가 모든 wlx* 인터페이스를 영구 unmanaged로 고정 (C-3)
#
# *** 경고: conf 적용은 재부팅으로만 가능 ***
#   systemctl reload/restart NetworkManager 및 nmcli reload 는 절대 금지 —
#   VM 네트워크 전체 사망 확인 (2026-08-21 실측, docs/09-testing-audit-20260821.md D-7).
#   이 스크립트는 conf 파일만 기록하며, 서비스 재시작/reload는 절대 수행하지 않는다.
#
# 배경:
#   unmanaged conf를 MAC(mac:) 기반으로 쓰면 카드 교체 시 새 카드를 NM이 다시
#   관리하게 되고, ldn의 REGISTER_FRAME이 "Match already configured"로 반복
#   실패한다 (2026-08-21 실측, docs/09-testing-audit-20260821.md I-3).
#   interface-name:wlx* 는 MAC 불변이므로 카드 교체·추가에 면역.
#
# 사용법 (root 권한 필수):
#   sudo ./scripts/setup-nm-unmanaged.sh
#   재실행 안전(idempotent): 이미 설정돼 있으면 변경 없이 종료.
#
# 적용 확인 (재부팅 후):
#   nmcli -t -f DEVICE,STATE device | grep wlx   →  wlx*:unmanaged 여야 함

set -euo pipefail

readonly CONF="/etc/NetworkManager/conf.d/unmanaged-wlx.conf"
readonly HEADER="[keyfile]"

msg() { printf '%s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[[ ${EUID} -eq 0 ]] || die "root 권한 필요 — sudo ./scripts/setup-nm-unmanaged.sh"

mkdir -p "$(dirname "$CONF")"

# 기존 conf의 unmanaged-devices 토큰 수집 (mac: 등 기존 항목 보존 대상)
old_tokens=""
if [[ -f $CONF ]]; then
    old_tokens="$(sed -n 's/^[[:space:]]*unmanaged-devices[[:space:]]*=[[:space:]]*//p' "$CONF" \
        | tr ',' '\n' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' \
        | grep -v '^$' || true)"
fi

new_line="unmanaged-devices=interface-name:wlx*"
if [[ -n $old_tokens ]]; then
    # 새 규칙이 이미 커버하는 interface-name:wlx* 토큰은 제외하고,
    # 나머지(mac: 등)는 보존 + 중복 제거
    preserved="$(printf '%s\n' "$old_tokens" \
        | grep -v '^interface-name:wlx\*$' \
        | sort -u \
        | paste -sd, - || true)"
    if [[ -n $preserved ]]; then
        new_line="${new_line},${preserved}"
    fi
fi

desired="${HEADER}
${new_line}"

current="$(cat "$CONF" 2>/dev/null || true)"
if [[ $current == "$desired" ]]; then
    msg "변경 없음 (이미 설정됨): $CONF"
else
    tmp="$(mktemp "$(dirname "$CONF")/.unmanaged-wlx.XXXXXX")"
    trap 'rm -f "$tmp"' EXIT
    printf '%s\n' "$desired" > "$tmp"
    chmod 0644 "$tmp"
    mv -f "$tmp" "$CONF"
    trap - EXIT
    msg "기록 완료: $CONF"
fi

msg "--- 현재 내용 ---"
cat "$CONF"
msg "-----------------"
msg "적용은 재부팅으로만 가능합니다."
msg "systemctl reload/restart NetworkManager 금지 — VM 네트워크 전체 사망 (2026-08-21 실측)."
msg "재부팅 후 확인: nmcli -t -f DEVICE,STATE device | grep wlx  → unmanaged"
