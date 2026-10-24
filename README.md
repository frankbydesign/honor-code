# Honor Code

A personal app for keeping track of the commitments I make on calls and in
email, and following through on them. It reads Fathom transcripts now and will
read Gmail later. It runs on my own machine: one SQLite file, Google sign-in,
nothing hosted.

The repo is a monorepo. `apps/api` is the FastAPI backend, `apps/web` is the
Angular frontend, `docs/` is notes.

## Running it

You need `uv` (Python) and `pnpm` (Node). Then:

```bash
cd apps/api
cp .env.example .env        # fill it in; the comments say how
uv sync
uv run --env-file .env alembic upgrade head
uv run --env-file .env uvicorn app.main:app --reload
```

That is the API on `localhost:8000`. `/api/health` returns
`{"status":"ok","database":"connected"}` when things are working. The database
is `apps/api/data/honor-code.db`, created on the first run.

The frontend, in a second terminal:

```bash
cd apps/web
pnpm install                # first time
pnpm start
```

That is `localhost:4200`. The dev server proxies `/api` to the API, so the
browser only ever talks to one origin and there is no CORS anywhere. For sign-in
to land you back on the dev server, set `POST_LOGIN_REDIRECT=http://localhost:4200/`
in `apps/api/.env`.

## Google sign-in

One OAuth client in Google Cloud Console, with one authorized redirect URI:
`http://localhost:8000/api/auth/google/callback`. Put its client ID and secret in
`.env`, and your own address in `ALLOWED_EMAILS`. Nobody else can sign in.

The API derives that redirect URI from `APP_BASE_URL`; it never trusts the
incoming request for it. Cookies are `Secure` only when `APP_BASE_URL` is
https, and plain http is refused for any host but localhost.

## Database changes

Models live in `apps/api/app/db/models/`. After editing them:

```bash
cd apps/api
uv run --env-file .env alembic revision --autogenerate -m "what changed"
uv run --env-file .env alembic upgrade head
```

`alembic downgrade -1` undoes the last migration; `alembic downgrade base` drops
everything. Re-running `upgrade head` on a current database does nothing.

## Tests

```bash
cd apps/api && uv run pytest      # no .env, no network, nothing running
cd apps/web && pnpm test          # vitest, headless
```

The API suite mocks Google at one seam (Authlib's token exchange) and refuses
any real network call. The one thing it cannot check is the actual Google
round-trip; do that in a browser after changing anything in `app/auth/`.

## Notes to self

- Timestamps are `UTCDateTime` (`app/db/types.py`), never a bare `DateTime`.
  SQLite returns naive datetimes otherwise and the session-expiry comparison
  blows up. Never import from `sqlalchemy.dialects`; the models are
  dialect-neutral on purpose so moving to Postgres later is one new migration.
- Foreign keys are only enforced because `make_engine` turns the pragma on
  for every connection. Without it, deleting a user leaves its sessions behind.
- Cookies on `localhost` are shared across ports. That is why a session set by
  the API on `:8000` is sent on requests from the page on `:4200`, and why dev
  mode works without any cross-origin configuration.
- The default `DATABASE_URL` is an absolute path anchored to `apps/api`, so the
  server and Alembic use the same file no matter which directory they start in.
- Not here yet: a one-process mode where the API serves the built frontend, and
  CI. Both are in the plan; see `docs/`.
