#!/bin/bash
# Lets the gandytradeco user run its own containers in the background.
# Only that user is affected: no other account, service or setting changes.
# Run as root:  bash /home/gandytradeco/gandytrade-lab/deploy/scripts/02-prepare-user.sh
set -euo pipefail
source "$(dirname "$0")/settings.sh"

[ "$(id -u)" -eq 0 ] || { echo "Run as root."; exit 1; }
id "$APP_USER" >/dev/null

# 1. A private range of sub-user IDs, used inside the user's containers.
if grep -q "^$APP_USER:" /etc/subuid && grep -q "^$APP_USER:" /etc/subgid; then
  ok "Sub-user IDs already set"
else
  next=$(awk -F: 'BEGIN{m=100000} {e=$2+$3; if (e>m) m=e} END{print m}' /etc/subuid /etc/subgid 2>/dev/null)
  start=$(( (next + 65535) / 65536 * 65536 ))
  end=$(( start + 65535 ))
  usermod --add-subuids "$start-$end" --add-subgids "$start-$end" "$APP_USER"
  ok "Sub-user IDs $start-$end added for $APP_USER"
fi

# 2. Allow the user's services to keep running when nobody is logged in.
loginctl enable-linger "$APP_USER"
for _ in $(seq 1 20); do
  [ -S "/run/user/$(id -u "$APP_USER")/bus" ] && break
  sleep 1
done
ok "Background services enabled for $APP_USER"

echo
echo "Done. Next: install the app as $APP_USER:"
echo "  bash $(dirname "$0")/as-app-user.sh deploy/scripts/03-install-app.sh"
