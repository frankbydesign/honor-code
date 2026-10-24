#!/usr/bin/env bash
# Frontend development: the API with --reload on :8000 and the Angular dev
# server with hot reload on :4200, in one terminal. The dev server proxies
# /api to the API (apps/web/proxy.conf.json). Ctrl-C stops both.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API="$ROOT/apps/api"
WEB="$ROOT/apps/web"
ENV_FILE="$API/.env"
API_PORT=8000   # must match the proxy target in apps/web/proxy.conf.json
WEB_PORT=4200
. "$ROOT/scripts/_lib.sh"

die() { say "dev.sh: $*"; exit 1; }

command -v uv >/dev/null || die "uv is not installed (https://docs.astral.sh/uv/)"
command -v pnpm >/dev/null || die "pnpm is not installed (https://pnpm.io/)"
command -v curl >/dev/null || die "curl is not installed"
[ -f "$ENV_FILE" ] || die "no $ENV_FILE. Copy apps/api/.env.example to apps/api/.env and fill it in."

# Google redirects the browser to APP_BASE_URL/api/auth/google/callback, so
# the API has to be listening where APP_BASE_URL says, and the proxy only
# knows about :8000.
base_url="$(read_env_var "$ENV_FILE" APP_BASE_URL)"
[ -n "$base_url" ] || die "APP_BASE_URL is not set in $ENV_FILE"
if [ "$(url_port "$base_url")" != "$API_PORT" ]; then
  die "APP_BASE_URL is $base_url but the dev proxy targets :$API_PORT. Keep APP_BASE_URL on :$API_PORT for dev.sh."
fi

for port in "$API_PORT" "$WEB_PORT"; do
  port_in_use "$port" && die "something is already listening on port $port. Stop it first."
done

ensure_node_modules "$WEB"
(cd "$API" && uv sync --quiet >&2)
(cd "$API" && uv run --env-file "$ENV_FILE" alembic upgrade head >&2)

# After sign-in the browser should land on the dev server, not the API.
# Exported here so .env never needs editing between run.sh and dev.sh; an
# exported variable wins over --env-file.
export POST_LOGIN_REDIRECT="http://localhost:$WEB_PORT/"

(cd "$API" && exec uv run --env-file "$ENV_FILE" uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT" --reload) &
api_pid=$!
(cd "$WEB" && exec pnpm start) &
web_pid=$!

cleanup() {
  kill_tree "$api_pid"
  kill_tree "$web_pid"
  wait "$api_pid" "$web_pid" 2>/dev/null || true
}
trap 'cleanup; exit 0' INT TERM

say "API: http://localhost:$API_PORT   app: http://localhost:$WEB_PORT   (Ctrl-C stops both)"

# Stay up while both are alive; stop both when either exits. (`wait -n`
# would be the natural tool, but it needs bash 4.3 and macOS ships 3.2.)
while kill -0 "$api_pid" 2>/dev/null && kill -0 "$web_pid" 2>/dev/null; do
  sleep 1
done
cleanup
