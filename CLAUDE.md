# CLAUDE.md

Operating notes for Claude (and future contributors) working in this repo.

## Project

Honor Code is a personal app that extracts and tracks commitments from
Fathom transcripts (and, eventually, Gmail). Single user, single developer,
runs on the owner's own machine. There is no hosted deployment and none is
planned for now. Optimize for clarity and small focused changes, not scale.

## Repo layout

- `apps/api` — FastAPI backend, Python 3.12+, managed with `uv`. SQLite via
  aiosqlite at `apps/api/data/honor-code.db`. Alembic for migrations. Google
  OAuth login via Authlib; sessions are signed opaque IDs in a cookie backed by
  a `sessions` table. All routes live under `/api`.
- `apps/web` — Angular frontend, standalone components + signals, managed with
  `pnpm`. Reaches the API by relative `/api` paths; in development the dev
  server proxies those to `localhost:8000`.
- `docs/` — architecture notes and ADRs.

## Session protocol

1. **Read the task description carefully.** Stop at the scope boundary the
   task defines. Do not add hosting, Docker, CORS, multi-user support, or
   external integrations (Fathom API, Gmail) unless the task asks for them.
2. **Keep diffs small and focused.** Feature tasks should not refactor
   unrelated code.
3. **Never commit secrets.** No `.env` files, no API keys, no credentials.
   `.env.example` is the template; `.env` is ignored.
4. **Verify before reporting done.** API changes: `uv run pytest` green, then
   hit the endpoint with `curl`. Frontend changes: `pnpm test` and `pnpm build`
   green, then load the page.
5. **Use the right tooling.** Python: `uv` only (`uv add`, `uv run`). Node:
   `pnpm` only.
6. **Angular conventions.** Standalone components only, no NgModules. Angular
   Signals for component state.
7. **Database conventions.** Timestamp columns use `UTCDateTime` from
   `app/db/types.py`, never `DateTime` directly. Never import from
   `sqlalchemy.dialects`; models stay dialect-neutral. Every schema change
   ships with an Alembic migration, and `tests/test_migrations.py` must stay
   green (it checks the migration matches the models).
8. **Tests run offline.** The API suite must pass with no `.env`, no network,
   and nothing running. The conftest enforces this; do not weaken it.

## Commands

```bash
# API (from apps/api)
uv run --env-file .env alembic upgrade head
uv run --env-file .env uvicorn app.main:app --reload
uv run pytest

# Frontend (from apps/web)
pnpm start
pnpm test
pnpm build
```

## Out of scope for now

- Hosted deployment of any kind, CORS, any PaaS
- Multi-user support
- Fathom API and Gmail integrations (manual transcript paste comes first)
- Docker, launchd, packaging
