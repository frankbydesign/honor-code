#!/usr/bin/env bash
# Frontend development: the API with --reload on :8000 and the Angular dev
# server with hot reload on :4200, in one terminal. The dev server proxies
# /api to the API. Ctrl-C stops both.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API="$ROOT/apps/api"
WEB="$ROOT/apps/web"
ENV_FILE="$API/.env"

say() { printf '%s\n' "$*" >&2; }
die() { say "dev.sh: $*"; exit 1; }

command -v uv >/dev/null || die "uv is not installed (https://docs.astral.sh/uv/)"
command -v pnpm >/dev/null || die "pnpm is not installed (https://pnpm.io/)"
[ -f "$ENV_FILE" ] || die "no $ENV_FILE. Copy apps/api/.env.example to apps/api/.env and fill it in."

if ! grep -qE '^POST_LOGIN_REDIRECT=http://localhost:4200/?$' "$ENV_FILE"; then
  say "note: set POST_LOGIN_REDIRECT=http://localhost:4200/ in apps/api/.env so sign-in lands back on the dev server."
fi

[ -d "$WEB/node_modules" ] || (cd "$WEB" && pnpm install --frozen-lockfile >&2)
(cd "$API" && uv sync --quiet >&2)
(cd "$API" && uv run --env-file "$ENV_FILE" alembic upgrade head >&2)

(cd "$API" && exec uv run --env-file "$ENV_FILE" uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload) &
api_pid=$!
(cd "$WEB" && exec pnpm start) &
web_pid=$!

cleanup() {
  kill "$api_pid" "$web_pid" 2>/dev/null || true
  wait "$api_pid" "$web_pid" 2>/dev/null || true
}
trap 'cleanup; exit 0' INT TERM

say "API: http://localhost:8000   app: http://localhost:4200   (Ctrl-C stops both)"
wait -n "$api_pid" "$web_pid" || true
cleanup
