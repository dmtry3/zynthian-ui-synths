#!/usr/bin/env bash
set -euo pipefail

# Apply (or revert with --revert / check with --check) zynthian-ui patches.
# Auto-detects local Zynthian vs remote SSH host (default remote: root@zynthian.local).

MODE="apply"
HOST="${ZYNTHIAN_HOST:-}"
FORCE_LOCAL=0

for arg in "$@"; do
    case "$arg" in
        --revert|-R) MODE="revert" ;;
        --check) MODE="check" ;;
        --local) FORCE_LOCAL=1 ;;
        -h|--help)
            echo "Usage: $(basename "$0") [--check|--revert] [--local | user@host]"
            exit 0
            ;;
        *) HOST="$arg" ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ZYNTHIAN_REPO="/zynthian/zynthian-ui"

shopt -s nullglob
PATCHES=("${SCRIPT_DIR}"/*.patch)
shopt -u nullglob
if [ ${#PATCHES[@]} -eq 0 ]; then
    echo "No .patch files found in ${SCRIPT_DIR}" >&2
    exit 1
fi

IS_LOCAL=0
if [ "$FORCE_LOCAL" -eq 1 ]; then
    IS_LOCAL=1
elif [ -z "$HOST" ] && [ -d "${ZYNTHIAN_REPO}/.git" ]; then
    IS_LOCAL=1
fi

if [ "$IS_LOCAL" -eq 1 ]; then
    echo "Target: ${ZYNTHIAN_REPO} (local, mode: ${MODE})"
    test -d "${ZYNTHIAN_REPO}/.git" || {
        echo "${ZYNTHIAN_REPO} is not a git repo" >&2
        exit 1
    }
    for p in "${PATCHES[@]}"; do
        name="$(basename "$p")"
        if [ "$MODE" = "check" ]; then
            if git -C "$ZYNTHIAN_REPO" apply --reverse --check "$p" 2>/dev/null; then
                echo "  [applied]     ${name}"
            elif git -C "$ZYNTHIAN_REPO" apply --check "$p" 2>/dev/null; then
                echo "  [not applied] ${name}"
            else
                echo "  [conflict]    ${name}"
            fi
        elif [ "$MODE" = "revert" ]; then
            if git -C "$ZYNTHIAN_REPO" apply --reverse --check "$p" 2>/dev/null; then
                git -C "$ZYNTHIAN_REPO" apply --reverse "$p"
                echo "  [reverted]    ${name}"
            else
                echo "  [skip]        ${name} (not currently applied)"
            fi
        else
            if git -C "$ZYNTHIAN_REPO" apply --reverse --check "$p" 2>/dev/null; then
                echo "  [already ok]  ${name}"
            else
                git -C "$ZYNTHIAN_REPO" apply "$p"
                echo "  [applied]     ${name}"
            fi
        fi
    done

    if [ "$MODE" != "check" ]; then
        echo "Done! Restart Zynthian UI if needed: systemctl restart zynthian"
    fi
    exit 0
fi

HOST="${HOST:-root@zynthian.local}"
echo "Target: ${HOST}:${ZYNTHIAN_REPO} (mode: ${MODE})"
ssh -o ConnectTimeout=5 "$HOST" "test -d ${ZYNTHIAN_REPO}/.git" || {
    echo "Failed to reach ${HOST} or ${ZYNTHIAN_REPO} is not a git repo" >&2
    exit 1
}
for p in "${PATCHES[@]}"; do
    name="$(basename "$p")"
    if [ "$MODE" = "check" ]; then
        if ssh "$HOST" "cd ${ZYNTHIAN_REPO} && git apply --reverse --check" < "$p" 2>/dev/null; then
            echo "  [applied]     ${name}"
        elif ssh "$HOST" "cd ${ZYNTHIAN_REPO} && git apply --check" < "$p" 2>/dev/null; then
            echo "  [not applied] ${name}"
        else
            echo "  [conflict]    ${name}"
        fi
    elif [ "$MODE" = "revert" ]; then
        if ssh "$HOST" "cd ${ZYNTHIAN_REPO} && git apply --reverse --check" < "$p" 2>/dev/null; then
            ssh "$HOST" "cd ${ZYNTHIAN_REPO} && git apply --reverse" < "$p"
            echo "  [reverted]    ${name}"
        else
            echo "  [skip]        ${name} (not currently applied)"
        fi
    else
        if ssh "$HOST" "cd ${ZYNTHIAN_REPO} && git apply --reverse --check" < "$p" 2>/dev/null; then
            echo "  [already ok]  ${name}"
        else
            ssh "$HOST" "cd ${ZYNTHIAN_REPO} && git apply" < "$p"
            echo "  [applied]     ${name}"
        fi
    fi
done

if [ "$MODE" != "check" ]; then
    echo "Done! Restart Zynthian UI if needed: ssh ${HOST} systemctl restart zynthian"
fi
