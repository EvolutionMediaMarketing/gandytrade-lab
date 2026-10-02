#!/bin/bash
# Pulls the latest version from GitHub, rebuilds and restarts the app. Data is kept.
# Run via root:  bash deploy/scripts/as-app-user.sh deploy/scripts/update.sh
set -euo pipefail
source "$(dirname "$0")/settings.sh"

[ "$(id -un)" = "$APP_USER" ] || { echo "Run this as $APP_USER (use as-app-user.sh)."; exit 1; }
cd "$HOME/gandytrade-lab"
git pull --ff-only

# Back up the database before the new version upgrades its tables.
# Kept in ~/gandytrade/backups (owner-only); the 10 most recent are kept.
BACKUPS="$HOME/gandytrade/backups"
mkdir -p "$BACKUPS" && chmod 700 "$BACKUPS"
if podman container exists gandytrade-db && [ "$(podman inspect -f '{{.State.Running}}' gandytrade-db)" = "true" ]; then
  file="$BACKUPS/pre-update-$(date -u +%Y%m%d-%H%M%S).sql.gz"
  if ( umask 077
       podman exec gandytrade-db sh -c 'pg_dump --no-owner -U "$POSTGRES_USER" "$POSTGRES_DB"' | gzip > "$file.part" ) \
     && [ -s "$file.part" ] && gzip -t "$file.part"; then
    mv "$file.part" "$file"
    ok "Database backed up to $file"
  else
    rm -f "$file.part"
    fail "Database backup failed, so the new version was not installed; the app keeps running as before. Paste this to Claude."
    exit 1
  fi
  ls -1t "$BACKUPS"/pre-update-*.sql.gz 2>/dev/null | tail -n +11 | xargs -r rm -f
fi

exec bash deploy/scripts/03-install-app.sh
