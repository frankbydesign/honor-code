# Honor Code

A personal app to track commitments extracted from Fathom transcripts (and, eventually, Gmail).

This repository is a monorepo containing:

- `apps/api` — FastAPI backend (Python 3.12+, managed with [uv](https://docs.astral.sh/uv/))
- `apps/web` — Angular frontend (standalone components + signals, managed with [pnpm](https://pnpm.io/))
- `docs/` — architecture and design notes

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) for Python dependency management
- Node.js 20+ and [pnpm](https://pnpm.io/)
- A Postgres `DATABASE_URL` — local development uses the Railway-hosted Postgres directly (there is no local Postgres setup). Grab the URL from the Railway dashboard for the `honor-code` service (it's exposed there as a reference variable to the Postgres service).

## Run the API locally

The API needs the following in its environment:

- `DATABASE_URL` — Postgres URL from Railway
- `SESSION_SECRET` — at least 32 bytes of random data, used to sign session cookies and the transient OAuth state cookie
- `ENCRYPTION_KEY` — a Fernet key, used to encrypt OAuth tokens at rest
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` — OAuth credentials from Google Cloud Console
- `ALLOWED_EMAILS` — comma- or whitespace-separated list of Google account emails permitted to log in (case-insensitive)
- `OAUTH_REDIRECT_URI` *(optional)* — the exact callback URL registered with Google. If unset, the app derives one from the incoming request, which only works if the proxy headers are trustworthy. On Railway, set it explicitly.

Generate the two secrets like this:

```bash
cd apps/api
uv run python -c 'import secrets; print(secrets.token_urlsafe(48))'                # SESSION_SECRET
uv run python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'  # ENCRYPTION_KEY
```

The app refuses to start if any required variable is missing or malformed. Then run it:

```bash
cd apps/api
DATABASE_URL='postgresql://...' \
  SESSION_SECRET='...' ENCRYPTION_KEY='...' \
  GOOGLE_CLIENT_ID='...' GOOGLE_CLIENT_SECRET='...' \
  ALLOWED_EMAILS='you@example.com' \
  uv run uvicorn app.main:app --reload
```

The API listens on http://localhost:8000. Verify with:

```bash
curl http://localhost:8000/health
# {"status":"ok","database":"connected"}
```

If the database is unreachable, `/health` returns HTTP 503 with
`{"detail":{"status":"error","database":"unreachable"}}`. The connection string is never echoed in the response or logged.

### Testing the Google OAuth flow

Register `http://localhost:8000/auth/google/callback` as an authorized redirect URI in Google Cloud Console (or use your Railway URL for production). Then in a browser:

1. Open `http://localhost:8000/auth/google/login` — you'll land on Google's consent screen.
2. Sign in with an email listed in `ALLOWED_EMAILS`. Google sends you back to `/auth/google/callback`, the API sets a `honor_code_session` cookie, and you're redirected to `/auth/me`, which returns your email and display name.
3. Hitting `/auth/me` from a fresh browser (no cookie) returns 401. Tampering with the cookie also returns 401 and logs a warning.
4. `POST /auth/logout` clears the cookie and deletes the session row; `/auth/me` then returns 401 again.
5. Signing in with an email not in `ALLOWED_EMAILS` is rejected with 403 at the callback; no user row is created.

## Database migrations (Alembic)

Migrations live in `apps/api/alembic/versions/`. Alembic reads `DATABASE_URL` from the environment (no need to edit `alembic.ini`). The application uses asyncpg at runtime; Alembic uses sync psycopg2 internally — both drivers are dependencies of `apps/api`.

All commands below are run from `apps/api/`:

```bash
cd apps/api

# Apply all pending migrations
DATABASE_URL='postgresql://...' uv run alembic upgrade head

# Roll back the most recent migration
DATABASE_URL='postgresql://...' uv run alembic downgrade -1

# Roll back everything (drops the users and sessions tables)
DATABASE_URL='postgresql://...' uv run alembic downgrade base

# Create a new migration after editing models in app/db/models/
DATABASE_URL='postgresql://...' uv run alembic revision --autogenerate -m "describe change"

# Show current revision
DATABASE_URL='postgresql://...' uv run alembic current
```

Re-running `alembic upgrade head` against an already-migrated database is a no-op.

### Tables created by the initial migration

- `users` — `id` (UUID PK, default `gen_random_uuid()`), `email` (unique), `google_sub` (unique nullable), `display_name`, `created_at`, `last_login_at`
- `sessions` — `id` (UUID PK), `user_id` (FK to `users.id` ON DELETE CASCADE), `expires_at`, `created_at`, `last_seen_at`, `user_agent`, `ip_address` (INET); indexed on `user_id` and `expires_at`

The migration also creates the `pgcrypto` extension (used by `gen_random_uuid()`).

## Run the web app locally

```bash
cd apps/web
pnpm install   # first time only
pnpm start
```

The Angular dev server listens on http://localhost:4200.

## Repository layout

```
honor-code/
├── apps/
│   ├── api/        # FastAPI app
│   │   ├── app/
│   │   │   ├── auth/      # Google OAuth + session cookies
│   │   │   ├── db/        # SQLAlchemy engine, session, models
│   │   │   ├── security/  # token encryption helpers (Fernet)
│   │   │   └── main.py
│   │   ├── alembic/    # migration environment + versions
│   │   └── alembic.ini
│   └── web/        # Angular app
└── docs/
    └── architecture.md
```
