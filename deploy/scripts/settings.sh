# shellcheck shell=bash
# Shared settings for the deployment scripts.
APP_USER="${APP_USER:-gandytradeco}"
DOMAIN="${DOMAIN:-gandytrade.co.uk}"
APP_PORT="${APP_PORT:-8601}"
HTPASSWD_FILE="${HTPASSWD_FILE:-/etc/gandytrade/htpasswd}"

ok()   { printf '  \033[32mOK\033[0m    %s\n' "$*"; }
warn() { printf '  \033[33mCHECK\033[0m %s\n' "$*"; }
fail() { printf '  \033[31mSTOP\033[0m  %s\n' "$*"; }
