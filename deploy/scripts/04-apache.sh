#!/bin/bash
# Puts the app on https://gandytrade.co.uk behind a password gate.
# Only gandytrade.co.uk's own Apache settings are added; other sites are untouched.
# Apache's configuration is tested before it's reloaded, and rolled back if the test fails.
#
# Run as root:  bash /home/gandytradeco/gandytrade-lab/deploy/scripts/04-apache.sh
# Undo:         bash /home/gandytradeco/gandytrade-lab/deploy/scripts/04-apache.sh --remove
set -euo pipefail
source "$(dirname "$0")/settings.sh"

[ "$(id -u)" -eq 0 ] || { echo "Run as root."; exit 1; }
HERE="$(cd "$(dirname "$0")/.." && pwd)"
SSL_DIR="/etc/apache2/conf.d/userdata/ssl/2_4/$APP_USER/$DOMAIN"
STD_DIR="/etc/apache2/conf.d/userdata/std/2_4/$APP_USER/$DOMAIN"
SSL_FILE="$SSL_DIR/gandytrade.conf"
STD_FILE="$STD_DIR/gandytrade.conf"
REBUILD=/usr/local/cpanel/scripts/rebuildhttpdconf
RESTART=/usr/local/cpanel/scripts/restartsrv_httpd

config_test() { /usr/sbin/httpd -t >/dev/null 2>&1; }

remove_files() {
  rm -f "$SSL_FILE" "$STD_FILE"
  rmdir "$SSL_DIR" "$STD_DIR" 2>/dev/null || true
}

if [ "${1:-}" = "--remove" ]; then
  remove_files
  "$REBUILD" >/dev/null
  config_test || { fail "Apache config test failed after removal; nothing restarted. Paste this to Claude."; exit 1; }
  "$RESTART" >/dev/null
  ok "GandyTrade settings removed from $DOMAIN and Apache reloaded"
  exit 0
fi

# 0. The app must be running first.
curl -fsS "http://127.0.0.1:$APP_PORT/api/health" >/dev/null || { fail "App isn't running on port $APP_PORT. Run 03-install-app.sh first."; exit 1; }

# 0b. Apache must be healthy before we touch anything.
config_test || { fail "Apache's current configuration already fails its test. Not changing anything."; exit 1; }

# 1. Password gate file (asks for a username and password the first time).
mkdir -p "$(dirname "$HTPASSWD_FILE")"
if [ ! -s "$HTPASSWD_FILE" ]; then
  read -rp "Choose a username for the site's password gate: " gate_user
  [ -n "$gate_user" ] || { echo "Username can't be empty."; exit 1; }
  if command -v htpasswd >/dev/null; then
    htpasswd -B -c "$HTPASSWD_FILE" "$gate_user"
  else
    read -rsp "Password: " p1; echo
    read -rsp "Repeat password: " p2; echo
    [ "$p1" = "$p2" ] || { echo "Passwords don't match."; exit 1; }
    printf '%s:%s\n' "$gate_user" "$(openssl passwd -apr1 "$p1")" > "$HTPASSWD_FILE"
  fi
fi
web_group=$( (ps -o group= -C httpd 2>/dev/null || true) | (grep -v root || true) | sort -u | head -1 | tr -d ' ')
chown root:"${web_group:-nobody}" "$HTPASSWD_FILE"
chmod 640 "$HTPASSWD_FILE"
ok "Password gate file ready ($HTPASSWD_FILE)"

# 2. Site-specific settings for gandytrade.co.uk only.
mkdir -p "$SSL_DIR" "$STD_DIR"
render() {
  sed -e "s#__DOMAIN__#$DOMAIN#g" -e "s#__PORT__#$APP_PORT#g" -e "s#__HTPASSWD__#$HTPASSWD_FILE#g" "$1"
}
render "$HERE/apache/ssl.conf.tmpl" > "$SSL_FILE"
render "$HERE/apache/std.conf.tmpl" > "$STD_FILE"
"$REBUILD" >/dev/null

# 3. Test before reloading; roll back if the test fails, so other sites are never affected.
if ! config_test; then
  /usr/sbin/httpd -t 2>&1 | tail -5
  remove_files
  "$REBUILD" >/dev/null
  fail "Apache rejected the new settings. They've been removed and nothing was restarted. Paste this to Claude."
  exit 1
fi
"$RESTART" >/dev/null
ok "Apache reloaded with settings for $DOMAIN only"
echo
echo "Open https://$DOMAIN : you'll see the password prompt, then the app's sign-in page."
