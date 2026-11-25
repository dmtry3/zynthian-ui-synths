#!/usr/bin/env bash
set -euo pipefail

# UI Synths (zynthian-ui-synths) installer
HOST="${1:-root@10.0.99.99}"
REMOTE_DIR="/zynthian/zynthian-ui/zyngui/widgets_user"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

WIDGETS=("${SCRIPT_DIR}"/zynthian_widget_*.py)
if [ ${#WIDGETS[@]} -eq 0 ]; then
    echo "No zynthian_widget_*.py files found in ${SCRIPT_DIR}" >&2
    exit 1
fi

echo "Installing UI Synths (${#WIDGETS[@]} widget(s)) to ${HOST}:${REMOTE_DIR}/ ..."
for f in "${WIDGETS[@]}"; do
    echo "  -> $(basename "$f")"
    scp "$f" "${HOST}:${REMOTE_DIR}/$(basename "$f")"
done
echo "Done! Load or reload the synth in Zynthian (or restart zynthian service if it was already open)."
