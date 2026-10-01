#!/bin/bash
# Run a command as the app user, from the code folder, with its background
# service manager available. Used by root for the steps that belong to the user.
# Example:  bash as-app-user.sh deploy/scripts/03-install-app.sh
set -euo pipefail
source "$(dirname "$0")/settings.sh"

[ "$(id -u)" -eq 0 ] || { echo "Run as root."; exit 1; }
[ $# -gt 0 ] || { echo "Usage: $0 <command> [args...]"; exit 1; }

uid=$(id -u "$APP_USER")
home=$(getent passwd "$APP_USER" | cut -d: -f6)
exec runuser -u "$APP_USER" -- env -i \
  HOME="$home" USER="$APP_USER" LOGNAME="$APP_USER" TERM="${TERM:-xterm}" \
  PATH=/usr/local/bin:/usr/bin:/bin \
  XDG_RUNTIME_DIR="/run/user/$uid" \
  DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$uid/bus" \
  APP_USER="$APP_USER" DOMAIN="$DOMAIN" APP_PORT="$APP_PORT" \
  bash -c 'cd "$HOME/gandytrade-lab" && exec "$@"' bash "$@"
