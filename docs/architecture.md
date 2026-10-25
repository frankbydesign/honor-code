# Architecture

One process, one origin, one file of data. The decisions behind this shape are
in [ADR 0001](adr/0001-local-first-sqlite-no-deployment.md).

## Request path

Daily use (`scripts/run.sh`):

```
browser ──► FastAPI :8000 ──┬── /api/*  ──► routers ──► SQLite (apps/api/data/honor-code.db)
                            └── /*      ──► built Angular app (apps/web/dist/web/browser)
```

Frontend development (`scripts/dev.sh`):

```
browser ──► Angular dev server :4200 ──┬── /api/*  ──proxy──► FastAPI :8000 ──► SQLite
                                       └── /*      ──► live-reloaded app
```

In both modes the browser talks to exactly one origin, so there is no CORS
configuration anywhere. Cookies set by the API on `localhost` are shared across
ports, which is why the dev-server mode works without special handling.

## Backend (`apps/api`)

FastAPI, built by `create_app()` in `app/main.py`. Routes live under `/api`,
and nothing under `/api` is ever served from disk, whatever the method: a miss
is a JSON 404, a known path with the wrong method is a 405 with `Allow`, and
the answers are the same with or without a frontend build mounted. When
`apps/web/dist/web/browser` exists it is mounted at `/` with an SPA fallback: a
miss on a path with no file extension returns `index.html` (sent with
`Cache-Control: no-cache`, so a rebuild is picked up on the next load), a miss
on a file-looking path stays 404.

Persistence is SQLAlchemy 2 (async, aiosqlite) with Alembic migrations.
`app/db/session.py` owns the engine: it creates the data directory on demand
and turns on `PRAGMA foreign_keys` for every connection. Models use only
dialect-neutral types; timestamps use `UTCDateTime` from `app/db/types.py`,
which returns aware UTC values on every dialect.

Configuration is read once at import in `app/auth/config.py` and the app
refuses to start on a missing or malformed value, with the variable named in
the error.

## Auth

Google OAuth through Authlib; the app holds sessions itself.

1. The browser navigates to `/api/auth/google/login`. The API sends it to
   Google with `redirect_uri` derived from `APP_BASE_URL`, never from request
   headers, and stashes the OAuth state in a short-lived signed cookie.
2. Google sends the browser back to `/api/auth/google/callback`.
3. The API exchanges the code, requires a verified email, and checks it against
   `ALLOWED_EMAILS` (case-insensitive). Anyone else gets 403 and no rows.
4. The `users` row is created or updated; a `sessions` row is created.
5. The session's UUID, signed with `SESSION_SECRET`, becomes the
   `honor_code_session` cookie: HttpOnly, SameSite=Lax, Secure iff
   `APP_BASE_URL` is https. The browser is redirected to `POST_LOGIN_REDIRECT`
   (default `/`).
6. Every authenticated request verifies the signature, loads the row, rejects
   it if expired, slides the 30-day expiry forward, and re-checks the email
   against `ALLOWED_EMAILS`, deleting the session if it has been removed.
   `POST /api/auth/logout` deletes the row and clears the cookie (204).

## Tables

`users`: `id` (UUID), `email` (unique), `google_sub` (unique, nullable),
`display_name`, `created_at`, `last_login_at`.

`sessions`: `id` (UUID), `user_id` (→ `users.id`, ON DELETE CASCADE),
`expires_at`, `created_at`, `last_seen_at`, `user_agent`, `ip_address`
(`String(45)`). Indexed on `user_id` and `expires_at`.

`source_documents`: one row per meeting (`kind` is `fathom_meeting`; Gmail
threads come later). Unique on (`user_id`, `kind`, `external_id`), where the
external id is Fathom's recording id. Holds the rendered transcript, the
speaker turns, which speaker label is Frank (`my_speaker`), the local meeting
date, and Fathom's own action items for comparison. Removing a meeting clears
its text and children and keeps the row as a tombstone (`removed_at`), so a
later sync does not bring it back.

`extraction_runs`: one row per model call against a meeting, with model,
prompt version, token counts, timing, and a safe error description. Written
before the call; candidates are written only together with success.

`commitments`: what a run found, plus Frank's decisions. Status is one of
`candidate`, `accepted`, `rejected`, `done`, `dropped`; the allowed moves are a
fixed table in `app/commitments/service.py`. `quote_found` says whether the
quoted words appear in a single speaker turn.

`status_events`: append-only history, one row per status change.

`sync_runs`: one row per Fathom sync, with its window and counts.

Every foreign key is indexed and cascades from its parent.

## Sync and extraction

```
Fathom API ──► sync (in-app, ADR 0003) ──► source_documents ──► Extractor ──► commitments ──► Review screen
                  every 30 min / startup / Sync now        (Anthropic; one forced tool call)
```

`app/sync/service.py` lists meetings created since the window start, stores
new ones (a failed or empty transcript counts as pending and is retried), and
extracts every live meeting without a successful run and with fewer than
three failed ones. One sync runs at a time. The two external services sit
behind one seam each, `MeetingSource` (`app/sources/fathom.py`) and
`Extractor` (`app/commitments/extraction.py`), which is where the tests swap
in fakes. The extraction prompt is a versioned file under
`app/commitments/prompts/`; its quality is measured by the eval script, not
by tests (ADR 0002).

## Environment

All in `apps/api/.env` (template: `.env.example`). `APP_BASE_URL` (required;
drives the redirect URI and cookie flags), `POST_LOGIN_REDIRECT` (optional),
`DATABASE_URL` (optional; defaults to the file under `apps/api/data/`),
`SESSION_SECRET`, `ENCRYPTION_KEY` (Fernet; for OAuth tokens stored later),
`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `ALLOWED_EMAILS`. `WEB_DIST_DIR`
overrides where the built frontend is looked for; the tests use it.

Phase 1, all optional at startup: `ANTHROPIC_API_KEY`, `FATHOM_API_KEY`,
`EXTRACTION_MODEL` (default `claude-sonnet-5-5`), `EXTRACTION_TIMEOUT_SECONDS`,
`FATHOM_BACKFILL_DAYS` (14), `FATHOM_SYNC_INTERVAL_MINUTES` (30),
`LOCAL_TIMEZONE` (`America/Los_Angeles`; a bad value stops startup),
`SYNC_ENABLED`. Without the two keys the app runs and the sync status names
what is missing.

## Tests

`apps/api/tests` runs with no `.env`, no network, and nothing listening. The
conftest sets every variable itself, seeds Authlib's Google metadata so no
discovery fetch happens, and patches httpx's real transport to fail loudly on
any escape, for both httpx and the httpx2 library the Anthropic SDK uses.
Google is mocked at one seam, Authlib's token exchange; Fathom and the model
at theirs (`tests/fakes.py`); everything after the seams is real.
`apps/web` has vitest specs for the services and screens. The real
Google round-trip is the one thing neither suite covers; check it in a browser
after touching `app/auth/`.
