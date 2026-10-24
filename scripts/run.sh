#!/usr/bin/env bash
# Daily use: one process on http://localhost:8000 serving the API and the
# built frontend. Builds the frontend only when it is missing or stale,
# applies any pending migrations, then starts the server. Ctrl-C stops it.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API="$ROOT/apps/api"
WEB="$ROOT/apps/web"
DIST="$WEB/dist/web/browser"
ENV_FILE="$API/.env"
PORT="${PORT:-8000}"
URL="http://localhost:$PORT"

say() { printf '%s\n' "$*" >&2; }
die() { say "run.sh: $*"; exit 1; }

command -v uv >/dev/null || die "uv is not installed (https://docs.astral.sh/uv/)"
command -v pnpm >/dev/null || die "pnpm is not installed (https://pnpm.io/)"

[ -f "$ENV_FILE" ] || die "no $ENV_FILE. Copy apps/api/.env.example to apps/api/.env and fill it in."

# Refuse early if the port is taken, instead of a traceback from uvicorn.
if (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; then
  die "port $PORT is already in use. Stop the other server (or run with PORT=8001)."
fi

# Frontend: build when there is no build, or any source is newer than it.
needs_build=0
if [ ! -f "$DIST/index.html" ]; then
  needs_build=1
elif [ -n "$(find "$WEB/src" "$WEB/angular.json" "$WEB/package.json" -newer "$DIST/index.html" -type f -print -quit 2>/dev/null)" ]; then
  needs_build=1
fi
if [ "$needs_build" = 1 ]; then
  [ -d "$WEB/node_modules" ] || (cd "$WEB" && pnpm install --frozen-lockfile >&2)
  say "building frontend..."
  (cd "$WEB" && pnpm build >&2)
fi

# Backend: dependencies, migrations, then the server.
(cd "$API" && uv sync --quiet >&2)
(cd "$API" && uv run --env-file "$ENV_FILE" alembic upgrade head >&2)

cd "$API"
uv run --env-file "$ENV_FILE" uvicorn app.main:app --host 127.0.0.1 --port "$PORT" \
  --log-level warning --no-access-log &
server=$!
trap 'kill "$server" 2>/dev/null; wait "$server" 2>/dev/null; exit 0' INT TERM

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
kill "$server" 2>/dev/null || true
die "the server did not answer /api/health within 30 seconds."
