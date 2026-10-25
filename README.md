# Honor Code

A personal app for keeping track of the commitments I make on calls and in
email, and following through on them. It pulls my Fathom meetings on its own,
has a model pick out what I said I would do, and gives me one screen to accept,
reject, fix, and later close those out. Gmail comes next. It runs on my own
machine: one SQLite file, Google sign-in, nothing hosted.

The repo is a monorepo. `apps/api` is the FastAPI backend, `apps/web` is the
Angular frontend, `docs/` is notes.

## Running it

You need `uv` (Python) and `pnpm` (Node). Then, from the repo root:

```bash
cp apps/api/.env.example apps/api/.env   # fill it in; the comments say how
scripts/run.sh
```

It builds the frontend if needed, applies migrations, starts one process, and
prints the URL: `http://localhost:8000`. That is the whole app. Ctrl-C stops
it. Run it again any time; it only rebuilds when something the build reads is
newer than the last build, and it refuses plainly if the port is taken. The
database is `apps/api/data/honor-code.db`, created on the first run.

The port is whatever `APP_BASE_URL` says. It is not a separate setting, because
the Google redirect URI is derived from `APP_BASE_URL` too; to move the app to
another port, change `APP_BASE_URL` and the redirect URI registered in Google
Cloud Console together.

### Working on the frontend

```bash
scripts/dev.sh
```

That runs the API with reload on `:8000` and the Angular dev server with hot
reload on `:4200`, in one terminal. The dev server proxies `/api` to the API, so
the browser only ever talks to one origin and there is no CORS anywhere. Both
scripts set `POST_LOGIN_REDIRECT` themselves (`/` for `run.sh`,
`http://localhost:4200/` for `dev.sh`), so sign-in lands on the right server
without editing `.env` between them. The scripts need bash 3.2 or later, which
is what macOS ships.

### By hand

The scripts are thin. The same thing, spelled out:

```bash
cd apps/web && pnpm install && pnpm build          # the built app; the API serves it from /
cd ../api
uv run --env-file .env alembic upgrade head
uv run --env-file .env uvicorn app.main:app        # http://localhost:8000
```

The API decides at startup whether a build exists, so build first (or restart
after building). For the dev-server flow, run `uvicorn ... --reload` in one
terminal with `POST_LOGIN_REDIRECT=http://localhost:4200/` exported, and
`pnpm start` in `apps/web` in another.

`/api/health` returns `{"status":"ok","database":"connected"}` when things are
working. Without a frontend build the API starts anyway, logs one warning, and
`/` is a 404.

## Using it

Put `ANTHROPIC_API_KEY` and `FATHOM_API_KEY` in `apps/api/.env` (the template
says where each comes from), start the app, and sign in once. A few seconds
after startup it syncs: the first time it reaches 14 days back, after that it
picks up from the last sync, and it syncs again every 30 minutes while it
runs. **Sync now** in the header does it on demand. Each new meeting is read
by the model, and whatever you committed to lands on **Review** as a
candidate, grouped by who it is for. Accept the real ones, reject the noise,
fix the wording or the date in place, and mark them done (or drop them, with
a reason) when they are finished. **Meetings** lists what has been synced; a
meeting's page shows its transcript, the extraction runs, and Fathom's own
action items for comparison.

Without the keys the app still runs, and the header says which key is
missing. The sync only runs while the app does (ADR 0003).

## Evaluating the prompt

Tests cannot say whether the model finds the right commitments; your own
meetings can. `apps/api/eval/README.md` walks through a round: save a few
real meetings (git-ignored), write down what you know you promised, run the
script against one or two models, read the scores. ADR 0002 explains why it
works this way.

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
- One-process mode serves `apps/web/dist/web/browser` from `/` with an SPA
  fallback for paths without a file extension. Nothing under `/api` is ever
  served from disk, whatever the method: a miss is a JSON 404, a known path
  with the wrong method is a 405 with `Allow`, same as with no build mounted.
  `index.html` goes out with `Cache-Control: no-cache` so a rebuild cannot
  leave the browser holding a page that names bundles that no longer exist.
  `WEB_DIST_DIR` overrides the location (the tests use it).
- CI runs both suites and the build on every PR (`.github/workflows/ci.yml`). The
  decisions behind the whole shape are in `docs/adr/0001-local-first-sqlite-no-deployment.md`.
