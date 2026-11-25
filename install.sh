#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# UI Synths (zynthian-ui-synths) Universal Installer
#
# Works in three modes automatically:
#   1. Direct one-liner on Zynthian (downloads latest from GitHub):
#        curl -fsSL https://raw.githubusercontent.com/dmtry3/zynthian-ui-synths/main/install.sh | bash
#        curl -fsSL https://raw.githubusercontent.com/dmtry3/zynthian-ui-synths/main/install.sh | bash -s -- --with-patches --restart
#   2. Local clone on Zynthian:
#        ./install.sh [--with-patches] [--restart]
#   3. Remote install from PC/Mac over SSH:
#        ./install.sh [root@zynthian.local | root@<ip>] [--with-patches] [--restart]
# ==============================================================================

REPO_SLUG="${ZYNTHIAN_UI_SYNTHS_REPO:-dmtry3/zynthian-ui-synths}"
REPO_BRANCH="${ZYNTHIAN_UI_SYNTHS_BRANCH:-main}"
ZYNTHIAN_UI_DIR="/zynthian/zynthian-ui"
WIDGETS_DIR="${ZYNTHIAN_UI_DIR}/zyngui/widgets_user"
MANIFEST_NAME=".zynthian-ui-synths.manifest"

ACTION="install"      # install | uninstall | check-patches | revert-patches
WITH_PATCHES=0
RESTART_UI=0
HOST="${ZYNTHIAN_HOST:-}"
FORCE_LOCAL=0
TMP_DIR=""

cleanup() {
    if [ -n "$TMP_DIR" ] && [ -d "$TMP_DIR" ]; then
        rm -rf "$TMP_DIR"
    fi
}
trap cleanup EXIT

usage() {
    cat <<EOF
UI Synths (zynthian-ui-synths) Installer

Usage:
  install.sh [OPTIONS] [user@host]

Modes:
  * Run directly on Zynthian (locally or via curl | bash):
      Installs widgets directly to ${WIDGETS_DIR}/
  * Run from another computer (PC/Mac):
      Installs widgets remotely via SSH (default host: root@zynthian.local)

Options:
  --with-patches     Also apply optional zynthian-ui patches (menu badge, widget priority, ZynAddSubFX)
  --check-patches    Check status of optional zynthian-ui patches and exit
  --revert-patches   Revert optional zynthian-ui patches and exit
  --restart          Restart zynthian systemd service after install/uninstall/patch
  --uninstall        Remove installed UI Synths widgets (and revert patches if applied)
  --local            Force local installation into ${WIDGETS_DIR}
  --host USER@HOST   Install remotely to the specified SSH host
  --branch BRANCH    GitHub branch/tag to download when running via curl | bash (default: ${REPO_BRANCH})
  -h, --help         Show this help message

Examples:
  # One-liner directly on Zynthian:
  curl -fsSL https://raw.githubusercontent.com/${REPO_SLUG}/main/install.sh | bash
  curl -fsSL https://raw.githubusercontent.com/${REPO_SLUG}/main/install.sh | bash -s -- --with-patches --restart

  # From a cloned repo on Zynthian:
  ./install.sh --with-patches --restart

  # From a laptop/desktop to Zynthian over SSH:
  ./install.sh root@zynthian.local --with-patches --restart
  ./install.sh root@192.168.1.50

  # Uninstall:
  ./install.sh --uninstall --restart
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --with-patches|-p)
            WITH_PATCHES=1
            ;;
        --check-patches)
            ACTION="check-patches"
            ;;
        --revert-patches)
            ACTION="revert-patches"
            ;;
        --restart|-r)
            RESTART_UI=1
            ;;
        --uninstall|-u)
            ACTION="uninstall"
            ;;
        --local)
            FORCE_LOCAL=1
            ;;
        --host)
            shift
            [ $# -gt 0 ] || { echo "Error: --host requires an argument" >&2; exit 1; }
            HOST="$1"
            ;;
        --branch)
            shift
            [ $# -gt 0 ] || { echo "Error: --branch requires an argument" >&2; exit 1; }
            REPO_BRANCH="$1"
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        -*)
            echo "Unknown option: $1" >&2
            echo "Run with --help for usage." >&2
            exit 1
            ;;
        *)
            HOST="$1"
            ;;
    esac
    shift
done

# Determine local vs remote mode
IS_LOCAL=0
if [ "$FORCE_LOCAL" -eq 1 ]; then
    IS_LOCAL=1
elif [ -z "$HOST" ] && [ -d "${ZYNTHIAN_UI_DIR}/zyngui" ]; then
    IS_LOCAL=1
fi

if [ "$IS_LOCAL" -eq 0 ] && [ -z "$HOST" ]; then
    HOST="root@zynthian.local"
fi

# Locate source directory (local checkout or download from GitHub when piped via curl | bash)
SRC_DIR=""
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
    CANDIDATE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    shopt -s nullglob
    CANDIDATE_WIDGETS=("${CANDIDATE_DIR}"/zynthian_widget_*.py)
    shopt -u nullglob
    if [ ${#CANDIDATE_WIDGETS[@]} -gt 0 ]; then
        SRC_DIR="$CANDIDATE_DIR"
    fi
fi

download_repo() {
    TMP_DIR="$(mktemp -d)"
    local tarball_url="https://github.com/${REPO_SLUG}/archive/refs/heads/${REPO_BRANCH}.tar.gz"
    echo "Downloading ${REPO_SLUG} (${REPO_BRANCH}) from GitHub..."
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "$tarball_url" | tar -xz -C "$TMP_DIR" --strip-components=1
    elif command -v wget >/dev/null 2>&1; then
        wget -qO- "$tarball_url" | tar -xz -C "$TMP_DIR" --strip-components=1
    elif command -v git >/dev/null 2>&1; then
        git clone --depth 1 --branch "$REPO_BRANCH" "https://github.com/${REPO_SLUG}.git" "$TMP_DIR"
    else
        echo "Error: curl, wget, or git is required to download ${REPO_SLUG}." >&2
        exit 1
    fi
    SRC_DIR="$TMP_DIR"
}

if [ -z "$SRC_DIR" ]; then
    download_repo
fi

shopt -s nullglob
WIDGETS=("${SRC_DIR}"/zynthian_widget_*.py)
PATCHES=("${SRC_DIR}"/patches/*.patch)
shopt -u nullglob

if [ "$ACTION" = "install" ] && [ ${#WIDGETS[@]} -eq 0 ]; then
    echo "Error: no zynthian_widget_*.py files found in ${SRC_DIR}" >&2
    exit 1
fi

# ------------------------------------------------------------------------------
# Patch Helpers (local & remote)
# ------------------------------------------------------------------------------
run_patches_local() {
    local mode="$1" # apply | revert | check
    if [ ${#PATCHES[@]} -eq 0 ]; then
        echo "No .patch files found." >&2
        return 0
    fi
    if [ ! -d "${ZYNTHIAN_UI_DIR}/.git" ]; then
        echo "Warning: ${ZYNTHIAN_UI_DIR} is not a git repository; skipping patches." >&2
        return 1
    fi
    echo "Patches target: ${ZYNTHIAN_UI_DIR} (mode: ${mode})"
    for p in "${PATCHES[@]}"; do
        local name
        name="$(basename "$p")"
        if [ "$mode" = "check" ]; then
            if git -C "$ZYNTHIAN_UI_DIR" apply --reverse --check "$p" 2>/dev/null; then
                echo "  [applied]     ${name}"
            elif git -C "$ZYNTHIAN_UI_DIR" apply --check "$p" 2>/dev/null; then
                echo "  [not applied] ${name}"
            else
                echo "  [conflict]    ${name}"
            fi
        elif [ "$mode" = "revert" ]; then
            if git -C "$ZYNTHIAN_UI_DIR" apply --reverse --check "$p" 2>/dev/null; then
                git -C "$ZYNTHIAN_UI_DIR" apply --reverse "$p"
                echo "  [reverted]    ${name}"
            else
                echo "  [skip]        ${name} (not currently applied)"
            fi
        else
            if git -C "$ZYNTHIAN_UI_DIR" apply --reverse --check "$p" 2>/dev/null; then
                echo "  [already ok]  ${name}"
            elif git -C "$ZYNTHIAN_UI_DIR" apply --check "$p" 2>/dev/null; then
                git -C "$ZYNTHIAN_UI_DIR" apply "$p"
                echo "  [applied]     ${name}"
            else
                echo "  [conflict]    ${name} (skipped — Zynthian UI version may differ)" >&2
            fi
        fi
    done
}

run_patches_remote() {
    local mode="$1" # apply | revert | check
    if [ ${#PATCHES[@]} -eq 0 ]; then
        echo "No .patch files found." >&2
        return 0
    fi
    echo "Patches target: ${HOST}:${ZYNTHIAN_UI_DIR} (mode: ${mode})"
    if ! ssh -o ConnectTimeout=5 "$HOST" "test -d ${ZYNTHIAN_UI_DIR}/.git"; then
        echo "Warning: ${HOST}:${ZYNTHIAN_UI_DIR} is not reachable or not a git repository." >&2
        return 1
    fi
    for p in "${PATCHES[@]}"; do
        local name
        name="$(basename "$p")"
        if [ "$mode" = "check" ]; then
            if ssh "$HOST" "cd ${ZYNTHIAN_UI_DIR} && git apply --reverse --check" < "$p" 2>/dev/null; then
                echo "  [applied]     ${name}"
            elif ssh "$HOST" "cd ${ZYNTHIAN_UI_DIR} && git apply --check" < "$p" 2>/dev/null; then
                echo "  [not applied] ${name}"
            else
                echo "  [conflict]    ${name}"
            fi
        elif [ "$mode" = "revert" ]; then
            if ssh "$HOST" "cd ${ZYNTHIAN_UI_DIR} && git apply --reverse --check" < "$p" 2>/dev/null; then
                ssh "$HOST" "cd ${ZYNTHIAN_UI_DIR} && git apply --reverse" < "$p"
                echo "  [reverted]    ${name}"
            else
                echo "  [skip]        ${name} (not currently applied)"
            fi
        else
            if ssh "$HOST" "cd ${ZYNTHIAN_UI_DIR} && git apply --reverse --check" < "$p" 2>/dev/null; then
                echo "  [already ok]  ${name}"
            elif ssh "$HOST" "cd ${ZYNTHIAN_UI_DIR} && git apply --check" < "$p" 2>/dev/null; then
                ssh "$HOST" "cd ${ZYNTHIAN_UI_DIR} && git apply" < "$p"
                echo "  [applied]     ${name}"
            else
                echo "  [conflict]    ${name} (skipped — Zynthian UI version may differ)" >&2
            fi
        fi
    done
}

run_patches() {
    if [ "$IS_LOCAL" -eq 1 ]; then
        run_patches_local "$1"
    else
        run_patches_remote "$1"
    fi
}

restart_zynthian() {
    echo "Restarting Zynthian UI service..."
    if [ "$IS_LOCAL" -eq 1 ]; then
        systemctl restart zynthian
    else
        ssh "$HOST" "systemctl restart zynthian"
    fi
    echo "Zynthian UI restarted."
}

# ------------------------------------------------------------------------------
# Actions
# ------------------------------------------------------------------------------
if [ "$ACTION" = "check-patches" ]; then
    run_patches "check"
    exit 0
fi

if [ "$ACTION" = "revert-patches" ]; then
    run_patches "revert"
    if [ "$RESTART_UI" -eq 1 ]; then
        restart_zynthian
    else
        if [ "$IS_LOCAL" -eq 1 ]; then
            echo "Done! Restart Zynthian UI if needed: systemctl restart zynthian"
        else
            echo "Done! Restart Zynthian UI if needed: ssh ${HOST} systemctl restart zynthian"
        fi
    fi
    exit 0
fi

if [ "$ACTION" = "uninstall" ]; then
    if [ "$IS_LOCAL" -eq 1 ]; then
        echo "Uninstalling UI Synths widgets from ${WIDGETS_DIR}/ ..."
        if [ -f "${WIDGETS_DIR}/${MANIFEST_NAME}" ]; then
            while IFS= read -r fname; do
                [ -n "$fname" ] || continue
                if [ -f "${WIDGETS_DIR}/${fname}" ]; then
                    rm -f "${WIDGETS_DIR}/${fname}"
                    echo "  [removed] ${fname}"
                fi
            done < "${WIDGETS_DIR}/${MANIFEST_NAME}"
            rm -f "${WIDGETS_DIR}/${MANIFEST_NAME}"
        else
            for f in "${WIDGETS[@]}"; do
                fname="$(basename "$f")"
                if [ -f "${WIDGETS_DIR}/${fname}" ]; then
                    rm -f "${WIDGETS_DIR}/${fname}"
                    echo "  [removed] ${fname}"
                fi
            done
        fi
        run_patches_local "revert" || true
    else
        echo "Uninstalling UI Synths widgets from ${HOST}:${WIDGETS_DIR}/ ..."
        WIDGET_NAMES=()
        for f in "${WIDGETS[@]}"; do
            WIDGET_NAMES+=("$(basename "$f")")
        done
        ssh -o ConnectTimeout=5 "$HOST" bash -s -- "$WIDGETS_DIR" "$MANIFEST_NAME" "${WIDGET_NAMES[@]}" <<'EOF'
set -euo pipefail
WDIR="$1"
MANIFEST="$2"
shift 2
if [ -f "${WDIR}/${MANIFEST}" ]; then
    while IFS= read -r fname; do
        [ -n "$fname" ] || continue
        if [ -f "${WDIR}/${fname}" ]; then
            rm -f "${WDIR}/${fname}"
            echo "  [removed] ${fname}"
        fi
    done < "${WDIR}/${MANIFEST}"
    rm -f "${WDIR}/${MANIFEST}"
else
    for fname in "$@"; do
        if [ -f "${WDIR}/${fname}" ]; then
            rm -f "${WDIR}/${fname}"
            echo "  [removed] ${fname}"
        fi
    done
fi
EOF
        run_patches_remote "revert" || true
    fi

    if [ "$RESTART_UI" -eq 1 ]; then
        restart_zynthian
    else
        if [ "$IS_LOCAL" -eq 1 ]; then
            echo "Done! Restart Zynthian UI: systemctl restart zynthian"
        else
            echo "Done! Restart Zynthian UI: ssh ${HOST} systemctl restart zynthian"
        fi
    fi
    exit 0
fi

# Default action: install
if [ "$IS_LOCAL" -eq 1 ]; then
    echo "Installing UI Synths (${#WIDGETS[@]} widgets) locally to ${WIDGETS_DIR}/ ..."
    mkdir -p "$WIDGETS_DIR"
    : > "${WIDGETS_DIR}/${MANIFEST_NAME}"
    for f in "${WIDGETS[@]}"; do
        fname="$(basename "$f")"
        install -m 644 "$f" "${WIDGETS_DIR}/${fname}"
        echo "$fname" >> "${WIDGETS_DIR}/${MANIFEST_NAME}"
        echo "  -> ${fname}"
    done
else
    echo "Installing UI Synths (${#WIDGETS[@]} widgets) to ${HOST}:${WIDGETS_DIR}/ ..."
    if ! ssh -o ConnectTimeout=5 "$HOST" "mkdir -p '${WIDGETS_DIR}'" 2>/dev/null; then
        echo "Error: failed to connect to ${HOST} via SSH." >&2
        echo "Hint: specify your Zynthian address, e.g.: ./install.sh root@<zynthian-ip>" >&2
        exit 1
    fi
    # Single-connection transfer via tar over SSH (much faster than N separate scp calls)
    WIDGET_BASENAMES=()
    for f in "${WIDGETS[@]}"; do
        fname="$(basename "$f")"
        WIDGET_BASENAMES+=("$fname")
        echo "  -> ${fname}"
    done
    tar -C "$SRC_DIR" -cf - "${WIDGET_BASENAMES[@]}" \
        | ssh "$HOST" "tar -C '${WIDGETS_DIR}' -xf - && chmod 644 '${WIDGETS_DIR}'/zynthian_widget_*.py"
    printf '%s\n' "${WIDGET_BASENAMES[@]}" \
        | ssh "$HOST" "cat > '${WIDGETS_DIR}/${MANIFEST_NAME}'"
fi

if [ "$WITH_PATCHES" -eq 1 ]; then
    echo ""
    run_patches "apply"
fi

echo ""
if [ "$RESTART_UI" -eq 1 ]; then
    restart_zynthian
else
    echo "Done! Installed ${#WIDGETS[@]} widgets."
    if [ "$WITH_PATCHES" -eq 0 ]; then
        echo "Optional: re-run with --with-patches to also apply Zynthian UI patches (menu ◆ badge & widget priority)."
    fi
    if [ "$IS_LOCAL" -eq 1 ]; then
        echo "Load/reload a synth in Zynthian, or restart UI: systemctl restart zynthian"
    else
        echo "Load/reload a synth in Zynthian, or restart UI: ssh ${HOST} systemctl restart zynthian"
    fi
fi
