#!/usr/bin/env bash
set -euo pipefail

# Apply (or revert with --revert) zynthian-ui patches on Zynthian
MODE="apply"
HOST="root@10.0.99.99"

for arg in "$@"; do
    case "$arg" in
        --revert|-R) MODE="revert" ;;
        --check) MODE="check" ;;
        *) HOST="$arg" ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REMOTE_REPO="/zynthian/zynthian-ui"

shopt -s nullglob
PATCHES=("${SCRIPT_DIR}"/*.patch)
if [ ${#PATCHES[@]} -eq 0 ]; then
    echo "No .patch files found in ${SCRIPT_DIR}" >&2
    exit 1
fi

echo "Target: ${HOST}:${REMOTE_REPO} (mode: ${MODE})"
ssh -o ConnectTimeout=5 "$HOST" "test -d ${REMOTE_REPO}/.git" || {
    echo "Failed to reach ${HOST} or ${REMOTE_REPO} is not a git repo" >&2
    exit 1
}
for p in "${PATCHES[@]}"; do
    name="$(basename "$p")"
    if [ "$MODE" = "check" ]; then
        if ssh "$HOST" "cd ${REMOTE_REPO} && git apply --reverse --check" < "$p" 2>/dev/null; then
            echo "  [applied]     ${name}"
        elif ssh "$HOST" "cd ${REMOTE_REPO} && git apply --check" < "$p" 2>/dev/null; then
            echo "  [not applied] ${name}"
        else
            echo "  [conflict]    ${name}"
        fi
    elif [ "$MODE" = "revert" ]; then
        if ssh "$HOST" "cd ${REMOTE_REPO} && git apply --reverse --check" < "$p" 2>/dev/null; then
            ssh "$HOST" "cd ${REMOTE_REPO} && git apply --reverse" < "$p"
            echo "  [reverted]    ${name}"
        else
            echo "  [skip]        ${name} (not currently applied)"
        fi
    else
        if ssh "$HOST" "cd ${REMOTE_REPO} && git apply --reverse --check" < "$p" 2>/dev/null; then
            echo "  [already ok]  ${name}"
        else
            ssh "$HOST" "cd ${REMOTE_REPO} && git apply" < "$p"
            echo "  [applied]     ${name}"
        fi
    fi
done

if [ "$MODE" != "check" ]; then
    echo "Done! Restart Zynthian UI if needed: ssh ${HOST} systemctl restart zynthian"
fi
