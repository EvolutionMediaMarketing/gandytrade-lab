#!/bin/bash
# Nightly backup, run by the gandytrade-backup timer (and safe to run by hand):
#   1. dump the database to ~/gandytrade/backups (owner-only),
#   2. prove the dump restores, by loading it into a scratch database and comparing it with the real one,
#   3. encrypt it and copy it to the Backblaze bucket (when the GT_BACKUP_ settings are in app.env),
#   4. record the result, so the app can warn you if backups stop working.
# By hand (as root):  bash deploy/scripts/as-app-user.sh deploy/scripts/backup.sh
set -euo pipefail
source "$(dirname "$0")/settings.sh"

[ "$(id -un)" = "$APP_USER" ] || { echo "Run this as $APP_USER (use as-app-user.sh)."; exit 1; }
CONF="$HOME/gandytrade"
BACKUPS="$CONF/backups"
IMAGE=localhost/gandytrade-app:latest
KEEP_LOCAL=14
SCRATCH=gt_restore_test
mkdir -p "$BACKUPS" && chmod 700 "$BACKUPS"

# A throwaway, locked-down copy of the app container: reads the backup from standard input, never from disk.
app_tool() {
  podman run --rm -i --network gandytrade --env-file "$CONF/app.env" \
    --read-only --cap-drop all --security-opt no-new-privileges "$IMAGE" python -m app.backup "$@"
}
failed() {
  fail "$1"
  app_tool record-failure "$1" </dev/null >/dev/null 2>&1 || true
  exit 1
}
db() {  # run a command inside the database container, with its own settings
  podman exec -i gandytrade-db sh -c "$1"
}

podman container exists gandytrade-db && [ "$(podman inspect -f '{{.State.Running}}' gandytrade-db)" = "true" ] \
  || failed "Backup skipped: the database wasn't running."

# 1. Dump
ts=$(date -u +%Y%m%d-%H%M%S)
name="gandytrade-$ts.sql.gz"
file="$BACKUPS/nightly-$ts.sql.gz"
if ( umask 077; db 'pg_dump --no-owner -U "$POSTGRES_USER" "$POSTGRES_DB"' | gzip > "$file.part" ) \
   && [ -s "$file.part" ] && gzip -t "$file.part"; then
  mv "$file.part" "$file"
  ok "Database dumped ($(du -h "$file" | cut -f1))"
else
  rm -f "$file.part"
  failed "Backup failed: the database dump didn't complete."
fi

# 2. Test restore into a scratch database, then compare it with the real one
tested=""
count_sql="select (select count(*) from information_schema.tables where table_schema='public') || ':' || (select version_num from alembic_version) || ':' || (select count(*) from users)"
if db "dropdb --if-exists -U \"\$POSTGRES_USER\" $SCRATCH 2>/dev/null; createdb -U \"\$POSTGRES_USER\" $SCRATCH" \
   && gunzip -c "$file" | db "psql -v ON_ERROR_STOP=1 -q -U \"\$POSTGRES_USER\" -d $SCRATCH" >/dev/null; then
  live=$(db "psql -tA -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -c \"$count_sql\"") || live=""
  copy=$(db "psql -tA -U \"\$POSTGRES_USER\" -d $SCRATCH -c \"$count_sql\"") || copy=""
  if [ -n "$copy" ] && [ "$live" = "$copy" ]; then
    tested="--restore-tested"
    ok "Test restore matched the live database (tables:version:users = $copy)"
  else
    warn "Test restore didn't match the live database ($copy vs $live)"
  fi
else
  warn "Test restore failed"
fi
db "dropdb --if-exists -U \"\$POSTGRES_USER\" $SCRATCH" >/dev/null 2>&1 || true

# 3 and 4. Encrypt, upload and record (or record that it's kept on the server only)
if out=$(app_tool nightly "$name" $tested < "$file" 2>&1); then
  ok "$out"
else
  fail "$out"
  exit 1
fi
[ -n "$tested" ] || exit 1

# Keep the newest local copies; older ones live in the bucket.
ls -1t "$BACKUPS"/nightly-*.sql.gz 2>/dev/null | tail -n +$((KEEP_LOCAL + 1)) | xargs -r rm -f
