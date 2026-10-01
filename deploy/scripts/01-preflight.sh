#!/bin/bash
# Read-only checks before installing. Changes nothing on the server.
# Run as root:  bash /home/gandytradeco/gandytrade-lab/deploy/scripts/01-preflight.sh
set -uo pipefail
source "$(dirname "$0")/settings.sh"

problems=0
echo "GandyTrade Lab pre-flight checks (read-only)"
echo

[ "$(id -u)" -eq 0 ] && ok "Running as root" || { fail "Run this as root"; exit 1; }

if id "$APP_USER" >/dev/null 2>&1; then
  home=$(getent passwd "$APP_USER" | cut -d: -f6)
  ok "cPanel user $APP_USER exists (home $home)"
else
  fail "User $APP_USER not found"; problems=$((problems+1))
fi

if command -v podman >/dev/null; then
  v=$(podman version --format '{{.Client.Version}}' 2>/dev/null)
  major=${v%%.*}
  [ "${major:-0}" -ge 5 ] && ok "Podman $v (Quadlet supported)" || { warn "Podman $v: version 5+ expected"; }
else
  fail "Podman not installed"; problems=$((problems+1))
fi

mods=$(/usr/sbin/httpd -M 2>/dev/null)
for m in proxy_module proxy_http_module headers_module rewrite_module auth_basic_module authn_file_module authz_user_module; do
  if grep -q "$m" <<<"$mods"; then ok "Apache module $m"; else fail "Apache module $m missing"; problems=$((problems+1)); fi
done

if ss -ltn "( sport = :$APP_PORT )" | grep -q LISTEN; then
  if curl -fsS "http://127.0.0.1:$APP_PORT/api/health" >/dev/null 2>&1; then
    ok "Port $APP_PORT is already the GandyTrade app"
  else
    fail "Port $APP_PORT is used by something else"; problems=$((problems+1))
  fi
else
  ok "Port $APP_PORT is free"
fi

for tool in git curl openssl; do
  command -v "$tool" >/dev/null && ok "$tool available" || { fail "$tool missing"; problems=$((problems+1)); }
done
if command -v htpasswd >/dev/null; then ok "htpasswd available"; else warn "htpasswd not found; openssl will be used for the password gate"; fi

grep -q "^$APP_USER:" /etc/subuid 2>/dev/null && ok "Sub-user IDs set for $APP_USER" || warn "Sub-user IDs not set yet (02-prepare-user.sh does this)"
[ -f "/var/lib/systemd/linger/$APP_USER" ] && ok "Background services allowed for $APP_USER" || warn "Background services not enabled yet (02-prepare-user.sh does this)"

if command -v whmapi1 >/dev/null; then
  summary=$(whmapi1 accountsummary user="$APP_USER" 2>/dev/null)
  limit=$(awk '/disklimit:/ {print $2; exit}' <<<"$summary")
  used=$(awk '/diskused:/ {print $2; exit}' <<<"$summary")
  if [ "$limit" = "unlimited" ]; then
    ok "Disk quota for $APP_USER: unlimited (used $used)"
  else
    warn "Disk quota for $APP_USER: $limit (used $used). The app needs about 3 GB; raise it in WHM > Modify an Account if lower"
  fi
fi

[ -d "$(getent passwd "$APP_USER" | cut -d: -f6)/gandytrade-lab/.git" ] && ok "Code is in place" || warn "Code not found in ~$APP_USER/gandytrade-lab"

echo
if [ "$problems" -eq 0 ]; then
  echo "No blocking problems. Lines marked CHECK are handled by the next steps or need a look."
else
  echo "$problems blocking problem(s). Paste this output to Claude before continuing."
  exit 1
fi
