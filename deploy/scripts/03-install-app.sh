#!/bin/bash
# Builds and starts the app and its database as the gandytradeco user.
# Run via root:  bash deploy/scripts/as-app-user.sh deploy/scripts/03-install-app.sh
# Safe to run again; existing settings and data are kept.
set -euo pipefail
source "$(dirname "$0")/settings.sh"

[ "$(id -un)" = "$APP_USER" ] || { echo "Run this as $APP_USER (use as-app-user.sh)."; exit 1; }
REPO="$HOME/gandytrade-lab"
CONF="$HOME/gandytrade"
UNITS="$HOME/.config/containers/systemd"

mkdir -p "$CONF" "$UNITS"
chmod 700 "$CONF"

# 1. Settings files with freshly generated passwords (only created once).
if [ ! -f "$CONF/db.env" ]; then
  db_pw=$(openssl rand -hex 24)
  umask 077
  printf 'POSTGRES_USER=gandytrade\nPOSTGRES_PASSWORD=%s\nPOSTGRES_DB=gandytrade\n' "$db_pw" > "$CONF/db.env"
  ok "Database settings created"
fi
if [ ! -f "$CONF/app.env" ]; then
  db_pw=$(grep '^POSTGRES_PASSWORD=' "$CONF/db.env" | cut -d= -f2)
  umask 077
  cat > "$CONF/app.env" <<EOF
GT_DATABASE_URL=postgresql://gandytrade:${db_pw}@gandytrade-db:5432/gandytrade
GT_SECRET_KEY=$(openssl rand -hex 32)
GT_COOKIE_SECURE=true
# Read-only market data. Leave blank for clearly labelled sample data.
# OANDA: a DEMO ("fxTrade Practice") account token only.
GT_OANDA_TOKEN=
GT_TWELVEDATA_KEY=
EOF
  ok "App settings created at $CONF/app.env"
fi
chmod 600 "$CONF"/*.env

# 2. Build the app image (first build downloads base images; allow a few minutes).
echo "Building the app image..."
podman build -t localhost/gandytrade-app:latest -f "$REPO/deploy/Containerfile" "$REPO"
ok "App image built"

# 3. Install the service definitions and start everything.
for f in "$REPO"/deploy/quadlet/*; do
  sed -e "s#__CONF__#$CONF#g" -e "s#__PORT__#$APP_PORT#g" "$f" > "$UNITS/$(basename "$f")"
done
systemctl --user daemon-reload
systemctl --user restart gandytrade-db.service
systemctl --user restart gandytrade-app.service

echo "Waiting for the app to start..."
for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:$APP_PORT/api/health" >/dev/null 2>&1; then
    ok "App is running on 127.0.0.1:$APP_PORT (not reachable from outside yet)"
    echo
    echo "Next: create your login (as root):"
    echo "  bash deploy/scripts/as-app-user.sh podman exec -it gandytrade-app python -m app.cli create-user"
    exit 0
  fi
  sleep 3
done
fail "App didn't start. Recent logs:"
journalctl --user -u gandytrade-app.service -n 40 --no-pager || podman logs --tail 40 gandytrade-app || true
exit 1
