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

The API needs `DATABASE_URL` in its environment. Pass it inline or export it in your shell:

```bash
cd apps/api
DATABASE_URL='postgresql://...' uv run uvicorn app.main:app --reload
```

The API listens on http://localhost:8000. Verify with:

```bash
curl http://localhost:8000/health
# {"status":"ok","database":"connected"}
```

If the database is unreachable, `/health` returns HTTP 503 with
`{"detail":{"status":"error","database":"unreachable"}}`. The connection string is never echoed in the response or logged.

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
│   │   │   ├── db/     # SQLAlchemy engine, session, models
│   │   │   └── main.py
│   │   ├── alembic/    # migration environment + versions
│   │   └── alembic.ini
│   └── web/        # Angular app
└── docs/
    └── architecture.md
```
