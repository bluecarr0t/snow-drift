#!/usr/bin/env bash
# Stop, disable, and remove the snow-drift systemd unit.

set -euo pipefail

SERVICE_NAME="snow-drift"
TARGET="/etc/systemd/system/${SERVICE_NAME}.service"

if [[ $EUID -ne 0 ]]; then
    echo "ERROR: this script must be run as root (sudo)." >&2
    exit 1
fi

if systemctl list-unit-files "${SERVICE_NAME}.service" --no-legend 2>/dev/null \
    | grep -q "^${SERVICE_NAME}.service"; then
    systemctl stop "$SERVICE_NAME" 2>/dev/null || true
    systemctl disable "$SERVICE_NAME" 2>/dev/null || true
fi

rm -f "$TARGET"
systemctl daemon-reload

echo "Uninstalled $SERVICE_NAME. Journal history is retained;"
echo "run 'sudo journalctl --vacuum-time=1d' to drop old entries if desired."
