#!/usr/bin/env bash
# Daily use: one process serving the API and the built frontend at
# APP_BASE_URL (normally http://localhost:8000). Builds the frontend only when
# it is missing or stale, applies any pending migrations, then starts the
# server. Prints the URL once it answers. Ctrl-C stops it.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API="$ROOT/apps/api"
WEB="$ROOT/apps/web"
DIST="$WEB/dist/web/browser"
ENV_FILE="$API/.env"
. "$ROOT/scripts/_lib.sh"

die() { say "run.sh: $*"; exit 1; }

command -v uv >/dev/null || die "uv is not installed (https://docs.astral.sh/uv/)"
command -v pnpm >/dev/null || die "pnpm is not installed (https://pnpm.io/)"
command -v curl >/dev/null || die "curl is not installed"

[ -f "$ENV_FILE" ] || die "no $ENV_FILE. Copy apps/api/.env.example to apps/api/.env and fill it in."

# The port is not a knob of this script. It follows APP_BASE_URL, because the
# OAuth redirect URI (and the one registered with Google) is derived from
# that; a server on a different port could never complete a sign-in.
URL="$(read_env_var "$ENV_FILE" APP_BASE_URL)"
[ -n "$URL" ] || die "APP_BASE_URL is not set in $ENV_FILE"
URL="${URL%/}"
PORT="$(url_port "$URL")"

# Refuse early if the port is taken, instead of a traceback from uvicorn.
if port_in_use "$PORT"; then
  die "something is already listening on port $PORT (APP_BASE_URL is $URL). Stop it first."
fi

# Frontend: build when there is no build, or anything that feeds the build is
# newer than it. Deleting a source file does not count; run pnpm build by hand.
needs_build=0
if [ ! -f "$DIST/index.html" ]; then
  needs_build=1
else
  inputs=()
  for p in "$WEB/src" "$WEB/public" "$WEB/angular.json" "$WEB/package.json" "$WEB/pnpm-lock.yaml" "$WEB"/tsconfig*.json; do
    [ -e "$p" ] && inputs+=("$p")
  done
  if [ -n "$(find "${inputs[@]}" -newer "$DIST/index.html" -type f -print 2>/dev/null | head -n 1)" ]; then
    needs_build=1
  fi
fi
if [ "$needs_build" = 1 ]; then
  ensure_node_modules "$WEB"
  say "building frontend..."
  (cd "$WEB" && pnpm build >&2)
fi

# Backend: dependencies, migrations, then the server. In one-process mode the
# browser must land back on this server after sign-in, whatever .env says
# (dev.sh sets the dev-server value the same way). An exported variable wins
# over --env-file.
(cd "$API" && uv sync --quiet >&2)
(cd "$API" && uv run --env-file "$ENV_FILE" alembic upgrade head >&2)
export POST_LOGIN_REDIRECT=/

cd "$API"
uv run --env-file "$ENV_FILE" uvicorn app.main:app --host 127.0.0.1 --port "$PORT" \
  --log-level warning --no-access-log &
server=$!
trap 'kill_tree "$server"; wait "$server" 2>/dev/null; exit 0' INT TERM

# Wait for /api/health, then print the one line that matters.
for _ in $(seq 1 60); do
  if curl -fs "$URL/api/health" >/dev/null 2>&1; then
    printf '%s\n' "$URL"
    wait "$server"
    exit $?
  fi
  if ! kill -0 "$server" 2>/dev/null; then
    die "the server exited during startup; see the messages above."
  fi
  sleep 0.5
done
kill_tree "$server"
die "the server did not answer $URL/api/health within 30 seconds."
