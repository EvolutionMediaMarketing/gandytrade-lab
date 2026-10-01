#!/bin/bash
# Pulls the latest version from GitHub, rebuilds and restarts the app. Data is kept.
# Run via root:  bash deploy/scripts/as-app-user.sh deploy/scripts/update.sh
set -euo pipefail
source "$(dirname "$0")/settings.sh"

[ "$(id -un)" = "$APP_USER" ] || { echo "Run this as $APP_USER (use as-app-user.sh)."; exit 1; }
cd "$HOME/gandytrade-lab"
git pull --ff-only
exec bash deploy/scripts/03-install-app.sh
