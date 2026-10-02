#!/bin/bash
# Put a backup back. Replaces the current database, after saving a copy of it first.
#   FILE is either a .sql.gz from ~/gandytrade/backups, or a .enc file downloaded from the Backblaze
#   bucket and uploaded to ~/gandytrade/backups (it's decrypted with GT_BACKUP_PASSPHRASE from app.env).
# As root:  bash deploy/scripts/as-app-user.sh deploy/scripts/restore.sh ~/gandytrade/backups/FILE
set -euo pipefail
source "$(dirname "$0")/settings.sh"

[ "$(id -un)" = "$APP_USER" ] || { echo "Run this as $APP_USER (use as-app-user.sh)."; exit 1; }
[ $# -eq 1 ] && [ -f "$1" ] || { echo "Usage: restore.sh <backup file>"; exit 1; }
CONF="$HOME/gandytrade"
BACKUPS="$CONF/backups"
IMAGE=localhost/gandytrade-app:latest
src="$1"
ts=$(date -u +%Y%m%d-%H%M%S)
db() { podman exec -i gandytrade-db sh -c "$1"; }

if [[ "$src" == *.enc ]]; then
  plain="$BACKUPS/restore-$ts.sql.gz"
  ( umask 077
    podman run --rm -i --env-file "$CONF/app.env" --network none --read-only --cap-drop all \
      --security-opt no-new-privileges "$IMAGE" python -m app.backup decrypt < "$src" > "$plain" ) \
    || { rm -f "$plain"; fail "Couldn't decrypt it. Is GT_BACKUP_PASSPHRASE in app.env the one used when it was made?"; exit 1; }
  ok "Decrypted"
  src="$plain"
fi
gzip -t "$src" || { fail "That file is damaged or isn't a database backup."; exit 1; }

echo
echo "This will REPLACE the current database with: $(basename "$src") ($(du -h "$src" | cut -f1))"
echo "A copy of the current database is saved first, so this can be undone the same way."
read -r -p "Type RESTORE to go ahead: " answer
[ "$answer" = "RESTORE" ] || { echo "Nothing changed."; exit 0; }

safety="$BACKUPS/pre-restore-$ts.sql.gz"
( umask 077; db 'pg_dump --no-owner -U "$POSTGRES_USER" "$POSTGRES_DB"' | gzip > "$safety" ) && gzip -t "$safety" \
  || { fail "Couldn't save a copy of the current database first, so nothing was changed."; exit 1; }
ok "Current database saved to $safety"

systemctl --user stop gandytrade-worker.service gandytrade-app.service
if db 'dropdb -U "$POSTGRES_USER" "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB"' \
   && gunzip -c "$src" | db 'psql -v ON_ERROR_STOP=1 -q -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null; then
  ok "Backup loaded"
else
  fail "Loading the backup failed. To put things back as they were, run restore.sh again with: $safety"
fi
systemctl --user start gandytrade-app.service
for _ in $(seq 1 40); do
  curl -fsS "http://127.0.0.1:$APP_PORT/api/health" >/dev/null 2>&1 && break
  sleep 3
done
systemctl --user start gandytrade-worker.service
ok "App and worker restarted. Sign in and check your accounts."
