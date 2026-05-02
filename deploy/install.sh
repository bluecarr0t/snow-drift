#!/usr/bin/env bash
# Install (or refresh) the snow-drift systemd unit.
#
# Auto-detects user, working directory, and Python interpreter. Override
# any of those with environment variables or flags:
#
#   sudo ./deploy/install.sh
#   sudo SVC_USER=nick SVC_WORKDIR=/home/nick/snow-drift ./deploy/install.sh
#   sudo ./deploy/install.sh --user nick --workdir /home/nick/snow-drift
#
# Re-running this script is safe: it overwrites the unit file in place
# and reloads systemd. If the service is already running it will not be
# restarted automatically; use --restart to do that explicitly.

set -euo pipefail

SERVICE_NAME="snow-drift"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="${SCRIPT_DIR}/${SERVICE_NAME}.service.template"
TARGET="/etc/systemd/system/${SERVICE_NAME}.service"

# ---------------------------------------------------------------------------
# Defaults: prefer the invoking user, the repo root, and system Python.
# ---------------------------------------------------------------------------
SVC_USER="${SVC_USER:-${SUDO_USER:-${USER}}}"
SVC_GROUP="${SVC_GROUP:-${SVC_USER}}"
SVC_WORKDIR="${SVC_WORKDIR:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
SVC_PYTHON="${SVC_PYTHON:-/usr/bin/python3}"

DO_RESTART=0

# ---------------------------------------------------------------------------
# Parse flags (env vars still win as overrides via the := pattern above).
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --user)     SVC_USER="$2"; SVC_GROUP="${SVC_GROUP:-$2}"; shift 2 ;;
        --group)    SVC_GROUP="$2"; shift 2 ;;
        --workdir)  SVC_WORKDIR="$2"; shift 2 ;;
        --python)   SVC_PYTHON="$2"; shift 2 ;;
        --restart)  DO_RESTART=1; shift ;;
        -h|--help)
            sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 1
            ;;
    esac
done

# ---------------------------------------------------------------------------
# Sanity checks.
# ---------------------------------------------------------------------------
if [[ $EUID -ne 0 ]]; then
    echo "ERROR: this script must be run as root (sudo)." >&2
    exit 1
fi

if [[ ! -f "$TEMPLATE" ]]; then
    echo "ERROR: unit template not found at $TEMPLATE" >&2
    exit 1
fi

if ! id "$SVC_USER" >/dev/null 2>&1; then
    echo "ERROR: user '$SVC_USER' does not exist on this system." >&2
    exit 1
fi

if [[ ! -d "$SVC_WORKDIR" ]]; then
    echo "ERROR: working directory '$SVC_WORKDIR' does not exist." >&2
    exit 1
fi

if [[ ! -d "$SVC_WORKDIR/snow_drift" ]]; then
    echo "ERROR: '$SVC_WORKDIR' does not look like the snow-drift repo" >&2
    echo "       (no snow_drift/ package found inside)." >&2
    exit 1
fi

if [[ ! -x "$SVC_PYTHON" ]]; then
    echo "ERROR: python interpreter '$SVC_PYTHON' is not executable." >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Render and install.
# ---------------------------------------------------------------------------
echo "Installing $SERVICE_NAME systemd unit:"
echo "  User:        $SVC_USER"
echo "  Group:       $SVC_GROUP"
echo "  WorkingDir:  $SVC_WORKDIR"
echo "  Python:      $SVC_PYTHON"
echo "  Target:      $TARGET"

sed -e "s|@@USER@@|${SVC_USER}|g" \
    -e "s|@@GROUP@@|${SVC_GROUP}|g" \
    -e "s|@@WORKDIR@@|${SVC_WORKDIR}|g" \
    -e "s|@@PYTHON@@|${SVC_PYTHON}|g" \
    "$TEMPLATE" > "$TARGET"
chmod 644 "$TARGET"

# Warn if the service user is missing the GPIO / I2C groups. The
# service will fail at start otherwise, but it's friendlier to flag
# this here.
for grp in gpio i2c; do
    if getent group "$grp" >/dev/null 2>&1; then
        if ! id -nG "$SVC_USER" | tr ' ' '\n' | grep -qx "$grp"; then
            echo
            echo "WARNING: user '$SVC_USER' is not in the '$grp' group."
            echo "         Fix with: sudo usermod -aG $grp $SVC_USER"
            echo "         Then log out and back in (group changes need a fresh session)."
        fi
    fi
done

systemctl daemon-reload
systemctl enable "$SERVICE_NAME" >/dev/null

echo
echo "Installed. Useful commands:"
echo "  sudo systemctl start $SERVICE_NAME      # start now"
echo "  sudo systemctl stop $SERVICE_NAME       # stop"
echo "  sudo systemctl restart $SERVICE_NAME    # restart (e.g. after git pull)"
echo "  sudo systemctl status $SERVICE_NAME     # one-shot health check"
echo "  journalctl -u $SERVICE_NAME -f          # live logs"
echo "  journalctl -u $SERVICE_NAME -p warning  # warnings + errors only"

if [[ "$DO_RESTART" -eq 1 ]]; then
    echo
    echo "Restarting $SERVICE_NAME..."
    systemctl restart "$SERVICE_NAME"
    sleep 1
    systemctl --no-pager status "$SERVICE_NAME" | head -n 12 || true
fi
